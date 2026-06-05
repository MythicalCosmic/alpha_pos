from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from base.helpers.request import get_client_ip, get_user_agent, get_session_key, parse_json_body
from base.helpers.response import json_response, ServiceResponse
from base.helpers.cookie import set_session_cookie, clear_session_cookie
from base.security.rate_limit import rate_limit, rate_limit_by
from base.security.auth import login_required
from waiters.services.auth_service import WaiterAuthService


def _login_email(request):
    try:
        import json
        body = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return None
    email = body.get('email') if isinstance(body, dict) else None
    return (email or '').strip().lower()[:128] or None


@csrf_exempt
@rate_limit('waiter_login', 5, 60)
@rate_limit_by('waiter_login_user', 5, 60, _login_email)
@require_POST
def login(request):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not email or not password:
        return json_response(ServiceResponse.validation_error(
            errors={'email': 'Email is required', 'password': 'Password is required'},
            message='Email and password are required',
        ))

    result, status = WaiterAuthService.login(
        email=email,
        password=password,
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )

    response = JsonResponse(result, status=status)

    token = result.get('data', {}).get('token')
    if result.get('success') and token:
        set_session_cookie(response, token)

    return response


@csrf_exempt
@rate_limit('waiter_logout', 10, 60)
@require_POST
@login_required
def logout(request):
    session_key = get_session_key(request)
    if not session_key:
        return json_response(ServiceResponse.unauthorized("Session not provided"))

    result, status = WaiterAuthService.logout(session_key)
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

    result, status = WaiterAuthService.me(session_key)
    return JsonResponse(result, status=status)


@csrf_exempt
@rate_limit('waiter_change_password', 3, 60)
@require_POST
@login_required
def change_password(request):
    session_key = get_session_key(request)
    if not session_key:
        return json_response(ServiceResponse.unauthorized("Session not provided"))

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    if not current_password or not new_password:
        return json_response(ServiceResponse.validation_error(
            errors={
                'current_password': 'Current password is required',
                'new_password': 'New password is required',
            },
            message='Both current and new password are required',
        ))

    result, status = WaiterAuthService.change_password(
        session_key=session_key,
        current_password=current_password,
        new_password=new_password,
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
        result, status = WaiterAuthService.get_active_sessions(session_key)
        return JsonResponse(result, status=status)

    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    session_id = data.get('session_id')
    if not session_id:
        return json_response(ServiceResponse.validation_error(
            errors={'session_id': 'session_id is required'},
            message='session_id is required',
        ))

    result, status = WaiterAuthService.revoke_session(session_key, session_id)
    return JsonResponse(result, status=status)
