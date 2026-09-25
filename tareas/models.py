"""Persistent Phase 1/2 domain for internal tasks."""

import re
from decimal import Decimal
from os.path import splitext
from urllib.parse import urlparse

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from access_control.models import Empresa


class FormatoArchivo(models.TextChoices):
    PDF = "PDF", "PDF"
    JPG = "JPG", "JPG"
    JPEG = "JPEG", "JPEG"
    PNG = "PNG", "PNG"
    DOC = "DOC", "DOC"
    DOCX = "DOCX", "DOCX"
    XLS = "XLS", "XLS"
    XLSX = "XLSX", "XLSX"


def formato_coincide_extension(formato, extension):
    if formato in {FormatoArchivo.JPG, FormatoArchivo.JPEG}:
        return extension in {"jpg", "jpeg"}
    return extension == formato.lower()


class Tarea(models.Model):
    """Tarea interna de una empresa.

    Ciclo de vida: nace en BORRADOR (puede permanecer indefinidamente) y pasa a
    PUBLICADA mediante publicar(). La publicación es irreversible (Q2) y exige
    responsable válido/activo (Q1).
    """

    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "BORRADOR"
        ACTIVA = "ACTIVA", "ACTIVA"
        GESTION = "GESTION", "GESTION"
        PENDIENTE_APROBACION_CIERRE = (
            "PENDIENTE_APROBACION_CIERRE",
            "PENDIENTE_APROBACION_CIERRE",
        )
        CERRADA = "CERRADA", "CERRADA"

    class Prioridad(models.TextChoices):
        SIMPLE = "SIMPLE", "SIMPLE"
        NORMAL = "NORMAL", "NORMAL"
        URGENTE = "URGENTE", "URGENTE"
        CRITICA = "CRITICA", "CRITICA"

    class Ambito(models.TextChoices):
        LOCAL = "LOCAL", "LOCAL"
        DEPARTAMENTO = "DEPARTAMENTO", "DEPARTAMENTO"

    titulo = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, default="")
    prioridad = models.CharField(
        max_length=10,
        choices=Prioridad.choices,
        default=Prioridad.NORMAL,
    )
    correlativo = models.CharField(max_length=9)
    anulada = models.BooleanField(default=False)
    fechas_pendientes_confirmacion = models.BooleanField(default=False)
    cierre_completado = models.BooleanField(default=False)
    requiere_evidencia_cierre = models.BooleanField(default=False)
    estado = models.CharField(
        max_length=32,
        choices=Estado.choices,
        default=Estado.BORRADOR,
    )
    responsable = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tareas_responsable",
    )
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.PROTECT,
        related_name="tareas",
    )
    tipo_ambito = models.CharField(
        max_length=12,
        choices=Ambito.choices,
        null=True,
        blank=True,
    )
    local = models.ForeignKey(
        "organizacion.Local",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tareas",
    )
    departamento = models.ForeignKey(
        "organizacion.Departamento",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tareas",
    )
    creada_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="tareas_creadas",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_publicacion = models.DateTimeField(null=True, blank=True)
    fecha_asignacion = models.DateTimeField(null=True, blank=True)
    fecha_tope = models.DateField(null=True, blank=True)
    fecha_cumplimiento = models.DateTimeField(null=True, blank=True)
    todo_origen = models.ForeignKey(
        "Todo",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tareas_origen",
    )
    tarea_origen = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tareas_derivadas",
    )

    class Meta:
        indexes = [
            models.Index(fields=["empresa", "estado"]),
            models.Index(fields=["empresa", "fecha_creacion"]),
            models.Index(fields=["empresa", "correlativo"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "correlativo"],
                name="tareas_empresa_correlativo_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(todo_origen__isnull=True)
                | models.Q(tarea_origen__isnull=True),
                name="tareas_unico_origen_canonico",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        tipo_ambito__isnull=True,
                        local__isnull=True,
                        departamento__isnull=True,
                    )
                    | models.Q(
                        tipo_ambito="",
                        local__isnull=True,
                        departamento__isnull=True,
                    )
                    | models.Q(
                        tipo_ambito="LOCAL",
                        local__isnull=False,
                        departamento__isnull=True,
                    )
                    | models.Q(
                        tipo_ambito="DEPARTAMENTO",
                        local__isnull=True,
                        departamento__isnull=False,
                    )
                ),
                name="tareas_ambito_xor",
            ),
        ]

    def __str__(self):
        return f"{self.titulo} ({self.get_estado_display()})"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("tareas:detalle_tarea", kwargs={"pk": self.pk})

    def _responsable_es_valido(self):
        """Responsable asignado y activo (Q1)."""
        return self.responsable is not None and self.responsable.is_active

    def save(self, *args, **kwargs):
        if self._state.adding and not self.correlativo:
            if not self.empresa_id:
                raise ValidationError("Una tarea requiere empresa para reservar correlativo.")
            from .services.correlativos import reserve_next_number

            with transaction.atomic(using=kwargs.get("using")):
                self.correlativo = f"B{reserve_next_number(self.empresa_id):07d}"
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    def clean(self):
        """Reglas respaldadas por spec/clarifications.

        - FR-008/Q2: una PUBLICADA debe conservar responsable válido y
          fecha_publicacion fijada e inmutable; no puede volver a BORRADOR.

        Nota: la empresa NO es inmutable a nivel de modelo (regla descartada por no
        estar respaldada por la spec); el aislamiento multiempresa se garantiza en las
        vistas/querysets.
        """
        super().clean()
        errores = {}

        if self.todo_origen_id and self.tarea_origen_id:
            errores["todo_origen"] = (
                "Una tarea no puede tener TO-DO y tarea como origen canónico simultáneamente."
            )
        if self.todo_origen_id and self.empresa_id != self.todo_origen.empresa_id:
            errores["todo_origen"] = "El TO-DO de origen debe pertenecer a la misma empresa."
        if self.tarea_origen_id and self.empresa_id != self.tarea_origen.empresa_id:
            errores["tarea_origen"] = "La tarea de origen debe pertenecer a la misma empresa."

        if self.tipo_ambito in (None, ""):
            if self.local_id:
                errores["tipo_ambito"] = (
                    "Una dimensión Local requiere tipo_ambito=LOCAL."
                )
            if self.departamento_id:
                errores["tipo_ambito"] = (
                    "Una dimensión Departamento requiere tipo_ambito=DEPARTAMENTO."
                )
        elif self.tipo_ambito == self.Ambito.LOCAL:
            if not self.local_id:
                errores["local"] = "El ámbito LOCAL requiere un Local."
            if self.departamento_id:
                errores["departamento"] = (
                    "El ámbito LOCAL no puede tener Departamento."
                )
        elif self.tipo_ambito == self.Ambito.DEPARTAMENTO:
            if not self.departamento_id:
                errores["departamento"] = "El ámbito DEPARTAMENTO requiere un Departamento."
            if self.local_id:
                errores["local"] = "El ámbito DEPARTAMENTO no puede tener Local."

        if self.local_id and self.local.empresa_id != self.empresa_id:
            errores["local"] = "El Local debe pertenecer a la misma empresa que la tarea."
        if (
            self.departamento_id
            and self.departamento.empresa_id != self.empresa_id
        ):
            errores["departamento"] = (
                "El Departamento debe pertenecer a la misma empresa que la tarea."
            )

        if self.estado in {
            self.Estado.ACTIVA,
            self.Estado.GESTION,
            self.Estado.PENDIENTE_APROBACION_CIERRE,
            self.Estado.CERRADA,
        }:
            if not self._responsable_es_valido():
                errores["responsable"] = (
                    "Una tarea publicada debe tener un responsable válido y activo."
                )
            if self.fecha_publicacion is None:
                errores["fecha_publicacion"] = (
                    "Una tarea publicada debe tener fecha de publicación."
                )

        if self.pk:
            original = (
                Tarea.objects.filter(pk=self.pk)
                .only("estado", "fecha_publicacion", "fecha_asignacion")
                .first()
            )
            if original is not None:
                if (
                    original.estado != self.Estado.BORRADOR
                    and self.estado == self.Estado.BORRADOR
                ):
                    errores["estado"] = (
                        "La publicación es irreversible: una tarea publicada no puede volver a borrador."
                    )
                if (
                    original.estado != self.Estado.BORRADOR
                    and original.fecha_publicacion
                    and self.fecha_publicacion != original.fecha_publicacion
                ):
                    errores["fecha_publicacion"] = (
                        "La fecha de publicación es inmutable."
                    )
                if (
                    original.estado != self.Estado.BORRADOR
                    and original.fecha_asignacion
                    and self.fecha_asignacion != original.fecha_asignacion
                ):
                    errores["fecha_asignacion"] = (
                        "La fecha de asignación es inmutable."
                    )

        if self.estado in {
            self.Estado.ACTIVA,
            self.Estado.GESTION,
            self.Estado.PENDIENTE_APROBACION_CIERRE,
            self.Estado.CERRADA,
        } and self.fecha_tope is None:
            errores["fecha_tope"] = (
                "Una tarea publicada debe tener fecha tope."
            )

        if errores:
            raise ValidationError(errores)

    def publicar(self, usuario=None):
        """Publica el borrador: exige responsable válido/activo (Q1, FR-007).

        Fija estado=PUBLICADA y fecha_publicacion (FR-008). Si el responsable falta o
        está inactivo, lanza ValidationError sin persistir (la tarea permanece en
        BORRADOR).
        """
        if self.estado != self.Estado.BORRADOR:
            raise ValidationError("La tarea ya está publicada.")
        if not self._responsable_es_valido():
            raise ValidationError(
                "No se puede publicar: la tarea requiere un responsable válido y activo."
            )
        if self.fecha_tope is None:
            raise ValidationError(
                "No se puede publicar: la tarea requiere fecha tope."
            )
        if not re.fullmatch(r"B[0-9]{7}", self.correlativo or ""):
            raise ValidationError(
                "No se puede publicar: el correlativo de borrador no es válido."
            )
        self.estado = self.Estado.ACTIVA
        self.correlativo = f"A{self.correlativo[1:]}"
        ahora = timezone.now()
        self.fecha_publicacion = ahora
        if self.fecha_asignacion is None:
            self.fecha_asignacion = ahora
        self.full_clean()
        self.save()
        TareaTransicion.objects.create(
            tarea=self,
            estado_origen=self.Estado.BORRADOR,
            estado_destino=self.Estado.ACTIVA,
            accion_evento="PUBLICAR",
            usuario=usuario or self.creada_por,
        )


