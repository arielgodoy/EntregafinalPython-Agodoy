from django.urls import path
from . import views

app_name = 'control_operacional'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('alertas/', views.alertas_operacionales, name='alertas_operacionales'),
    path('alertas/ack/', views.ack_alerta, name='ack_alerta'),
]
