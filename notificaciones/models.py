from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

from access_control.models import Empresa


class Notification(models.Model):
    class Tipo(models.TextChoices):
        SYSTEM = "SYSTEM", "SYSTEM"
        ALERT = "ALERT", "ALERT"
        MESSAGE = "MESSAGE", "MESSAGE"

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, null=True, blank=True)
    destinatario = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notificaciones_recibidas")
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="notificaciones_emitidas")
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    titulo = models.CharField(max_length=255)
    cuerpo = models.TextField(blank=True)
    url = models.CharField(max_length=500, blank=True)
    dedupe_key = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["destinatario", "is_read"]),
            models.Index(fields=["empresa", "destinatario", "created_at"]),
            models.Index(fields=["dedupe_key", "destinatario"]),
        ]

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])

    def __str__(self):
        return f"{self.destinatario.username} - {self.tipo} - {self.titulo}"


class DemoSeedLog(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name="demo_seed_logs")
    created_by_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="demo_seed_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    payload_json = models.JSONField(default=dict)

    def __str__(self):
        return f"DemoSeedLog {self.empresa_id} {self.created_at}"
