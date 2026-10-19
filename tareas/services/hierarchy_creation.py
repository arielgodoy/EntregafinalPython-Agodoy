"""Atomic creation of a task and its parent relation."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from access_control.services.permissions import get_valid_users_for_empresa
from settings.services.mysql_connections import open_mysql_connection

from ..models import Tarea, TareaRelacion
from .connection_roles import TareaConnectionError, resolve_operational_backend
from .hierarchy import validate_relation
from .task_mutation_locks import (
    TaskMutationLockError,
    bounded_django_lock_wait,
    bounded_mysql_lock_wait,
    lock_mysql_task_company,
    lock_orm_task_rows,
    mysql_mutation_transaction,
    TaskMutationScopeError,
)
from .task_storage import (
    CreateTaskDraftInput,
    CreatedTaskResult,
    TaskStorageError,
)


@dataclass(frozen=True)
class AtomicChildTaskResult:
    task: CreatedTaskResult
    relation_id: int


def _validate_responsible(data: CreateTaskDraftInput, active_company) -> None:
    if data.responsable_id is not None and not get_valid_users_for_empresa(
        active_company,
        active_only=True,
    ).filter(pk=data.responsable_id).exists():
        raise ValidationError(
            "El responsable debe estar activo y pertenecer a la Empresa activa."
        )


def _validate_parent(parent, *, company_id: int) -> None:
    if parent is None or parent.empresa_id != company_id:
        raise ValidationError(
            "El padre debe existir en la empresa activa."
        )
    if parent.anulada:
        raise ValidationError("Una tarea anulada no puede recibir hijas.")


def _create_django_child(
    data: CreateTaskDraftInput,
    *,
    active_company,
    actor,
    parent_id: int,
    alias: str,
) -> AtomicChildTaskResult:
    company_id = active_company.pk
    with transaction.atomic(using=alias):
        with bounded_django_lock_wait(alias):
            try:
                locked = lock_orm_task_rows(alias, company_id, (parent_id,))
            except TaskMutationScopeError as exc:
                raise ValidationError(
                    "El padre debe existir en la empresa activa."
                ) from exc
            parent = locked[0] if locked else None
            _validate_parent(parent, company_id=company_id)
            parent_by_child = {}
            relations = (
                TareaRelacion.objects.using(alias)
                .select_related("padre", "hija")
                .select_for_update()
                .filter(
                    padre__empresa_id=company_id,
                    hija__empresa_id=company_id,
                    padre__eliminada=False,
                    hija__eliminada=False,
                )
                .order_by("padre_id", "hija_id")
            )
            for relation in relations:
                if relation.hija_id in parent_by_child:
                    raise ValidationError(
                        "La jerarquía contiene más de un padre para una tarea."
                    )
                parent_by_child[relation.hija_id] = relation.padre
            task = Tarea(
                titulo=data.titulo,
                descripcion=data.descripcion,
                prioridad=data.prioridad,
                responsable_id=data.responsable_id,
                fecha_tope=data.fecha_tope,
                empresa_id=company_id,
                creada_por_id=actor.pk,
            )
            task.save(using=alias, force_insert=True)
            validate_relation(
                parent,
                task,
                parent_resolver=lambda item: parent_by_child.get(item.pk),
            )
            relation = TareaRelacion.objects.using(alias).create(
                padre_id=parent_id,
                hija_id=task.pk,
            )
    result = CreatedTaskResult(
        id=task.pk,
        empresa_id=company_id,
        correlativo=task.correlativo,
        estado=task.estado,
        task=task,
        responsable_id=task.responsable_id,
        prioridad=task.prioridad,
    )
    return AtomicChildTaskResult(result, relation.pk)


def _create_mysql_child(
    data: CreateTaskDraftInput,
    *,
    active_company,
    actor,
    parent_id: int,
    connection_config,
    database_name: str,
) -> AtomicChildTaskResult:
    company_id = active_company.pk
    try:
        with open_mysql_connection(
            connection_config,
            database_name=database_name,
        ) as connection:
            with bounded_mysql_lock_wait(connection):
                with mysql_mutation_transaction(connection):
                    lock_mysql_task_company(connection, company_id)
                    cursor = connection.cursor()
                    try:
                        cursor.execute(
                            "SELECT id, empresa_id, estado, anulada "
                            "FROM tareas_tarea WHERE id=%s AND eliminada=0 FOR UPDATE",
                            (parent_id,),
                        )
                        row = cursor.fetchone()
                        parent = (
                            SimpleNamespace(
                                pk=row[0],
                                empresa_id=row[1],
                                estado=row[2],
                                anulada=bool(row[3]),
                            )
                            if row is not None
                            else None
                        )
                        _validate_parent(parent, company_id=company_id)
                        cursor.execute(
                            "SELECT relation.padre_id, relation.hija_id "
                            "FROM tareas_tarearelacion relation "
                            "JOIN tareas_tarea parent ON parent.id=relation.padre_id "
                            "JOIN tareas_tarea child ON child.id=relation.hija_id "
                            "WHERE parent.empresa_id=%s AND child.empresa_id=%s "
                            "AND parent.eliminada=0 AND child.eliminada=0 "
                            "ORDER BY relation.padre_id, relation.hija_id FOR UPDATE",
                            (company_id, company_id),
                        )
                        parent_by_child = {
                            int(child_id): SimpleNamespace(
                                pk=int(parent_id_row),
                                empresa_id=company_id,
                            )
                            for parent_id_row, child_id in cursor.fetchall()
                        }
                        number_cursor = connection.cursor()
                        try:
                            number_cursor.execute(
                                "SELECT siguiente_numero "
                                "FROM tareas_correlativoempresa "
                                "WHERE empresa_id=%s FOR UPDATE",
                                (company_id,),
                            )
                            number_row = number_cursor.fetchone()
                            if number_row is None:
                                raise TaskStorageError(
                                    "No se pudo reservar el correlativo de Tareas."
                                )
                            number = int(number_row[0])
                            number_cursor.execute(
                                "UPDATE tareas_correlativoempresa "
                                "SET siguiente_numero=%s WHERE empresa_id=%s",
                                (number + 1, company_id),
                            )
                        finally:
                            number_cursor.close()
                        created_at = timezone.now()
                        cursor.execute(
                            "INSERT INTO tareas_tarea ("
                            "titulo,descripcion,prioridad,correlativo,anulada,"
                            "fechas_pendientes_confirmacion,cierre_completado,"
                            "requiere_evidencia_cierre,estado,responsable_id,empresa_id,"
                            "tipo_ambito,local_id,departamento_id,creada_por_id,"
                            "fecha_creacion,fecha_publicacion,fecha_asignacion,fecha_tope,"
                            "fecha_cumplimiento,todo_origen_id,tarea_origen_id"
                            ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                            "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                data.titulo, data.descripcion, data.prioridad,
                                f"B{number:07d}", False, False, False, False,
                                Tarea.Estado.BORRADOR, data.responsable_id, company_id,
                                None, None, None, actor.pk, created_at, None, None,
                                data.fecha_tope, None, None, None,
                            ),
                        )
                        task_id = int(cursor.lastrowid)
                        child = SimpleNamespace(
                            pk=task_id,
                            empresa_id=company_id,
                            estado=Tarea.Estado.BORRADOR,
                            anulada=False,
                        )
                        validate_relation(
                            parent,
                            child,
                            parent_resolver=lambda item: parent_by_child.get(item.pk),
                        )
                        cursor.execute(
                            "INSERT INTO tareas_tarearelacion "
                            "(padre_id,hija_id,fecha) VALUES (%s,%s,%s)",
                            (parent_id, task_id, created_at),
                        )
                        relation_id = int(cursor.lastrowid)
                    finally:
                        cursor.close()
    except (ValidationError, TaskMutationLockError, TaskStorageError):
        raise
    except Exception as exc:
        raise TaskStorageError(
            "No se pudo crear y vincular la tarea hija."
        ) from exc
    result = CreatedTaskResult(
        id=task_id,
        empresa_id=company_id,
        correlativo=f"B{number:07d}",
        estado=Tarea.Estado.BORRADOR,
        responsable_id=data.responsable_id,
        prioridad=data.prioridad,
    )
    return AtomicChildTaskResult(result, relation_id)


def create_child_task_atomic(
    data: CreateTaskDraftInput,
    *,
    active_company,
    actor,
    parent_id: int,
) -> AtomicChildTaskResult:
    """Create a draft and its parent relation without an intermediate commit."""
    _validate_responsible(data, active_company)
    try:
        context = resolve_operational_backend("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise TaskStorageError(
            "No se pudo resolver el backend de BASE_TAREAS."
        ) from exc
    if context.backend_type == "DJANGO":
        result = _create_django_child(
            data,
            active_company=active_company,
            actor=actor,
            parent_id=parent_id,
            alias=context.django_alias,
        )
    elif context.backend_type == "MYSQL_CONFIG":
        result = _create_mysql_child(
            data,
            active_company=active_company,
            actor=actor,
            parent_id=parent_id,
            connection_config=context.mysql_connection,
            database_name=context.database_name,
        )
    else:
        raise TaskStorageError("El backend de BASE_TAREAS no es válido.")
    return result
