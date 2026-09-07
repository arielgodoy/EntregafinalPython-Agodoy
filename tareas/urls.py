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
]
