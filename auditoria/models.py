from django.db import models
from django.contrib.auth import get_user_model

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
