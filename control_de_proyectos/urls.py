from django.urls import path
from . import views

app_name = 'control_de_proyectos'

urlpatterns = [
    # Proyectos
    path('proyectos/', views.ListarProyectosView.as_view(), name='listar_proyectos'),
    path('proyectos/<int:pk>/', views.DetalleProyectoView.as_view(), name='detalle_proyecto'),
    path('proyectos/crear/', views.CrearProyectoView.as_view(), name='crear_proyecto'),
    path('proyectos/<int:pk>/editar/', views.EditarProyectoView.as_view(), name='editar_proyecto'),
    path('proyectos/<int:pk>/eliminar/', views.EliminarProyectoView.as_view(), name='eliminar_proyecto'),

    # Tareas
    path('proyectos/<int:proyecto_id>/tareas/crear/', views.CrearTareaView.as_view(), name='crear_tarea'),
    path('tareas/<int:pk>/editar/', views.EditarTareaView.as_view(), name='editar_tarea'),
    path('tareas/<int:pk>/eliminar/', views.EliminarTareaView.as_view(), name='eliminar_tarea'),
    path('tareas/<int:tarea_id>/documentos/subir/', views.SubirDocumentoTareaView.as_view(), name='subir_documento_tarea'),
    path('tareas/<int:tarea_id>/avance/', views.ActualizarAvanceTareaView.as_view(), name='actualizar_avance_tarea'),

    # Clientes
    path('clientes/', views.ListarClientesView.as_view(), name='listar_clientes'),
    path('clientes/crear/', views.CrearClienteView.as_view(), name='crear_cliente'),
    path('clientes/<int:pk>/editar/', views.EditarClienteView.as_view(), name='editar_cliente'),

    # Profesionales
    path('profesionales/', views.ListarProfesionalesView.as_view(), name='listar_profesionales'),
    path('profesionales/crear/', views.CrearProfesionalView.as_view(), name='crear_profesional'),
    path('profesionales/<int:pk>/editar/', views.EditarProfesionalView.as_view(), name='editar_profesional'),

    # Tipos de Tarea
    path('tipos-tarea/crear/', views.CrearTipoTareaView.as_view(), name='crear_tipo_tarea'),

    # AJAX - Autocomplete/Sugerencias
    path('api/sugerir-tipos/', views.sugerir_tipos_proyecto, name='sugerir_tipos'),
    path('api/sugerir-especialidades/', views.sugerir_especialidades, name='sugerir_especialidades'),
]
