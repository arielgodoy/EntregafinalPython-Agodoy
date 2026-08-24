from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class AuditEventBase(models.Model):
    """
    Modelo abstracto base para eventos de auditoría.
    Define campos comunes para todas las tablas de auditoría por app.
    """
    
    # Acción realizada
    ACTION_CHOICES = [
        ('VIEW', 'Ver'),
        ('CREATE', 'Crear'),
        ('UPDATE', 'Actualizar'),
        ('DELETE', 'Eliminar'),
        ('DOWNLOAD', 'Descargar'),
        ('SHARE', 'Compartir'),
        ('EXECUTE', 'Ejecutar'),
        ('ERROR_403', 'Error 403 - Prohibido'),
        ('ERROR_500', 'Error 500 - Servidor'),
    ]
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, db_index=True)
    empresa_id = models.IntegerField(null=True, blank=True, db_index=True, help_text="ID de empresa desde session")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    
    # Información del objeto afectado (si aplica)
    object_type = models.CharField(max_length=100, null=True, blank=True, help_text="Ej: Documento, Propiedad")
    object_id = models.CharField(max_length=255, null=True, blank=True, help_text="ID del objeto como string")
    
    # Información de la petición HTTP
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, null=True, blank=True)  # CharField truncado automático
    method = models.CharField(max_length=10, null=True, blank=True, help_text="GET, POST, etc.")
    path = models.CharField(max_length=500, db_index=True)
    querystring = models.TextField(null=True, blank=True)
    status_code = models.IntegerField(null=True, blank=True, db_index=True)
    duration_ms = models.IntegerField(null=True, blank=True, help_text="Duración en milisegundos")
    vista_nombre = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    
    # Información de negocio
    message_key = models.CharField(max_length=255, null=True, blank=True, help_text="Clave i18n del mensaje")
    meta = models.JSONField(null=True, blank=True, help_text="Metadata adicional sanitizada")
    before = models.JSONField(null=True, blank=True, help_text="Estado anterior (UPDATE/DELETE)")
    after = models.JSONField(null=True, blank=True, help_text="Estado posterior (UPDATE/CREATE)")
    
    class Meta:
        abstract = True
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at', 'empresa_id']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['action', 'created_at']),
        ]
    
    def __str__(self):
        user_str = self.user.username if self.user else 'Anónimo'
        return f"{self.created_at} | {user_str} | {self.action} | {self.path}"


class AuditoriaBibliotecaEvent(AuditEventBase):
    """
    Eventos de auditoría específicos de la app biblioteca.
    Tabla concreta: auditoria_biblioteca_event
    """
    
    class Meta:
        db_table = 'auditoria_biblioteca_event'
        verbose_name = 'Evento de Auditoría Biblioteca'
        verbose_name_plural = 'Eventos de Auditoría Biblioteca'
        ordering = ['-created_at']


class AuditoriaGestionDTEEvent(AuditEventBase):
    """Eventos de auditoría específicos de la app gestiondte."""

    class Meta:
        db_table = 'auditoria_gestiondte_event'
        verbose_name = 'Evento de Auditoría Gestión DTE'
        verbose_name_plural = 'Eventos de Auditoría Gestión DTE'
        ordering = ['-created_at']


class UserPresence(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='audit_presence')
    empresa_id = models.IntegerField(null=True, blank=True, db_index=True)
    app_label = models.CharField(max_length=50, db_index=True)
    vista_nombre = models.CharField(max_length=255, null=True, blank=True)
    path = models.CharField(max_length=500)
    last_seen = models.DateTimeField(auto_now=True, db_index=True)

    @property
    def activity_status(self):
        seconds = (timezone.now() - self.last_seen).total_seconds()
        if seconds < 5 * 60:
            return 'Activo'
        if seconds <= 15 * 60:
            return 'Reciente'
        return 'Inactivo'

    class Meta:
        db_table = 'auditoria_user_presence'
        indexes = [
            models.Index(fields=['app_label', 'empresa_id', 'last_seen']),
        ]


class AuditArchiveBatch(models.Model):
    """Estado de archivado seguro de eventos de auditoría sin borrar el origen."""
    STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('completed', 'Completado'),
        ('failed', 'Fallido'),
    ]

    batch_id = models.CharField(max_length=255, db_index=True, unique=True)
    app_label = models.CharField(max_length=50, db_index=True)
    cutoff_datetime = models.DateTimeField(db_index=True)
    source_min_id = models.BigIntegerField(null=True, blank=True)
    source_max_id = models.BigIntegerField(null=True, blank=True)
    company_ids = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    archive_path = models.CharField(max_length=500, blank=True, default='')
    archive_count = models.PositiveIntegerField(default=0)
    source_checksum = models.CharField(max_length=128, blank=True, default='')
    archive_checksum = models.CharField(max_length=128, blank=True, default='')
    manifest = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        db_table = 'auditoria_archive_batch'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['app_label', 'cutoff_datetime', 'source_max_id']),
        ]

    def __str__(self):
        return f"{self.batch_id} ({self.app_label})"
