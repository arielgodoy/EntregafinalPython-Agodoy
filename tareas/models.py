"""Modelos de la app tareas (Tareas Internas).

Implementa specs/001-tareas-internas/data-model.md:
- Ciclo BORRADOR -> PUBLICADA (publicación irreversible).
- Publicación exige responsable válido/activo (FR-007/FR-008, Clarification Q1).
- Aislamiento por empresa (FK access_control.Empresa; FR-003).
"""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
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
        PUBLICADA = "PUBLICADA", "PUBLICADA"

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
    estado = models.CharField(
        max_length=10,
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
        ]

    def __str__(self):
        return f"{self.titulo} ({self.get_estado_display()})"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("tareas:detalle_tarea", kwargs={"pk": self.pk})

    def _responsable_es_valido(self):
        """Responsable asignado y activo (Q1)."""
        return self.responsable is not None and self.responsable.is_active

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

        if self.estado == self.Estado.PUBLICADA:
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
                    original.estado == self.Estado.PUBLICADA
                    and self.estado == self.Estado.BORRADOR
                ):
                    errores["estado"] = (
                        "La publicación es irreversible: una tarea publicada no puede volver a borrador."
                    )
                if (
                    original.estado == self.Estado.PUBLICADA
                    and original.fecha_publicacion
                    and self.fecha_publicacion != original.fecha_publicacion
                ):
                    errores["fecha_publicacion"] = (
                        "La fecha de publicación es inmutable."
                    )

        if errores:
            raise ValidationError(errores)

    def publicar(self):
        """Publica el borrador: exige responsable válido/activo (Q1, FR-007).

        Fija estado=PUBLICADA y fecha_publicacion (FR-008). Si el responsable falta o
        está inactivo, lanza ValidationError sin persistir (la tarea permanece en
        BORRADOR).
        """
        if self.estado == self.Estado.PUBLICADA:
            raise ValidationError("La tarea ya está publicada.")
        if not self._responsable_es_valido():
            raise ValidationError(
                "No se puede publicar: la tarea requiere un responsable válido y activo."
            )
        self.estado = self.Estado.PUBLICADA
        self.fecha_publicacion = timezone.now()
        self.full_clean()
        self.save()
