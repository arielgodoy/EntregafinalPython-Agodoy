from django.urls import path
from . import views

app_name = 'gestion_dte'

urlpatterns = [
    path('', views.index, name='index'),
    path('dashboard/resumen/', views.dashboard_resumen, name='dashboard_resumen'),
    path('cesiones/', views.cesiones, name='cesiones'),
    path('cesiones/data/', views.cesiones_data, name='cesiones_data'),
    path('cesiones/sincronizar/', views.sincronizar_cesiones_rpetc, name='sincronizar_cesiones_rpetc'),
    path('cesiones/<int:pk>/detalle-contable/', views.detalle_contable_cesion, name='detalle_contable_cesion'),
    path('lectura-automatica-cesiones/', views.lectura_automatica_cesiones, name='lectura_automatica_cesiones'),
    path('lectura-automatica-cesiones/ejecutar/', views.ejecutar_lectura_automatica_cesiones, name='ejecutar_lectura_automatica_cesiones'),
    path('lectura-automatica-cesiones/estado/', views.estado_lectura_automatica_cesiones, name='estado_lectura_automatica_cesiones'),
    path('cesiones/verificar/', views.verificar_cesion, name='verificar_cesion'),
    path('certificados/', views.certificados_list, name='certificados'),
    path('certificados/cargar/', views.certificados_cargar, name='certificados_cargar'),
    path('certificados/<str:codigoempresa>/', views.certificados_detail, name='certificados_detail'),
    path('certificados/toggle/<int:pk>/', views.certificados_toggle_active, name='certificados_toggle_active'),
    path('certificados/eliminar/<int:pk>/', views.certificados_eliminar, name='certificados_eliminar'),
    path('certificados/probar/<int:pk>/', views.certificados_probar_conexion, name='certificados_probar_conexion'),
]
