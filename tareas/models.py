"""Persistent Phase 1/2 domain for internal tasks."""

import re

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from access_control.models import Empresa


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
        if self.cumplimiento < 0 or self.cumplimiento > 100:
            errores["cumplimiento"] = "El cumplimiento debe estar entre 0 y 100."
        if self.peso <= 0:
            errores["peso"] = "El peso debe ser mayor que cero."
        if errores:
            raise ValidationError(errores)


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

    tarea = models.ForeignKey(
        Tarea,
        on_delete=models.PROTECT,
        related_name="documentos",
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
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
        if tiene_archivo == tiene_url:
            raise ValidationError(
                "El documento debe indicar exactamente un archivo o una URL."
            )

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
    tarea = models.OneToOneField(
        Tarea,
        on_delete=models.PROTECT,
        related_name="evidencia_cierre",
    )
    documento = models.ForeignKey(
        DocumentoTarea,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evidencias_cierre",
    )
    requerida = models.BooleanField(default=False)
    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="evidencias_cierre_registradas",
    )
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["tarea", "requerida"])]


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

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tarea", "usuario"],
                name="tareas_lectura_unica_por_usuario",
            ),
        ]
        indexes = [models.Index(fields=["tarea", "usuario", "leido"])]


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
