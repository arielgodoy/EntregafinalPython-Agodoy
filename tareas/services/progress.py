"""Services for task progress modes (T035)."""

from decimal import Decimal

from tareas.models import Avance


def set_manual_progress(tarea, porcentaje):
    avance, _ = Avance.objects.get_or_create(tarea=tarea)
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