from django.db import models
from django.contrib.auth.models import User
from django.core.validators import RegexValidator


class Empresa(models.Model):

    codigo = models.CharField(
    max_length=2,
    unique=True,
    validators=[
        RegexValidator(
            regex=r'^\d{2}$',
            message="El código debe ser un número de 2 dígitos entre 00 y 99."
        )
    ],
    verbose_name="Código"
)

    
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.codigo} - {self.descripcion or 'Sin descripción'}"


class Vista(models.Model):
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nombre


class Permiso(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    vista = models.ForeignKey(Vista, on_delete=models.CASCADE)
    ingresar = models.BooleanField(default=False)
    crear = models.BooleanField(default=False)
    modificar = models.BooleanField(default=False)
    eliminar = models.BooleanField(default=False)
    autorizar = models.BooleanField(default=False)
    supervisor = models.BooleanField(default=False)

    class Meta:
        unique_together = ('usuario', 'empresa', 'vista')

    def __str__(self):
        return f"{self.usuario.username} - {self.vista.nombre} - {self.empresa.descripcion or 'Sin descripción'}"


class PerfilAcceso(models.Model):
    nombre = models.CharField(max_length=150, unique=True)
    descripcion = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre


class PerfilAccesoDetalle(models.Model):
    perfil = models.ForeignKey(PerfilAcceso, on_delete=models.CASCADE, related_name='detalles')
    vista = models.ForeignKey(Vista, on_delete=models.CASCADE)
    ingresar = models.BooleanField(default=False)
    crear = models.BooleanField(default=False)
    modificar = models.BooleanField(default=False)
    eliminar = models.BooleanField(default=False)
    autorizar = models.BooleanField(default=False)
    supervisor = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['perfil', 'vista'], name='uniq_perfil_vista'),
        ]

    def __str__(self):
        return f"{self.perfil.nombre} - {self.vista.nombre}"


class UsuarioPerfilEmpresa(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    perfil = models.ForeignKey(PerfilAcceso, on_delete=models.PROTECT)
    asignado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='perfiles_asignados')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['usuario', 'empresa'], name='uniq_usuario_empresa_perfil'),
        ]

    def __str__(self):
        return f"{self.usuario.username} - {self.empresa.codigo} - {self.perfil.nombre}"


class AccessRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "PENDING"
        APPROVED = "APPROVED", "APPROVED"
        REJECTED = "REJECTED", "REJECTED"
        RESPONDED = "RESPONDED", "RESPONDED"
        RESOLVED = "RESOLVED", "RESOLVED"

    class EmailStatus(models.TextChoices):
        SKIPPED = "SKIPPED", "SKIPPED"
        SENT = "SENT", "SENT"
        FAILED = "FAILED", "FAILED"

    solicitante = models.ForeignKey(User, on_delete=models.CASCADE, related_name="access_requests")
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, null=True, blank=True)
    vista_nombre = models.CharField(max_length=255)
    motivo = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    responded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="access_requests_responded",
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    response_text = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="access_requests_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_note = models.TextField(blank=True)
    email_attempted = models.BooleanField(default=False)
    email_sent = models.BooleanField(default=False)
    email_status = models.CharField(
        max_length=20,
        choices=EmailStatus.choices,
        default=EmailStatus.SKIPPED,
    )
    email_from = models.TextField(blank=True, default="")
    email_error = models.TextField(blank=True, default="")
    email_recipients = models.TextField(blank=True, default="")
    staff_recipient_ids = models.TextField(blank=True, default="")
    notified_staff_count = models.PositiveIntegerField(default=0)
    emailed_at = models.DateTimeField(null=True, blank=True)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["solicitante", "status", "created_at"]),
            models.Index(fields=["empresa", "vista_nombre", "status"]),
        ]

    def __str__(self):
        return (
            f"{self.solicitante.username} - {self.vista_nombre} - {self.status} "
            f"- email_status={self.email_status}"
        )
