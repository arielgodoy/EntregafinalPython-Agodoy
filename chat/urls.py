from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from .views import (
    ChatInboxView,
    ChatCentroMensajesView,
    ListaConversacionesView,
    CrearConversacionView,
    DetalleConversacionView,
    EnviarMensajeView,
    EliminarConversacionView,
)

urlpatterns = [
    path('chat/', ChatInboxView.as_view(), name='chat_inbox'),
    path('centro/', ChatCentroMensajesView.as_view(), name='centro_mensajes'),

    path('conversaciones/', ListaConversacionesView.as_view(), name='lista_conversaciones'),
    path('conversaciones/crear/', CrearConversacionView.as_view(), name='crear_conversacion'),

    path('conversaciones/<int:pk>/', DetalleConversacionView.as_view(), name='detalle_conversacion'),
    path('conversaciones/<int:pk>/enviar-mensaje/', EnviarMensajeView.as_view(), name='enviar_mensaje'),
    path('conversaciones/<int:pk>/eliminar/', EliminarConversacionView.as_view(), name='eliminar_conversacion'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
