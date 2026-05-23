from functools import wraps
from django.http import JsonResponse
from base.helpers.request import get_session_key
from base.repositories import SessionRepository


def login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        session_key = get_session_key(request)
        if not session_key:
            return JsonResponse(
                {"success": False, "message": "Authentication required"},
                status=401,
            )
        # Use the cached lookup with `select_related('user_id')` — `first()`
        # neither caches nor preloads the user FK, so this saves both a
        # repeat session lookup and a lazy user query per request.
        session = SessionRepository.get_by_session_key(session_key)
        if not session or not session.user_id or session.user_id.is_deleted:
            return JsonResponse(
                {"success": False, "message": "Invalid or expired session"},
                status=401,
            )
        if session.is_expired():
            SessionRepository.invalidate_cache(session_key)
            SessionRepository.delete(session)
            return JsonResponse(
                {"success": False, "message": "Invalid or expired session"},
                status=401,
            )
        request.user = session.user_id
        request.session_key = session_key
        return view_func(request, *args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not hasattr(request, 'user') or request.user is None:
                return JsonResponse(
                    {"success": False, "message": "Authentication required"},
                    status=401,
                )
            if request.user.role not in roles:
                return JsonResponse(
                    {"success": False, "message": "Insufficient permissions"},
                    status=403,
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