class EvaluacionSimilitud(models.Model):
    class Decision(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        MISMO_PROBLEMA = "MISMO_PROBLEMA", "Mismo problema"
        DISTINTO_PROBLEMA = "DISTINTO_PROBLEMA", "Distinto problema"

    tarea = models.ForeignKey(
        Tarea,
        on_delete=models.PROTECT,
        related_name="evaluaciones_similitud",
    )
    tarea_candidata = models.ForeignKey(
        Tarea,
        on_delete=models.PROTECT,
        related_name="evaluaciones_como_candidata",
    )
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2)
    umbral_aplicado = models.DecimalField(max_digits=5, decimal_places=2)
    supera_umbral = models.BooleanField()
    decision = models.CharField(
        max_length=20,
        choices=Decision.choices,
        default=Decision.PENDIENTE,
    )
    confirmada_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evaluaciones_similitud_confirmadas",
    )
    confirmada_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tarea", "tarea_candidata"),
                name="unique_evaluacion_similitud_pareja",
            ),
            models.CheckConstraint(
                condition=~models.Q(tarea=models.F("tarea_candidata")),
                name="evaluacion_similitud_tareas_distintas",
            ),
            models.CheckConstraint(
                condition=models.Q(porcentaje__gte=0, porcentaje__lte=100),
                name="evaluacion_similitud_porcentaje_rango",
            ),
            models.CheckConstraint(
                condition=models.Q(umbral_aplicado__gte=0, umbral_aplicado__lte=100),
                name="evaluacion_similitud_umbral_rango",
            ),
        ]

    def clean(self):
        super().clean()
        errores = {}
        if self.tarea_id and self.tarea_candidata_id:
            if self.tarea_id == self.tarea_candidata_id:
                errores["tarea_candidata"] = "Una Tarea no puede compararse consigo misma."
            if self.tarea.empresa_id != self.tarea_candidata.empresa_id:
                errores["tarea_candidata"] = "Las Tareas deben pertenecer a la misma Empresa."
        if self.porcentaje is not None and not 0 <= self.porcentaje <= 100:
            errores["porcentaje"] = "El porcentaje debe estar entre 0 y 100."
        if self.umbral_aplicado is not None and not 0 <= self.umbral_aplicado <= 100:
            errores["umbral_aplicado"] = "El umbral debe estar entre 0 y 100."
        if self.decision == self.Decision.PENDIENTE:
            if self.confirmada_por_id or self.confirmada_at:
                errores["decision"] = "Una evaluación pendiente no puede tener confirmación."
        elif not self.confirmada_por_id or not self.confirmada_at:
            errores["decision"] = "Una decisión confirmada requiere actor y fecha."
        if errores:
            raise ValidationError(errores)


