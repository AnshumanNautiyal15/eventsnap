"""Simple per-minute request limits kept in Django's cache (one server, so the local cache is enough)."""
import hashlib
import time
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse


def client_ip(request):
    # In production gunicorn only listens on 127.0.0.1 and nginx sets X-Real-IP, so it can be trusted.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR", "")


def allow(scope, key, per_minute=None):
    """Count one request for (scope, key); False once the per-minute limit is used up."""
    limit = per_minute or settings.RATE_LIMITS[scope]
    window = int(time.time() // 60)
    cache_key = "rl:" + hashlib.sha1(f"{scope}|{key}|{window}".encode()).hexdigest()
    if cache.add(cache_key, 1, timeout=70):
        return True
    try:
        return cache.incr(cache_key) <= limit
    except ValueError:  # expired between add() and incr()
        cache.add(cache_key, 1, timeout=70)
        return True


def too_many():
    return JsonResponse({"error": "Too many attempts. Please wait a minute and try again."}, status=429)


def limit(scope, key_func):
    """Decorator: key_func(request, **kwargs) -> key string."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not allow(scope, key_func(request, **kwargs)):
                return too_many()
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
