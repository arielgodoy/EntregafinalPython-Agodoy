from django.urls import path, include
from rest_framework import routers
from .api_views import (
    TipoProyectoViewSet,
    EspecialidadProfesionalViewSet,
    ClienteEmpresaViewSet,
    ProfesionalViewSet,
    ProyectoViewSet,
    TareaViewSet,
    TipoTareaViewSet,
    DocumentoRequeridoTipoTareaViewSet,
    TareaDocumentoViewSet,
)

router = routers.DefaultRouter()

router.register(r'tipos-proyecto', TipoProyectoViewSet, basename='tipo-proyecto')
router.register(r'especialidades', EspecialidadProfesionalViewSet, basename='especialidad')
router.register(r'clientes', ClienteEmpresaViewSet, basename='cliente-empresa')
router.register(r'profesionales', ProfesionalViewSet, basename='profesional')
router.register(r'proyectos', ProyectoViewSet, basename='proyecto')
router.register(r'tareas', TareaViewSet, basename='tarea')
router.register(r'tipos-tarea', TipoTareaViewSet, basename='tipo-tarea')
router.register(r'documentos-requeridos', DocumentoRequeridoTipoTareaViewSet, basename='documento-requerido')
router.register(r'documentos-tarea', TareaDocumentoViewSet, basename='documento-tarea')
urlpatterns = [
    path('', include(router.urls)),
]