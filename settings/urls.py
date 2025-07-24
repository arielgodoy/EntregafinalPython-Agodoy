from django.urls import path
from .views import (
    configurar_email,  
    probar_configuracion_entrada,
    probar_configuracion_salida,
    enviar_correo_prueba,
    recibir_correo_prueba
    
    
)

urlpatterns = [
    path('configurar-email/', configurar_email, name='configurar_email'),
    path('probar-configuracion-entrada/', probar_configuracion_entrada, name='probar_configuracion_entrada'),
    path('probar-configuracion-salida/', probar_configuracion_salida, name='probar_configuracion_salida'),
    path('enviar-correo-prueba/', enviar_correo_prueba, name='enviar_correo_prueba'),
    path('recibir-correo-prueba/', recibir_correo_prueba, name='recibir_correo_prueba'),

    
]


