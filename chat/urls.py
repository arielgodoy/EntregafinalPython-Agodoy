# urls.py
from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth.views import LoginView

urlpatterns = [
    
    path('conversaciones/', views.lista_conversaciones, name='lista_conversaciones'),
    path('conversaciones/<int:conversacion_id>/enviar-mensaje/', views.enviar_mensaje, name='enviar_mensaje'),
    path('conversaciones/crear/', views.crear_conversacion, name='crear_conversacion'),
    path('conversaciones/<int:conversacion_id>/', views.detalle_conversacion, name='detalle_conversacion'),
    path('conversacion/<int:conversacion_id>/eliminar/', views.eliminar_conversacion, name='eliminar_conversacion'),


]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)