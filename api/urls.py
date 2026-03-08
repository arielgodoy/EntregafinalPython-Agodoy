from django.urls import path, include
from rest_framework import routers
from api.views import PropietarioViewSet, TrabajadoresViewSet, invite_user, employees_active
from . import views_maestros

router = routers.DefaultRouter()

router.register(r'propietarios', PropietarioViewSet, basename='propietarios')
router.register(r'trabajadores', TrabajadoresViewSet, basename='trabajadores')


urlpatterns = [

    path(
        "maestros/rubros/",
        views_maestros.maestros_rubros_list,
        name="api_maestros_rubros_list"
    ),

    path(
        "maestros/rubros/<str:codigo>/",
        views_maestros.maestros_rubros_detail,
        name="api_maestros_rubros_detail"
    ),
    
    path('', include(router.urls)),
    path('employees/active/', employees_active, name='employees_active'),
    path('employees/active', employees_active),


    path('auth/invite/', invite_user, name='auth_invite'),
]
