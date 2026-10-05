from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .closure import validate_closure_requirements
from .lifecycle import approve_closure, complete_task, reject_closure
from .task_storage import EditTaskNotFound, TaskStorageError
from .connection_roles import TareaConnectionError, get_tarea_connection, get_tarea_mysql_connection
from settings.services.mysql_connections import open_mysql_connection
from ..models import Empresa, Tarea, TareaCierre
from .notifications import emit_task_event
from django.contrib.auth.models import User


@dataclass(frozen=True)
class ClosureCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    comentario: str = ""


@dataclass(frozen=True)
class ClosureResult:
    task_id: int
    empresa_id: int
    state: str
    cierre_completado: bool
    fecha_cumplimiento: object
    transition_id: int | None = None
    cierre_id: int | None = None


class DjangoClosureStorage:
    def __init__(self, alias: str):
        self.alias = alias

    def _task(self, command):
        try:
            return Tarea.objects.using(self.alias).get(
                pk=command.task_id,
                empresa_id=command.empresa_id,
            )
        except Tarea.DoesNotExist as exc:
            raise EditTaskNotFound from exc

    def complete(self, command: ClosureCommand) -> ClosureResult:
        task = self._task(command)
        transition = complete_task(task, User.objects.using("default").get(pk=command.actor_id))
        task.refresh_from_db(using=self.alias)
        return ClosureResult(task.pk, task.empresa_id, task.estado, task.cierre_completado, task.fecha_cumplimiento, transition.pk)

    def approve(self, command: ClosureCommand) -> ClosureResult:
        task = self._task(command)
        actor = User.objects.using("default").get(pk=command.actor_id)
        transition = approve_closure(task, actor, command.comentario)
        task.refresh_from_db(using=self.alias)
        cierre = TareaCierre.objects.using(self.alias).filter(tarea_id=task.pk).order_by("-pk").first()
        return ClosureResult(task.pk, task.empresa_id, task.estado, task.cierre_completado, task.fecha_cumplimiento, transition.pk, cierre.pk if cierre else None)

    def reject(self, command: ClosureCommand) -> ClosureResult:
        task = self._task(command)
        actor = User.objects.using("default").get(pk=command.actor_id)
        transition = reject_closure(task, actor, command.comentario)
        task.refresh_from_db(using=self.alias)
        cierre = TareaCierre.objects.using(self.alias).filter(tarea_id=task.pk).order_by("-pk").first()
        return ClosureResult(task.pk, task.empresa_id, task.estado, task.cierre_completado, task.fecha_cumplimiento, transition.pk, cierre.pk if cierre else None)


class MySQLClosureStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    @staticmethod
    def _notify(empresa_id, task_id, actor_id, user_ids, event, title, body):
        try:
            empresa = Empresa.objects.using("default").get(pk=empresa_id)
            recipients = list(
                User.objects.using("default")
                .filter(pk__in={item for item in user_ids if item is not None}, is_active=True)
                .exclude(pk=actor_id)
            )
            emit_task_event(
                tarea=SimpleNamespace(pk=task_id, empresa=empresa),
                event=event,
                recipients=recipients,
                title=title,
                body=body,
                actor=User.objects.using("default").get(pk=actor_id),
            )
        except Exception:
            return

    @staticmethod
    def _validate_blockers(cursor, task_id, empresa_id, requires_evidence):
        errors = []
        cursor.execute(
            "SELECT COUNT(*) FROM tareas_minitarea m JOIN tareas_tarea t ON t.id=m.tarea_id "
            "WHERE m.tarea_id=%s AND t.empresa_id=%s AND m.hecho=%s",
            (task_id, empresa_id, False),
        )
        if (cursor.fetchone() or (0,))[0]:
            errors.append("MINI_TASKS_PENDING: No se puede cerrar una tarea con mini-tareas pendientes.")

        cursor.execute(
            "SELECT r.hija_id, c.estado, c.anulada FROM tareas_tarearelacion r "
            "JOIN tareas_tarea c ON c.id=r.hija_id "
            "WHERE r.padre_id=%s AND c.empresa_id=%s ORDER BY c.id",
            (task_id, empresa_id),
        )
        children = cursor.fetchall()
        child_ids = [row[0] for row in children]
        descendants = list(children)
        if child_ids:
            marks = ",".join("%s" for _ in child_ids)
            cursor.execute(
                f"SELECT r.hija_id, c.estado, c.anulada, r.padre_id FROM tareas_tarearelacion r "
                f"JOIN tareas_tarea c ON c.id=r.hija_id WHERE r.padre_id IN ({marks}) AND c.empresa_id=%s ORDER BY c.id",
                tuple(child_ids) + (empresa_id,),
            )
            descendants.extend(cursor.fetchall())
        if any(row[1] != Tarea.Estado.CERRADA and not row[2] for row in descendants):
            errors.append("DESCENDANTS_PENDING: No se puede cerrar una tarea con descendientes operativos pendientes.")

        if requires_evidence:
            cursor.execute(
                "SELECT formato_archivo, archivo, url FROM tareas_evidenciacierre WHERE tarea_id=%s",
                (task_id,),
            )
            valid = any(bool(row[1] or row[2]) and bool(row[0]) for row in cursor.fetchall())
            if not valid:
                errors.append("CLOSURE_EVIDENCE_REQUIRED: Se requiere al menos una evidencia de cierre válida.")

        cursor.execute(
            "SELECT r.minimo_cotizaciones FROM tareas_rondacotizacion r "
            "WHERE r.tarea_id=%s ORDER BY r.numero DESC LIMIT 1",
            (task_id,),
        )
        round_row = cursor.fetchone()
        if round_row:
            cursor.execute(
                "SELECT COUNT(DISTINCT c.proveedor_id) FROM tareas_cotizacion c "
                "JOIN tareas_rondacotizacion r ON r.id=c.ronda_id "
                "WHERE r.tarea_id=%s AND r.numero=(SELECT MAX(numero) FROM tareas_rondacotizacion WHERE tarea_id=%s) "
                "AND c.vigente=%s AND c.proveedor_id IS NOT NULL",
                (task_id, task_id, True),
            )
            if (cursor.fetchone() or (0,))[0] < round_row[0]:
                errors.append("QUOTATION_MINIMUM_NOT_MET: La última ronda no cumple el mínimo de cotizaciones vigentes.")
        if errors:
            raise ValidationError(errors)

    def _open_task(self, cursor, command):
        cursor.execute(
            "SELECT id, empresa_id, estado, anulada, cierre_completado, "
            "fecha_cumplimiento, requiere_evidencia_cierre, responsable_id, creada_por_id "
            "FROM tareas_tarea WHERE id=%s AND empresa_id=%s FOR UPDATE",
            (command.task_id, command.empresa_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise EditTaskNotFound
        return row

    def complete(self, command: ClosureCommand) -> ClosureResult:
        return self._complete_or_reject(command, approve=False)

    def _complete_or_reject(self, command, approve):
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor = connection.cursor()
                try:
                    if callable(getattr(connection, "begin", None)):
                        connection.begin()
                    row = self._open_task(cursor, command)
                    _id, _company, state, annulled, _closed, _completed_at, _requires, _responsible, _creator = row
                    if (approve and state != Tarea.Estado.PENDIENTE_APROBACION_CIERRE) or (not approve and state != Tarea.Estado.GESTION):
                        raise ValidationError("Transición no permitida para el estado actual de la tarea.")
                    if annulled:
                        raise ValidationError("La tarea está anulada; no admite operaciones de ciclo.")
                    if not approve:
                        now = timezone.now()
                        cursor.execute("UPDATE tareas_tarea SET cierre_completado=%s, fecha_cumplimiento=%s, estado=%s WHERE id=%s AND empresa_id=%s", (True, now, Tarea.Estado.PENDIENTE_APROBACION_CIERRE, command.task_id, command.empresa_id))
                        cursor.execute("INSERT INTO tareas_tareatransicion (tarea_id, estado_origen, estado_destino, accion_evento, usuario_id, timestamp, motivo) VALUES (%s,%s,%s,%s,%s,%s,%s)", (command.task_id, Tarea.Estado.GESTION, Tarea.Estado.PENDIENTE_APROBACION_CIERRE, "MARCAR_100", command.actor_id, now, ""))
                        transition_id = cursor.lastrowid
                        connection.commit()
                        self._notify(command.empresa_id, command.task_id, command.actor_id, [row[8], row[7]], "solicitud_aprobacion_cierre", "Solicitud de aprobación de cierre", "La tarea está pendiente de aprobación de cierre.")
                        return ClosureResult(command.task_id, command.empresa_id, Tarea.Estado.PENDIENTE_APROBACION_CIERRE, True, now, transition_id)
                    self._validate_blockers(cursor, command.task_id, command.empresa_id, row[6])
                    cursor.execute("UPDATE tareas_tarea SET estado=%s, cierre_completado=%s WHERE id=%s AND empresa_id=%s", (Tarea.Estado.CERRADA, True, command.task_id, command.empresa_id))
                    cursor.execute("INSERT INTO tareas_tareatransicion (tarea_id, estado_origen, estado_destino, accion_evento, usuario_id, timestamp, motivo) VALUES (%s,%s,%s,%s,%s,%s,%s)", (command.task_id, Tarea.Estado.PENDIENTE_APROBACION_CIERRE, Tarea.Estado.CERRADA, "APROBAR_CIERRE", command.actor_id, timezone.now(), command.comentario))
                    transition_id = cursor.lastrowid
                    cursor.execute("INSERT INTO tareas_tareacierre (tarea_id, usuario_id, timestamp, resultado, comentario) VALUES (%s,%s,%s,%s,%s)", (command.task_id, command.actor_id, timezone.now(), TareaCierre.Resultado.APROBADO, command.comentario))
                    cierre_id = cursor.lastrowid
                    connection.commit()
                    self._notify(command.empresa_id, command.task_id, command.actor_id, [row[8], row[7]], "aprobacion_cierre", "Cierre de tarea aprobado", "El cierre de la tarea fue aprobado.")
                    return ClosureResult(command.task_id, command.empresa_id, Tarea.Estado.CERRADA, True, row[5], transition_id, cierre_id)
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except (EditTaskNotFound, ValidationError):
            raise
        except Exception as exc:
            raise TaskStorageError("No se pudo procesar el cierre de la Tarea.") from exc

    def approve(self, command):
        return self._complete_or_reject(command, approve=True)

    def reject(self, command: ClosureCommand) -> ClosureResult:
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor = connection.cursor()
                try:
                    if callable(getattr(connection, "begin", None)):
                        connection.begin()
                    row = self._open_task(cursor, command)
                    if row[2] != Tarea.Estado.PENDIENTE_APROBACION_CIERRE:
                        raise ValidationError("Transición no permitida para el estado actual de la tarea.")
                    if row[3]:
                        raise ValidationError("La tarea está anulada; no admite operaciones de ciclo.")
                    now = timezone.now()
                    cursor.execute("UPDATE tareas_tarea SET estado=%s, fecha_cumplimiento=%s, cierre_completado=%s WHERE id=%s AND empresa_id=%s", (Tarea.Estado.GESTION, None, True, command.task_id, command.empresa_id))
                    cursor.execute("INSERT INTO tareas_tareatransicion (tarea_id, estado_origen, estado_destino, accion_evento, usuario_id, timestamp, motivo) VALUES (%s,%s,%s,%s,%s,%s,%s)", (command.task_id, Tarea.Estado.PENDIENTE_APROBACION_CIERRE, Tarea.Estado.GESTION, "RECHAZAR_CIERRE", command.actor_id, now, command.comentario))
                    transition_id = cursor.lastrowid
                    cursor.execute("INSERT INTO tareas_tareacierre (tarea_id, usuario_id, timestamp, resultado, comentario) VALUES (%s,%s,%s,%s,%s)", (command.task_id, command.actor_id, now, TareaCierre.Resultado.RECHAZADO, command.comentario))
                    cierre_id = cursor.lastrowid
                    connection.commit()
                    self._notify(command.empresa_id, command.task_id, command.actor_id, [row[8], row[7]], "rechazo_cierre", "Cierre de tarea rechazado", "El cierre de la tarea fue rechazado.")
                    return ClosureResult(command.task_id, command.empresa_id, Tarea.Estado.GESTION, True, None, transition_id, cierre_id)
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except (EditTaskNotFound, ValidationError):
            raise
        except Exception as exc:
            raise TaskStorageError("No se pudo rechazar el cierre de la Tarea.") from exc


def resolve_closure_storage():
    source = get_tarea_connection("BASE_TAREAS")
    if source["type"] == "DJANGO":
        return DjangoClosureStorage(source["alias"])
    if source["type"] == "MYSQL_CONFIG":
        return MySQLClosureStorage(get_tarea_mysql_connection("BASE_TAREAS"), source["database_name"])
    raise TaskStorageError("El backend de BASE_TAREAS no es válido.")
