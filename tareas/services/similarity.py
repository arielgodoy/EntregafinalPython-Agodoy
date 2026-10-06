import re
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher

from django.core.exceptions import ValidationError
from django.utils import timezone

from tareas.models import EvaluacionSimilitud, Tarea, UmbralSimilitudEmpresa
from tareas.services.similarity_storage import resolve_similarity_storage


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
    storage = resolve_similarity_storage()
    with storage.atomic() as unit:
        configuration = unit.get_threshold(empresa.pk)
    if configuration is None:
        return DEFAULT_SIMILARITY_THRESHOLD
    return configuration.porcentaje


def set_similarity_threshold(*, empresa, porcentaje, actor):
    if empresa is None or empresa.pk is None:
        raise ValidationError("La Empresa es obligatoria.")
    if actor is None or actor.pk is None:
        raise ValidationError("El actor es obligatorio.")
    porcentaje = _validate_threshold(porcentaje)
    storage = resolve_similarity_storage()
    with storage.atomic() as unit:
        configuration = unit.get_threshold(empresa.pk)
        if configuration is None:
            configuration = UmbralSimilitudEmpresa(
                empresa=empresa,
                porcentaje=porcentaje,
                actualizado_por=actor,
            )
        else:
            configuration.porcentaje = porcentaje
            configuration.actualizado_por = actor
        return unit.save_threshold(configuration)


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


def _persist_evaluation(*, unit, tarea, candidata, porcentaje, threshold):
    evaluation = unit.get_evaluation_for_pair(
        tarea.pk,
        candidata.pk,
        tarea,
        candidata,
    )
    if evaluation is None:
        evaluation = EvaluacionSimilitud(
            tarea=tarea,
            tarea_candidata=candidata,
        )
    evaluation.porcentaje = porcentaje
    evaluation.umbral_aplicado = threshold
    evaluation.supera_umbral = porcentaje >= threshold
    return unit.save_evaluation(
        evaluation,
        update_fields=(
            ["porcentaje", "umbral_aplicado", "supera_umbral"]
            if evaluation.pk
            else None
        ),
    )


def evaluate_task_similarity(*, tarea, threshold):
    if tarea.pk is None or tarea.empresa_id is None:
        raise ValidationError("La Tarea evaluada debe existir y pertenecer a una Empresa.")
    threshold = _validate_threshold(threshold)
    storage = resolve_similarity_storage()
    with storage.atomic() as unit:
        operational_task = unit.get_task(tarea.pk, company_id=tarea.empresa_id)
        candidates = [
            candidate
            for candidate in unit.candidate_tasks(operational_task, CANDIDATE_STATES)
            if _compatible_scope(operational_task, candidate)
        ]
        for candidate in candidates:
            _persist_evaluation(
                unit=unit,
                tarea=operational_task,
                candidata=candidate,
                porcentaje=_similarity_percentage(operational_task, candidate),
                threshold=threshold,
            )
        return unit.list_evaluations(operational_task.pk)


def confirm_similarity(*, evaluacion, decision, actor):
    if decision not in EvaluacionSimilitud.Decision.values:
        raise ValidationError("La decisión de similitud no es válida.")
    storage = resolve_similarity_storage()
    with storage.atomic() as unit:
        evaluation = unit.get_evaluation(evaluacion.pk)
        if evaluation.tarea.empresa_id != evaluation.tarea_candidata.empresa_id:
            raise ValidationError("Las Tareas deben pertenecer a la misma Empresa.")
        if decision != EvaluacionSimilitud.Decision.PENDIENTE:
            if actor is None or not actor.is_active:
                raise ValidationError("La confirmación requiere un usuario activo.")
        if decision == EvaluacionSimilitud.Decision.PENDIENTE:
            evaluation.decision = decision
            evaluation.confirmada_por = None
            evaluation.confirmada_at = None
            unit.save_evaluation(
                evaluation,
                update_fields=["decision", "confirmada_por", "confirmada_at"],
            )
            evaluacion.tarea = evaluation.tarea
            evaluacion.tarea_candidata = evaluation.tarea_candidata
            evaluacion.decision = evaluation.decision
            evaluacion.confirmada_por = evaluation.confirmada_por
            evaluacion.confirmada_at = evaluation.confirmada_at
            return evaluacion

        tarea = unit.get_task(evaluation.tarea_id, lock=True)
        candidata = unit.get_task(evaluation.tarea_candidata_id)
        if decision == EvaluacionSimilitud.Decision.MISMO_PROBLEMA:
            if tarea.todo_origen_id:
                raise ValidationError(
                    "La Tarea ya tiene un TO-DO como origen canónico."
                )
            if tarea.tarea_origen_id and tarea.tarea_origen_id != candidata.pk:
                raise ValidationError(
                    "La Tarea ya tiene otro origen canónico directo."
                )
            if (
                unit.has_confirmed_origin(tarea.pk, evaluation.pk)
                and tarea.tarea_origen_id != candidata.pk
            ):
                raise ValidationError(
                    "Solo una evaluación puede establecer el origen canónico directo."
                )
            unit.save_task_origin(tarea, candidata)
        evaluation.tarea = tarea
        evaluation.tarea_candidata = candidata
        evaluation.decision = decision
        evaluation.confirmada_por = actor
        evaluation.confirmada_at = timezone.now()
        unit.save_evaluation(
            evaluation,
            update_fields=["decision", "confirmada_por", "confirmada_at"],
        )
        evaluacion.tarea = evaluation.tarea
        evaluacion.tarea_candidata = evaluation.tarea_candidata
        evaluacion.decision = evaluation.decision
        evaluacion.confirmada_por = evaluation.confirmada_por
        evaluacion.confirmada_at = evaluation.confirmada_at
        return evaluacion
