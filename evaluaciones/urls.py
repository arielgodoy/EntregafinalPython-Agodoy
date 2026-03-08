from django.urls import path

from .views import ImportarPersonasStartView, ImportarPersonasStatusView, ImportarPersonasView

app_name = 'evaluaciones'

urlpatterns = [
     path("importar-personas/", ImportarPersonasView.as_view(), name="importar_personas"),
     path("importar-personas/start/", ImportarPersonasStartView.as_view(), name="importar_personas_start"),
     path("importar-personas/status/", ImportarPersonasStatusView.as_view(), name="importar_personas_status"),
]
