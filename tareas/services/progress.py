"""Compatibility entry points delegating all mutations to canonical storage."""

from django.core.exceptions import PermissionDenied, ValidationError

from tareas.models import Avance, Hito, Tarea
from .milestone_storage import (
    CompleteMilestoneCommand, CreateMilestoneCommand, DeleteMilestoneCommand,
    DjangoMilestoneStorage, ReassignMilestoneCommand, SetMilestoneAnnulledCommand,
    SetWeightedProgressModeCommand, UpdateManualProgressCommand, UpdateMilestoneCommand,
    _eligible, _identity, _manager, resolve_milestone_storage,
)
from .task_storage import TaskStorageError


def _scope(tarea, actor):
    if actor is None:
        raise ValidationError("tareas.messages.generic_error")
    return dict(task_id=tarea.pk, empresa_id=tarea.empresa_id, actor_id=actor.pk)


def _legacy_storage(tarea):
    storage = resolve_milestone_storage()
    if not isinstance(storage, DjangoMilestoneStorage):
        raise TaskStorageError("tareas.messages.generic_error")
    return storage


def _returned(storage, result, empresa_id, actor_id, original=None):
    if isinstance(storage, DjangoMilestoneStorage):
        row = Hito.objects.using(storage.alias).get(
            pk=result.milestone_id, tarea__empresa_id=empresa_id,
        )
        if original is not None:
            original.__dict__.update(row.__dict__)
            return original
        return row
    detail = storage.detail(task_id=result.task_id, empresa_id=empresa_id, actor_id=actor_id)
    return next(row for row in detail.milestones if row.pk == result.milestone_id)


def validate_milestone_responsible(tarea, user):
    from access_control.models import Empresa
    _eligible(Empresa.objects.using("default").get(pk=tarea.empresa_id), user.pk if user else None)
    return user


def milestone_capability(tarea, hito, actor):
    storage = _legacy_storage(tarea)
    try:
        empresa, user = _identity(tarea.empresa_id, actor.pk if actor else None, "ingresar")
    except PermissionDenied:
        return None
    def read(adapter):
        task = adapter.task(tarea.pk, tarea.empresa_id)
        persisted = adapter.hito(hito.pk, task.pk)
        if _manager(adapter, task, empresa, user):
            return "manage"
        return "progress" if persisted.responsable_id == user.pk else "read"
    return storage._read(read)


def weighted_progress(tarea):
    return _legacy_storage(tarea).weighted(task_id=tarea.pk, empresa_id=tarea.empresa_id)


def set_manual_progress(tarea, porcentaje, actor=None):
    storage = _legacy_storage(tarea)
    scope = _scope(tarea, actor)
    storage.execute(UpdateManualProgressCommand(**scope, porcentaje=porcentaje))
    if isinstance(storage, DjangoMilestoneStorage):
        return Avance.objects.using(storage.alias).get(tarea_id=tarea.pk)
    return storage.detail(**scope).progress


def set_weighted_progress_mode(tarea, actor=None):
    storage = _legacy_storage(tarea)
    scope = _scope(tarea, actor)
    storage.execute(SetWeightedProgressModeCommand(**scope))
    if isinstance(storage, DjangoMilestoneStorage):
        return Avance.objects.using(storage.alias).get(tarea_id=tarea.pk)
    return storage.detail(**scope).progress


def create_milestone(tarea, nombre, cumplimiento=0, peso=1, responsable=None, actor=None):
    storage = _legacy_storage(tarea)
    scope = _scope(tarea, actor)
    result = storage.execute(CreateMilestoneCommand(
        **scope, nombre=nombre, cumplimiento=cumplimiento, peso=peso,
        responsable_id=responsable.pk if responsable else None,
    ))
    return _returned(storage, result, scope["empresa_id"], scope["actor_id"])


def _mutate(hito, actor, command_type, **values):
    # Use IDs only; storage reloads persisted-before even if a ModelForm mutated hito.
    storage = resolve_milestone_storage()
    if not isinstance(storage, DjangoMilestoneStorage):
        raise TaskStorageError("tareas.messages.generic_error")
    task = Tarea.objects.using(storage.alias).only("empresa_id").get(pk=hito.tarea_id)
    scope = _scope(task, actor)
    result = storage.execute(command_type(**scope, milestone_id=hito.pk, **values))
    if result.deleted:
        return None
    return _returned(storage, result, scope["empresa_id"], scope["actor_id"], hito)


def update_milestone(hito, actor, *, nombre=None, cumplimiento=None, peso=None):
    return _mutate(hito, actor, UpdateMilestoneCommand,
                   nombre=nombre, cumplimiento=cumplimiento, peso=peso)


def complete_milestone(hito, actor, *, resena_cierre, formato_archivo, archivo=None, url=""):
    return _mutate(hito, actor, CompleteMilestoneCommand, resena_cierre=resena_cierre,
                   formato_archivo=formato_archivo, archivo=archivo, url=url)


def reassign_milestone(hito, actor, responsable, motivo):
    return _mutate(hito, actor, ReassignMilestoneCommand,
                   responsable_id=responsable.pk, motivo=motivo)


def set_milestone_annulled(hito, actor, annulled):
    return _mutate(hito, actor, SetMilestoneAnnulledCommand, anulado=annulled)


def delete_milestone_safely(hito, actor):
    return _mutate(hito, actor, DeleteMilestoneCommand)
