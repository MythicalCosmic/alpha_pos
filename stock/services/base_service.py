from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from django.db.models import Model
from django.utils import timezone


def to_decimal(value, default=Decimal("0")):
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def round_decimal(value, places=4):
    if value is None:
        return Decimal("0")
    quantize_str = "0." + "0" * places
    return value.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)


def generate_number(prefix, model_class, field="order_number"):
    today = timezone.now()
    date_part = today.strftime("%Y%m%d")
    filter_kwargs = {f"{field}__startswith": f"{prefix}-{date_part}"}
    last = model_class.objects.filter(**filter_kwargs).order_by(f"-{field}").first()

    if last:
        last_num = getattr(last, field)
        try:
            seq = int(last_num.split("-")[-1]) + 1
        except Exception:
            seq = 1
    else:
        seq = 1

    return f"{prefix}-{date_part}-{seq:04d}"


def get_date_range(period):
    today = timezone.now().date()

    if period == "today":
        return today, today
    elif period == "yesterday":
        return today - timedelta(days=1), today - timedelta(days=1)
    elif period == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, today
    elif period == "last_week":
        end = today - timedelta(days=today.weekday() + 1)
        start = end - timedelta(days=6)
        return start, end
    elif period == "this_month":
        return today.replace(day=1), today
    elif period == "last_month":
        first_of_month = today.replace(day=1)
        last_month_end = first_of_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return last_month_start, last_month_end
    elif period == "this_year":
        return today.replace(month=1, day=1), today
    elif period.startswith("last_") and period.endswith("_days"):
        try:
            days = int(period.replace("last_", "").replace("_days", ""))
            return today - timedelta(days=days), today
        except Exception:
            pass

    return today, today
