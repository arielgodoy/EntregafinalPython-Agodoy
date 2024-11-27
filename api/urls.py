from django.urls import path, include
from rest_framework import routers
from api.views import CompanyViewSet, PersonaViewSet  # Asegúrate de tener un ViewSet para cada recurso

router = routers.DefaultRouter()
router.register(r'companies', CompanyViewSet, basename='companies')  # Para empresas
router.register(r'personas', PersonaViewSet, basename='personas')    # Para personas

urlpatterns = [
    path('', include(router.urls)),
]
