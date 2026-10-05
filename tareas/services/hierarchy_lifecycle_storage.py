from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .connection_roles import get_tarea_connection, get_tarea_mysql_connection
from .lifecycle import annul_task, reactivate_task
from .notifications import emit_task_event
from .task_storage import EditTaskNotFound, TaskStorageError
from settings.services.mysql_connections import open_mysql_connection
from ..models import Empresa, Tarea, TareaTransicion


@dataclass(frozen=True)
class HierarchyLifecycleCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    motivo: str = ""


@dataclass(frozen=True)
class HierarchyLifecycleResult:
    task_id: int
    empresa_id: int
    anulada: bool
    transition_id: int | None = None


class DjangoHierarchyLifecycleStorage:
    def __init__(self, alias: str):
        self.alias = alias

    def _task(self, command):
        try:
            return Tarea.objects.using(self.alias).get(pk=command.task_id, empresa_id=command.empresa_id)
        except Tarea.DoesNotExist as exc:
            raise EditTaskNotFound from exc

    def annul(self, command):
        task = self._task(command)
        actor = User.objects.using("default").get(pk=command.actor_id)
        annul_task(task, actor, command.motivo)
        task.refresh_from_db(using=self.alias)
        transition = TareaTransicion.objects.using(self.alias).filter(tarea_id=task.pk, accion_evento="ANULAR").order_by("-pk").first()
        return HierarchyLifecycleResult(task.pk, task.empresa_id, task.anulada, transition.pk if transition else None)

    def reactivate(self, command):
        task = self._task(command)
        actor = User.objects.using("default").get(pk=command.actor_id)
        reactivate_task(task, actor, command.motivo)
        task.refresh_from_db(using=self.alias)
        transition = TareaTransicion.objects.using(self.alias).filter(tarea_id=task.pk, accion_evento="REACTIVAR").order_by("-pk").first()
        return HierarchyLifecycleResult(task.pk, task.empresa_id, task.anulada, transition.pk if transition else None)


class MySQLHierarchyLifecycleStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    def _notify(self, empresa_id, task_id, actor_id, creator_id, responsible_id, event, title, body):
        try:
            empresa = Empresa.objects.using("default").get(pk=empresa_id)
            recipients = list(User.objects.using("default").filter(pk__in={creator_id, responsible_id}, is_active=True).exclude(pk=actor_id))
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

    def _change(self, command, *, reactivate: bool):
        action = "REACTIVAR" if reactivate else "ANULAR"
        expected = True if reactivate else False
        target = False if reactivate else True
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor = connection.cursor()
                try:
                    if callable(getattr(connection, "begin", None)):
                        connection.begin()
                    cursor.execute(
                        "SELECT id, empresa_id, estado, anulada, creada_por_id, responsable_id "
                        "FROM tareas_tarea WHERE id=%s AND empresa_id=%s FOR UPDATE",
                        (command.task_id, command.empresa_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise EditTaskNotFound
                    task_id, empresa_id, state, annulled, creator_id, responsible_id = row
                    if bool(annulled) != expected:
                        raise ValidationError(
                            "La tarea ya está anulada." if not reactivate else "La tarea no está anulada."
                        )
                    if not reactivate and state == Tarea.Estado.BORRADOR:
                        raise ValidationError("Una tarea en borrador no puede anularse.")
                    cursor.execute(
                        "UPDATE tareas_tarea SET anulada=%s WHERE id=%s AND empresa_id=%s",
                        (target, command.task_id, command.empresa_id),
                    )
                    cursor.execute(
                        "INSERT INTO tareas_tareatransicion "
                        "(tarea_id, estado_origen, estado_destino, accion_evento, usuario_id, timestamp, motivo) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (command.task_id, state, state, action, command.actor_id, timezone.now(), command.motivo),
                    )
                    transition_id = cursor.lastrowid
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except (EditTaskNotFound, ValidationError):
            raise
        except Exception as exc:
            raise TaskStorageError("No se pudo actualizar la anulación de la Tarea.") from exc
        self._notify(
            empresa_id,
            task_id,
            command.actor_id,
            creator_id,
            responsible_id,
            "reactivacion" if reactivate else "anulacion",
            "Tarea reactivada" if reactivate else "Tarea anulada",
            "La tarea fue reactivada." if reactivate else "La tarea fue anulada.",
        )
        return HierarchyLifecycleResult(task_id, empresa_id, target, transition_id)

    def annul(self, command):
        return self._change(command, reactivate=False)

    def reactivate(self, command):
        return self._change(command, reactivate=True)


def resolve_hierarchy_lifecycle_storage():
    source = get_tarea_connection("BASE_TAREAS")
    if source["type"] == "DJANGO":
        return DjangoHierarchyLifecycleStorage(source["alias"])
    if source["type"] == "MYSQL_CONFIG":
        return MySQLHierarchyLifecycleStorage(
            get_tarea_mysql_connection("BASE_TAREAS"),
            source["database_name"],
        )
    raise TaskStorageError("El backend de BASE_TAREAS no es válido.")
