from django.urls import path
from . import views
from .views import UsuariosListaView,UsuarioEditarView, UsuarioEliminarView,UsuarioCrearView
from .views import EmpresaListaView,EmpresaCrearView,EmpresaEditarView,EmpresaEliminarView
from .views import PermisoListaView,PermisoCrearView,PermisoEditarView,PermisoEliminarView
from .views import VistaListaView,VistaCrearView,VistaEditarView,VistaEliminarView
from .views import toggle_permiso,PermisosFiltradosView, CopyPermisosView, seleccionar_empresa


#from .views import permisos_filtrados_view, toggle_permiso,PermisosFiltradosView


app_name = 'access_control'  # Define el espacio de nombres

urlpatterns = [
    #path('permisos-filtrados/', permisos_filtrados_view, name='permisos_filtrados'),  
    #path("seleccionar_empresa/", SeleccionarEmpresaView.as_view(), name="seleccionar_empresa"),
    path('seleccionar_empresa/', views.seleccionar_empresa, name='seleccionar_empresa'), 
    path('copiar-permisos/', CopyPermisosView.as_view(), name='copy_permissions'),
    path('permisos-filtrados/', PermisosFiltradosView.as_view(), name='permisos_filtrados'), 
    

    
    path('toggle-permiso/', views.toggle_permiso, name='toggle_permiso'),

    path('vistas/', VistaListaView.as_view(), name='vistas_lista'),
    path('vistas/crear/', VistaCrearView.as_view(), name='vista_crear'),
    path('vistas/editar/<int:pk>/', VistaEditarView.as_view(), name='vista_editar'),
    path('vistas/eliminar/<int:pk>/', VistaEliminarView.as_view(), name='vista_eliminar'),

    path('permisos/', PermisoListaView.as_view(), name='permisos_lista'),
    path('permisos/crear/', PermisoCrearView.as_view(), name='permiso_crear'),
    path('permisos/editar/<int:pk>/', PermisoEditarView.as_view(), name='permiso_editar'),
    path('permisos/eliminar/<int:pk>/', PermisoEliminarView.as_view(), name='permiso_eliminar'),  


    path('usuarios/', UsuariosListaView.as_view(), name='usuarios_lista'),
    path('usuarios/crear/', UsuarioCrearView.as_view(), name='usuario_crear'),
    path('usuarios/editar/<int:pk>/', UsuarioEditarView.as_view(), name='usuario_editar'),
    path('usuarios/eliminar/<int:pk>/', UsuarioEliminarView.as_view(), name='usuario_eliminar'),


    path('empresas/', EmpresaListaView.as_view(), name='empresas_lista'),
    path('empresas/crear/', EmpresaCrearView.as_view(), name='empresa_crear'),
    path('empresas/editar/<int:pk>/', EmpresaEditarView.as_view(), name='empresa_editar'),
    path('empresas/eliminar/<int:pk>/', EmpresaEliminarView.as_view(), name='empresa_eliminar'),



    
    
]
