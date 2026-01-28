from django.db import models
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import User
from access_control.models import Empresa
import os
from datetime import datetime


def archivo_tarea_path(instance, filename):
    """
    Genera ruta personalizada para archivos de tarea.
    Ejemplo: tareas_documentos/1/doc_20260128143022.pdf
    Usa IDs en lugar de nombres para evitar rutas muy largas en Windows
    """
    extension = os.path.splitext(filename)[1].lower()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    nombre = f"doc_{timestamp}{extension}"
    tarea_id = instance.tarea.id
    
    return f"tareas_documentos/{tarea_id}/{nombre}"


def validate_file_extension_tareas(value):
    """Valida que solo se carguen archivos permitidos"""
    extensiones_permitidas = ('.pdf', '.doc', '.docx', '.xlsx', '.xls', 
                              '.jpg', '.jpeg', '.png', '.gif', '.zip', '.rar')
    if not value.name.lower().endswith(extensiones_permitidas):
        raise ValidationError(
            'Formato no admitido. Permitidos: PDF, DOC, DOCX, XLSX, XLS, JPG, PNG, ZIP, RAR'
        )


def validar_rut(rut):
    """
    Valida RUT chileno verificando dígito verificador.
    Acepta formatos: XX.XXX.XXX-X o XXXXXXXX-X o XXXXXXXX-K
    """
    rut = rut.upper().replace(".", "").replace("-", "")
    cuerpo, dv = rut[:-1], rut[-1]

    suma = sum(int(cuerpo[::-1][i]) * (2 + i % 6) for i in range(len(cuerpo)))
    dv_esperado = 11 - (suma % 11)
    dv_esperado = '0' if dv_esperado == 11 else 'K' if dv_esperado == 10 else str(dv_esperado)

    if dv != dv_esperado:
        raise ValidationError(_("RUT inválido: dígito verificador incorrecto"))


def normalizar_rut(rut):
    """Normaliza RUT al formato XX.XXX.XXX-X"""
    rut = rut.upper().replace(".", "").replace("-", "").strip()
    if len(rut) < 2:
        return rut
    cuerpo = rut[:-1].zfill(8)
    dv = rut[-1]
    return f"{cuerpo[0:2]}.{cuerpo[2:5]}.{cuerpo[5:8]}-{dv}"


class TipoProyecto(models.Model):
    """Catálogo de tipos de proyectos (aprende automáticamente)"""
    nombre = models.CharField(max_length=100, unique=True)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = "Tipo de Proyecto"
        verbose_name_plural = "Tipos de Proyectos"

    def __str__(self):
        return f"{self.nombre} {'(Inactivo)' if not self.activo else ''}"


class EspecialidadProfesional(models.Model):
    """Catálogo de especialidades (aprende automáticamente)"""
    nombre = models.CharField(max_length=100, unique=True)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = "Especialidad Profesional"
        verbose_name_plural = "Especialidades Profesionales"

    def __str__(self):
        return f"{self.nombre} {'(Inactivo)' if not self.activo else ''}"


class ClienteEmpresa(models.Model):
    """Cliente externo (diferente de Empresa interna)"""
    nombre = models.CharField(max_length=150)
    rut = models.CharField(
        max_length=20,
        unique=True,
        validators=[validar_rut],
        help_text="Formato: XX.XXX.XXX-X"
    )
    telefono = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    direccion = models.TextField(blank=True)
    ciudad = models.CharField(max_length=100, blank=True)
    contacto_nombre = models.CharField(max_length=100, blank=True)
    contacto_telefono = models.CharField(max_length=20, blank=True)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = "Cliente Empresa"
        verbose_name_plural = "Clientes Empresas"

    def __str__(self):
        return f"{self.nombre} ({self.rut})"

    def save(self, *args, **kwargs):
        self.rut = normalizar_rut(self.rut)
        super().save(*args, **kwargs)


class Profesional(models.Model):
    """Profesional que trabaja en proyectos"""
    nombre = models.CharField(max_length=150)
    rut = models.CharField(
        max_length=20,
        unique=True,
        validators=[validar_rut],
        help_text="Formato: XX.XXX.XXX-X"
    )
    email = models.EmailField()
    telefono = models.CharField(max_length=20, blank=True)
    especialidad_texto = models.CharField(
        max_length=100,
        help_text="Especialidad (se normaliza automáticamente)"
    )
    especialidad_ref = models.ForeignKey(
        EspecialidadProfesional,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='profesionales'
    )
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='profesional_profile'
    )
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = "Profesional"
        verbose_name_plural = "Profesionales"

    def __str__(self):
        return f"{self.nombre} ({self.especialidad_texto})"

    def save(self, *args, **kwargs):
        # Normalizar RUT
        self.rut = normalizar_rut(self.rut)

        # Normalizar especialidad_texto
        especialidad_normalizada = self.especialidad_texto.strip().title()

        # Crear o obtener EspecialidadProfesional
        if especialidad_normalizada:
            especialidad_obj, _ = EspecialidadProfesional.objects.get_or_create(
                nombre=especialidad_normalizada,
                defaults={'activo': True}
            )
            self.especialidad_ref = especialidad_obj

        super().save(*args, **kwargs)


