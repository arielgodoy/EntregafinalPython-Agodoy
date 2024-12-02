from django.urls import path
from . import views
from .views import UsuariosListaView,UsuarioEditarView, UsuarioEliminarView,UsuarioCrearView

app_name = 'access_control'  # Define el espacio de nombres

urlpatterns = [
    path('usuarios/', UsuariosListaView.as_view(), name='usuarios_lista'),
    path('usuarios/crear/', UsuarioCrearView.as_view(), name='usuario_crear'),
    path('usuarios/editar/<int:pk>/', UsuarioEditarView.as_view(), name='usuario_editar'),
    path('usuarios/eliminar/<int:pk>/', UsuarioEliminarView.as_view(), name='usuario_eliminar'),

    

    
    # path('empresas/', views.empresas_lista, name='empresas_lista'),
    # path('empresas/crear/', views.empresa_crear, name='empresa_crear'),
    # path('empresas/editar/<int:pk>/', views.empresa_editar, name='empresa_editar'),
    # path('empresas/eliminar/<int:pk>/', views.empresa_eliminar, name='empresa_eliminar'),

    # path('permisos/<int:usuario_id>/<int:empresa_id>/', views.permisos_editar, name='permisos_editar'),
]
