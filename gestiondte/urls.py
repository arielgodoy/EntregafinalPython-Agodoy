from django.urls import path
from . import views

app_name = 'gestion_dte'

urlpatterns = [
    path('', views.index, name='index'),
    path('cesiones/', views.cesiones, name='cesiones'),
    path('cesiones/sincronizar/', views.sincronizar_cesiones_rpetc, name='sincronizar_cesiones_rpetc'),
    path('cesiones/verificar/', views.verificar_cesion, name='verificar_cesion'),
    path('certificados/', views.certificados_list, name='certificados'),
    path('certificados/cargar/', views.certificados_cargar, name='certificados_cargar'),
    path('certificados/<str:codigoempresa>/', views.certificados_detail, name='certificados_detail'),
    path('certificados/toggle/<int:pk>/', views.certificados_toggle_active, name='certificados_toggle_active'),
    path('certificados/probar/<int:pk>/', views.certificados_probar_conexion, name='certificados_probar_conexion'),
]
