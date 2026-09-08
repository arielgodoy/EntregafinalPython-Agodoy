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
                self.correlativo = f"A{reserve_next_number(self.empresa_id):07d}"
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
                .only("estado", "fecha_publicacion")
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
        if not re.fullmatch(r"A[0-9]{7}", self.correlativo or ""):
            raise ValidationError(
                "No se puede publicar: el correlativo de borrador no es válido."
            )
        self.estado = self.Estado.ACTIVA
        self.correlativo = f"B{self.correlativo[1:]}"
        self.fecha_publicacion = timezone.now()
        self.full_clean()
        self.save()
        TareaTransicion.objects.create(
            tarea=self,
            estado_origen=self.Estado.BORRADOR,
            estado_destino=self.Estado.ACTIVA,
            accion_evento="PUBLICAR",
            usuario=usuario or self.creada_por,
        )


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
