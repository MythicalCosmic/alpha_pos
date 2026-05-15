import json
from django.conf import settings


def get_client_ip(request):
    # See base/security/rate_limit.py — same trust rule.
    if getattr(settings, 'TRUST_FORWARDED_FOR', False):
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def get_user_agent(request):
    ua = request.META.get('HTTP_USER_AGENT', '')
    return ua[:256]


def get_session_key(request):
    key = request.COOKIES.get('session_key')
    if key:
        return key
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.startswith('Bearer '):
        return auth[7:]
    return None


def validate_pagination(request, default_per_page=20):
    from django.conf import settings
    max_per_page = getattr(settings, 'MAX_PER_PAGE', 100)
    try:
        page = max(1, int(request.GET.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = max(1, min(int(request.GET.get('per_page', default_per_page)), max_per_page))
    except (ValueError, TypeError):
        per_page = default_per_page
    return page, per_page


def safe_per_page(request, default=20):
    # Return per_page bounded by MAX_PER_PAGE, for callers that read page
    # separately. Use validate_pagination when both are needed.
    from django.conf import settings
    max_per_page = getattr(settings, 'MAX_PER_PAGE', 100)
    try:
        return max(1, min(int(request.GET.get('per_page', default)), max_per_page))
    except (ValueError, TypeError):
        return default


def safe_page(request, default=1):
    try:
        return max(1, int(request.GET.get('page', default)))
    except (ValueError, TypeError):
        return default


def parse_json_body(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            return None, ({"success": False, "message": "Expected JSON object"}, 400)
        return data, None
    except (json.JSONDecodeError, ValueError):
        return None, ({"success": False, "message": "Invalid JSON"}, 400)
