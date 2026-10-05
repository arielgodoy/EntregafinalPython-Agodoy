"""Progress rules shared by the milestone aggregate's explicit adapters."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from tareas.models import Avance

ERROR_KEY = "tareas.messages.generic_error"


def progress_percentage(value):
    try:
        number = Decimal(str(value))
        number = Avance._meta.get_field("porcentaje").clean(number, None)
        if not number.is_finite() or not 0 <= number <= 100:
            raise ValidationError(ERROR_KEY)
        return number
    except (InvalidOperation, TypeError, ValueError, ValidationError):
        raise ValidationError(ERROR_KEY) from None


def calculate_weighted_progress(rows):
    active = [row for row in rows if not row.anulado]
    weight = sum((row.peso for row in active), Decimal("0"))
    if not weight:
        return Decimal("0.00")
    return (
        sum((row.cumplimiento * row.peso for row in active), Decimal("0")) / weight
    ).quantize(Decimal("0.01"))


def refresh_weighted_progress(adapter, task_id):
    progress = adapter.progress(task_id)
    if progress is not None and progress.modo == Avance.Modo.PONDERADO:
        adapter.save_progress(
            task_id, progress.modo, calculate_weighted_progress(adapter.milestones(task_id))
        )
