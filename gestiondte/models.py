import uuid
import re

from django.db import models, transaction
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from access_control.models import Empresa
from settings.models import SettingsMySQLConnection

def upload_to_certificado(instance, filename):
    return f'gestiondte/certificados/{instance.empresa_codigo}/{filename}'


class GestionDTEConnectionRole(models.Model):
    DATABASE_CONFIGURABLE_ROLES = frozenset({
        'serverbasedte',
        'serverauditoriagestiondte',
    })
    DATABASE_NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')

    ROLE_CHOICES = (
        ('serverbasedte', 'Base DTE'),
        ('serverauditoriagestiondte', 'Auditoría Gestión DTE'),
        ('servercontabilidad', 'Contabilidad'),
        ('serverauditoriacontabilidad', 'Auditoría Contabilidad'),
    )
    SOURCE_TYPE_CHOICES = (
        ('DJANGO', 'Sistema Django'),
        ('MYSQL_CONFIG', 'Conexión MySQL'),
    )

    role = models.CharField(max_length=40, choices=ROLE_CHOICES, unique=True)
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPE_CHOICES)
    django_alias = models.CharField(max_length=100, null=True, blank=True)
    database_name = models.CharField(max_length=64, null=True, blank=True)
    mysql_connection = models.ForeignKey(
        SettingsMySQLConnection,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='gestiondte_roles',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        source_type='DJANGO',
                        django_alias__isnull=False,
                        mysql_connection__isnull=True,
                    )
                    & ~models.Q(django_alias='')
                )
                | (
                    models.Q(
                        source_type='MYSQL_CONFIG',
                        django_alias__isnull=True,
                        mysql_connection__isnull=False,
                    )
                ),
                name='gestiondte_role_source_xor',
            ),
        ]

    def clean(self):
        from gestiondte.services.connection_roles import get_system_database_catalog

        errors = {}
        alias = (self.django_alias or '').strip()
        database_name = (self.database_name or '').strip()
        if self.source_type == 'DJANGO':
            if not alias:
                errors['django_alias'] = 'Debe seleccionar un alias Django SYSTEM.'
            elif alias not in {item['alias'] for item in get_system_database_catalog()}:
                errors['django_alias'] = 'El alias debe existir y estar clasificado como SYSTEM.'
            if self.mysql_connection_id is not None:
                errors['mysql_connection'] = 'No puede combinar alias Django y conexión MySQL.'
            self.django_alias = alias or None
            self.database_name = None
        elif self.source_type == 'MYSQL_CONFIG':
            if self.mysql_connection_id is None:
                errors['mysql_connection'] = 'Debe seleccionar una conexión MySQL activa.'
            elif not self.mysql_connection.is_active:
                errors['mysql_connection'] = 'La conexión MySQL seleccionada está inactiva.'
            if alias:
                errors['django_alias'] = 'No puede combinar conexión MySQL y alias Django.'
            self.django_alias = None
            if self.role in self.DATABASE_CONFIGURABLE_ROLES:
                if not database_name:
                    errors['database_name'] = 'Debe indicar una base de datos MySQL.'
                elif not self.DATABASE_NAME_PATTERN.fullmatch(database_name):
                    errors['database_name'] = 'El nombre de base de datos no es válido.'
                else:
                    self.database_name = database_name
            else:
                if database_name:
                    errors['database_name'] = 'Este rol no admite una base de datos por rol.'
                self.database_name = None
        else:
            errors['source_type'] = 'Tipo de conexión inválido.'

        if errors:
            raise ValidationError(errors)
        super().clean()


