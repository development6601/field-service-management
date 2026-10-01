import threading

_thread_locals = threading.local()


def get_current_request():
    """Returns the active HTTP request for the current thread."""
    return getattr(_thread_locals, "request", None)


def get_current_user():
    """Returns the authenticated User for the current request thread, or None."""
    request = get_current_request()
    if request and hasattr(request, "user") and request.user.is_authenticated:
        return request.user
    return None


def get_client_ip(request=None):
    """Extracts client IP address respecting X-Forwarded-For reverse proxies."""
    req = request or get_current_request()
    if not req:
        return None
    x_forwarded_for = req.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return req.META.get("REMOTE_ADDR")


def get_user_agent(request=None):
    """Extracts client User-Agent string from headers."""
    req = request or get_current_request()
    if not req:
        return ""
    return req.META.get("HTTP_USER_AGENT", "")[:500]


class AuditLogMiddleware:
    """
    Middleware that captures the current HTTP request in thread-local storage
    so automated model signals and domain services can record the actor and client IP.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_locals.request = request
        try:
            response = self.get_response(request)
        finally:
            _thread_locals.request = None
        return response
