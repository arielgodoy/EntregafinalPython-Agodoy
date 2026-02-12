from django.urls import path

from notificaciones import views

app_name = "notificaciones"

urlpatterns = [
    path("topbar/", views.topbar, name="topbar"),
    path("<int:notification_id>/read/", views.mark_read_view, name="mark_read"),
    path("mark-all-read/", views.mark_all_read_view, name="mark_all_read"),
    path("mis-notificaciones/", views.mis_notificaciones, name="mis_notificaciones"),
    path("mis-notificaciones/<int:pk>/", views.ver_notificacion, name="ver_notificacion"),
    path("centro/", views.centro_alertas, name="centro_alertas"),
    path("forzar/", views.forzar_notificaciones, name="forzar_notificaciones"),
    path("alerta-personalizada/", views.alerta_personalizada, name="alerta_personalizada"),
]