class CertificadoSII(models.Model):
    empresa_codigo = models.CharField(max_length=10, db_index=True)
    archivo = models.FileField(upload_to=upload_to_certificado)
    password_encrypted = models.BinaryField(null=True, blank=True)
    activo = models.BooleanField(default=False)
    titular = models.CharField(max_length=255, null=True, blank=True)
    emisor_certificado = models.CharField(max_length=255, null=True, blank=True)
    numero_serie = models.CharField(max_length=255, null=True, blank=True)
    rut_titular = models.CharField(max_length=64, null=True, blank=True)
    valido_desde = models.DateTimeField(null=True, blank=True)
    valido_hasta = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='certificados_creados')
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='certificados_actualizados')
    created_by_username = models.CharField(max_length=150, null=True, blank=True)
    updated_by_username = models.CharField(max_length=150, null=True, blank=True)

    class Meta:
        verbose_name = 'Certificado PFX'
        verbose_name_plural = 'Certificados PFX'
        ordering = ['-created_at']

    def set_password(self, plain: str):
        from .utils.crypto import encrypt_password
        if plain is None:
            self.password_encrypted = None
        else:
            self.password_encrypted = encrypt_password(plain)

    def get_password(self) -> str | None:
        from .utils.crypto import decrypt_password
        return decrypt_password(self.password_encrypted)

    def save(self, *args, **kwargs):
        # Persist then enforce single active per empresa_codigo
        with transaction.atomic():
            super().save(*args, **kwargs)
            if self.activo:
                self.__class__.objects.filter(empresa_codigo=self.empresa_codigo).exclude(pk=self.pk).update(activo=False)

    @property
    def estado_vigencia(self):
        from django.utils import timezone
        if not self.valido_hasta:
            return 'Desconocido'
        ahora = timezone.now()
        delta = (self.valido_hasta - ahora).days
        if ahora > self.valido_hasta:
            return 'Vencido'
        if delta <= 30:
            return 'Por vencer'
        return 'Vigente'

    def __str__(self):
        return f"Certificado {self.archivo.name} ({self.empresa_codigo})"


class TareaRPETC(models.Model):
    TIPO_CONSULTA_CHOICES = (
        ('DEUDOR', 'Deudor'),
        ('CEDENTE', 'Cedente'),
        ('CESIONARIO', 'Cesionario'),
    )
    FORMATO_CHOICES = (
        ('TXT', 'TXT'),
        ('XML', 'XML'),
    )

    empresa = models.ForeignKey(
        Empresa,
        to_field='codigo',
        db_column='empresa_codigo',
        on_delete=models.PROTECT,
        related_name='tareas_rpetc',
    )
    id_tarea = models.CharField(max_length=64, unique=True)
    tipo_consulta = models.CharField(max_length=20, choices=TIPO_CONSULTA_CHOICES)
    rut_consultado = models.CharField(max_length=12)
    dv_consultado = models.CharField(max_length=2)
    fecha_desde = models.DateField()
    fecha_hasta = models.DateField()
    formato = models.CharField(max_length=4, choices=FORMATO_CHOICES)
    rut_autenticado = models.CharField(max_length=12, null=True, blank=True)
    dv_autenticado = models.CharField(max_length=2, null=True, blank=True)
    nombre_tarea = models.CharField(max_length=100, null=True, blank=True)
    estado = models.CharField(max_length=30)
    resultado = models.CharField(max_length=100, null=True, blank=True)
    hora_creado_sii = models.DateTimeField(null=True, blank=True)
    hora_en_proceso_sii = models.DateTimeField(null=True, blank=True)
    hora_terminado_sii = models.DateTimeField(null=True, blank=True)
    file_size = models.PositiveBigIntegerField(null=True, blank=True)
    cantidad_lineas = models.PositiveIntegerField(null=True, blank=True)
    comprimido = models.BooleanField(null=True, blank=True)
    codigo_error = models.CharField(max_length=50, null=True, blank=True)
    descripcion_error = models.TextField(null=True, blank=True)
    parametros = models.JSONField(null=True, blank=True)
    parametros_raw = models.TextField(null=True, blank=True)
    consultada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-consultada_en']
        indexes = [
            models.Index(fields=['empresa', 'tipo_consulta'], name='rpetc_tarea_emp_tipo_idx'),
            models.Index(fields=['estado'], name='rpetc_tarea_estado_idx'),
            models.Index(fields=['fecha_desde', 'fecha_hasta'], name='rpetc_tarea_periodo_idx'),
        ]

    def __str__(self):
        return f'{self.nombre_tarea or self.tipo_consulta} - {self.id_tarea}'


