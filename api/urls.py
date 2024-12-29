from django.urls import path, include
from rest_framework import routers
from api.views import ContratopublicidadViewSet,LmovimientosDetalle19ViewSet,PropietarioViewSet

router = routers.DefaultRouter()


router.register(r'contratos', ContratopublicidadViewSet, basename='contratos')  # Para contratos
router.register(r'lmdetalle', LmovimientosDetalle19ViewSet, basename='lmdetalle')  # Para lmdetalle
router.register(r'propietarios', PropietarioViewSet  , basename='propietarios')  # Para lmdetalle


urlpatterns = [
    path('', include(router.urls)),
]
