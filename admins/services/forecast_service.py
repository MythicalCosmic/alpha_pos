"""Demand forecasting via Gemini.

Pulls the last 30 days of order history aggregated by product × weekday ×
hour, hands it to Gemini, and asks for a prep-quantity recommendation for
tomorrow. Reuses the existing GEMINI_API_KEY wiring from the stock AI
assistant.

The Gemini call is isolated in `_call_gemini` so tests can monkeypatch
it without configuring an API key.
"""
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, F, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30
DEFAULT_TOP_N = 15  # cap on products returned so a 200-item menu doesn't blow up the Gemini prompt


def gather_history(days=WINDOW_DAYS, top_n=DEFAULT_TOP_N):
    """Build the per-product × weekday × hour aggregate the forecaster reads.

    Returns a dict shaped like:
      {
        "window_days": 30,
        "products": [
          {
            "id": 12, "name": "Margherita",
            "total_qty": 145,
            "by_weekday": {"Mon": 20, "Tue": 18, ...},
            "by_hour": {"12": 25, "13": 30, ...},
          },
          ...
        ],
      }
    """
    from base.models import OrderItem
    cutoff = timezone.now() - timedelta(days=days)

    # Top-N products by total quantity in the window — keeps the prompt
    # bounded and focuses Gemini on the products that actually drive prep.
    top = (
        OrderItem.objects.filter(
            order__is_deleted=False,
            order__created_at__gte=cutoff,
        )
        .values('product_id', 'product__name')
        .annotate(total_qty=Sum('quantity'))
        .order_by('-total_qty')[:top_n]
    )
    products = []
    for row in top:
        pid = row['product_id']
        breakdown = (
            OrderItem.objects.filter(
                product_id=pid,
                order__is_deleted=False,
                order__created_at__gte=cutoff,
            )
            .values(
                weekday=F('order__created_at__week_day'),
                hour=F('order__created_at__hour'),
            )
            .annotate(qty=Sum('quantity'))
        )
        by_weekday = {}
        by_hour = {}
        # Django's week_day is 1=Sunday..7=Saturday — map to short names.
        weekday_map = {1: 'Sun', 2: 'Mon', 3: 'Tue', 4: 'Wed',
                       5: 'Thu', 6: 'Fri', 7: 'Sat'}
        for cell in breakdown:
            wd = weekday_map.get(cell['weekday'], str(cell['weekday']))
            by_weekday[wd] = by_weekday.get(wd, 0) + int(cell['qty'] or 0)
            hr = str(cell['hour'])
            by_hour[hr] = by_hour.get(hr, 0) + int(cell['qty'] or 0)
        products.append({
            'id': pid,
            'name': row['product__name'],
            'total_qty': int(row['total_qty'] or 0),
            'by_weekday': by_weekday,
            'by_hour': by_hour,
        })

    return {'window_days': days, 'products': products}


_PROMPT = """You are a restaurant prep planner. Given the last {days} days
of order history below, predict the quantity to prep tomorrow for each
product. Account for:

- Tomorrow is a {weekday_name}. Weight that weekday's history more heavily.
- Prefer slight over-prep to under-prep for high-margin items.
- Round to whole units.

Return JSON only, in this exact shape (no preamble, no markdown):

{{
  "tomorrow": "{tomorrow_iso}",
  "predictions": [
    {{"product_id": int, "product_name": str, "suggested_qty": int, "reason": "short string"}}
  ]
}}

DATA:
{data_json}
"""


def _call_gemini(prompt_text):
    """Isolated so tests can monkeypatch without configuring an API key."""
    try:
        import google.generativeai as genai
    except ImportError:
        return None, 'gemini_sdk_missing'
    api_key = getattr(settings, 'GEMINI_API_KEY', '') or ''
    if not api_key:
        return None, 'gemini_key_missing'
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name='gemini-2.5-flash',
        generation_config={'temperature': 0.2, 'max_output_tokens': 2048},
    )
    try:
        resp = model.generate_content(prompt_text)
        return resp.text, None
    except Exception as e:
        logger.exception('gemini forecast call failed')
        return None, str(e)


def forecast_tomorrow():
    """Return (data, error). `data` is the parsed JSON from Gemini; `error`
    is a short code on failure."""
    history = gather_history()
    if not history['products']:
        return {'predictions': [], 'reason': 'no_history'}, None

    tomorrow = timezone.now() + timedelta(days=1)
    weekday_name = tomorrow.strftime('%A')

    prompt = _PROMPT.format(
        days=WINDOW_DAYS,
        weekday_name=weekday_name,
        tomorrow_iso=tomorrow.date().isoformat(),
        data_json=json.dumps(history, ensure_ascii=False),
    )

    raw, err = _call_gemini(prompt)
    if err:
        return None, err

    # Gemini sometimes wraps JSON in ``` fences despite instructions.
    text = raw.strip()
    if text.startswith('```'):
        text = text.strip('`')
        # Drop a leading "json" language tag if present.
        if text.lower().startswith('json'):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        logger.warning('gemini returned non-JSON forecast: %s', raw[:200])
        return None, 'parse_error'
    return parsed, None
