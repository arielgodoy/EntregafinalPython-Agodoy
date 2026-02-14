from django.urls import path
from .views import (
    ConfigurarEmailView,
    ProbarConfiguracionEntradaView,
    ProbarConfiguracionSalidaView,
    EnviarCorreoPruebaView,
    RecibirCorreoPruebaView,
    SetFechaSistemaView,
    guardar_preferencias,
)

urlpatterns = [
    path('configurar-email/', ConfigurarEmailView.as_view(), name='configurar_email'),
    path('probar-configuracion-entrada/', ProbarConfiguracionEntradaView.as_view(), name='probar_configuracion_entrada'),
    path('probar-configuracion-salida/', ProbarConfiguracionSalidaView.as_view(), name='probar_configuracion_salida'),
    path('enviar-correo-prueba/', EnviarCorreoPruebaView.as_view(), name='enviar_correo_prueba'),
    path('recibir-correo-prueba/', RecibirCorreoPruebaView.as_view(), name='recibir_correo_prueba'),
    path('guardar-preferencias/', guardar_preferencias, name='guardar_preferencias'),
    path('fecha-sistema/set/', SetFechaSistemaView.as_view(), name='set_fecha_sistema'),
]