class UmbralSimilitudEmpresa(models.Model):
    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.PROTECT,
        related_name="umbral_similitud",
    )
    porcentaje = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )
    actualizado_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="umbrales_similitud_actualizados",
    )
    actualizado_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(porcentaje__gte=0, porcentaje__lte=100),
                name="umbral_similitud_empresa_porcentaje_rango",
            ),
        ]


class ReunionRevision(models.Model):
    class Modalidad(models.TextChoices):
        ZOOM = "ZOOM", "ZOOM"
        PRESENCIAL = "PRESENCIAL", "PRESENCIAL"

    class TipoAmbito(models.TextChoices):
        LOCAL = "LOCAL", "LOCAL"
        DEPARTAMENTO = "DEPARTAMENTO", "DEPARTAMENTO"

    class Estado(models.TextChoices):
        PLANIFICADA = "PLANIFICADA", "PLANIFICADA"
        REALIZADA = "REALIZADA", "REALIZADA"

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="reuniones_revision")
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, default="")
    fecha_hora_programada = models.DateTimeField()
    modalidad = models.CharField(max_length=10, choices=Modalidad.choices)
    lugar_o_enlace = models.CharField(max_length=500, null=True, blank=True)
    tipo_ambito = models.CharField(max_length=12, choices=TipoAmbito.choices)
    local = models.ForeignKey("organizacion.Local", on_delete=models.PROTECT, null=True, blank=True, related_name="reuniones_revision")
    departamento = models.ForeignKey("organizacion.Departamento", on_delete=models.PROTECT, null=True, blank=True, related_name="reuniones_revision")
    tarea_planificada = models.OneToOneField(Tarea, on_delete=models.PROTECT, related_name="reunion_revision")
    creada_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name="reuniones_revision_creadas")
    estado = models.CharField(max_length=11, choices=Estado.choices, default=Estado.PLANIFICADA)
    convocada_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        errores = {}
        if self.tipo_ambito == self.TipoAmbito.LOCAL:
            if not self.local_id:
                errores["local"] = "El ámbito LOCAL requiere un Local."
            if self.departamento_id:
                errores["departamento"] = "El ámbito LOCAL no admite Departamento."
        elif self.tipo_ambito == self.TipoAmbito.DEPARTAMENTO:
            if not self.departamento_id:
                errores["departamento"] = "El ámbito DEPARTAMENTO requiere un Departamento."
            if self.local_id:
                errores["local"] = "El ámbito DEPARTAMENTO no admite Local."
        if self.local_id and self.local.empresa_id != self.empresa_id:
            errores["local"] = "El Local debe pertenecer a la misma Empresa."
        if self.departamento_id and self.departamento.empresa_id != self.empresa_id:
            errores["departamento"] = "El Departamento debe pertenecer a la misma Empresa."
        if self.tarea_planificada_id:
            tarea = self.tarea_planificada
            if tarea.empresa_id != self.empresa_id:
                errores["tarea_planificada"] = "La Tarea planificada debe pertenecer a la misma Empresa."
            if tarea.tipo_ambito != self.tipo_ambito or tarea.local_id != self.local_id or tarea.departamento_id != self.departamento_id:
                errores["tarea_planificada"] = "La Tarea planificada debe tener el mismo ámbito."
        if errores:
            raise ValidationError(errores)


class ReunionTarea(models.Model):
    reunion = models.ForeignKey(ReunionRevision, on_delete=models.CASCADE, related_name="agenda")
    tarea = models.ForeignKey(Tarea, on_delete=models.PROTECT, related_name="reuniones_revision")
    orden = models.PositiveIntegerField()
    comentario_revision = models.TextField(blank=True, default="")
    comentario_cierre = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("reunion", "tarea"), name="unique_reunion_revision_tarea"),
            models.UniqueConstraint(fields=("reunion", "orden"), name="unique_reunion_revision_orden"),
        ]

    def clean(self):
        super().clean()
        if not self.reunion_id or not self.tarea_id:
            return
        reunion = self.reunion
        tarea = self.tarea
        if reunion.empresa_id != tarea.empresa_id:
            raise ValidationError({"tarea": "La Tarea debe pertenecer a la misma Empresa."})
        if reunion.tipo_ambito == ReunionRevision.TipoAmbito.LOCAL:
            valid = tarea.tipo_ambito == Tarea.Ambito.LOCAL and tarea.local_id == reunion.local_id
        else:
            valid = tarea.tipo_ambito == Tarea.Ambito.DEPARTAMENTO and tarea.departamento_id == reunion.departamento_id
        if not valid:
            raise ValidationError({"tarea": "La Tarea debe coincidir con el ámbito de la reunión."})