class LecturaAutomaticaConfig(models.Model):
    INTERVALO_CHOICES = (
        (15, '15 minutos'),
        (30, '30 minutos'),
        (60, '1 hora'),
    )

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    habilitado = models.BooleanField(default=False)
    intervalo_minutos = models.PositiveSmallIntegerField(choices=INTERVALO_CHOICES, default=60)
    ultima_ejecucion = models.DateTimeField(null=True, blank=True)
    proxima_ejecucion = models.DateTimeField(null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return 'Configuración de lectura automática de cesiones'


class LecturaAutomaticaEjecucion(models.Model):
    TIPO_EJECUCION_CHOICES = (
        ('MANUAL', 'Manual'),
        ('AUTOMATICA', 'Automática'),
    )
    ESTADO_CHOICES = (
        ('PENDIENTE', 'Pendiente'),
        ('EN_PROCESO', 'En proceso'),
        ('ACTUALIZADO', 'Actualizado'),
        ('ERROR', 'Error'),
    )

    lote_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name='lecturas_automaticas')
    tipo_ejecucion = models.CharField(max_length=12, choices=TIPO_EJECUCION_CHOICES)
    fecha_desde = models.DateField()
    fecha_hasta = models.DateField()
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='PENDIENTE', db_index=True)
    progreso = models.PositiveSmallIntegerField(default=0)
    total_documentos = models.PositiveIntegerField(null=True, blank=True)
    documentos_procesados = models.PositiveIntegerField(default=0)
    fecha_inicio = models.DateTimeField(null=True, blank=True)
    fecha_termino = models.DateTimeField(null=True, blank=True)
    ultima_actualizacion = models.DateTimeField(auto_now=True)
    mensaje_error = models.TextField(null=True, blank=True)
    tarea_rpetc = models.ForeignKey(TareaRPETC, null=True, blank=True, on_delete=models.SET_NULL, related_name='lecturas_automaticas')

    class Meta:
        indexes = [
            models.Index(fields=['lote_id', 'estado'], name='lectura_auto_lote_estado_idx'),
            models.Index(fields=['empresa', 'estado'], name='lectura_auto_emp_estado_idx'),
        ]

    def __str__(self):
        return f'{self.empresa.codigo} - {self.estado}'


class CesionRPETC(models.Model):
    id_cesion = models.CharField(max_length=64, db_index=True)
    estado_cesion = models.CharField(max_length=80, db_index=True)
    vendedor_rut = models.CharField(max_length=12, null=True, blank=True, db_index=True)
    vendedor_dv = models.CharField(max_length=2, null=True, blank=True)
    deudor_rut = models.CharField(max_length=12, db_index=True)
    deudor_dv = models.CharField(max_length=2)
    deudor_email = models.EmailField(max_length=254, null=True, blank=True)
    tipo_doc = models.CharField(max_length=10)
    nombre_doc = models.CharField(max_length=100, null=True, blank=True)
    folio_doc = models.CharField(max_length=40)
    fecha_emision = models.DateField(null=True, blank=True, db_index=True)
    monto_total = models.DecimalField(max_digits=20, decimal_places=0, null=True, blank=True)
    cedente_rut = models.CharField(max_length=12, null=True, blank=True, db_index=True)
    cedente_dv = models.CharField(max_length=2, null=True, blank=True)
    cedente_razon_social = models.CharField(max_length=255, null=True, blank=True)
    cedente_email = models.EmailField(max_length=254, null=True, blank=True)
    cesionario_rut = models.CharField(max_length=12, null=True, blank=True, db_index=True)
    cesionario_dv = models.CharField(max_length=2, null=True, blank=True)
    cesionario_razon_social = models.CharField(max_length=255, null=True, blank=True)
    cesionario_email = models.EmailField(max_length=254, null=True, blank=True)
    fecha_cesion = models.DateTimeField(null=True, blank=True, db_index=True)
    monto_cesion = models.DecimalField(max_digits=20, decimal_places=0, null=True, blank=True)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    detectada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha_cesion', '-detectada_en']
        constraints = [
            models.UniqueConstraint(
                fields=['id_cesion', 'deudor_rut', 'deudor_dv', 'tipo_doc', 'folio_doc'],
                name='rpetc_cesion_identidad_unica',
            ),
        ]
        indexes = [
            models.Index(fields=['tipo_doc', 'folio_doc'], name='rpetc_cesion_doc_idx'),
        ]

    def __str__(self):
        return f'{self.id_cesion} - {self.tipo_doc}/{self.folio_doc}'


class RevisionCesionRPETC(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name='revisiones_cesiones_rpetc')
    cesion = models.ForeignKey(CesionRPETC, on_delete=models.CASCADE, related_name='revisiones')
    glosa = models.TextField(max_length=2000)
    creado_por = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='revisiones_cesiones_creadas')
    creado_en = models.DateTimeField(auto_now_add=True)
    modificado_por = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='revisiones_cesiones_modificadas')
    modificado_en = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'cesion'], name='revision_cesion_empresa_unica'),
        ]
        indexes = [
            models.Index(fields=['empresa', 'cesion'], name='revision_cesion_emp_idx'),
        ]


class RevisionCesionComentario(models.Model):
    revision = models.ForeignKey(
        RevisionCesionRPETC,
        on_delete=models.CASCADE,
        related_name='comentarios',
    )
    comentario = models.TextField(max_length=2000)
    creado_por = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='comentarios_revision_cesiones_creados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    modificado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['creado_en', 'pk']

    def __str__(self):
        return f'Revisión {self.revision_id} - comentario {self.pk}'


