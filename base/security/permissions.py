from functools import wraps
from django.http import JsonResponse
from base.helpers.request import get_session_key
from base.repositories import SessionRepository


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        session_key = get_session_key(request)
        if not session_key:
            return JsonResponse(
                {"success": False, "message": "Authentication required"},
                status=401,
            )
        session = SessionRepository.first(payload=session_key)
        if not session or not session.user_id or session.user_id.is_deleted:
            return JsonResponse(
                {"success": False, "message": "Invalid or expired session"},
                status=401,
            )
        if session.user_id.role != 'ADMIN':
            return JsonResponse(
                {"success": False, "message": "Hell no"},
                status=403,
            )
        if session.user_id.status != 'ACTIVE':
            return JsonResponse(
                {"success": False, "message": "Account is suspended"},
                status=403,
            )
        request.user = session.user_id
        request.session_key = session_key
        return view_func(request, *args, **kwargs)
    return wrapper


def permission_required(*permissions):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not hasattr(request, 'user') or request.user is None:
                return JsonResponse(
                    {"success": False, "message": "Authentication required"},
                    status=401,
                )
            user_perms = request.user.permissions or []
            if '*' in user_perms or request.user.role == 'ADMIN':
                return view_func(request, *args, **kwargs)
            missing = [p for p in permissions if p not in user_perms]
            if missing:
                return JsonResponse(
                    {"success": False, "message": "You don't have permission to perform this action"},
                    status=403,
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