class ReunionParticipante(models.Model):
    reunion = models.ForeignKey(ReunionRevision, on_delete=models.CASCADE, related_name="participantes")
    usuario = models.ForeignKey(User, on_delete=models.PROTECT, related_name="reuniones_revision_participante")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("reunion", "usuario"), name="unique_reunion_revision_participante")
        ]

    class FormatoArchivo(models.TextChoices):
        PDF = "PDF", "PDF"
        JPG = "JPG", "JPG"
        JPEG = "JPEG", "JPEG"
        PNG = "PNG", "PNG"
        DOC = "DOC", "DOC"
        DOCX = "DOCX", "DOCX"
        XLS = "XLS", "XLS"
        XLSX = "XLSX", "XLSX"


def formato_coincide_extension(formato, extension):
    if formato in {FormatoArchivo.JPG, FormatoArchivo.JPEG}:
        return extension in {"jpg", "jpeg"}
    return extension == formato.lower()



class Avance(models.Model):
    class Modo(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        PONDERADO = "PONDERADO", "Ponderado"

    tarea = models.OneToOneField(
        Tarea,
        on_delete=models.PROTECT,
        related_name="avance",
    )
    modo = models.CharField(
        max_length=10,
        choices=Modo.choices,
        default=Modo.MANUAL,
    )
    porcentaje = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
    )
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if self.porcentaje < 0 or self.porcentaje > 100:
            raise ValidationError({"porcentaje": "El avance debe estar entre 0 y 100."})


class Hito(models.Model):
    tarea = models.ForeignKey(
        Tarea,
        on_delete=models.PROTECT,
        related_name="hitos",
    )
    nombre = models.CharField(max_length=200)
    responsable = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="hitos_responsable",
    )
    anulado = models.BooleanField(default=False)
    completado = models.BooleanField(default=False)
    completado_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="hitos_completados",
    )
    fecha_completado = models.DateTimeField(null=True, blank=True)
    resena_cierre = models.TextField(blank=True, default="")
    cumplimiento = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
    )
    peso = models.DecimalField(
        max_digits=7,
        decimal_places=2,
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha_creacion", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cumplimiento__gte=0)
                & models.Q(cumplimiento__lte=100),
                name="tareas_hito_cumplimiento_rango",
            ),
            models.CheckConstraint(
                condition=models.Q(peso__gt=0),
                name="tareas_hito_peso_positivo",
            ),
        ]

    def clean(self):
        super().clean()
        errores = {}
        if self.responsable_id is None:
            errores["responsable"] = "El hito requiere un responsable."
        elif not self.responsable.is_active:
            errores["responsable"] = "El responsable del hito debe estar activo."
        if self.cumplimiento < 0 or self.cumplimiento > 100:
            errores["cumplimiento"] = "El cumplimiento debe estar entre 0 y 100."
        if self.peso <= 0:
            errores["peso"] = "El peso debe ser mayor que cero."
        if errores:
            raise ValidationError(errores)


class HitoHistorial(models.Model):
    class Evento(models.TextChoices):
        CREACION = "CREACION", "Creación"
        CAMBIO_NOMBRE = "CAMBIO_NOMBRE", "Cambio de nombre"
        CAMBIO_CUMPLIMIENTO = "CAMBIO_CUMPLIMIENTO", "Cambio de cumplimiento"
        CAMBIO_PESO = "CAMBIO_PESO", "Cambio de peso"
        REASIGNACION = "REASIGNACION", "Reasignación"
        ANULACION = "ANULACION", "Anulación"
        REACTIVACION = "REACTIVACION", "Reactivación"
        ELIMINACION_FISICA = "ELIMINACION_FISICA", "Eliminación física"
        COMPLETADO = "COMPLETADO", "Completado"

    hito = models.ForeignKey(Hito, on_delete=models.CASCADE, related_name="historial")
    tipo_evento = models.CharField(max_length=32, choices=Evento.choices)
    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="historial_hitos",
    )
    fecha = models.DateTimeField(default=timezone.now)
    datos_anteriores = models.JSONField(default=dict)
    datos_nuevos = models.JSONField(default=dict)
    motivo = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["fecha", "pk"]
        indexes = [
            models.Index(
                fields=["hito", "fecha"],
                name="tareas_hh_hito_fecha_idx",
            )
        ]


class HitoEvidencia(models.Model):
    FormatoArchivo = FormatoArchivo

    hito = models.ForeignKey(
        Hito,
        on_delete=models.CASCADE,
        related_name="evidencias",
    )
    formato_archivo = models.CharField(max_length=4, choices=FormatoArchivo.choices)
    archivo = models.FileField(
        upload_to="tareas/hitos/evidencias/",
        blank=True,
        default="",
    )
    url = models.URLField(blank=True, default="")
    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="evidencias_hitos_registradas",
    )
    fecha = models.DateTimeField(default=timezone.now)

    def clean(self):
        super().clean()
        tiene_archivo = bool(self.archivo)
        tiene_url = bool(self.url)
        errores = {}
        if tiene_archivo == tiene_url:
            errores["archivo"] = "La evidencia debe indicar exactamente un archivo o una URL."
        else:
            fuente = self.archivo.name if tiene_archivo else urlparse(self.url).path
            extension = splitext(fuente)[1].lower().lstrip(".")
            if tiene_archivo and not extension:
                errores["formato_archivo"] = "El archivo debe tener una extensión reconocible."
            elif extension and not formato_coincide_extension(self.formato_archivo, extension):
                errores["formato_archivo"] = "El formato declarado no coincide con la extensión de la evidencia."
        if errores:
            raise ValidationError(errores)

    class Meta:
        ordering = ["-fecha", "-pk"]
        indexes = [models.Index(fields=["hito", "fecha"], name="tareas_he_hito_fecha_idx")]


