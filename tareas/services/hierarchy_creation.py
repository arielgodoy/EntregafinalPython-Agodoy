"""Atomic creation of a task and its parent relation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

from access_control.services.permissions import get_valid_users_for_empresa
from organizacion.models import Departamento, Local
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


@dataclass(frozen=True)
class HierarchyParentOption:
    task_id: int
    correlativo: str
    titulo: str
    depth: int
    tipo_ambito: str | None
    local_id: int | None
    departamento_id: int | None


def _task_snapshot(row) -> SimpleNamespace:
    return SimpleNamespace(
        pk=int(row[0]),
        empresa_id=int(row[1]),
        correlativo=row[2],
        titulo=row[3],
        estado=row[4],
        anulada=bool(row[5]),
        eliminada=bool(row[6]),
        tipo_ambito=row[7],
        local_id=int(row[8]) if row[8] is not None else None,
        departamento_id=int(row[9]) if row[9] is not None else None,
    )


def _hierarchy_snapshot(task_rows, relation_rows, *, empresa_id: int):
    tasks = {
        task.pk: task
        for task in (_task_snapshot(row) for row in task_rows)
    }
    parent_by_child = {}
    for parent_id, child_id, parent_company_id, child_company_id in relation_rows:
        parent_id = int(parent_id)
        child_id = int(child_id)
        if (
            int(parent_company_id) != empresa_id
            or int(child_company_id) != empresa_id
        ):
            raise ValidationError(
                "La jerarquía contiene una relación entre empresas."
            )
        if child_id in parent_by_child:
            raise ValidationError(
                "La jerarquía contiene más de un padre para una tarea."
            )
        parent = tasks.get(parent_id)
        if parent is None:
            raise ValidationError(
                "La jerarquía contiene una tarea padre inexistente."
            )
        parent_by_child[child_id] = parent
    return tasks, parent_by_child


def _task_dimensions_are_consistent(task) -> bool:
    if task.tipo_ambito == Tarea.Ambito.LOCAL:
        return task.local_id is not None and task.departamento_id is None
    if task.tipo_ambito == Tarea.Ambito.DEPARTAMENTO:
        return task.local_id is None and task.departamento_id is not None
    return (
        task.tipo_ambito is None
        and task.local_id is None
        and task.departamento_id is None
    )


def _eligible_parent_options(tasks, parent_by_child, *, empresa_id: int):
    candidates = []
    local_ids = set()
    departamento_ids = set()
    for task in tasks.values():
        if (
            task.empresa_id != empresa_id
            or task.eliminada
            or task.anulada
            or task.estado != Tarea.Estado.ACTIVA
            or not _task_dimensions_are_consistent(task)
        ):
            continue

        depth = 0
        current = task
        seen = set()
        eligible = True
        while current.pk in parent_by_child:
            if current.pk in seen:
                eligible = False
                break
            seen.add(current.pk)
            parent = parent_by_child[current.pk]
            if (
                parent.empresa_id != empresa_id
                or parent.eliminada
                or parent.anulada
            ):
                eligible = False
                break
            depth += 1
            if depth > 2:
                eligible = False
                break
            current = parent
        if not eligible or depth >= 2:
            continue
        if task.local_id is not None:
            local_ids.add(task.local_id)
        if task.departamento_id is not None:
            departamento_ids.add(task.departamento_id)
        candidates.append((task, depth))

    valid_local_ids = (
        set(
            Local.objects.using("default")
            .filter(empresa_id=empresa_id, pk__in=local_ids)
            .values_list("pk", flat=True)
        )
        if local_ids
        else set()
    )
    valid_departamento_ids = (
        set(
            Departamento.objects.using("default")
            .filter(empresa_id=empresa_id, pk__in=departamento_ids)
            .values_list("pk", flat=True)
        )
        if departamento_ids
        else set()
    )

    options = []
    for task, depth in candidates:
        if (
            task.local_id is not None
            and task.local_id not in valid_local_ids
        ) or (
            task.departamento_id is not None
            and task.departamento_id not in valid_departamento_ids
        ):
            continue
        options.append(
            HierarchyParentOption(
                task_id=task.pk,
                correlativo=task.correlativo,
                titulo=task.titulo,
                depth=depth,
                tipo_ambito=task.tipo_ambito,
                local_id=task.local_id,
                departamento_id=task.departamento_id,
            )
        )
    return tuple(sorted(options, key=lambda item: (item.correlativo, item.task_id)))


def list_eligible_hierarchy_parents(
    *,
    empresa_id: int,
) -> tuple[HierarchyParentOption, ...]:
    try:
        context = resolve_operational_backend("BASE_TAREAS")
        if context.backend_type == "DJANGO":
            task_rows = tuple(
                Tarea.all_objects.using(context.django_alias)
                .filter(empresa_id=empresa_id)
                .order_by("pk")
                .values_list(
                    "pk",
                    "empresa_id",
                    "correlativo",
                    "titulo",
                    "estado",
                    "anulada",
                    "eliminada",
                    "tipo_ambito",
                    "local_id",
                    "departamento_id",
                )
            )
            relation_rows = tuple(
                TareaRelacion.objects.using(context.django_alias)
                .filter(
                    Q(padre__empresa_id=empresa_id)
                    | Q(hija__empresa_id=empresa_id)
                )
                .order_by("padre_id", "hija_id")
                .values_list(
                    "padre_id",
                    "hija_id",
                    "padre__empresa_id",
                    "hija__empresa_id",
                )
            )
        elif context.backend_type == "MYSQL_CONFIG":
            with open_mysql_connection(
                context.mysql_connection,
                database_name=context.database_name,
            ) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        "SELECT id,empresa_id,correlativo,titulo,estado,anulada,"
                        "eliminada,tipo_ambito,local_id,departamento_id "
                        "FROM tareas_tarea WHERE empresa_id=%s ORDER BY id",
                        (empresa_id,),
                    )
                    task_rows = tuple(cursor.fetchall())
                    cursor.execute(
                        "SELECT relation.padre_id,relation.hija_id,"
                        "parent.empresa_id,child.empresa_id "
                        "FROM tareas_tarearelacion relation "
                        "JOIN tareas_tarea parent ON parent.id=relation.padre_id "
                        "JOIN tareas_tarea child ON child.id=relation.hija_id "
                        "WHERE parent.empresa_id=%s OR child.empresa_id=%s "
                        "ORDER BY relation.padre_id,relation.hija_id",
                        (empresa_id, empresa_id),
                    )
                    relation_rows = tuple(cursor.fetchall())
                finally:
                    cursor.close()
        else:
            raise TaskStorageError("El backend de BASE_TAREAS no es válido.")
    except (TareaConnectionError, DatabaseError, TaskStorageError) as exc:
        raise TaskStorageError(
            "No se pudieron consultar las tareas madre elegibles."
        ) from exc
    except Exception as exc:
        raise TaskStorageError(
            "No se pudieron consultar las tareas madre elegibles."
        ) from exc

    try:
        tasks, parent_by_child = _hierarchy_snapshot(
            task_rows,
            relation_rows,
            empresa_id=empresa_id,
        )
        return _eligible_parent_options(
            tasks,
            parent_by_child,
            empresa_id=empresa_id,
        )
    except ValidationError:
        raise
    except DatabaseError as exc:
        raise TaskStorageError(
            "No se pudieron consultar las dimensiones de las tareas madre."
        ) from exc


def _validate_responsible(data: CreateTaskDraftInput, active_company) -> None:
    if data.responsable_id is not None and not get_valid_users_for_empresa(
        active_company,
        active_only=True,
    ).filter(pk=data.responsable_id).exists():
        raise ValidationError(
            "El responsable debe estar activo y pertenecer a la Empresa activa."
        )


def _validate_child_input(data: CreateTaskDraftInput) -> None:
    if not isinstance(data.titulo, str) or not data.titulo.strip():
        raise ValidationError("El título de la tarea es obligatorio.")
    if not isinstance(data.fecha_tope, date):
        raise ValidationError("La fecha tope es obligatoria.")


def _validate_parent(parent, *, company_id: int) -> None:
    if parent is None or parent.empresa_id != company_id:
        raise ValidationError(
            "El padre debe existir en la empresa activa."
        )
    if (
        parent.estado != Tarea.Estado.ACTIVA
        or parent.anulada
        or getattr(parent, "eliminada", False)
    ):
        raise ValidationError(
            "Solo una tarea ACTIVA y no anulada puede recibir hijas."
        )


def _validate_parent_ancestors(parent, parent_by_child) -> None:
    current = parent_by_child.get(parent.pk)
    seen = {parent.pk}
    while current is not None:
        if current.pk in seen:
            raise ValidationError("La jerarquía contiene un ciclo.")
        seen.add(current.pk)
        if current.anulada or current.eliminada:
            raise ValidationError(
                "Una tarea anulada o eliminada efectivamente no puede recibir hijas."
            )
        current = parent_by_child.get(current.pk)


def _resolve_child_dimensions(
    parent,
    *,
    empresa_id: int,
    departamento_id: int | None,
) -> tuple[str | None, int | None, int | None]:
    if parent.tipo_ambito == Tarea.Ambito.LOCAL:
        if parent.local_id is None or parent.departamento_id is not None:
            raise ValidationError(
                "Las dimensiones de la tarea madre son inconsistentes."
            )
        if departamento_id is not None:
            raise ValidationError(
                "Una tarea de ámbito LOCAL conserva el Local de su madre."
            )
        if not Local.objects.using("default").filter(
            pk=parent.local_id,
            empresa_id=empresa_id,
        ).exists():
            raise ValidationError(
                "El Local de la tarea madre no pertenece a la empresa."
            )
        return Tarea.Ambito.LOCAL, parent.local_id, None

    if parent.tipo_ambito == Tarea.Ambito.DEPARTAMENTO:
        if parent.departamento_id is None or parent.local_id is not None:
            raise ValidationError(
                "Las dimensiones de la tarea madre son inconsistentes."
            )
        if departamento_id is not None and (
            type(departamento_id) is not int or departamento_id < 1
        ):
            raise ValidationError(
                "El Departamento de la tarea hija no es válido."
            )
        child_department_id = (
            departamento_id
            if departamento_id is not None
            else parent.departamento_id
        )
        if (
            not Departamento.objects.using("default").filter(
                pk=parent.departamento_id,
                empresa_id=empresa_id,
            ).exists()
            or not Departamento.objects.using("default").filter(
                pk=child_department_id,
                empresa_id=empresa_id,
            ).exists()
        ):
            raise ValidationError(
                "El Departamento debe pertenecer a la empresa activa."
            )
        return Tarea.Ambito.DEPARTAMENTO, None, child_department_id

    if (
        parent.tipo_ambito is None
        and parent.local_id is None
        and parent.departamento_id is None
        and departamento_id is None
    ):
        return None, None, None
    raise ValidationError("Las dimensiones de la tarea madre son inconsistentes.")


def _create_django_child(
    data: CreateTaskDraftInput,
    *,
    active_company,
    actor,
    parent_id: int,
    departamento_id: int | None,
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
                    Q(padre__empresa_id=company_id)
                    | Q(hija__empresa_id=company_id)
                )
                .order_by("padre_id", "hija_id")
            )
            for relation in relations:
                if (
                    relation.padre.empresa_id != company_id
                    or relation.hija.empresa_id != company_id
                ):
                    raise ValidationError(
                        "La jerarquía contiene una relación entre empresas."
                    )
                if relation.hija_id in parent_by_child:
                    raise ValidationError(
                        "La jerarquía contiene más de un padre para una tarea."
                    )
                parent_by_child[relation.hija_id] = relation.padre
            _validate_parent_ancestors(parent, parent_by_child)
            tipo_ambito, local_id, child_department_id = _resolve_child_dimensions(
                parent,
                empresa_id=company_id,
                departamento_id=departamento_id,
            )
            task = Tarea(
                titulo=data.titulo,
                descripcion=data.descripcion,
                prioridad=data.prioridad,
                responsable_id=data.responsable_id,
                fecha_tope=data.fecha_tope,
                empresa_id=company_id,
                creada_por_id=actor.pk,
                tipo_ambito=tipo_ambito,
                local_id=local_id,
                departamento_id=child_department_id,
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
    departamento_id: int | None,
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
                            "SELECT id, empresa_id, estado, anulada, eliminada, "
                            "tipo_ambito, local_id, departamento_id "
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
                                eliminada=bool(row[4]),
                                tipo_ambito=row[5],
                                local_id=int(row[6]) if row[6] is not None else None,
                                departamento_id=(
                                    int(row[7]) if row[7] is not None else None
                                ),
                            )
                            if row is not None
                            else None
                        )
                        _validate_parent(parent, company_id=company_id)
                        cursor.execute(
                            "SELECT relation.padre_id, relation.hija_id, "
                            "parent.empresa_id, child.empresa_id, parent.estado, "
                            "parent.anulada, parent.eliminada, parent.tipo_ambito, "
                            "parent.local_id, parent.departamento_id "
                            "FROM tareas_tarearelacion relation "
                            "JOIN tareas_tarea parent ON parent.id=relation.padre_id "
                            "JOIN tareas_tarea child ON child.id=relation.hija_id "
                            "WHERE parent.empresa_id=%s OR child.empresa_id=%s "
                            "ORDER BY relation.padre_id, relation.hija_id FOR UPDATE",
                            (company_id, company_id),
                        )
                        parent_by_child = {}
                        for row in cursor.fetchall():
                            (
                                parent_id_row,
                                child_id,
                                parent_company_id,
                                child_company_id,
                                parent_state,
                                parent_annulled,
                                parent_deleted,
                                parent_scope,
                                parent_local_id,
                                parent_department_id,
                            ) = row
                            if (
                                int(parent_company_id) != company_id
                                or int(child_company_id) != company_id
                            ):
                                raise ValidationError(
                                    "La jerarquía contiene una relación entre empresas."
                                )
                            if int(child_id) in parent_by_child:
                                raise ValidationError(
                                    "La jerarquía contiene más de un padre para una tarea."
                                )
                            parent_by_child[int(child_id)] = SimpleNamespace(
                                pk=int(parent_id_row),
                                empresa_id=int(parent_company_id),
                                estado=parent_state,
                                anulada=bool(parent_annulled),
                                eliminada=bool(parent_deleted),
                                tipo_ambito=parent_scope,
                                local_id=(
                                    int(parent_local_id)
                                    if parent_local_id is not None
                                    else None
                                ),
                                departamento_id=(
                                    int(parent_department_id)
                                    if parent_department_id is not None
                                    else None
                                ),
                            )
                        _validate_parent_ancestors(parent, parent_by_child)
                        tipo_ambito, local_id, child_department_id = (
                            _resolve_child_dimensions(
                                parent,
                                empresa_id=company_id,
                                departamento_id=departamento_id,
                            )
                        )
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
                                tipo_ambito, local_id, child_department_id, actor.pk,
                                created_at, None, None,
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
    departamento_id: int | None = None,
) -> AtomicChildTaskResult:
    """Create a draft and its parent relation without an intermediate commit."""
    _validate_child_input(data)
    _validate_responsible(data, active_company)
    try:
        context = resolve_operational_backend("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise TaskStorageError(
            "No se pudo resolver el backend de BASE_TAREAS."
        ) from exc
    if context.backend_type == "DJANGO":
        try:
            result = _create_django_child(
                data,
                active_company=active_company,
                actor=actor,
                parent_id=parent_id,
                departamento_id=departamento_id,
                alias=context.django_alias,
            )
        except (ValidationError, TaskStorageError):
            raise
        except (DatabaseError, TaskMutationLockError, TaskMutationScopeError) as exc:
            raise TaskStorageError(
                "No se pudo crear y vincular la tarea hija."
            ) from exc
    elif context.backend_type == "MYSQL_CONFIG":
        result = _create_mysql_child(
            data,
            active_company=active_company,
            actor=actor,
            parent_id=parent_id,
            departamento_id=departamento_id,
            connection_config=context.mysql_connection,
            database_name=context.database_name,
        )
    else:
        raise TaskStorageError("El backend de BASE_TAREAS no es válido.")
    return result