class Proyecto(models.Model):
    """Proyecto principal con relación a Empresa interna"""
    ESTADO_CHOICES = (
        ('FUTURO_ESTUDIO', 'Futuro Estudio'),
        ('EN_ESTUDIO', 'En Estudio'),
        ('EN_COTIZACION', 'En Cotización'),
        ('EN_EJECUCION', 'En Ejecución'),
        ('TERMINADO', 'Terminado'),
    )

    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    empresa_interna = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name='proyectos'
    )
    cliente = models.ForeignKey(
        ClienteEmpresa,
        on_delete=models.CASCADE,
        related_name='proyectos'
    )
    tipo_texto = models.CharField(
        max_length=100,
        help_text="Tipo de proyecto (se normaliza automáticamente)"
    )
    tipo_ref = models.ForeignKey(
        TipoProyecto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='proyectos'
    )
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='FUTURO_ESTUDIO'
    )
    profesionales = models.ManyToManyField(
        Profesional,
        related_name='proyectos',
        blank=True
    )
    fecha_inicio_estimada = models.DateField(null=True, blank=True)
    fecha_termino_estimada = models.DateField(null=True, blank=True)
    fecha_inicio_real = models.DateField(null=True, blank=True)
    fecha_termino_real = models.DateField(null=True, blank=True)
    presupuesto = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )
    monto_facturado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=0
    )
    observaciones = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = "Proyecto"
        verbose_name_plural = "Proyectos"
        unique_together = ('nombre', 'empresa_interna', 'cliente')

    def __str__(self):
        return f"{self.nombre} - {self.cliente.nombre} ({self.estado})"

    def save(self, *args, **kwargs):
        # Normalizar tipo_texto
        tipo_normalizado = self.tipo_texto.strip().title()

        # Crear o obtener TipoProyecto
        if tipo_normalizado:
            tipo_obj, _ = TipoProyecto.objects.get_or_create(
                nombre=tipo_normalizado,
                defaults={'activo': True}
            )
            self.tipo_ref = tipo_obj

        super().save(*args, **kwargs)


class Tarea(models.Model):
    """Tareas dentro de un proyecto"""
    PRIORIDAD_CHOICES = (
        ('BAJA', 'Baja'),
        ('MEDIA', 'Media'),
        ('ALTA', 'Alta'),
        ('URGENTE', 'Urgente'),
    )

    ESTADO_TAREA_CHOICES = (
        ('PENDIENTE', 'Pendiente'),
        ('EN_CURSO', 'En Curso'),
        ('BLOQUEADA', 'Bloqueada'),
        ('TERMINADA', 'Terminada'),
        ('CANCELADA', 'Cancelada'),
    )

    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.CASCADE,
        related_name='tareas'
    )
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    profesional_asignado = models.ForeignKey(
        Profesional,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    # Relación con Tipo de Tarea
    tipo_tarea = models.ForeignKey(
        'TipoTarea',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tareas'
    )
    
    # Estado
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_TAREA_CHOICES,
        default='PENDIENTE'
    )
    prioridad = models.CharField(
        max_length=20,
        choices=PRIORIDAD_CHOICES,
        default='MEDIA'
    )
    
    # Fechas de planificación (Gantt)
    fecha_inicio_plan = models.DateField(null=True, blank=True)
    fecha_fin_plan = models.DateField(null=True, blank=True)
    
    # Fechas reales (Gantt)
    fecha_inicio_real = models.DateField(null=True, blank=True)
    fecha_fin_real = models.DateField(null=True, blank=True)
    
    # Campos heredados (mantener compatibilidad)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_termino_estimada = models.DateField(null=True, blank=True)
    fecha_termino_real = models.DateField(null=True, blank=True)
    
    # Gantt - Progreso y horas
    porcentaje_avance = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    horas_estimadas = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True
    )
    horas_reales = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    # Dependencias (Gantt)
    depende_de = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='tareas_dependientes'
    )
    
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['proyecto', '-prioridad', '-fecha_creacion']
        verbose_name = "Tarea"
        verbose_name_plural = "Tareas"

    def __str__(self):
        return f"{self.nombre} ({self.proyecto.nombre})"
    
    def puede_marcar_terminada(self):
        """Verifica si la tarea puede marcarse como terminada"""
        # No permitir si faltan documentos SALIDA obligatorios entregados/aprobados
        docs_salida_obligatorios = self.documentos.filter(
            tipo_doc='SALIDA',
            es_obligatorio=True
        ).exclude(
            estado__in=['ENTREGADO', 'APROBADO']
        )
        return not docs_salida_obligatorios.exists()
    
    def marcar_bloqueada_si_necesario(self):
        """Marca bloqueada si hay documentos obligatorios rechazados"""
        docs_rechazados = self.documentos.filter(
            es_obligatorio=True,
            estado='RECHAZADO'
        )
        if docs_rechazados.exists() and self.estado != 'BLOQUEADA':
            self.estado = 'BLOQUEADA'
            self.save()
            return True
        return False
    
    def puede_marcar_en_curso(self):
        """Verifica si la tarea puede marcar como En curso"""
        # Permitir solo si documentos ENTRADA obligatorios están Recibidos/Aprobados
        docs_entrada_obligatorios = self.documentos.filter(
            tipo_doc='ENTRADA',
            es_obligatorio=True
        ).exclude(
            estado__in=['RECIBIDO', 'APROBADO']
        )
        return not docs_entrada_obligatorios.exists()