class MiniTarea(models.Model):
    tarea = models.ForeignKey(
        Tarea,
        on_delete=models.PROTECT,
        related_name="mini_tareas",
    )
    descripcion = models.CharField(max_length=200)
    persona = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="mini_tareas_asignadas",
    )
    hecho = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_completado = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["fecha_creacion", "pk"]
        indexes = [models.Index(fields=["tarea", "hecho"])]

    def __str__(self):
        return self.descripcion


class DocumentoTarea(models.Model):
    class Tipo(models.TextChoices):
        COTIZACION = "COTIZACION", "Cotización"
        FOTOGRAFIA = "FOTOGRAFIA", "Fotografía"
        INFORME = "INFORME", "Informe"
        ORDEN_TRABAJO = "ORDEN_TRABAJO", "Orden de trabajo"
        FACTURA = "FACTURA", "Factura"
        CONTRATO = "CONTRATO", "Contrato"
        PLANO = "PLANO", "Plano"
        CERTIFICADO = "CERTIFICADO", "Certificado"
        OTRO = "OTRO", "Otro"

    FormatoArchivo = FormatoArchivo

    tarea = models.ForeignKey(
        Tarea,
        on_delete=models.PROTECT,
        related_name="documentos",
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    formato_archivo = models.CharField(max_length=4, choices=FormatoArchivo.choices)
    archivo = models.FileField(
        upload_to="tareas/documentos/",
        blank=True,
        default="",
    )
    url = models.URLField(blank=True, default="")
    fecha_documento = models.DateField(default=timezone.localdate)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="documentos_tareas",
    )
    estado = models.CharField(max_length=20, blank=True, default="")

    def clean(self):
        super().clean()
        tiene_archivo = bool(self.archivo)
        tiene_url = bool(self.url)
        errores = {}
        if tiene_archivo == tiene_url:
            errores["archivo"] = "El documento debe indicar exactamente un archivo o una URL."
        if tiene_archivo:
            extension = splitext(self.archivo.name)[1].lower().lstrip(".")
            if not extension:
                errores["formato_archivo"] = "El archivo debe tener una extensión reconocible."
            elif not formato_coincide_extension(self.formato_archivo, extension):
                errores["formato_archivo"] = "El formato declarado no coincide con la extensión del archivo."
        elif tiene_url:
            extension = splitext(urlparse(self.url).path)[1].lower().lstrip(".")
            if extension and not formato_coincide_extension(self.formato_archivo, extension):
                errores["formato_archivo"] = "El formato declarado no coincide con la extensión de la URL."
        if errores:
            raise ValidationError(errores)

    class Meta:
        indexes = [
            models.Index(fields=["tarea", "tipo"]),
            models.Index(fields=["tarea", "estado"]),
        ]


class DocumentoHistorial(models.Model):
    documento = models.ForeignKey(
        DocumentoTarea,
        on_delete=models.PROTECT,
        related_name="historial",
    )
    accion = models.CharField(max_length=20)
    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="historial_documentos_tareas",
    )
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["fecha", "pk"]
        indexes = [models.Index(fields=["documento", "fecha"])]


class EvidenciaCierre(models.Model):
    tarea = models.ForeignKey(
        Tarea,
        on_delete=models.PROTECT,
        related_name="evidencias_cierre",
    )
    documento = models.ForeignKey(
        DocumentoTarea,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evidencias_cierre",
    )
    formato_archivo = models.CharField(
        max_length=4,
        choices=FormatoArchivo.choices,
        blank=True,
        default="",
    )
    archivo = models.FileField(
        upload_to="tareas/evidencias/",
        blank=True,
        default="",
    )
    url = models.URLField(blank=True, default="")
    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="evidencias_cierre_registradas",
    )
    fecha = models.DateTimeField(default=timezone.now)

    def clean(self):
        super().clean()
        tiene_archivo = bool(self.archivo)
        tiene_url = bool(self.url)
        errores = {}
        if tiene_archivo and tiene_url:
            errores["archivo"] = "La evidencia debe indicar exactamente un archivo o una URL."
        elif tiene_archivo or tiene_url:
            if not self.formato_archivo:
                errores["formato_archivo"] = "La evidencia requiere un formato de archivo."
            else:
                fuente = self.archivo.name if tiene_archivo else urlparse(self.url).path
                extension = splitext(fuente)[1].lower().lstrip(".")
                if extension and not formato_coincide_extension(self.formato_archivo, extension):
                    errores["formato_archivo"] = "El formato declarado no coincide con la extensión de la evidencia."
        elif self.formato_archivo:
            errores["archivo"] = "La evidencia debe indicar exactamente un archivo o una URL."
        if errores:
            raise ValidationError(errores)

    class Meta:
        ordering = ["-fecha", "-pk"]
        indexes = [
            models.Index(
                fields=["tarea", "fecha"],
                name="tareas_evid_tarea_fecha_idx",
            )
        ]


# Compatibility access for existing MVP callers; ACTIVA is the persisted choice.
Tarea.Estado.PUBLICADA = Tarea.Estado.ACTIVA


class CorrelativoEmpresa(models.Model):
    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.PROTECT,
        related_name="correlativo_tareas",
    )
    siguiente_numero = models.PositiveIntegerField(default=1)

    class Meta:
        indexes = [models.Index(fields=["empresa"])]


class CorrelativoTodoEmpresa(models.Model):
    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.PROTECT,
        related_name="correlativo_todos",
    )
    siguiente_numero = models.PositiveIntegerField(default=1)

    class Meta:
        indexes = [models.Index(fields=["empresa"])]


