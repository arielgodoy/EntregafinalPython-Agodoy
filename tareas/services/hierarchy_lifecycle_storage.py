from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.db.models import Q
from django.utils import timezone

from .connection_roles import resolve_operational_backend
from .lifecycle import annul_task, reactivate_task
from .notifications import emit_task_event
from .task_storage import EditTaskNotFound, TaskStorageError
from settings.services.mysql_connections import open_mysql_connection
from .task_mutation_locks import (
    TaskMutationConflict,
    TaskMutationLockError,
    TaskMutationScopeError,
    bounded_django_lock_wait,
    bounded_mysql_lock_wait,
    is_task_mutation_conflict,
    lock_mysql_task_rows,
    lock_orm_task_rows,
    mysql_mutation_transaction,
)
from ..models import Empresa, Tarea, TareaRelacion, TareaTransicion


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

    def get_parent(self, task_id, empresa_id=None):
        relation = TareaRelacion.objects.using(self.alias).filter(
            hija_id=task_id,
        ).select_related("padre").first()
        return relation.padre if relation else None

    def get_children(self, task_id, empresa_id=None):
        return Tarea.objects.using(self.alias).filter(
            relaciones_padre__padre_id=task_id,
        ).order_by("id")

    def _relation_parent_map(self, empresa_id):
        queryset = (
            TareaRelacion.objects.using(self.alias)
            .filter(
                Q(padre__empresa_id=empresa_id)
                | Q(hija__empresa_id=empresa_id)
            )
            .select_related("padre", "hija")
            .order_by("padre_id", "hija_id")
        )
        if connections[self.alias].features.has_select_for_update:
            queryset = queryset.select_for_update()
        parent_by_child = {}
        for relation in queryset:
            if (
                relation.padre.empresa_id != empresa_id
                or relation.hija.empresa_id != empresa_id
            ):
                raise ValidationError(
                    "La jerarquía contiene una relación entre empresas."
                )
            if relation.hija_id in parent_by_child:
                raise ValidationError(
                    "La jerarquía contiene más de un padre para una tarea."
                )
            parent_by_child[relation.hija_id] = relation.padre
        return parent_by_child

    def create_relation(self, parent_id, child_id, *, company_id):
        try:
            with transaction.atomic(using=self.alias):
                with bounded_django_lock_wait(self.alias):
                    locked_tasks = lock_orm_task_rows(
                        self.alias,
                        company_id,
                    )
                    tasks = {task.pk: task for task in locked_tasks}
                    parent = tasks.get(parent_id)
                    child = tasks.get(child_id)
                    if parent is None or child is None:
                        raise ValidationError(
                            "Padre e hija deben existir en la empresa activa."
                        )
                    parent_by_child = self._relation_parent_map(company_id)
                    from .hierarchy import validate_relation

                    validate_relation(
                        parent,
                        child,
                        parent_resolver=lambda task: parent_by_child.get(task.pk),
                    )
                    return TareaRelacion.objects.using(self.alias).create(
                        padre_id=parent_id,
                        hija_id=child_id,
                    )
        except (ValidationError, TaskMutationLockError):
            raise
        except Exception as exc:
            if is_task_mutation_conflict(exc):
                raise TaskMutationConflict(
                    "La jerarquía cambió en otra operación; vuelva a intentarlo."
                ) from exc
            raise TaskStorageError(
                "No se pudo crear la relación jerárquica."
            ) from exc

    def annulment_timestamp(self, task_id):
        return TareaTransicion.objects.using(self.alias).filter(
            tarea_id=task_id, accion_evento="ANULAR",
        ).order_by("-timestamp").values_list("timestamp", flat=True).first()

    def annul(self, command):
        with transaction.atomic(using=self.alias):
            task = self._task(command)
            actor = User.objects.using("default").get(pk=command.actor_id)
            annul_task(task, actor, command.motivo)
            task.refresh_from_db(using=self.alias)
            transition = TareaTransicion.objects.using(self.alias).filter(tarea_id=task.pk, accion_evento="ANULAR").order_by("-pk").first()
            return HierarchyLifecycleResult(task.pk, task.empresa_id, task.anulada, transition.pk if transition else None)

    def reactivate(self, command):
        with transaction.atomic(using=self.alias):
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

    @staticmethod
    def _task_data(row):
        if row is None:
            return None
        task_id, company_id, state, annulled = row
        return SimpleNamespace(
            pk=task_id,
            empresa_id=company_id,
            estado=state,
            anulada=bool(annulled),
        )

    def get_parent(self, task_id, empresa_id=None):
        with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT parent.id,parent.empresa_id,parent.estado,parent.anulada "
                    "FROM tareas_tarearelacion relation "
                    "JOIN tareas_tarea parent ON parent.id=relation.padre_id "
                    "JOIN tareas_tarea child ON child.id=relation.hija_id "
                    "WHERE relation.hija_id=%s "
                    "AND (%s IS NULL OR child.empresa_id=%s) "
                    "AND (%s IS NULL OR parent.empresa_id=%s)",
                    (task_id, empresa_id, empresa_id, empresa_id, empresa_id),
                )
                return self._task_data(cursor.fetchone())
            finally:
                cursor.close()

    def get_children(self, task_id, empresa_id=None):
        with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT child.id,child.empresa_id,child.estado,child.anulada "
                    "FROM tareas_tarearelacion relation "
                    "JOIN tareas_tarea parent ON parent.id=relation.padre_id "
                    "JOIN tareas_tarea child ON child.id=relation.hija_id "
                    "WHERE relation.padre_id=%s "
                    "AND (%s IS NULL OR parent.empresa_id=%s) "
                    "AND (%s IS NULL OR child.empresa_id=%s) "
                    "ORDER BY child.id",
                    (task_id, empresa_id, empresa_id, empresa_id, empresa_id),
                )
                return [self._task_data(row) for row in cursor.fetchall()]
            finally:
                cursor.close()

    @staticmethod
    def _relation_parent_map(connection, empresa_id):
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT relation.padre_id, relation.hija_id, "
                "parent.empresa_id, child.empresa_id "
                "FROM tareas_tarearelacion AS relation "
                "INNER JOIN tareas_tarea AS parent "
                "ON parent.id = relation.padre_id "
                "INNER JOIN tareas_tarea AS child "
                "ON child.id = relation.hija_id "
                "WHERE parent.empresa_id = %s OR child.empresa_id = %s "
                "ORDER BY relation.padre_id, relation.hija_id FOR UPDATE",
                (empresa_id, empresa_id),
            )
            rows = tuple(cursor.fetchall())
        finally:
            cursor.close()
        parent_by_child = {}
        for parent_id, child_id, parent_company, child_company in rows:
            if parent_company != empresa_id or child_company != empresa_id:
                raise ValidationError(
                    "La jerarquía contiene una relación entre empresas."
                )
            if child_id in parent_by_child:
                raise ValidationError(
                    "La jerarquía contiene más de un padre para una tarea."
                )
            parent_by_child[child_id] = SimpleNamespace(
                pk=parent_id,
                empresa_id=parent_company,
            )
        return parent_by_child

    def create_relation(self, parent_id, child_id, *, company_id):
        try:
            with open_mysql_connection(
                self.connection_config,
                database_name=self.database_name,
            ) as connection:
                with bounded_mysql_lock_wait(connection):
                    with mysql_mutation_transaction(connection):
                        task_ids = lock_mysql_task_rows(connection, company_id)
                        if parent_id not in task_ids or child_id not in task_ids:
                            raise ValidationError(
                                "Padre e hija deben existir en la empresa activa."
                            )
                        parent_by_id = {}
                        for task_id in (parent_id, child_id):
                            parent_by_id[task_id] = SimpleNamespace(
                                pk=task_id,
                                empresa_id=company_id,
                            )
                        parent_by_child = self._relation_parent_map(
                            connection,
                            company_id,
                        )
                        from .hierarchy import validate_relation

                        validate_relation(
                            parent_by_id[parent_id],
                            parent_by_id[child_id],
                            parent_resolver=lambda task: parent_by_child.get(
                                task.pk
                            ),
                        )
                        cursor = connection.cursor()
                        try:
                            cursor.execute(
                                "INSERT INTO tareas_tarearelacion "
                                "(padre_id,hija_id) VALUES (%s,%s)",
                                (parent_id, child_id),
                            )
                            relation_id = cursor.lastrowid
                        finally:
                            cursor.close()
        except (ValidationError, TaskMutationLockError):
            raise
        except Exception as exc:
            if is_task_mutation_conflict(exc):
                raise TaskMutationConflict(
                    "La jerarquía cambió en otra operación; vuelva a intentarlo."
                ) from exc
            raise TaskStorageError(
                "No se pudo crear la relación jerárquica."
            ) from exc
        return SimpleNamespace(
            id=relation_id,
            padre_id=parent_id,
            hija_id=child_id,
        )

    def annulment_timestamp(self, task_id):
        with open_mysql_connection(
            self.connection_config, database_name=self.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT timestamp FROM tareas_tareatransicion "
                    "WHERE tarea_id=%s AND accion_evento=%s "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (task_id, "ANULAR"),
                )
                row = cursor.fetchone()
                return row[0] if row else None
            finally:
                cursor.close()

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
    context = resolve_operational_backend("BASE_TAREAS")
    if context.backend_type == "DJANGO":
        return DjangoHierarchyLifecycleStorage(context.django_alias)
    if context.backend_type == "MYSQL_CONFIG":
        return MySQLHierarchyLifecycleStorage(
            context.mysql_connection,
            context.database_name,
        )
    raise TaskStorageError("El backend de BASE_TAREAS no es válido.")
