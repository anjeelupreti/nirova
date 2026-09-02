"""Small HTTP helpers shared across apps."""


def client_ip(request):
    """Best-effort client address behind a proxy.

    Only the first entry of X-Forwarded-For is used, and only because the
    deployment terminates TLS at a trusted proxy that rewrites the header.
    Without that guarantee this value is client-controlled and must not be
    trusted for anything beyond a log line.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