class Todo(models.Model):
    class Estado(models.TextChoices):
        ABIERTO = "ABIERTO", "ABIERTO"
        CERRADO = "CERRADO", "CERRADO"

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.PROTECT,
        related_name="todos",
    )
    correlativo = models.CharField(max_length=9)
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, default="")
    estado = models.CharField(
        max_length=8,
        choices=Estado.choices,
        default=Estado.ABIERTO,
    )
    creada_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="todos_creados",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    cerrada_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="todos_cerrados",
    )
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    comentario_cierre = models.TextField(blank=True, default="")
    todo_anterior = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="episodios_siguientes",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "correlativo"],
                name="tareas_empresa_todo_correlativo_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "estado"]),
            models.Index(fields=["empresa", "fecha_creacion"]),
        ]

    def __str__(self):
        return f"{self.correlativo}: {self.titulo}"

    def save(self, *args, **kwargs):
        if self.pk and self.estado == self.Estado.ABIERTO:
            original = type(self).objects.filter(pk=self.pk).only("estado").first()
            if original and original.estado == self.Estado.CERRADO:
                raise ValidationError("Un TO-DO cerrado no puede reabrirse.")
        if self._state.adding and not self.correlativo:
            if not self.empresa_id:
                raise ValidationError("Un TO-DO requiere empresa para reservar correlativo.")
            from .services.correlativos import reserve_next_todo_number

            with transaction.atomic(using=kwargs.get("using")):
                self.correlativo = f"TD{reserve_next_todo_number(self.empresa_id):07d}"
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.todo_anterior_id and self.todo_anterior.empresa_id != self.empresa_id:
            raise ValidationError({"todo_anterior": "El episodio anterior debe pertenecer a la misma empresa."})
        if self.estado == self.Estado.ABIERTO and self.pk:
            original = type(self).objects.filter(pk=self.pk).only("estado").first()
            if original and original.estado == self.Estado.CERRADO:
                raise ValidationError({"estado": "Un TO-DO cerrado no puede reabrirse."})


class TodoEvento(models.Model):
    class Tipo(models.TextChoices):
        CREADO = "CREADO", "CREADO"
        CERRADO = "CERRADO", "CERRADO"
        TAREA_CREADA = "TAREA_CREADA", "TAREA_CREADA"

    todo = models.ForeignKey(Todo, on_delete=models.PROTECT, related_name="eventos")
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    usuario = models.ForeignKey(User, on_delete=models.PROTECT, related_name="eventos_todo")
    timestamp = models.DateTimeField(auto_now_add=True)
    comentario = models.TextField(blank=True, default="")
    tarea = models.ForeignKey(
        Tarea,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="eventos_todo",
    )

    class Meta:
        indexes = [models.Index(fields=["todo", "timestamp"])]


class TareaTransicion(models.Model):
    tarea = models.ForeignKey(Tarea, on_delete=models.PROTECT, related_name="transiciones")
    estado_origen = models.CharField(max_length=32)
    estado_destino = models.CharField(max_length=32, blank=True, default="")
    accion_evento = models.CharField(max_length=64)
    usuario = models.ForeignKey(User, on_delete=models.PROTECT, related_name="tareas_transiciones")
    timestamp = models.DateTimeField(auto_now_add=True)
    motivo = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["tarea", "timestamp"])]


class TareaCierre(models.Model):
    class Resultado(models.TextChoices):
        APROBADO = "APROBADO", "APROBADO"
        RECHAZADO = "RECHAZADO", "RECHAZADO"

    tarea = models.ForeignKey(Tarea, on_delete=models.PROTECT, related_name="cierres")
    usuario = models.ForeignKey(User, on_delete=models.PROTECT, related_name="tareas_cierres")
    timestamp = models.DateTimeField(auto_now_add=True)
    resultado = models.CharField(max_length=10, choices=Resultado.choices)
    comentario = models.TextField(blank=True, default="")


class TareaAnulacionSnapshot(models.Model):
    """Modelo histórico de Phase 2 (estado ANULADA + restauración de estado).

    Conservado temporalmente solo para que la migración de datos pueda leer
    `estado_anterior` de tareas que quedaron en estado ANULADA y restaurar su estado
    funcional. Sin uso nuevo tras la remediación al flag `Tarea.anulada`. Su retiro se
    evaluará en una migración futura (documentado en data-model.md).
    """

    tarea = models.ForeignKey(Tarea, on_delete=models.PROTECT, related_name="snapshots_anulacion")
    estado_anterior = models.CharField(max_length=32)
    fechas_pendientes_confirmacion = models.BooleanField(default=False)
    usuario_anulo = models.ForeignKey(User, on_delete=models.PROTECT, related_name="tareas_anuladas")
    timestamp_anulacion = models.DateTimeField(auto_now_add=True)
    usuario_reactivo = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tareas_reactivadas",
    )
    timestamp_reactivacion = models.DateTimeField(null=True, blank=True)


class TareaParticipante(models.Model):
    class Rol(models.TextChoices):
        CREADOR = "CREADOR", "CREADOR"
        RESPONSABLE_LIDER = "RESPONSABLE_LIDER", "RESPONSABLE_LIDER"
        SUPERVISOR = "SUPERVISOR", "SUPERVISOR"
        AUTORIZADOR = "AUTORIZADOR", "AUTORIZADOR"
        PARTICIPANTE = "PARTICIPANTE", "PARTICIPANTE"
        INVITADO_OBSERVADOR = "INVITADO_OBSERVADOR", "INVITADO_OBSERVADOR"

    tarea = models.ForeignKey(Tarea, on_delete=models.PROTECT, related_name="participantes")
    usuario = models.ForeignKey(User, on_delete=models.PROTECT, related_name="participaciones_tareas")
    rol = models.CharField(max_length=32, choices=Rol.choices, default=Rol.PARTICIPANTE)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tarea", "usuario"],
                name="tareas_participante_unico_por_tarea",
            ),
        ]
        indexes = [models.Index(fields=["tarea", "usuario"])]


