from django.urls import path

from .views import (
    BaseEvaluacionesSchemaInstallView,
    EvaluacionesConnectionProbeView,
    EvaluacionesConnectionRolesView,
    ImportarPersonasStartView,
    ImportarPersonasStatusView,
    ImportarPersonasView,
)

app_name = 'evaluaciones'

urlpatterns = [
     path("importar-personas/", ImportarPersonasView.as_view(), name="importar_personas"),
     path("importar-personas/start/", ImportarPersonasStartView.as_view(), name="importar_personas_start"),
     path("importar-personas/status/", ImportarPersonasStatusView.as_view(), name="importar_personas_status"),
     path("conexiones-sql/", EvaluacionesConnectionRolesView.as_view(), name="connection_roles"),
     path(
         "conexiones-sql/probar/",
         EvaluacionesConnectionProbeView.as_view(),
         name="connection_probe",
     ),
     path(
         "conexiones-sql/base-evaluaciones/crear/",
         BaseEvaluacionesSchemaInstallView.as_view(),
         name="base_evaluaciones_schema_install",
     ),
]
