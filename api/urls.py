from django.urls import path, include
from rest_framework import routers
from api.views import PropietarioViewSet,TrabajadoresViewSet

router = routers.DefaultRouter()

router.register(r'propietarios', PropietarioViewSet, basename='propietarios')
router.register(r'trabajadores', TrabajadoresViewSet, basename='trabajadores')


urlpatterns = [
    path('', include(router.urls)),
]