class TareaLectura(models.Model):
    tarea = models.ForeignKey(Tarea, on_delete=models.PROTECT, related_name="lecturas")
    usuario = models.ForeignKey(User, on_delete=models.PROTECT, related_name="lecturas_tareas")
    leido = models.BooleanField(default=False)
    fecha_lectura = models.DateTimeField(null=True, blank=True)
    comentario_leido_hasta = models.ForeignKey(
        "Comentario",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lecturas_hasta_aqui",
    )

    def clean(self):
        super().clean()
        if self.tarea_id and self.comentario_leido_hasta_id:
            if self.comentario_leido_hasta.tarea_id != self.tarea_id:
                raise ValidationError({"comentario_leido_hasta": "El comentario no pertenece a la tarea."})

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tarea", "usuario"],
                name="tareas_lectura_unica_por_usuario",
            ),
        ]
        indexes = [models.Index(fields=["tarea", "usuario", "leido"])]


class Comentario(models.Model):
    tarea = models.ForeignKey(Tarea, on_delete=models.PROTECT, related_name="comentarios")
    autor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="comentarios_tareas")
    contenido = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    oculto = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["tarea", "created_at", "id"])]


class ComentarioAdjunto(models.Model):
    comentario = models.ForeignKey(Comentario, on_delete=models.PROTECT, related_name="adjuntos")
    documento = models.ForeignKey(DocumentoTarea, on_delete=models.PROTECT, related_name="adjuntos_comentarios")

    def clean(self):
        super().clean()
        if self.comentario_id and self.documento_id:
            if self.comentario.tarea_id != self.documento.tarea_id:
                raise ValidationError({"documento": "El documento no pertenece a la tarea del comentario."})

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["comentario", "documento"],
                name="tareas_com_adjunto_unico",
            ),
        ]


class ComentarioVersion(models.Model):
    class Evento(models.TextChoices):
        CREADO = "CREADO", "CREADO"
        EDITADO = "EDITADO", "EDITADO"
        OCULTADO = "OCULTADO", "OCULTADO"
        RESTAURADO = "RESTAURADO", "RESTAURADO"

    comentario = models.ForeignKey(Comentario, on_delete=models.PROTECT, related_name="versiones")
    evento = models.CharField(max_length=10, choices=Evento.choices)
    numero_version = models.PositiveIntegerField(null=True, blank=True)
    contenido = models.TextField(blank=True, default="")
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="versiones_comentarios_tareas")
    fecha = models.DateTimeField(default=timezone.now)
    motivo = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["fecha", "pk"]
        indexes = [models.Index(fields=["comentario", "fecha", "id"])]
        constraints = [
            models.UniqueConstraint(
                fields=["comentario", "numero_version"],
                name="tareas_com_version_unica",
            ),
        ]


class ComentarioVersionDocumento(models.Model):
    version = models.ForeignKey(ComentarioVersion, on_delete=models.PROTECT, related_name="documentos")
    documento = models.ForeignKey(DocumentoTarea, on_delete=models.PROTECT, related_name="versiones_comentarios")

    def clean(self):
        super().clean()
        if self.version_id and self.documento_id:
            if self.version.comentario.tarea_id != self.documento.tarea_id:
                raise ValidationError({"documento": "El documento no pertenece a la tarea del comentario."})

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["version", "documento"],
                name="tareas_com_ver_doc_unico",
            ),
        ]


class ComentarioPausaLectura(models.Model):
    lectura = models.ForeignKey(TareaLectura, on_delete=models.PROTECT, related_name="pausas_comentarios")
    desde = models.DateTimeField()
    hasta = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["desde", "pk"]
        indexes = [models.Index(fields=["lectura", "desde"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(hasta__isnull=True) | models.Q(hasta__gte=models.F("desde")),
                name="tareas_com_pausa_intervalo",
            ),
        ]


class EnlaceTarea(models.Model):
    tarea = models.ForeignKey(Tarea, on_delete=models.CASCADE, related_name="enlaces")
    destinatario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="enlaces_tareas_recibidos",
    )
    creado_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="enlaces_tareas_creados",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_expiracion = models.DateTimeField()
    revocado_at = models.DateTimeField(null=True, blank=True)
    revocado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="enlaces_tareas_revocados",
    )


class EventoAccesoEnlace(models.Model):
    class Resultado(models.TextChoices):
        ACCESO_OK = "ACCESO_OK", "ACCESO_OK"
        RECHAZADO_USUARIO = "RECHAZADO_USUARIO", "RECHAZADO_USUARIO"
        RECHAZADO_EMPRESA = "RECHAZADO_EMPRESA", "RECHAZADO_EMPRESA"
        RECHAZADO_EXPIRADO = "RECHAZADO_EXPIRADO", "RECHAZADO_EXPIRADO"
        RECHAZADO_REVOCADO = "RECHAZADO_REVOCADO", "RECHAZADO_REVOCADO"

    enlace = models.ForeignKey(
        EnlaceTarea,
        on_delete=models.CASCADE,
        related_name="eventos_acceso",
    )
    usuario = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eventos_acceso_enlaces",
    )
    fecha = models.DateTimeField(auto_now_add=True)
    resultado = models.CharField(max_length=24, choices=Resultado.choices)


class TareaReasignacion(models.Model):
    tarea = models.ForeignKey(Tarea, on_delete=models.PROTECT, related_name="reasignaciones")
    responsable_anterior = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tareas_reasignadas_desde",
    )
    responsable_nuevo = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="tareas_reasignadas_a",
    )
    usuario = models.ForeignKey(User, on_delete=models.PROTECT, related_name="tareas_reasignaciones_realizadas")
    fecha = models.DateTimeField(default=timezone.now)
    motivo = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["tarea", "fecha"])]


