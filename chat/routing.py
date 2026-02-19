from django.urls import path

from . import consumers

websocket_urlpatterns = [
    # WebSocket endpoint for chat conversations (conversation_id as int)
    path('ws/chat/<int:conversation_id>/', consumers.ChatConsumer.as_asgi()),
]
