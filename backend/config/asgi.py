"""The ASGI entry point.

Served by `daphne` in its own container for `/ws/` only (see
`infra/docker-compose.yml`). HTTP stays on gunicorn and WSGI: every view in
this project is synchronous, and moving them under an event loop to gain a
socket would be a large change made for a small feature.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

# Django first: the routing imports models.
django_asgi = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
from django.urls import path  # noqa: E402

from apps.realtime.consumers import LiveConsumer  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi,
    # Origin checked against ALLOWED_HOSTS: a page on another site must not be
    # able to open a socket with a token it lifted from somewhere.
    "websocket": AllowedHostsOriginValidator(
        URLRouter([path("ws/", LiveConsumer.as_asgi())]),
    ),
})
