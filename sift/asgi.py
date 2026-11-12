"""ASGI entry point: one process serves HTTP now and WebSocket from F5 (D10)."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sift.settings")

# Django must be set up before importing anything that may touch models.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter  # noqa: E402

application = ProtocolTypeRouter({"http": django_asgi_app})
