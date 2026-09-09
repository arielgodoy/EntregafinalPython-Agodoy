"""Services for task progress modes and milestones (T035-T036)."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from access_control.services.permissions import (
    get_valid_users_for_empresa,
    user_has_permission_for_empresa,
)
from tareas.models import Avance, Hito, HitoHistorial, TareaParticipante


def validate_milestone_responsible(tarea, user):
    if user is None or not user.is_active:
        raise ValidationError("El responsable del hito debe estar activo.")
    if not get_valid_users_for_empresa(tarea.empresa).filter(pk=user.pk).exists():
        raise ValidationError("El responsable no es válido para la empresa de la tarea.")
    return user


def _actor_is_valid_for_task(tarea, actor):
    if actor is None or not actor.is_active:
        return False
    return get_valid_users_for_empresa(tarea.empresa).filter(pk=actor.pk).exists()


def _is_manager(tarea, actor):
    if not _actor_is_valid_for_task(tarea, actor):
        return False
    if actor.pk in {tarea.responsable_id, tarea.creada_por_id}:
        return True
    if tarea.participantes.filter(
        usuario=actor,
        rol__in=[
            TareaParticipante.Rol.RESPONSABLE_LIDER,
            TareaParticipante.Rol.SUPERVISOR,
            TareaParticipante.Rol.AUTORIZADOR,
        ],
    ).exists():
        return True
    return user_has_permission_for_empresa(
        user=actor,
        empresa=tarea.empresa,
        vista_nombre="Tareas - Hitos",
        accion="supervisor",
    ) or user_has_permission_for_empresa(
        user=actor,
        empresa=tarea.empresa,
        vista_nombre="Tareas - Hitos",
        accion="autorizar",
    )


def milestone_capability(tarea, hito, actor):
    if not _actor_is_valid_for_task(tarea, actor):
        return None
    if _is_manager(tarea, actor):
        return "manage"
    if hito.responsable_id == actor.pk:
        return "progress"
    return "read"


def _require_manager(tarea, hito, actor):
    if milestone_capability(tarea, hito, actor) != "manage":
        raise ValidationError("No tienes autorización para gestionar este hito.")


def _record_history(hito, event, actor, previous=None, new=None, reason=""):
    return HitoHistorial.objects.create(
        hito=hito,
        tipo_evento=event,
        usuario=actor,
        datos_anteriores=previous or {},
        datos_nuevos=new or {},
        motivo=reason.strip(),
    )


def _refresh_weighted_progress(tarea):
    avance = Avance.objects.filter(tarea=tarea, modo=Avance.Modo.PONDERADO).first()
    if avance is None:
        return None
    avance.porcentaje = weighted_progress(tarea)
    avance.full_clean()
    avance.save(update_fields=["porcentaje", "fecha_actualizacion"])
    return avance


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
    hitos = Hito.objects.filter(tarea=tarea, anulado=False)
    peso_total = sum((hito.peso for hito in hitos), Decimal("0"))
    if not peso_total:
        return Decimal("0.00")
    avance = sum(
        (hito.cumplimiento * hito.peso for hito in hitos),
        Decimal("0"),
    ) / peso_total
    return avance.quantize(Decimal("0.01"))


@transaction.atomic
def create_milestone(tarea, nombre, cumplimiento=0, peso=1, responsable=None, actor=None):
    if actor is None or not _is_manager(tarea, actor):
        raise ValidationError("No tienes autorización para crear este hito.")
    if responsable is None:
        raise ValidationError("El hito requiere un responsable.")
    validate_milestone_responsible(tarea, responsable)
    hito = Hito(
        tarea=tarea,
        nombre=nombre,
        cumplimiento=Decimal(str(cumplimiento)),
        peso=Decimal(str(peso)),
        responsable=responsable,
    )
    hito.full_clean()
    hito.save()
    _record_history(
        hito,
        HitoHistorial.Evento.CREACION,
        actor,
        new={
            "nombre": hito.nombre,
            "cumplimiento": str(hito.cumplimiento),
            "peso": str(hito.peso),
            "responsable": hito.responsable_id,
        },
    )
    _refresh_weighted_progress(tarea)
    return hito


@transaction.atomic
def update_milestone(
    hito,
    actor,
    *,
    nombre=None,
    cumplimiento=None,
    peso=None,
    responsable=None,
    motivo="",
):
    capability = milestone_capability(hito.tarea, hito, actor)
    if capability not in {"progress", "manage"}:
        raise ValidationError("No tienes autorización para editar este hito.")
    manager = capability == "manage"
    changes = {}
    if nombre is not None and nombre != hito.nombre:
        if not manager:
            raise ValidationError("El responsable del hito solo puede cambiar cumplimiento.")
        changes["nombre"] = (hito.nombre, nombre)
    if cumplimiento is not None and Decimal(str(cumplimiento)) != hito.cumplimiento:
        changes["cumplimiento"] = (hito.cumplimiento, Decimal(str(cumplimiento)))
    if peso is not None and Decimal(str(peso)) != hito.peso:
        if not manager:
            raise ValidationError("El responsable del hito solo puede cambiar cumplimiento.")
        changes["peso"] = (hito.peso, Decimal(str(peso)))
    if responsable is not None and responsable.pk != hito.responsable_id:
        if not manager:
            raise ValidationError("El responsable del hito no puede reasignarse.")
        motivo = (motivo or "").strip()
        if not motivo:
            raise ValidationError("El motivo de reasignación es obligatorio.")
        validate_milestone_responsible(hito.tarea, responsable)
        changes["responsable"] = (hito.responsable_id, responsable.pk)
    if not changes:
        return hito
    for field, (_old, new) in changes.items():
        if field == "responsable":
            hito.responsable_id = new
        else:
            setattr(hito, field, new)
    hito.full_clean()
    hito.save(update_fields=list(changes))
    events = {
        "nombre": HitoHistorial.Evento.CAMBIO_NOMBRE,
        "cumplimiento": HitoHistorial.Evento.CAMBIO_CUMPLIMIENTO,
        "peso": HitoHistorial.Evento.CAMBIO_PESO,
        "responsable": HitoHistorial.Evento.REASIGNACION,
    }
    for field, (old, new) in changes.items():
        _record_history(
            hito,
            events[field],
            actor,
            {field: str(old)},
            {field: str(new)},
            motivo if field == "responsable" else "",
        )
    _refresh_weighted_progress(hito.tarea)
    return hito


@transaction.atomic
def reassign_milestone(hito, actor, responsable, motivo):
    _require_manager(hito.tarea, hito, actor)
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("El motivo de reasignación es obligatorio.")
    validate_milestone_responsible(hito.tarea, responsable)
    if responsable.pk == hito.responsable_id:
        raise ValidationError("El responsable nuevo debe ser diferente.")
    anterior = hito.responsable_id
    hito.responsable = responsable
    hito.full_clean()
    hito.save(update_fields=["responsable"])
    _record_history(
        hito,
        HitoHistorial.Evento.REASIGNACION,
        actor,
        {"responsable": anterior},
        {"responsable": responsable.pk},
        motivo,
    )
    return hito


@transaction.atomic
def set_milestone_annulled(hito, actor, annulled):
    _require_manager(hito.tarea, hito, actor)
    if hito.anulado == annulled:
        return hito
    previous = hito.anulado
    hito.anulado = annulled
    hito.save(update_fields=["anulado"])
    _record_history(
        hito,
        HitoHistorial.Evento.ANULACION if annulled else HitoHistorial.Evento.REACTIVACION,
        actor,
        {"anulado": previous},
        {"anulado": annulled},
    )
    _refresh_weighted_progress(hito.tarea)
    return hito


@transaction.atomic
def delete_milestone_safely(hito, actor):
    _require_manager(hito.tarea, hito, actor)
    if hito.historial.exclude(tipo_evento=HitoHistorial.Evento.CREACION).exists():
        return set_milestone_annulled(hito, actor, True)
    tarea = hito.tarea
    hito.delete()
    _refresh_weighted_progress(tarea)
    return None