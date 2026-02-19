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

# Import chat routing here to keep routing encapsulated in the chat app
import chat.routing

application = ProtocolTypeRouter({
	# HTTP -> Django ASGI application
	"http": get_asgi_application(),
	# WebSocket -> route to chat (AuthMiddlewareStack provides request.user)
	"websocket": AuthMiddlewareStack(
		URLRouter(
			chat.routing.websocket_urlpatterns
		)
	),
})
