from django.urls import path
from . import views

app_name = 'control_operacional'

urlpatterns = [
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('alertas/', views.AlertasOperacionalesView.as_view(), name='alertas_operacionales'),
    path('alertas/ack/', views.AckAlertaView.as_view(), name='ack_alerta'),
]
