"""Scoped deadline changes and their operational ledger."""

from dataclasses import dataclass
from datetime import date, datetime, timezone as datetime_timezone
import logging
from types import SimpleNamespace

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

from ..models import CausaAtraso, Reprogramacion, Tarea, TareaParticipante, TareaRelacion
from .connection_roles import TareaConnectionError, get_tarea_connection, get_tarea_mysql_connection
from .notifications import emit_task_event
from .task_storage import EditTaskNotFound, TaskStorageError

logger = logging.getLogger(__name__)
ALLOWED_REPROGRAMMING_STATES = {Tarea.Estado.ACTIVA, Tarea.Estado.GESTION}


@dataclass(frozen=True)
class ReprogramTaskCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    fecha_tope_nueva: date
    justificacion: str
    causa_ids: tuple[int, ...]


@dataclass(frozen=True)
class ReprogramTaskResult:
    task_id: int
    empresa_id: int
    reprogramacion_id: int
    fecha_tope_anterior: date
    fecha_tope_nueva: date
    fecha_operacion: datetime


@dataclass(frozen=True)
class ReprogrammingCause:
    id: int
    codigo: str
    nombre: str


@dataclass(frozen=True)
class ReprogrammingHistory:
    id: int
    fecha_tope_anterior: date
    fecha_tope_nueva: date
    justificacion: str
    usuario_id: int
    fecha_operacion: datetime
    causas: tuple[ReprogrammingCause, ...]
    usuario_username: str = ""
    usuario_avatar_url: str = ""


def normalize_reprogramming(command):
    value = command.fecha_tope_nueva
    if isinstance(value, datetime):
        value = timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    if not isinstance(value, date):
        raise ValidationError("tareas.reprogramming.errors.invalid_date")
    if value < timezone.localdate():
        raise ValidationError("tareas.reprogramming.errors.past_date")
    justification = str(command.justificacion or "").strip()
    if not justification:
        raise ValidationError("tareas.reprogramming.errors.justification_required")
    ids = tuple(command.causa_ids or ())
    if not ids:
        raise ValidationError("tareas.reprogramming.errors.causes_required")
    if any(type(item) is not int or item <= 0 for item in ids):
        raise ValidationError("tareas.reprogramming.errors.invalid_causes")
    if len(set(ids)) != len(ids):
        raise ValidationError("tareas.reprogramming.errors.duplicate_causes")
    return ReprogramTaskCommand(
        command.task_id, command.empresa_id, command.actor_id, value, justification, ids
    )


def validate_reprogramming_task(state, effectively_annulled, old_date, new_date):
    if state not in ALLOWED_REPROGRAMMING_STATES:
        raise ValidationError("tareas.reprogramming.errors.invalid_state")
    if effectively_annulled:
        raise ValidationError("tareas.reprogramming.errors.annulled")
    if old_date is None:
        raise ValidationError("tareas.reprogramming.errors.missing_current_date")
    if old_date == new_date:
        raise ValidationError("tareas.reprogramming.errors.same_date")


def authorize_reprogramming(*, empresa_id, actor_id):
    try:
        empresa = Empresa.objects.using("default").get(pk=empresa_id)
        actor = User.objects.using("default").get(pk=actor_id, is_active=True)
    except (Empresa.DoesNotExist, User.DoesNotExist) as exc:
        raise PermissionDenied from exc
    if not (
        get_valid_users_for_empresa(empresa, active_only=True).filter(pk=actor_id).exists()
        and user_has_permission_for_empresa(
            user=actor, empresa=empresa, vista_nombre="Tareas", accion="modificar"
        )
    ):
        raise PermissionDenied


def _notify(command, priority, recipient_ids):
    # Resolve SYSTEM identities only after the operational commit.
    try:
        empresa = Empresa.objects.using("default").get(pk=command.empresa_id)
        actor = User.objects.using("default").get(pk=command.actor_id)
        recipients = User.objects.using("default").filter(
            pk__in=recipient_ids, is_active=True
        ).exclude(pk=command.actor_id)
        emit_task_event(
            tarea=SimpleNamespace(pk=command.task_id, empresa=empresa, prioridad=priority),
            event="reprogramacion",
            recipients=recipients,
            title="Fecha tope reprogramada",
            body="La fecha tope de la tarea fue reprogramada.",
            actor=actor,
        )
    except Exception:
        logger.error(
            "Reprogramming communication failed: task=%s company=%s",
            command.task_id, command.empresa_id,
        )


