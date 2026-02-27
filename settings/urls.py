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

from .views import (
    MySQLConnectionListView,
    MySQLConnectionCreateView,
    MySQLConnectionUpdateView,
    MySQLConnectionDeleteView,
    MySQLConnectionTestView,
)

urlpatterns = [
    path('configurar-email/', ConfigurarEmailView.as_view(), name='configurar_email'),
    path('probar-configuracion-entrada/', ProbarConfiguracionEntradaView.as_view(), name='probar_configuracion_entrada'),
    path('probar-configuracion-salida/', ProbarConfiguracionSalidaView.as_view(), name='probar_configuracion_salida'),
    path('enviar-correo-prueba/', EnviarCorreoPruebaView.as_view(), name='enviar_correo_prueba'),
    path('recibir-correo-prueba/', RecibirCorreoPruebaView.as_view(), name='recibir_correo_prueba'),
    path('guardar-preferencias/', guardar_preferencias, name='guardar_preferencias'),
    path('fecha-sistema/set/', SetFechaSistemaView.as_view(), name='set_fecha_sistema'),
    # MySQL Connections per company
    path('mysql-connections/', MySQLConnectionListView.as_view(), name='mysql_connections_list'),
    path('mysql-connections/create/', MySQLConnectionCreateView.as_view(), name='mysql_connections_create'),
    path('mysql-connections/<int:pk>/edit/', MySQLConnectionUpdateView.as_view(), name='mysql_connections_edit'),
    path('mysql-connections/<int:pk>/delete/', MySQLConnectionDeleteView.as_view(), name='mysql_connections_delete'),
    path('mysql-connections/<int:pk>/test/', MySQLConnectionTestView.as_view(), name='mysql_connections_test'),
]


