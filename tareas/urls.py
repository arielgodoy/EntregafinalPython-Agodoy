"""URLs de la app tareas (contracts/web-urls.md)."""

from django.urls import path

from . import views

app_name = 'tareas'

urlpatterns = [
    path('', views.ListarTareasView.as_view(), name='listar_tareas'),
    path('mis-tareas/', views.MisTareasDashboardView.as_view(), name='mis_tareas'),
    path('dashboard/general/', views.TareasDashboardGeneralView.as_view(), name='dashboard_general'),
    path('dashboard/general/empresa/<int:empresa_id>/', views.TareasDashboardEmpresaView.as_view(), name='dashboard_general_empresa'),
    path('dashboard/general/empresa/<int:empresa_id>/departamento/<int:departamento_id>/', views.TareasDashboardDepartamentoView.as_view(), name='dashboard_general_departamento'),
    path('dashboard/general/empresa/<int:empresa_id>/usuario/<int:usuario_id>/', views.TareasDashboardUsuarioView.as_view(), name='dashboard_general_usuario'),
    path('enlace/<str:token>/', views.AbrirEnlaceTareaView.as_view(), name='enlace_tarea'),
    path('enlaces/<int:enlace_id>/revocar/', views.RevocarEnlaceTareaView.as_view(), name='revocar_enlace_tarea'),
    path('<int:pk>/', views.DetalleTareaView.as_view(), name='detalle_tarea'),
    path('<int:tarea_id>/enlaces/crear/', views.CrearEnlaceTareaView.as_view(), name='crear_enlace_tarea'),
    path('crear/', views.CrearTareaView.as_view(), name='crear_tarea'),
    path('<int:pk>/editar/', views.EditarTareaView.as_view(), name='editar_tarea'),
    path('<int:pk>/publicar/', views.PublicarTareaView.as_view(), name='publicar_tarea'),
    path('<int:pk>/gestionar/', views.IniciarGestionView.as_view(), name='gestionar_tarea'),
    path('<int:pk>/completar/', views.CompletarTareaView.as_view(), name='completar_tarea'),
    path('<int:pk>/aprobar-cierre/', views.AprobarCierreView.as_view(), name='aprobar_cierre'),
    path('<int:pk>/rechazar-cierre/', views.RechazarCierreView.as_view(), name='rechazar_cierre'),
    path('<int:pk>/anular/', views.AnularTareaView.as_view(), name='anular_tarea'),
    path('<int:pk>/reactivar/', views.ReactivarTareaView.as_view(), name='reactivar_tarea'),
    path('<int:pk>/hitos/', views.HitosTareaView.as_view(), name='hitos_tarea'),
    path('<int:pk>/documentos/', views.DocumentosTareaView.as_view(), name='documentos_tarea'),
    path('reuniones/', views.ListarReunionesRevisionView.as_view(), name='reunion_revision_lista'),
    path('reuniones/crear/', views.CrearReunionRevisionView.as_view(), name='reunion_revision_crear'),
    path('reuniones/<int:pk>/', views.DetalleReunionRevisionView.as_view(), name='reunion_revision_detalle'),
    path('reuniones/<int:pk>/editar/', views.EditarReunionRevisionView.as_view(), name='reunion_revision_editar'),
    path('reuniones/<int:pk>/accion/', views.ReunionRevisionActionView.as_view(), name='reunion_revision_accion'),
]
