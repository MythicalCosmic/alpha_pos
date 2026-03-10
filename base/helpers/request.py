import json


def get_client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def get_user_agent(request):
    ua = request.META.get('HTTP_USER_AGENT', '')
    return ua[:30]


def get_session_key(request):
    key = request.COOKIES.get('session_key')
    if key:
        return key
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.startswith('Bearer '):
        return auth[7:]
    return None


def parse_json_body(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            return None, ({"success": False, "message": "Expected JSON object"}, 400)
        return data, None
    except (json.JSONDecodeError, ValueError):
        return None, ({"success": False, "message": "Invalid JSON"}, 400)
