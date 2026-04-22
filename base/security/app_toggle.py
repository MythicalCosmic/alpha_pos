from functools import wraps
from django.http import JsonResponse


def app_required(app_name):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            from base.models import AppSettings
            settings = AppSettings.load()
            if app_name == 'hr' and not settings.hr_enabled:
                return JsonResponse({'success': False, 'message': 'HR module is disabled'}, status=403)
            if app_name == 'waiter' and not settings.waiter_enabled:
                return JsonResponse({'success': False, 'message': 'Waiter module is disabled'}, status=403)
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
