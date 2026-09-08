"""URLs de la app tareas (contracts/web-urls.md)."""

from django.urls import path

from . import views

app_name = 'tareas'

urlpatterns = [
    path('', views.ListarTareasView.as_view(), name='listar_tareas'),
    path('<int:pk>/', views.DetalleTareaView.as_view(), name='detalle_tarea'),
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
]