class CausaAtraso(models.Model):
    codigo = models.CharField(max_length=40, unique=True)
    nombre = models.CharField(max_length=120, unique=True)

    class Meta:
        ordering = ["codigo"]

    def __str__(self):
        return self.nombre


class Reprogramacion(models.Model):
    tarea = models.ForeignKey(
        Tarea,
        on_delete=models.PROTECT,
        related_name="reprogramaciones",
    )
    fecha_tope_anterior = models.DateField()
    fecha_tope_nueva = models.DateField()
    justificacion = models.TextField()
    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="reprogramaciones_tareas",
    )
    fecha_operacion = models.DateTimeField(default=timezone.now)
    causas = models.ManyToManyField(
        CausaAtraso,
        related_name="reprogramaciones",
    )

    class Meta:
        indexes = [models.Index(fields=["tarea", "fecha_operacion"])]


class TareaRelacion(models.Model):
    padre = models.ForeignKey(Tarea, on_delete=models.PROTECT, related_name="relaciones_hijas")
    hija = models.ForeignKey(Tarea, on_delete=models.PROTECT, related_name="relaciones_padre")
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["hija"],
                name="tareas_relacion_hija_unico_padre",
            ),
        ]
        indexes = [
            models.Index(fields=["padre"]),
            models.Index(fields=["hija"]),
        ]


class RondaCotizacion(models.Model):
    class Estado(models.TextChoices):
        ABIERTA = "ABIERTA", "ABIERTA"
        CERRADA = "CERRADA", "CERRADA"

    tarea = models.ForeignKey(
        Tarea,
        on_delete=models.CASCADE,
        related_name="rondas_cotizacion",
    )
    numero = models.PositiveIntegerField()
    minimo_cotizaciones = models.PositiveIntegerField(default=3)
    estado = models.CharField(
        max_length=8,
        choices=Estado.choices,
        default=Estado.ABIERTA,
    )
    fecha_apertura = models.DateTimeField(default=timezone.now)
    fecha_cierre = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["tarea_id", "numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["tarea", "numero"],
                name="tareas_ronda_tarea_numero_unico",
            ),
            models.CheckConstraint(
                condition=models.Q(numero__gte=1),
                name="tareas_ronda_numero_positivo",
            ),
            models.CheckConstraint(
                condition=models.Q(minimo_cotizaciones__gte=1),
                name="tareas_ronda_minimo_positivo",
            ),
        ]
        indexes = [models.Index(fields=["tarea", "estado"])]

    def clean(self):
        super().clean()
        if self.numero < 1:
            raise ValidationError({"numero": "El número de ronda debe ser mayor que cero."})
        if self.minimo_cotizaciones < 1:
            raise ValidationError(
                {"minimo_cotizaciones": "El mínimo de cotizaciones debe ser mayor que cero."}
            )


class Cotizacion(models.Model):
    class Estado(models.TextChoices):
        RECIBIDA = "RECIBIDA", "RECIBIDA"
        SELECCIONADA = "SELECCIONADA", "SELECCIONADA"
        DESCARTADA = "DESCARTADA", "DESCARTADA"

    ronda = models.ForeignKey(
        RondaCotizacion,
        on_delete=models.PROTECT,
        related_name="cotizaciones",
    )
    proveedor = models.ForeignKey(
        "proveedores.Proveedor",
        on_delete=models.PROTECT,
        related_name="cotizaciones",
        null=True,
        blank=True,
    )
    version = models.PositiveIntegerField()
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    vigente = models.BooleanField(default=True)
    estado = models.CharField(
        max_length=13,
        choices=Estado.choices,
        default=Estado.RECIBIDA,
    )
    fecha_cotizacion = models.DateField()
    observaciones = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["ronda_id", "version", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="tareas_cotizacion_version_positiva",
            ),
            models.CheckConstraint(
                condition=models.Q(monto__gte=Decimal("0")),
                name="tareas_cotizacion_monto_no_negativo",
            ),
        ]
        indexes = [models.Index(fields=["ronda", "estado"])]

    def clean(self):
        super().clean()
        if self.version < 1:
            raise ValidationError({"version": "La versión debe ser mayor que cero."})
        if self.monto < 0:
            raise ValidationError({"monto": "El monto no puede ser negativo."})


class DocumentoCotizacion(models.Model):
    FormatoArchivo = FormatoArchivo

    cotizacion = models.ForeignKey(
        Cotizacion,
        on_delete=models.CASCADE,
        related_name="documentos",
    )
    formato_archivo = models.CharField(max_length=4, choices=FormatoArchivo.choices)
    archivo = models.FileField(
        upload_to="tareas/cotizaciones/",
        blank=True,
        default="",
    )
    url = models.URLField(blank=True, default="")
    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="documentos_cotizaciones",
    )
    fecha = models.DateTimeField(default=timezone.now)

    def clean(self):
        super().clean()
        tiene_archivo = bool(self.archivo)
        tiene_url = bool(self.url)
        errores = {}
        if tiene_archivo == tiene_url:
            errores["archivo"] = "El documento debe indicar exactamente un archivo o una URL."
        else:
            fuente = self.archivo.name if tiene_archivo else urlparse(self.url).path
            extension = splitext(fuente)[1].lower().lstrip(".")
            if tiene_archivo and not extension:
                errores["formato_archivo"] = "El archivo debe tener una extensión reconocible."
            elif extension and not formato_coincide_extension(self.formato_archivo, extension):
                errores["formato_archivo"] = "El formato declarado no coincide con la extensión del documento."
        if errores:
            raise ValidationError(errores)

    class Meta:
        ordering = ["-fecha", "-pk"]
        indexes = [models.Index(fields=["cotizacion", "fecha"])]