class EstadoContableCesion(models.Model):
    ESTADO_CONTABILIZACION_CHOICES = (
        ('CONTABILIZADA', 'Contabilizada'),
        ('NO_CONTABILIZADA', 'No contabilizada'),
        ('REVISAR', 'Revisar'),
        ('NO_DISPONIBLE', 'No disponible'),
    )
    ESTADO_PAGO_CHOICES = (
        ('PAGADA', 'Pagada'),
        ('NO_PAGADA', 'No pagada'),
        ('REVISAR', 'Revisar'),
        ('NO_DISPONIBLE', 'No disponible'),
    )
    ESTADO_PAGO_RESUMEN_CHOICES = (
        ('PENDIENTE', 'Pendiente'),
        ('PAGADA_FACTORING', 'Pagada a factoring'),
        ('PAGADA_PROVEEDOR', 'Pagada a proveedor'),
        ('PAGADA_AMBOS', 'Pagada a factoring y proveedor'),
        ('REVISAR', 'Revisar'),
        ('NO_DISPONIBLE', 'No disponible'),
    )
    ESTADO_VERIFICACION_CHOICES = (
        ('OK', 'Correcta'),
        ('ERROR', 'Error'),
    )

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name='estados_contables_cesiones')
    cesion = models.ForeignKey(CesionRPETC, on_delete=models.PROTECT, related_name='estados_contables')
    estado_contabilizacion = models.CharField(max_length=20, choices=ESTADO_CONTABILIZACION_CHOICES)
    estado_factoring = models.CharField(max_length=20, choices=ESTADO_PAGO_CHOICES)
    estado_proveedor = models.CharField(max_length=20, choices=ESTADO_PAGO_CHOICES)
    estado_pago_resumen = models.CharField(max_length=20, choices=ESTADO_PAGO_RESUMEN_CHOICES)
    fecha_pago_factoring = models.DateTimeField(null=True, blank=True)
    monto_pago_factoring = models.DecimalField(max_digits=20, decimal_places=0, null=True, blank=True)
    fecha_pago_proveedor = models.DateTimeField(null=True, blank=True)
    monto_pago_proveedor = models.DecimalField(max_digits=20, decimal_places=0, null=True, blank=True)
    fecha_verificacion = models.DateTimeField(default=timezone.now)
    estado_verificacion = models.CharField(max_length=5, choices=ESTADO_VERIFICACION_CHOICES, default='OK')
    mensaje_error = models.CharField(max_length=500, null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'cesion'], name='rpetc_estado_empresa_cesion_unico'),
        ]
        indexes = [
            models.Index(fields=['empresa', 'estado_pago_resumen'], name='rpetc_estado_emp_pago_idx'),
            models.Index(fields=['empresa', 'fecha_verificacion'], name='rpetc_estado_emp_verif_idx'),
        ]

    def __str__(self):
        return f'{self.empresa.codigo} - cesión {self.cesion_id} - {self.estado_pago_resumen}'


class TareaCesionRPETC(models.Model):
    ROL_CONSULTA_CHOICES = (
        ('DEUDOR', 'Deudor'),
        ('CEDENTE', 'Cedente'),
        ('CESIONARIO', 'Cesionario'),
    )

    tarea = models.ForeignKey(TareaRPETC, on_delete=models.CASCADE, related_name='cesiones')
    cesion = models.ForeignKey(CesionRPETC, on_delete=models.CASCADE, related_name='tareas')
    fecha_detectada = models.DateTimeField(auto_now_add=True)
    rol_consulta = models.CharField(max_length=20, choices=ROL_CONSULTA_CHOICES)
    fila_origen = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['tarea', 'cesion'], name='rpetc_tarea_cesion_unica'),
        ]
        indexes = [
            models.Index(fields=['rol_consulta'], name='rpetc_tarea_rol_idx'),
        ]


class CesionRPETCHistorial(models.Model):
    cesion = models.ForeignKey(
        CesionRPETC,
        on_delete=models.CASCADE,
        related_name='historial_estados',
    )
    estado = models.CharField(max_length=80)
    estado_anterior = models.CharField(max_length=80, null=True, blank=True)
    fecha_detectado = models.DateTimeField(auto_now_add=True)
    tarea_origen = models.ForeignKey(
        TareaRPETC,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='historial_cesiones',
    )
    observacion = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha_detectado']
        indexes = [
            models.Index(fields=['cesion', 'fecha_detectado'], name='rpetc_hist_cesion_fecha_idx'),
        ]
