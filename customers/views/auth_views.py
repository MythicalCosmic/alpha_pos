from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from base.helpers.request import get_client_ip, get_user_agent, get_session_key
from base.helpers.response import json_response, ServiceResponse
from base.helpers.cookie import set_session_cookie, clear_session_cookie
from base.security.rate_limit import rate_limit, rate_limit_by
from base.security.auth import login_required
from customers.services.auth_service import AuthService
from customers.requests.auth_requests import (
    login_request,
    change_password_request,
    revoke_session_request,
)


def _login_email(request):
    try:
        import json
        body = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return None
    email = body.get('email') if isinstance(body, dict) else None
    return (email or '').strip().lower()[:128] or None


def _login_user_id(request):
    try:
        import json
        body = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return None
    user_id = body.get('user_id') if isinstance(body, dict) else None
    if user_id is None:
        return None
    return str(user_id).strip()[:128] or None


@csrf_exempt
@rate_limit('login', 5, 60)
@rate_limit_by('login_user', 5, 60, _login_email)
@rate_limit_by('login_uid', 5, 60, _login_user_id)
@require_POST
def login(request):
    data, error = login_request(request)
    if error:
        return json_response(error)

    result, status = AuthService.login(
        email=data.get('email'),
        user_id=data.get('user_id'),
        password=data['password'],
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )

    response = JsonResponse(result, status=status)

    token = result.get('data', {}).get('token')
    if result.get('success') and token:
        set_session_cookie(response, token)

    return response


@csrf_exempt
@rate_limit('logout', 10, 60)
@require_POST
@login_required
def logout(request):
    session_key = get_session_key(request)
    if not session_key:
        return json_response(ServiceResponse.unauthorized("Session not provided"))

    result, status = AuthService.logout(session_key)
    response = JsonResponse(result, status=status)

    if result.get('success'):
        clear_session_cookie(response)

    return response


@csrf_exempt
@rate_limit('logout_all', 5, 60)
@require_POST
@login_required
def logout_all(request):
    session_key = get_session_key(request)
    if not session_key:
        return json_response(ServiceResponse.unauthorized("Session not provided"))

    result, status = AuthService.logout_all(session_key)
    response = JsonResponse(result, status=status)

    if result.get('success'):
        clear_session_cookie(response)

    return response


@csrf_exempt
@require_GET
@login_required
def me(request):
    session_key = get_session_key(request)
    if not session_key:
        return json_response(ServiceResponse.unauthorized("Session not provided"))

    result, status = AuthService.me(session_key)
    return JsonResponse(result, status=status)


@csrf_exempt
@rate_limit('change_password', 3, 60)
@require_POST
@login_required
def change_password(request):
    session_key = get_session_key(request)
    if not session_key:
        return json_response(ServiceResponse.unauthorized("Session not provided"))

    data, error = change_password_request(request)
    if error:
        return json_response(error)

    result, status = AuthService.change_password(
        session_key=session_key,
        current_password=data['current_password'],
        new_password=data['new_password'],
    )

    return JsonResponse(result, status=status)


@csrf_exempt
@require_http_methods(["GET", "DELETE"])
@login_required
def sessions(request):
    session_key = get_session_key(request)
    if not session_key:
        return json_response(ServiceResponse.unauthorized("Session not provided"))

    if request.method == "GET":
        result, status = AuthService.get_active_sessions(session_key)
        return JsonResponse(result, status=status)

    data, error = revoke_session_request(request)
    if error:
        return json_response(error)

    result, status = AuthService.revoke_session(session_key, data['session_id'])
    return JsonResponse(result, status=status)
