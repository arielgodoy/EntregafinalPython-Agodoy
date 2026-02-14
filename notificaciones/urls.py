from django.urls import path

from notificaciones import views
from notificaciones.views import (
    AlertaPersonalizadaView,
    CentroAlertasView,
    ForzarNotificacionesView,
    MisNotificacionesView,
    NotificacionesMarkAllReadView,
    NotificacionesMarkReadView,
    NotificacionesTopbarView,
    VerNotificacionView,
)

app_name = "notificaciones"

urlpatterns = [
    path("topbar/", NotificacionesTopbarView.as_view(), name="topbar"),
    path("<int:notification_id>/read/", NotificacionesMarkReadView.as_view(), name="mark_read"),
    path("mark-all-read/", NotificacionesMarkAllReadView.as_view(), name="mark_all_read"),
    path("mis-notificaciones/", MisNotificacionesView.as_view(), name="mis_notificaciones"),
    path("mis-notificaciones/<int:pk>/", VerNotificacionView.as_view(), name="ver_notificacion"),
    path("centro/", CentroAlertasView.as_view(), name="centro_alertas"),
    path("forzar/", ForzarNotificacionesView.as_view(), name="forzar_notificaciones"),
    path("alerta-personalizada/", AlertaPersonalizadaView.as_view(), name="alerta_personalizada"),
]
