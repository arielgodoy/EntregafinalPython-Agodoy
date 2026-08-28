from django.urls import path
from . import views

app_name = 'gestion_dte'

urlpatterns = [
    path('', views.index, name='index'),
    path('dashboard/resumen/', views.dashboard_resumen, name='dashboard_resumen'),
    path('cesiones/', views.cesiones, name='cesiones'),
    path('cesiones/data/', views.cesiones_data, name='cesiones_data'),
    path('cesiones/exportar-excel/', views.exportar_cesiones_excel, name='exportar_cesiones_excel'),
    path('cesiones/sincronizar/', views.sincronizar_cesiones_rpetc, name='sincronizar_cesiones_rpetc'),
    path('cesiones/<int:pk>/detalle-contable/', views.detalle_contable_cesion, name='detalle_contable_cesion'),
    path('cesiones/<int:pk>/revision/', views.revision_cesion, name='revision_cesion'),
    path('cesiones/<int:pk>/revision/comentarios/crear/', views.crear_comentario_revision, name='crear_comentario_revision'),
    path('cesiones/<int:pk>/revision/comentarios/<int:comentario_pk>/editar/', views.editar_comentario_revision, name='editar_comentario_revision'),
    path('cesiones/<int:pk>/revision/comentarios/<int:comentario_pk>/eliminar/', views.eliminar_comentario_revision, name='eliminar_comentario_revision'),
    path('cesiones/<int:pk>/revision/crear/', views.revision_cesion, name='crear_revision_cesion'),
    path('cesiones/<int:pk>/revision/editar/', views.revision_cesion, name='editar_revision_cesion'),
    path('cesiones/<int:pk>/revision/eliminar/', views.revision_cesion, name='eliminar_revision_cesion'),
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
