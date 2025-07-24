from django.urls import path

from .views import ImportarPersonasView

app_name = 'evaluaciones'

urlpatterns = [
     path("importar-personas/", ImportarPersonasView.as_view(), name="importar_personas"),
]
