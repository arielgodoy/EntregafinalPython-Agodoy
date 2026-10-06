"""Atomic, company-scoped responsibility and explicit participation mutations."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from types import SimpleNamespace
from uuid import uuid4

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from access_control.models import Empresa
from access_control.services.permissions import (
    get_valid_users_for_empresa,
    user_has_permission_for_empresa,
)
from settings.services.mysql_connections import open_mysql_connection

from ..models import Comentario, Tarea, TareaLectura, TareaParticipante, TareaReasignacion, TareaRelacion
from .connection_roles import get_tarea_connection, get_tarea_mysql_connection
from .notifications import emit_task_event
from .task_storage import EditTaskNotFound, TaskStorageError, UpdateTaskCommand

logger = logging.getLogger(__name__)
PUBLIC_ROLES = frozenset({"PARTICIPANTE", "INVITADO_OBSERVADOR"})
MUTABLE_STATES = frozenset({
    Tarea.Estado.BORRADOR, Tarea.Estado.ACTIVA, Tarea.Estado.GESTION,
    Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
})


@dataclass(frozen=True)
class ReassignResponsibleCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    new_responsible_id: int | None
    reason: str = ""
    edit: UpdateTaskCommand | None = None


@dataclass(frozen=True)
class AddParticipantCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    user_id: int
    role: str = "PARTICIPANTE"


@dataclass(frozen=True)
class RemoveParticipantCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    user_id: int


@dataclass(frozen=True)
class MarkTaskReadCommand:
    task_id: int
    empresa_id: int
    user_id: int
    leido: bool = True


@dataclass(frozen=True)
class ChangeParticipantRoleCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    user_id: int
    new_role: str


@dataclass(frozen=True)
class ParticipantMutationResult:
    changed: bool
    task_id: int
    empresa_id: int
    user_id: int | None = None
    old_responsible_id: int | None = None
    new_responsible_id: int | None = None
    old_role: str | None = None
    new_role: str | None = None
    reassignment_id: int | None = None
    participant_id: int | None = None


def _invalid(key):
    raise ValidationError(f"tareas.assignment.errors.{key}")


def _authorize(command, task):
    try:
        empresa = Empresa.objects.using("default").get(pk=command.empresa_id)
        actor = User.objects.using("default").get(pk=command.actor_id, is_active=True)
    except (Empresa.DoesNotExist, User.DoesNotExist) as exc:
        raise PermissionDenied from exc
    if not (
        get_valid_users_for_empresa(empresa, active_only=True).using("default")
        .filter(pk=actor.pk).exists()
        and user_has_permission_for_empresa(
            user=actor, empresa=empresa, vista_nombre="Tareas", accion="modificar"
        )
        and (
            actor.pk == task.creada_por_id
            or user_has_permission_for_empresa(
                user=actor, empresa=empresa, vista_nombre="Tareas", accion="supervisor"
            )
        )
    ):
        raise PermissionDenied
    return empresa


def _eligible(empresa, user_id):
    if type(user_id) is not int or user_id <= 0:
        _invalid("invalid_user")
    if not get_valid_users_for_empresa(empresa, active_only=True).using("default").filter(
        pk=user_id, is_active=True
    ).exists():
        _invalid("invalid_user")


def _notify(command, result, priority, mutation_id):
    """Resolve SYSTEM identities best-effort; each mutation has a unique event."""
    try:
        empresa = Empresa.objects.using("default").get(pk=command.empresa_id)
        actor = User.objects.using("default").get(pk=command.actor_id)
        if isinstance(command, ReassignResponsibleCommand):
            messages = [
                (result.old_responsible_id, "Responsable anterior reemplazado",
                 "Ya no eres el responsable de la tarea."),
                (result.new_responsible_id, "Nuevo responsable asignado",
                 "Has sido asignado como responsable de la tarea."),
            ]
            event = "reasignacion"
        elif isinstance(command, AddParticipantCommand):
            messages = [(result.user_id, "Participación agregada",
                         f"Has sido agregado a la tarea como {result.new_role}.")]
            event = "participante_alta"
        elif isinstance(command, RemoveParticipantCommand):
            messages = [(result.user_id, "Participación retirada",
                         "Has sido retirado de la tarea.")]
            event = "participante_baja"
        else:
            messages = [(result.user_id, "Rol de participación cambiado",
                         f"Tu rol cambió: {result.old_role} → {result.new_role}.")]
            event = "participante_rol"
        recipients = {
            user.pk: user for user in User.objects.using("default").filter(
                pk__in=[item[0] for item in messages if item[0] is not None],
                is_active=True,
            ).exclude(pk=command.actor_id)
        }
        task = SimpleNamespace(pk=command.task_id, empresa=empresa, prioridad=priority)
        for user_id, title, body in messages:
            if user_id in recipients:
                emit_task_event(
                    tarea=task, event=f"{event}:{mutation_id}", recipients=[recipients.pop(user_id)],
                    title=title, body=body, actor=actor,
                )
    except Exception:
        logger.error("Participant communication failed: task=%s company=%s",
                     command.task_id, command.empresa_id)


def _mutate(storage, command):
    task = storage.lock_task(command)
    empresa = _authorize(command, task)
    responsible = isinstance(command, ReassignResponsibleCommand)
    changed = responsible and task.responsable_id != command.new_responsible_id
    if not (responsible and command.edit is not None and not changed):
        if task.estado not in MUTABLE_STATES:
            _invalid("state")
        if storage.annulled(task, command):
            _invalid("annulled")
    if responsible:
        history_id = None
        reason = str(command.reason or "").strip()
        if changed:
            if command.new_responsible_id is None:
                if task.estado != Tarea.Estado.BORRADOR:
                    _invalid("invalid_user")
            else:
                _eligible(empresa, command.new_responsible_id)
            if task.estado != Tarea.Estado.BORRADOR and not reason:
                _invalid("reason_required")
        edit = command.edit
        fields = {}
        if edit is not None:
            if (edit.task_id, edit.empresa_id, edit.responsable_id) != (
                command.task_id, command.empresa_id, command.new_responsible_id
            ):
                _invalid("invalid_edit")
            fields = dict(titulo=edit.titulo, descripcion=edit.descripcion, prioridad=edit.prioridad)
            if task.estado == Tarea.Estado.BORRADOR:
                fields["fecha_tope"] = edit.fecha_tope
        if changed:
            fields["responsable_id"] = command.new_responsible_id
        if fields:
            storage.update_task(task, command, fields)
        if changed and command.new_responsible_id is not None:
            storage.ensure_reading(task, command.new_responsible_id)
            history_id = storage.reassignment(task, command, reason)
        result = ParticipantMutationResult(
            changed, task.pk, command.empresa_id, command.new_responsible_id,
            task.responsable_id, command.new_responsible_id, reassignment_id=history_id,
        )
        priority = fields.get("prioridad", task.prioridad)
    else:
        if type(command.user_id) is not int or command.user_id <= 0:
            _invalid("invalid_user")
        link = storage.participant(task, command.user_id)
        old_role = link.rol if link else None
        participant_id = link.pk if link else None
        new_role = None
        if isinstance(command, AddParticipantCommand):
            if command.role not in PUBLIC_ROLES:
                _invalid("invalid_role")
            _eligible(empresa, command.user_id)
            if command.user_id in {task.creada_por_id, task.responsable_id}:
                _invalid("implicit_user")
            if link is not None:
                _invalid("duplicate")
            new_role = command.role
            participant_id = storage.add_participant(task, command.user_id, new_role)
            storage.ensure_reading(task, command.user_id)
            changed = True
        else:
            if link is None:
                _invalid("missing")
            if isinstance(command, RemoveParticipantCommand):
                storage.delete_participant(link)
                changed = True
            else:
                if old_role not in PUBLIC_ROLES or command.new_role not in PUBLIC_ROLES:
                    _invalid("invalid_role")
                new_role = command.new_role
                changed = old_role != new_role
                if changed:
                    storage.update_role(link, new_role)
        result = ParticipantMutationResult(
            changed, task.pk, command.empresa_id, command.user_id,
            old_role=old_role, new_role=new_role, participant_id=participant_id,
        )
        priority = task.prioridad
    return result, priority


class _ParticipantStorage:
    def reassign(self, command):
        return self.reassign_responsible(command)

    def add(self, command):
        return self.add_task_participant(command)

    def remove(self, command):
        return self.remove_task_participant(command)

    def change_role(self, command):
        return self.change_participant_role(command)

    def reassign_responsible(self, command):
        return self._execute(command)

    def add_task_participant(self, command):
        return self._execute(command)

    def remove_task_participant(self, command):
        return self._execute(command)

    def change_participant_role(self, command):
        return self._execute(command)

    def mark_task_read(self, command):
        raise NotImplementedError

    def edit_task(self, command, *, actor_id, reason):
        return self.reassign_responsible(ReassignResponsibleCommand(
            command.task_id, command.empresa_id, actor_id, command.responsable_id,
            reason, edit=command,
        ))


class DjangoParticipantStorage(_ParticipantStorage):
    def __init__(self, alias):
        self.alias = alias

    def _execute(self, command):
        try:
            with transaction.atomic(using=self.alias):
                result, priority = _mutate(self, command)
                if result.changed:
                    mutation_id = uuid4().hex
                    transaction.on_commit(
                        lambda: _notify(command, result, priority, mutation_id), using=self.alias
                    )
            return result
        except (PermissionDenied, ValidationError, EditTaskNotFound):
            raise
        except Exception:
            logger.error("Participant storage failed: task=%s company=%s",
                         command.task_id, command.empresa_id)
            raise TaskStorageError("tareas.assignment.errors.storage") from None

    def lock_task(self, command):
        try:
            return Tarea.objects.using(self.alias).select_for_update().get(
                pk=command.task_id, empresa_id=command.empresa_id
            )
        except Tarea.DoesNotExist:
            raise EditTaskNotFound from None

    def annulled(self, task, command):
        annulled = task.anulada
        current_id = task.pk
        for _ in range(2):
            parent_id = TareaRelacion.objects.using(self.alias).select_for_update().filter(
                hija_id=current_id, hija__empresa_id=command.empresa_id,
                padre__empresa_id=command.empresa_id,
            ).values_list("padre_id", flat=True).first()
            if parent_id is None:
                break
            parent = Tarea.objects.using(self.alias).select_for_update().get(
                pk=parent_id, empresa_id=command.empresa_id
            )
            annulled = annulled or parent.anulada
            current_id = parent.pk
        return annulled

    def update_task(self, task, command, fields):
        Tarea.objects.using(self.alias).filter(
            pk=task.pk, empresa_id=command.empresa_id
        ).update(**fields)

    def participant(self, task, user_id):
        return TareaParticipante.objects.using(self.alias).select_for_update().filter(
            tarea_id=task.pk, usuario_id=user_id
        ).first()

    def add_participant(self, task, user_id, role):
        row = TareaParticipante(tarea_id=task.pk, usuario_id=user_id, rol=role)
        TareaParticipante.objects.using(self.alias).bulk_create([row])
        return row.pk

    def delete_participant(self, link):
        TareaParticipante.objects.using(self.alias).filter(pk=link.pk).delete()

    def update_role(self, link, role):
        TareaParticipante.objects.using(self.alias).filter(pk=link.pk).update(rol=role)

    def ensure_reading(self, task, user_id):
        if TareaLectura.objects.using(self.alias).filter(
            tarea_id=task.pk, usuario_id=user_id
        ).exists():
            return
        latest_id = Comentario.objects.using(self.alias).filter(
            tarea_id=task.pk
        ).order_by("-created_at", "-pk").values_list("pk", flat=True).first()
        TareaLectura.objects.using(self.alias).bulk_create([TareaLectura(
            tarea_id=task.pk, usuario_id=user_id, comentario_leido_hasta_id=latest_id
        )])

    def reassignment(self, task, command, reason):
        row = TareaReasignacion(
            tarea_id=task.pk, responsable_anterior_id=task.responsable_id,
            responsable_nuevo_id=command.new_responsible_id, usuario_id=command.actor_id,
            motivo=reason,
        )
        TareaReasignacion.objects.using(self.alias).bulk_create([row])
        return row.pk

    def mark_task_read(self, command):
        with transaction.atomic(using=self.alias):
            reading, _created = TareaLectura.objects.using(self.alias).update_or_create(
                tarea_id=command.task_id,
                usuario_id=command.user_id,
                defaults={
                    "leido": command.leido,
                    "fecha_lectura": timezone.now() if command.leido else None,
                },
            )
        return reading


class MySQLParticipantStorage(_ParticipantStorage):
    def __init__(self, config, database_name):
        self.connection_config = config
        self.database_name = database_name

    def _execute(self, command):
        try:
            with open_mysql_connection(
                self.connection_config, database_name=self.database_name
            ) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute("START TRANSACTION")
                    # Per-operation adapter: storage objects can safely be reused.
                    adapter = _MySQLMutation(cursor)
                    result, priority = _mutate(adapter, command)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except (PermissionDenied, ValidationError, EditTaskNotFound):
            raise
        except Exception:
            logger.error("Participant storage failed: task=%s company=%s",
                         command.task_id, command.empresa_id)
            raise TaskStorageError("tareas.assignment.errors.storage") from None
        if result.changed:
            _notify(command, result, priority, uuid4().hex)
        return result

    def mark_task_read(self, command):
        try:
            with open_mysql_connection(
                self.connection_config, database_name=self.database_name
            ) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute("START TRANSACTION")
                    reading = _MySQLMutation(cursor).mark_task_read(command)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
            return reading
        except Exception as exc:
            raise TaskStorageError("tareas.assignment.errors.storage") from exc


class _MySQLMutation:
    def __init__(self, cursor):
        self.cursor = cursor

    def lock_task(self, command):
        self.cursor.execute(
            "SELECT id, empresa_id, creada_por_id, responsable_id, estado, anulada, "
            "prioridad, fecha_tope FROM tareas_tarea "
            "WHERE id=%s AND empresa_id=%s FOR UPDATE",
            (command.task_id, command.empresa_id),
        )
        row = self.cursor.fetchone()
        if row is None:
            raise EditTaskNotFound
        return SimpleNamespace(**dict(zip(
            ("pk", "empresa_id", "creada_por_id", "responsable_id", "estado",
             "anulada", "prioridad", "fecha_tope"), row
        )))

    def annulled(self, task, command):
        annulled = bool(task.anulada)
        current_id = task.pk
        for _ in range(2):
            self.cursor.execute(
                "SELECT p.id, p.anulada FROM tareas_tarearelacion r "
                "JOIN tareas_tarea p ON p.id=r.padre_id "
                "JOIN tareas_tarea c ON c.id=r.hija_id "
                "WHERE r.hija_id=%s AND p.empresa_id=%s AND c.empresa_id=%s FOR UPDATE",
                (current_id, command.empresa_id, command.empresa_id),
            )
            row = self.cursor.fetchone()
            if row is None:
                break
            current_id = row[0]
            annulled = annulled or bool(row[1])
        return annulled

    def update_task(self, task, command, fields):
        # Column names originate exclusively from _mutate's fixed allowlist.
        setters = ", ".join(f"{name}=%s" for name in fields)
        self.cursor.execute(
            f"UPDATE tareas_tarea SET {setters} WHERE id=%s AND empresa_id=%s",
            (*fields.values(), task.pk, command.empresa_id),
        )

    def participant(self, task, user_id):
        self.cursor.execute(
            "SELECT id, rol FROM tareas_tareaparticipante "
            "WHERE tarea_id=%s AND usuario_id=%s FOR UPDATE", (task.pk, user_id),
        )
        row = self.cursor.fetchone()
        return SimpleNamespace(pk=row[0], rol=row[1]) if row else None

    def add_participant(self, task, user_id, role):
        self.cursor.execute(
            "INSERT INTO tareas_tareaparticipante (tarea_id, usuario_id, rol, fecha) "
            "VALUES (%s,%s,%s,%s)", (task.pk, user_id, role, timezone.now()),
        )
        return self.cursor.lastrowid

    def delete_participant(self, link):
        self.cursor.execute("DELETE FROM tareas_tareaparticipante WHERE id=%s", (link.pk,))

    def update_role(self, link, role):
        self.cursor.execute(
            "UPDATE tareas_tareaparticipante SET rol=%s WHERE id=%s", (role, link.pk),
        )

    def ensure_reading(self, task, user_id):
        self.cursor.execute(
            "SELECT id FROM tareas_tarealectura WHERE tarea_id=%s AND usuario_id=%s "
            "FOR UPDATE", (task.pk, user_id),
        )
        if self.cursor.fetchone() is not None:
            return
        self.cursor.execute(
            "SELECT id FROM tareas_comentario WHERE tarea_id=%s "
            "ORDER BY created_at DESC, id DESC LIMIT 1", (task.pk,),
        )
        row = self.cursor.fetchone()
        self.cursor.execute(
            "INSERT INTO tareas_tarealectura "
            "(tarea_id, usuario_id, leido, fecha_lectura, comentario_leido_hasta_id) "
            "VALUES (%s,%s,%s,%s,%s)", (task.pk, user_id, False, None, row[0] if row else None),
        )

    def reassignment(self, task, command, reason):
        self.cursor.execute(
            "INSERT INTO tareas_tareareasignacion "
            "(tarea_id, responsable_anterior_id, responsable_nuevo_id, usuario_id, fecha, motivo) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (task.pk, task.responsable_id, command.new_responsible_id,
             command.actor_id, timezone.now(), reason),
        )
        return self.cursor.lastrowid

    def mark_task_read(self, command):
        self.cursor.execute(
            "SELECT id FROM tareas_tarealectura WHERE tarea_id=%s AND usuario_id=%s FOR UPDATE",
            (command.task_id, command.user_id),
        )
        row = self.cursor.fetchone()
        fecha = timezone.now() if command.leido else None
        if row is None:
            self.cursor.execute(
                "INSERT INTO tareas_tarealectura "
                "(tarea_id, usuario_id, leido, fecha_lectura) VALUES (%s,%s,%s,%s)",
                (command.task_id, command.user_id, command.leido, fecha),
            )
            return SimpleNamespace(
                pk=self.cursor.lastrowid,
                tarea_id=command.task_id,
                usuario_id=command.user_id,
                leido=command.leido,
                fecha_lectura=fecha,
            )
        self.cursor.execute(
            "UPDATE tareas_tarealectura SET leido=%s, fecha_lectura=%s WHERE id=%s",
            (command.leido, fecha, row[0]),
        )
        return SimpleNamespace(
            pk=row[0], tarea_id=command.task_id, usuario_id=command.user_id,
            leido=command.leido, fecha_lectura=fecha,
        )


def resolve_participant_storage():
    try:
        source = get_tarea_connection("BASE_TAREAS")
        if source["type"] == "DJANGO":
            return DjangoParticipantStorage(source["alias"])
        if source["type"] == "MYSQL_CONFIG":
            return MySQLParticipantStorage(
                get_tarea_mysql_connection("BASE_TAREAS"), source["database_name"]
            )
    except Exception:
        logger.error("Participant backend resolution failed")
        raise TaskStorageError("tareas.assignment.errors.backend") from None
    logger.error("Participant backend resolution failed")
    raise TaskStorageError("tareas.assignment.errors.backend")


def reassign_responsible(command):
    return _dispatch("reassign_responsible", command)


def add_task_participant(command):
    return _dispatch("add_task_participant", command)


def remove_task_participant(command):
    return _dispatch("remove_task_participant", command)


def change_participant_role(command):
    return _dispatch("change_participant_role", command)


def _dispatch(operation, command):
    try:
        storage = resolve_participant_storage()
    except TaskStorageError:
        raise
    except Exception:
        logger.error("Participant backend resolution failed")
        raise TaskStorageError("tareas.assignment.errors.backend") from None
    return getattr(storage, operation)(command)