class DjangoReprogrammingStorage:
    def __init__(self, alias):
        self.alias = alias

    def reprogram(self, command):
        command = normalize_reprogramming(command)
        try:
            with transaction.atomic(using=self.alias):
                try:
                    task = Tarea.objects.using(self.alias).select_for_update().get(
                        pk=command.task_id, empresa_id=command.empresa_id
                    )
                except Tarea.DoesNotExist as exc:
                    raise EditTaskNotFound from exc
                annulled = task.anulada
                current_id = task.pk
                # Same task/parent/grandparent policy, with explicit backend and locks.
                for _ in range(2):
                    parent_id = TareaRelacion.objects.using(self.alias).filter(
                        hija_id=current_id,
                        hija__empresa_id=command.empresa_id,
                        padre__empresa_id=command.empresa_id,
                    ).values_list("padre_id", flat=True).first()
                    if parent_id is None:
                        break
                    parent = Tarea.objects.using(self.alias).select_for_update().get(
                        pk=parent_id, empresa_id=command.empresa_id
                    )
                    annulled = annulled or parent.anulada
                    current_id = parent.pk
                validate_reprogramming_task(
                    task.estado, annulled, task.fecha_tope, command.fecha_tope_nueva
                )
                causes = set(CausaAtraso.objects.using(self.alias).filter(
                    pk__in=command.causa_ids
                ).values_list("pk", flat=True))
                if causes != set(command.causa_ids):
                    raise ValidationError("tareas.reprogramming.errors.invalid_causes")
                old_date = task.fecha_tope
                now = timezone.now()
                Tarea.objects.using(self.alias).filter(
                    pk=command.task_id, empresa_id=command.empresa_id
                ).update(fecha_tope=command.fecha_tope_nueva)
                history = Reprogramacion.objects.using(self.alias).create(
                    tarea_id=task.pk, fecha_tope_anterior=old_date,
                    fecha_tope_nueva=command.fecha_tope_nueva,
                    justificacion=command.justificacion, usuario_id=command.actor_id,
                    fecha_operacion=now,
                )
                through = Reprogramacion.causas.through
                through.objects.using(self.alias).bulk_create([
                    through(reprogramacion_id=history.pk, causaatraso_id=cause_id)
                    for cause_id in command.causa_ids
                ])
                recipient_ids = set(TareaParticipante.objects.using(self.alias).filter(
                    tarea_id=task.pk, tarea__empresa_id=command.empresa_id
                ).values_list("usuario_id", flat=True))
                recipient_ids.add(task.responsable_id)
                transaction.on_commit(
                    lambda: _notify(command, task.prioridad, recipient_ids),
                    using=self.alias,
                )
                return ReprogramTaskResult(
                    task.pk, command.empresa_id, history.pk, old_date,
                    command.fecha_tope_nueva, now,
                )
        except (EditTaskNotFound, ValidationError):
            raise
        except Exception as exc:
            raise TaskStorageError("tareas.reprogramming.errors.storage") from exc


