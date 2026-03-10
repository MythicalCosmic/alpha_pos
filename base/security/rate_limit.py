from functools import wraps
from django.core.cache import cache
from django.http import JsonResponse


def _get_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def rate_limit(key_prefix, max_attempts, window):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            ip = _get_ip(request)
            key = f"rl:{key_prefix}:{ip}"
            count = cache.get(key)
            if count is not None and count >= max_attempts:
                retry_after = cache.ttl(key) if hasattr(cache, 'ttl') else window
                return JsonResponse(
                    {"success": False, "message": "Too many requests"},
                    status=429,
                    headers={"Retry-After": str(retry_after)},
                )
            if count is None:
                cache.set(key, 1, window)
            else:
                try:
                    cache.incr(key)
                except ValueError:
                    cache.set(key, 1, window)
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
