"""
ASGI config for AppDocs project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')

# Ensure Django app registry is loaded before importing app routing
django_asgi_app = get_asgi_application()

# Import chat routing after the application is initialized
import chat.routing

application = ProtocolTypeRouter({
	# HTTP -> Django ASGI application
	"http": django_asgi_app,
	# WebSocket -> route to chat (AuthMiddlewareStack provides request.user)
	"websocket": AuthMiddlewareStack(
		URLRouter(
			chat.routing.websocket_urlpatterns
		)
	),
})
