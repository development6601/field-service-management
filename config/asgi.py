"""
ASGI config for Field Service Management project.
Handles both HTTP and real-time WebSocket protocol routing via Django Channels.
"""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

# Initialize Django ASGI application early to ensure AppRegistry is populated
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from apps.core.channels_middleware import JWTAuthMiddlewareStack
from apps.scheduling.routing import websocket_urlpatterns

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            JWTAuthMiddlewareStack(
                URLRouter(websocket_urlpatterns)
            )
        ),
    }
)
