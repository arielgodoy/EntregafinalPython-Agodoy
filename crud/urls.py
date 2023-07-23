from . import views
from django.urls import path
from django.contrib.auth.views import LogoutView
from django.conf import settings
from django.conf.urls.static import static




urlpatterns = [    
   
    path('', views.inicio, name='inicio'),    
    path('listarDocs/', views.ListarDocsView.as_view(), name='listarDocs'), #claseView
    path('crea-Docs/', views.creaDocs, name='creaDocs'),
    path('update-Docs/<int:id>', views.updateDocs, name='updateDocs'),
    path('delete-Docs/<int:id>', views.deleteDocs, name='deleteDocs'),

    path('listarPropiedades/', views.ListarPropiedadesView.as_view(), name='listarPropiedades'), #claseView
    path('crea-Propiedades/', views.creaPropiedades, name='creaPropiedades'),
    path('update-Propiedades/<int:id>', views.updatePropiedades, name='updatePropiedades'),
    path('delete-Propiedades/<int:id>', views.deletePropiedades, name='deletePropiedades'),

    path('listarPropietarios/', views.ListarPropietariosView.as_view(), name='listarPropietarios'), #claseView
    path('crea-Propietario/', views.creaPropietario, name='creaPropietario'),
    path('update-Propietario/<int:id>', views.updatePropietario, name='updatePropietario'),
    path('delete-Propietario/<int:id>', views.deletePropietario, name='deletePropietario'),


    path('login', views.login_request, name='login'),
    path('register', views.register , name='register'),
    path('logout', LogoutView.as_view(template_name='logout.html'), name='logout'),
    path('editarUsuario', views.editarUsuario, name='editarUsuario'),
    path('subeavatar', views.subeAvatar, name='subeavatar'),

    path('conversaciones/', views.lista_conversaciones, name='lista_conversaciones'),
    path('conversaciones/<int:conversacion_id>/enviar-mensaje/', views.enviar_mensaje, name='enviar_mensaje'),
    path('conversaciones/crear/', views.crear_conversacion, name='crear_conversacion'),
    path('conversaciones/<int:conversacion_id>/', views.detalle_conversacion, name='detalle_conversacion'),
    # Otras URLs
        
]

urlpatterns+=static(settings.MEDIA_URL,document_root=settings.MEDIA_ROOT)