class TipoTarea(models.Model):
    """Catálogo de tipos de tareas con documentos requeridos"""
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = "Tipo de Tarea"
        verbose_name_plural = "Tipos de Tareas"

    def __str__(self):
        return f"{self.nombre} {'(Inactivo)' if not self.activo else ''}"


class DocumentoRequeridoTipoTarea(models.Model):
    """Define los documentos requeridos para cada tipo de tarea"""
    TIPO_DOCUMENTO_CHOICES = (
        ('ENTRADA', 'Entrada'),
        ('SALIDA', 'Salida'),
    )
    CATEGORIA_CHOICES = (
        ('ESPECIFICACION', 'Especificación'),
        ('DISEÑO', 'Diseño'),
        ('CODIGO', 'Código'),
        ('PRUEBA', 'Prueba'),
        ('DOCUMENTACION', 'Documentación'),
        ('APROBACION', 'Aprobación'),
        ('OTRO', 'Otro'),
    )

    tipo_tarea = models.ForeignKey(
        TipoTarea,
        on_delete=models.CASCADE,
        related_name='documentos_requeridos'
    )
    nombre_documento = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True)
    es_obligatorio = models.BooleanField(default=True)
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES)
    tipo_doc = models.CharField(max_length=10, choices=TIPO_DOCUMENTO_CHOICES)
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tipo_tarea', 'tipo_doc', 'orden']
        verbose_name = "Documento Requerido por Tipo Tarea"
        verbose_name_plural = "Documentos Requeridos por Tipo Tarea"
        unique_together = ('tipo_tarea', 'nombre_documento')

    def __str__(self):
        return f"{self.tipo_tarea.nombre} - {self.nombre_documento} ({self.get_tipo_doc_display()})"


class TareaDocumento(models.Model):
    """Documentos asociados a una tarea"""
    ESTADO_DOCUMENTO_CHOICES = (
        ('PENDIENTE', 'Pendiente'),
        ('ENVIADO', 'Enviado'),
        ('RECIBIDO', 'Recibido'),
        ('APROBADO', 'Aprobado'),
        ('RECHAZADO', 'Rechazado'),
        ('ENTREGADO', 'Entregado'),
    )
    TIPO_DOCUMENTO_CHOICES = (
        ('ENTRADA', 'Entrada'),
        ('SALIDA', 'Salida'),
    )

    tarea = models.ForeignKey(
        Tarea,
        on_delete=models.CASCADE,
        related_name='documentos'
    )
    nombre_documento = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True)
    tipo_doc = models.CharField(max_length=10, choices=TIPO_DOCUMENTO_CHOICES)
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_DOCUMENTO_CHOICES,
        default='PENDIENTE'
    )
    es_obligatorio = models.BooleanField(default=False)
    categoria = models.CharField(max_length=20, blank=True)
    
    # Fechas
    fecha_esperada = models.DateField(null=True, blank=True)
    fecha_recibida = models.DateField(null=True, blank=True)
    fecha_aprobacion = models.DateField(null=True, blank=True)
    
    # Referencias a documentos
    documento_biblioteca = models.ForeignKey(
        'biblioteca.Documento',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tareas'
    )
    url_documento = models.URLField(blank=True)
    archivo = models.FileField(
        upload_to=archivo_tarea_path,
        validators=[validate_file_extension_tareas],
        blank=True,
        max_length=500
    )
    
    # Información adicional
    observaciones = models.TextField(blank=True)
    responsable = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['tarea', 'tipo_doc', 'nombre_documento']
        verbose_name = "Documento Tarea"
        verbose_name_plural = "Documentos Tareas"

    def __str__(self):
        return f"{self.tarea.nombre} - {self.nombre_documento}"