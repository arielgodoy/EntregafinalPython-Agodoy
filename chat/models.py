from django.db import models
from django.contrib.auth.models import User
# Create your models here.





class Conversacion(models.Model):
    participantes = models.ManyToManyField(User, related_name='conversaciones')
    def __str__(self):
        return ', '.join([str(participante) for participante in self.participantes.all()])

class Mensaje(models.Model):
    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name='mensajes')
    remitente = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mensajes_enviados')
    contenido = models.TextField()
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.remitente}: {self.contenido}'