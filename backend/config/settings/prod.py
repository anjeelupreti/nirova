"""Production settings.

Everything here is hardening that assumes **TLS terminates in front of this
process** -- a load balancer, an ingress, or a reverse proxy. That assumption
is true in production and false in the local Docker stack, which serves plain
HTTP on localhost. Rather than fork these settings into a near-identical
`docker.py` that would drift, the TLS-dependent switches are behind one flag.

`DJANGO_BEHIND_TLS` defaults to **True**, so the safe configuration is the one
you get by saying nothing. `infra/docker-compose.yml` sets it to False and says
why in a comment. If you find yourself setting it to False anywhere else, you
are serving an authenticated healthcare application over cleartext.
"""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

BEHIND_TLS = env.bool("DJANGO_BEHIND_TLS", default=True)

# Sends a 301 to https for any http request. Correct in front of a terminating
# proxy; an infinite redirect loop, or simply a broken stack, without one.
SECURE_SSL_REDIRECT = BEHIND_TLS

# `Secure` cookies are never sent over http, so leaving these on without TLS
# does not fail loudly -- the browser silently drops the cookie and the Django
# admin login appears to succeed and then does nothing. Tied to the same flag
# for that reason. The API itself is JWT-bearer and unaffected either way.
SESSION_COOKIE_SECURE = BEHIND_TLS
CSRF_COOKIE_SECURE = BEHIND_TLS

# HSTS instructs the browser to refuse http for this host for a year, and it
# is remembered per host, not per port. Setting it while developing on
# localhost poisons localhost for every other project on the machine, which is
# a genuinely painful thing to undo -- so it is zero unless TLS is real.
SECURE_HSTS_SECONDS = 31536000 if BEHIND_TLS else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = BEHIND_TLS
SECURE_HSTS_PRELOAD = BEHIND_TLS

# Trusts the proxy's word on the original scheme. Only sound when a proxy you
# control sets this header and strips any client-supplied copy of it.
if BEHIND_TLS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Unconditional: these cost nothing and depend on no transport.
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

# Django will not start with DEBUG off and no ALLOWED_HOSTS, which is the
# right default, but the container's hostname is not knowable at image build
# time. Compose supplies the list; this is only the failure message improver.
if not ALLOWED_HOSTS:  # noqa: F405
    raise RuntimeError(
        "DJANGO_ALLOWED_HOSTS must be set when running production settings."
    )
