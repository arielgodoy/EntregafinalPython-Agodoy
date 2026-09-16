import re
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from tareas.models import EvaluacionSimilitud, Tarea, UmbralSimilitudEmpresa


CANDIDATE_STATES = frozenset(
    {
        Tarea.Estado.ACTIVA,
        Tarea.Estado.GESTION,
        Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
        Tarea.Estado.CERRADA,
    }
)
_SCORE_QUANTUM = Decimal("0.01")
DEFAULT_SIMILARITY_THRESHOLD = Decimal("80.00")


def _normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "").casefold().strip())


def _text_similarity(left, right):
    return SequenceMatcher(None, _normalize_text(left), _normalize_text(right)).ratio()


def _similarity_percentage(tarea, candidata):
    score = (
        _text_similarity(tarea.titulo, candidata.titulo) * 0.60
        + _text_similarity(tarea.descripcion, candidata.descripcion) * 0.40
    )
    return Decimal(str(score * 100)).quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def _validate_threshold(threshold):
    try:
        threshold = Decimal(str(threshold))
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise ValidationError("El umbral debe ser un número entre 0 y 100.") from exc
    if not 0 <= threshold <= 100:
        raise ValidationError("El umbral debe estar entre 0 y 100.")
    return threshold.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def get_similarity_threshold(empresa):
    configuration = UmbralSimilitudEmpresa.objects.filter(empresa=empresa).only(
        "porcentaje"
    ).first()
    if configuration is None:
        return DEFAULT_SIMILARITY_THRESHOLD
    return configuration.porcentaje


@transaction.atomic
def set_similarity_threshold(*, empresa, porcentaje, actor):
    if empresa is None or empresa.pk is None:
        raise ValidationError("La Empresa es obligatoria.")
    if actor is None or actor.pk is None:
        raise ValidationError("El actor es obligatorio.")
    porcentaje = _validate_threshold(porcentaje)
    configuration = UmbralSimilitudEmpresa.objects.filter(empresa=empresa).first()
    if configuration is None:
        configuration = UmbralSimilitudEmpresa(
            empresa=empresa,
            porcentaje=porcentaje,
            actualizado_por=actor,
        )
    else:
        configuration.porcentaje = porcentaje
        configuration.actualizado_por = actor
    configuration.full_clean()
    configuration.save()
    return configuration


def _compatible_scope(tarea, candidata):
    if not tarea.tipo_ambito or not candidata.tipo_ambito:
        return True
    if tarea.tipo_ambito != candidata.tipo_ambito:
        return False
    if tarea.tipo_ambito == Tarea.Ambito.LOCAL:
        return tarea.local_id == candidata.local_id
    if tarea.tipo_ambito == Tarea.Ambito.DEPARTAMENTO:
        return tarea.departamento_id == candidata.departamento_id
    return False


def _candidate_queryset(tarea):
    return (
        Tarea.objects.filter(
            empresa_id=tarea.empresa_id,
            estado__in=CANDIDATE_STATES,
            anulada=False,
        )
        .exclude(pk=tarea.pk)
        .order_by("pk")
    )


def _persist_evaluation(*, tarea, candidata, porcentaje, threshold):
    evaluation = (
        EvaluacionSimilitud.objects.filter(
            tarea=tarea,
            tarea_candidata=candidata,
        )
        .first()
    )
    if evaluation is None:
        evaluation = EvaluacionSimilitud(
            tarea=tarea,
            tarea_candidata=candidata,
        )
    evaluation.porcentaje = porcentaje
    evaluation.umbral_aplicado = threshold
    evaluation.supera_umbral = porcentaje >= threshold
    evaluation.full_clean()
    if evaluation.pk:
        evaluation.save(
            update_fields=[
                "porcentaje",
                "umbral_aplicado",
                "supera_umbral",
            ]
        )
    else:
        evaluation.save()
    return evaluation


@transaction.atomic
def evaluate_task_similarity(*, tarea, threshold):
    if tarea.pk is None or tarea.empresa_id is None:
        raise ValidationError("La Tarea evaluada debe existir y pertenecer a una Empresa.")
    threshold = _validate_threshold(threshold)
    candidates = [
        candidata
        for candidata in _candidate_queryset(tarea)
        if _compatible_scope(tarea, candidata)
    ]
    for candidata in candidates:
        _persist_evaluation(
            tarea=tarea,
            candidata=candidata,
            porcentaje=_similarity_percentage(tarea, candidata),
            threshold=threshold,
        )
    return list(
        EvaluacionSimilitud.objects.filter(tarea=tarea)
        .select_related("tarea_candidata")
        .order_by("-porcentaje", "tarea_candidata_id")
    )


def confirm_similarity(*, evaluacion, decision, actor):
    if decision not in EvaluacionSimilitud.Decision.values:
        raise ValidationError("La decisión de similitud no es válida.")
    if evaluacion.tarea.empresa_id != evaluacion.tarea_candidata.empresa_id:
        raise ValidationError("Las Tareas deben pertenecer a la misma Empresa.")
    if decision == EvaluacionSimilitud.Decision.PENDIENTE:
        evaluacion.decision = decision
        evaluacion.confirmada_por = None
        evaluacion.confirmada_at = None
        evaluacion.full_clean()
        evaluacion.save(update_fields=["decision", "confirmada_por", "confirmada_at"])
        return evaluacion
    if actor is None or not actor.is_active:
        raise ValidationError("La confirmación requiere un usuario activo.")

    with transaction.atomic():
        tarea = Tarea.objects.select_for_update().get(pk=evaluacion.tarea_id)
        candidata = Tarea.objects.get(pk=evaluacion.tarea_candidata_id)
        if decision == EvaluacionSimilitud.Decision.MISMO_PROBLEMA:
            if tarea.todo_origen_id:
                raise ValidationError(
                    "La Tarea ya tiene un TO-DO como origen canónico."
                )
            if tarea.tarea_origen_id and tarea.tarea_origen_id != candidata.pk:
                raise ValidationError(
                    "La Tarea ya tiene otro origen canónico directo."
                )
            existing_origin = (
                EvaluacionSimilitud.objects.filter(
                    tarea=tarea,
                    decision=EvaluacionSimilitud.Decision.MISMO_PROBLEMA,
                )
                .exclude(pk=evaluacion.pk)
                .exists()
            )
            if existing_origin and tarea.tarea_origen_id != candidata.pk:
                raise ValidationError(
                    "Solo una evaluación puede establecer el origen canónico directo."
                )
            tarea.tarea_origen = candidata
            tarea.full_clean()
            tarea.save(update_fields=["tarea_origen"])
        evaluacion.decision = decision
        evaluacion.confirmada_por = actor
        evaluacion.confirmada_at = timezone.now()
        evaluacion.full_clean()
        evaluacion.save(update_fields=["decision", "confirmada_por", "confirmada_at"])
    return evaluacion
