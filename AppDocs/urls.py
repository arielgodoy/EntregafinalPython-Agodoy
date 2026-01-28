"""
URL configuration for AppDocs project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("", include("biblioteca.urls")),
    path('acounts/',include('acounts.urls')),
    path('chat/',include('chat.urls')),
    path('admin/', admin.site.urls),
    path('api/v1/',include('api.urls')),
    path('api/v1/control-proyectos/', include('control_de_proyectos.api_urls')),
    #path('access-control/', include('access_control.urls')), 
    path('access-control/', include('access_control.urls', namespace='access_control')),
    path('control-proyectos/', include('control_de_proyectos.urls', namespace='control_de_proyectos')),
    path('settings/', include('settings.urls')),
    path('evaluaciones/', include('evaluaciones.urls')),

]

# Servir archivos multimedia en desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
