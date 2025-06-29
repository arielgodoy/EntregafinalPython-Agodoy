# urls.py
from django.urls import path,include
from . import views
from django.conf import settings
from django.conf.urls.static import static
from .views import ListadoDocumentosView
from .views import respaldo_biblioteca_zip
from .views import descargar_documentos_propiedad_zip
from .views import CrearPropietarioModalView


app_name = 'biblioteca'
urlpatterns = [
    #path('acounts/',include('acounts.urls')),
    path('modales-ejemplo/', views.ModalesEjemploView.as_view(), name='modales_ejemplo'),
    path('', views.ListarPropiedadesView.as_view(), name='listar_propiedades'),  # Redirigir a la lista de propiedades
    path('propiedades/<int:pk>/', views.DetallePropiedadView.as_view(), name='detalle_propiedad'),
    path('propiedades/<int:pk>/crear_documento/', views.CrearDocumentoView.as_view(), name='crear_documento'),
    path('documentos/<int:pk>/eliminar/', views.EliminarDocumentoView.as_view(), name='eliminar_documento'),
   

    path('ingresar_propietario/', views.CrearPropietarioView.as_view(), name='crear_propietario'),
    path('listar_propietarios/', views.ListarPropietariosView.as_view(), name='listar_propietarios'),
    path('propietarios/<int:pk>/', views.DetallePropietarioView.as_view(), name='detalle_propietario'),
    path('propietarios/<int:pk>/eliminar/', views.EliminarPropietarioView.as_view(), name='eliminar_propietario'),
    path('propietarios/<int:pk>/modificar/', views.ModificarPropietarioView.as_view(), name='modificar_propietario'),
    #path('propietario/nuevo/modal/', views.crear_propietario_modal, name='crear_propietario_modal'),
    path('crear-propietario-modal/', CrearPropietarioModalView.as_view(), name='crear_propietario_modal'),


    path('ingresar_propiedad/', views.CrearPropiedadView.as_view(), name='crear_propiedad'),
    path('ingresar_propiedad/<int:propietario_id>/', views.CrearPropiedadView.as_view(), name='crear_propiedad'),

    path('propiedades/<int:pk>/eliminar/', views.EliminarPropiedadView.as_view(), name='eliminar_propiedad'),
    path('propiedades/<int:pk>/modificar/', views.ModificarPropiedadView.as_view(), name='modificar_propiedad'),


    path('crear_tipo_documento/', views.CrearTipoDocumentoView.as_view(), name='crear_tipo_documento'),
    path('listar_tipos_documentos/', views.ListarTiposDocumentosView.as_view(), name='listar_tipos_documentos'),
    path('modificar_tipo_documento/<int:pk>/', views.ModificarTipoDocumentoView.as_view(), name='modificar_tipo_documento'),
    path('eliminar_tipo_documento/<int:pk>/', views.EliminarTipoDocumentoView.as_view(), name='eliminar_tipo_documento'),
    
    path('enviar-enlace/<int:documento_id>/', views.enviar_enlace_documento, name='enviar_enlace_documento'),

    path('documentos/listado/', ListadoDocumentosView.as_view(), name='listado_documentos'),    
    path('respaldo/descargar-zip/', respaldo_biblioteca_zip, name='respaldo_biblioteca_zip'),
    path('descargar/rol/<int:propiedad_id>/zip/', descargar_documentos_propiedad_zip, name='descargar_documentos_rol'),



    
    



    

]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)