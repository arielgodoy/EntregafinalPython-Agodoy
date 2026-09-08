"""Services for task progress modes and milestones (T035-T036)."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from tareas.models import Avance
from tareas.models import Hito


def set_manual_progress(tarea, porcentaje):
    avance, _ = Avance.objects.get_or_create(tarea=tarea)
    if avance.modo == Avance.Modo.PONDERADO:
        raise ValidationError("No se puede definir avance manual en modo ponderado.")
    avance.modo = Avance.Modo.MANUAL
    avance.porcentaje = Decimal(str(porcentaje))
    avance.full_clean()
    avance.save()
    return avance


def set_weighted_progress_mode(tarea):
    avance, _ = Avance.objects.get_or_create(tarea=tarea)
    avance.modo = Avance.Modo.PONDERADO
    avance.full_clean()
    avance.save()
    return avance


def weighted_progress(tarea):
    hitos = Hito.objects.filter(tarea=tarea)
    peso_total = sum((hito.peso for hito in hitos), Decimal("0"))
    if not peso_total:
        return Decimal("0.00")
    avance = sum(
        (hito.cumplimiento * hito.peso for hito in hitos),
        Decimal("0"),
    ) / peso_total
    return avance.quantize(Decimal("0.01"))


@transaction.atomic
def create_milestone(tarea, nombre, cumplimiento=0, peso=1):
    hito = Hito(
        tarea=tarea,
        nombre=nombre,
        cumplimiento=Decimal(str(cumplimiento)),
        peso=Decimal(str(peso)),
    )
    hito.full_clean()
    hito.save()
    avance = Avance.objects.filter(
        tarea=tarea,
        modo=Avance.Modo.PONDERADO,
    ).first()
    if avance is not None:
        avance.porcentaje = weighted_progress(tarea)
        avance.full_clean()
        avance.save(update_fields=["porcentaje", "fecha_actualizacion"])
    return hito