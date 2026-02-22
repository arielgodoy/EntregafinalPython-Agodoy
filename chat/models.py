from django.db import models
from django.contrib.auth.models import User
from access_control.models import Empresa
from django.utils import timezone
# Create your models here.





class Conversacion(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='conversaciones')
    participantes = models.ManyToManyField(User, related_name='conversaciones')
    is_group = models.BooleanField(default=False)
    nombre = models.CharField(max_length=200, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        title = self.nombre if self.is_group and self.nombre else ', '.join([str(p) for p in self.participantes.all()])
        return title

    @classmethod
    def get_or_create_dm(cls, empresa_id, user_a_id, user_b_id):
        """Return existing direct conversation between two users in company or create one."""
        if user_a_id == user_b_id:
            raise ValueError("cannot_create_dm_with_self")

        qs = cls.objects.filter(empresa_id=empresa_id, is_group=False)
        # Find conversation with exactly these two participants
        existing = (
            qs.filter(participantes__id=user_a_id)
            .filter(participantes__id=user_b_id)
            .annotate(participant_count=models.Count('participantes'))
            .filter(participant_count=2)
            .first()
        )
        if existing:
            return existing, False

        conv = cls.objects.create(empresa_id=empresa_id, is_group=False)
        conv.participantes.set([user_a_id, user_b_id])
        return conv, True

    def is_participant(self, user):
        return self.participantes.filter(id=getattr(user, 'id', user)).exists()

    def display_name_for(self, user):
        if self.is_group:
            return self.nombre or 'Grupo'
        others = [p.username for p in self.participantes.all() if p.id != getattr(user, 'id', user)]
        return others[0] if others else getattr(user, 'username', str(user))

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