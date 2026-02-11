from django.db import models
from django.contrib.auth.models import User
from access_control.models import Empresa
# Create your models here.





class Conversacion(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='conversaciones')
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


class MensajeLeido(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='mensajes_leidos')
    mensaje = models.ForeignKey(Mensaje, on_delete=models.CASCADE, related_name='leidos')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mensajes_leidos')
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['mensaje', 'user'], name='uniq_mensaje_user_leido'),
        ]
        indexes = [
            models.Index(fields=['user', 'mensaje']),
            models.Index(fields=['empresa', 'user']),
        ]

    def __str__(self):
        return f"{self.user_id} - {self.mensaje_id}"