class MySQLReprogrammingStorage:
    def __init__(self, connection_config, database_name):
        self.connection_config = connection_config
        self.database_name = database_name

    def reprogram(self, command):
        command = normalize_reprogramming(command)
        try:
            with open_mysql_connection(
                self.connection_config, database_name=self.database_name
            ) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute("START TRANSACTION")
                    cursor.execute(
                        "SELECT id, estado, anulada, fecha_tope, prioridad, responsable_id "
                        "FROM tareas_tarea WHERE id=%s AND empresa_id=%s FOR UPDATE",
                        (command.task_id, command.empresa_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise EditTaskNotFound
                    task_id, state, annulled, old_date, priority, responsible_id = row
                    current_id = task_id
                    for _ in range(2):
                        cursor.execute(
                            "SELECT p.id, p.anulada FROM tareas_tarearelacion r "
                            "JOIN tareas_tarea p ON p.id=r.padre_id "
                            "JOIN tareas_tarea c ON c.id=r.hija_id "
                            "WHERE r.hija_id=%s AND p.empresa_id=%s AND c.empresa_id=%s "
                            "FOR UPDATE",
                            (current_id, command.empresa_id, command.empresa_id),
                        )
                        parent = cursor.fetchone()
                        if parent is None:
                            break
                        current_id = parent[0]
                        annulled = bool(annulled) or bool(parent[1])
                    validate_reprogramming_task(
                        state, bool(annulled), old_date, command.fecha_tope_nueva
                    )
                    marks = ", ".join("%s" for _ in command.causa_ids)
                    cursor.execute(
                        f"SELECT id FROM tareas_causaatraso WHERE id IN ({marks})",
                        command.causa_ids,
                    )
                    if {item[0] for item in cursor.fetchall()} != set(command.causa_ids):
                        raise ValidationError("tareas.reprogramming.errors.invalid_causes")
                    cursor.execute(
                        "SELECT p.usuario_id FROM tareas_tareaparticipante p "
                        "JOIN tareas_tarea t ON t.id=p.tarea_id "
                        "WHERE p.tarea_id=%s AND t.empresa_id=%s",
                        (task_id, command.empresa_id),
                    )
                    recipient_ids = {item[0] for item in cursor.fetchall()}
                    recipient_ids.add(responsible_id)
                    now = timezone.now()
                    cursor.execute(
                        "UPDATE tareas_tarea SET fecha_tope=%s WHERE id=%s AND empresa_id=%s",
                        (command.fecha_tope_nueva, task_id, command.empresa_id),
                    )
                    cursor.execute(
                        "INSERT INTO tareas_reprogramacion "
                        "(tarea_id, fecha_tope_anterior, fecha_tope_nueva, justificacion, "
                        "usuario_id, fecha_operacion) VALUES (%s,%s,%s,%s,%s,%s)",
                        (task_id, old_date, command.fecha_tope_nueva,
                         command.justificacion, command.actor_id, now),
                    )
                    history_id = cursor.lastrowid
                    for cause_id in command.causa_ids:
                        cursor.execute(
                            "INSERT INTO tareas_reprogramacion_causas "
                            "(reprogramacion_id, causaatraso_id) VALUES (%s,%s)",
                            (history_id, cause_id),
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except (EditTaskNotFound, ValidationError):
            raise
        except Exception as exc:
            raise TaskStorageError("tareas.reprogramming.errors.storage") from exc
        _notify(command, priority, recipient_ids)
        return ReprogramTaskResult(
            task_id, command.empresa_id, history_id, old_date, command.fecha_tope_nueva, now
        )


def resolve_reprogramming_storage():
    try:
        source = get_tarea_connection("BASE_TAREAS")
        if source["type"] == "DJANGO":
            return DjangoReprogrammingStorage(source["alias"])
        if source["type"] == "MYSQL_CONFIG":
            return MySQLReprogrammingStorage(
                get_tarea_mysql_connection("BASE_TAREAS"), source["database_name"]
            )
    except TareaConnectionError as exc:
        raise TaskStorageError("tareas.reprogramming.errors.backend") from exc
    raise TaskStorageError("tareas.reprogramming.errors.backend")


def reprogram_task(command):
    authorize_reprogramming(empresa_id=command.empresa_id, actor_id=command.actor_id)
    return resolve_reprogramming_storage().reprogram(command)


def django_reprogramming_detail(alias, task_id, empresa_id):
    try:
        return _django_reprogramming_detail(alias, task_id, empresa_id)
    except Exception as exc:
        raise TaskStorageError("tareas.reprogramming.errors.storage") from exc


def _django_reprogramming_detail(alias, task_id, empresa_id):
    from django.db.models import Prefetch

    causes = tuple(
        ReprogrammingCause(item.pk, item.codigo, item.nombre)
        for item in CausaAtraso.objects.using(alias).order_by("codigo")
    )
    rows = Reprogramacion.objects.using(alias).filter(
        tarea_id=task_id, tarea__empresa_id=empresa_id
    ).prefetch_related(Prefetch(
        "causas", queryset=CausaAtraso.objects.using(alias).order_by("codigo")
    )).order_by("-fecha_operacion", "-pk")
    history = tuple(ReprogrammingHistory(
        item.pk, item.fecha_tope_anterior, item.fecha_tope_nueva, item.justificacion,
        item.usuario_id, item.fecha_operacion,
        tuple(ReprogrammingCause(c.pk, c.codigo, c.nombre) for c in item.causas.all()),
    ) for item in rows)
    return causes, history


def mysql_reprogramming_detail(cursor, task_id, empresa_id):
    cursor.execute("SELECT id, codigo, nombre FROM tareas_causaatraso ORDER BY codigo")
    causes = tuple(ReprogrammingCause(*row) for row in cursor.fetchall())
    cursor.execute(
        "SELECT r.id, r.fecha_tope_anterior, r.fecha_tope_nueva, r.justificacion, "
        "r.usuario_id, r.fecha_operacion FROM tareas_reprogramacion r "
        "JOIN tareas_tarea t ON t.id=r.tarea_id "
        "WHERE r.tarea_id=%s AND t.empresa_id=%s ORDER BY r.fecha_operacion DESC, r.id DESC",
        (task_id, empresa_id),
    )
    rows = cursor.fetchall()
    cursor.execute(
        "SELECT rc.reprogramacion_id, c.id, c.codigo, c.nombre "
        "FROM tareas_reprogramacion_causas rc "
        "JOIN tareas_causaatraso c ON c.id=rc.causaatraso_id "
        "JOIN tareas_reprogramacion r ON r.id=rc.reprogramacion_id "
        "JOIN tareas_tarea t ON t.id=r.tarea_id "
        "WHERE r.tarea_id=%s AND t.empresa_id=%s ORDER BY c.codigo",
        (task_id, empresa_id),
    )
    by_history = {}
    for history_id, cause_id, code, name in cursor.fetchall():
        by_history.setdefault(history_id, []).append(ReprogrammingCause(cause_id, code, name))
    history = tuple(ReprogrammingHistory(
        *row[:5],
        timezone.make_aware(row[5], datetime_timezone.utc)
        if timezone.is_naive(row[5]) else row[5],
        tuple(by_history.get(row[0], ())),
    ) for row in rows)
    return causes, history
