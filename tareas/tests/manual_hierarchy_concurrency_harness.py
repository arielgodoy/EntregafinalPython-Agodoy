"""Manual, explicitly authorized BASE_TAREAS hierarchy concurrency harness.

This module is intentionally not a Django TestCase and is never discovered by
the automatic test runner. It is an exceptional procedure for synthetic data.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AppDocs.settings")

import django
from django.utils import timezone

django.setup()

from settings.services.mysql_connections import open_mysql_connection

from django.contrib.auth.models import User
from tareas.models import Empresa
from tareas.services.assignment_storage import resolve_assignment_storage
from tareas.services.hierarchy_creation import create_child_task_atomic
from tareas.services.connection_roles import (
    get_tarea_connection,
    resolve_operational_backend,
)
from tareas.services.hierarchy_lifecycle_storage import (
    resolve_hierarchy_lifecycle_storage,
)
from tareas.services.task_mutation_locks import (
    bounded_mysql_lock_wait,
    lock_mysql_task_rows,
    mysql_mutation_transaction,
)
from tareas.services.task_storage import CreateTaskDraftInput


AUTHORIZATION = "I_ACKNOWLEDGE_BASE_TAREAS_TEST_DATA"
COMPANY_ID = 1
COMPANY_CODE = "00"
DATABASE_NAME = "tareas"
SYNTHETIC_PREFIX = "F2F2-HIERARCHY-"


class HarnessConfigurationError(RuntimeError):
    """The manual procedure is not explicitly authorized or safely targeted."""


class HarnessCleanupError(RuntimeError):
    """Synthetic data cannot be cleaned with a complete, verified scope."""


@dataclass
class HarnessState:
    task_ids: list[int] = field(default_factory=list)
    relation_ids: list[int] = field(default_factory=list)
    document_ids: list[int] = field(default_factory=list)
    participant_ids: list[int] = field(default_factory=list)
    assignment_task_ids: list[int] = field(default_factory=list)
    initial_correlativo: int | None = None
    results: dict[str, Any] = field(default_factory=dict)


def _require_authorized_target(context) -> None:
    if os.environ.get("TAREAS_MANUAL_BASE_TAREAS_AUTH") != AUTHORIZATION:
        raise HarnessConfigurationError(
            "Falta autorización explícita para pruebas manuales sobre BASE_TAREAS."
        )
    if os.environ.get("TAREAS_MANUAL_BASE_TAREAS_COMPANY") != COMPANY_CODE:
        raise HarnessConfigurationError(
            "La empresa manual debe ser explícitamente la Empresa 00."
        )
    if context.backend_type != "MYSQL_CONFIG":
        raise HarnessConfigurationError("BASE_TAREAS no utiliza MYSQL_CONFIG.")
    if context.database_name != DATABASE_NAME:
        raise HarnessConfigurationError(
            "El arnés solo acepta la base física tareas."
        )


def _marks(values: tuple[int, ...]) -> str:
    return ", ".join(["%s"] * len(values))


def _existing_actor(connection) -> tuple[int, int]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT creada_por_id, responsable_id "
            "FROM tareas_tarea WHERE empresa_id = %s ORDER BY id LIMIT 1",
            (COMPANY_ID,),
        )
        row = cursor.fetchone()
    finally:
        cursor.close()
    if row is None:
        raise HarnessConfigurationError(
            "No existe una tarea base para obtener un actor válido."
        )
    actor_id = row[0] or row[1]
    if not actor_id:
        raise HarnessConfigurationError("La tarea base no tiene actor válido.")
    return int(actor_id), int(row[1] or actor_id)


def _create_task(storage, actor_id: int, responsible_id: int, label: str) -> int:
    created = storage.create(
        empresa_id=COMPANY_ID,
        creador_id=actor_id,
        assignments=[
            {
                "titulo": f"{SYNTHETIC_PREFIX}{label}",
                "descripcion": "Synthetic manual concurrency test",
                "prioridad": "MEDIA",
                "responsable_id": responsible_id,
                "fecha_comun": timezone.now(),
                "motivo": "Fase 2F.2",
            }
        ],
    )
    return int(created[0].id)


def _lock_tree_and_inventory(connection, task_ids: tuple[int, ...]) -> dict[str, Any]:
    locked_ids = lock_mysql_task_rows(connection, COMPANY_ID, task_ids)
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT padre_id, hija_id FROM tareas_tarearelacion "
            "WHERE padre_id IN (%s) OR hija_id IN (%s) "
            "ORDER BY padre_id, hija_id FOR UPDATE"
            % (_marks(task_ids), _marks(task_ids)),
            task_ids + task_ids,
        )
        relations = tuple(cursor.fetchall())
    finally:
        cursor.close()
    return {
        "locked_task_ids": list(locked_ids),
        "inventory_task_ids": list(task_ids),
        "inventory_relations": [list(row) for row in relations],
    }


def _run_main_race(
    context,
    state: HarnessState,
    actor_id: int,
    responsible_id: int,
    active_company,
    actor,
    parent_id: int,
    child_id: int,
    grandchild_id: int,
) -> None:
    ready = threading.Event()
    release = threading.Event()
    holder_result: dict[str, Any] = {}
    writer_result: dict[str, Any] = {}

    def holder() -> None:
        try:
            with open_mysql_connection(
                context.mysql_connection,
                database_name=context.database_name,
            ) as connection:
                with bounded_mysql_lock_wait(connection):
                    with mysql_mutation_transaction(connection):
                        holder_result["inventory"] = _lock_tree_and_inventory(
                            connection,
                            (parent_id, child_id, grandchild_id),
                        )
                        ready.set()
                        release.wait(15)
            holder_result["status"] = "released"
        except Exception as exc:
            holder_result["status"] = "error"
            holder_result["error_type"] = type(exc).__name__
            holder_result["error"] = str(exc)
            ready.set()

    def writer() -> None:
        try:
            started = time.monotonic()
            result = create_child_task_atomic(
                CreateTaskDraftInput(
                    titulo=f"{SYNTHETIC_PREFIX}CONCURRENT-CHILD",
                    descripcion="Synthetic concurrent child",
                    prioridad="MEDIA",
                    responsable_id=responsible_id,
                    fecha_tope=timezone.localdate(),
                ),
                active_company=active_company,
                actor=actor,
                parent_id=parent_id,
            )
            new_task_id = int(result.task.id)
            state.task_ids.append(new_task_id)
            writer_result["task_id"] = new_task_id
            writer_result["operation_elapsed_seconds"] = round(
                time.monotonic() - started, 3
            )
            state.relation_ids.append(int(result.relation_id))
            writer_result["relation_id"] = int(result.relation_id)
            writer_result["status"] = "linked"
        except Exception as exc:
            writer_result["status"] = "error"
            writer_result["error_type"] = type(exc).__name__
            writer_result["error"] = str(exc)
            cause = exc.__cause__
            if cause is not None:
                writer_result["cause_type"] = type(cause).__name__
                writer_result["cause"] = str(cause)

    holder_thread = threading.Thread(target=holder, name="f2f2-tree-holder")
    holder_thread.start()
    if not ready.wait(5):
        raise RuntimeError("La transacción A no confirmó sus locks.")

    writer_thread = threading.Thread(target=writer, name="f2f2-child-writer")
    writer_thread.start()
    time.sleep(1)
    writer_result["blocked_before_release"] = writer_thread.is_alive()

    release.set()
    writer_thread.join(20)
    holder_thread.join(20)
    if writer_thread.is_alive() or holder_thread.is_alive():
        raise RuntimeError("El escenario A/B no terminó dentro del límite.")

    state.results["main_race"] = {
        "transaction_a": holder_result,
        "transaction_b": writer_result,
        "blocked_before_release": writer_result.get("blocked_before_release"),
        "atomic_public_child_link": writer_result.get("status") == "linked",
        "reason": (
            "La operación atómica creó y vinculó la hija en una sola transacción."
            if writer_result.get("status") == "linked"
            else "La operación atómica no pudo completar la creación y vinculación."
        ),
    }


def _verify_fk_scope(connection, task_ids: tuple[int, ...]) -> list[tuple[str, str, int]]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT table_name, column_name "
            "FROM information_schema.key_column_usage "
            "WHERE referenced_table_schema = DATABASE() "
            "AND referenced_table_name = 'tareas_tarea' "
            "AND referenced_column_name = 'id' "
            "ORDER BY table_name, column_name"
        )
        references = cursor.fetchall()
        findings = []
        for table, column in references:
            marks = _marks(task_ids)
            cursor.execute(
                f"SELECT COUNT(*) FROM `{table}` WHERE `{column}` IN ({marks})",
                task_ids,
            )
            count = int(cursor.fetchone()[0])
            if count:
                findings.append((str(table), str(column), count))
        return findings
    finally:
        cursor.close()


def _cleanup(connection, state: HarnessState) -> None:
    task_ids = tuple(sorted(set(state.task_ids)))
    if not task_ids:
        return
    cursor = connection.cursor()
    try:
        if state.initial_correlativo is None:
            raise HarnessCleanupError("Falta el correlativo inicial del inventario.")
        cursor.execute(
            "SELECT siguiente_numero FROM tareas_correlativoempresa "
            "WHERE empresa_id = %s FOR UPDATE",
            (COMPANY_ID,),
        )
        current_correlativo = cursor.fetchone()
        expected_correlativo = state.initial_correlativo + len(task_ids)
        if (
            current_correlativo is None
            or int(current_correlativo[0]) != expected_correlativo
        ):
            raise HarnessCleanupError(
                "El correlativo cambió fuera del alcance sintético; "
                f"esperado={expected_correlativo}, actual="
                f"{current_correlativo[0] if current_correlativo else None}, "
                f"tareas={task_ids!r}."
            )
        findings = _verify_fk_scope(connection, task_ids)
        allowed = {
            ("tareas_documentotarea", "tarea_id"),
            ("tareas_tarealectura", "tarea_id"),
            ("tareas_tareaparticipante", "tarea_id"),
            ("tareas_tareareasignacion", "tarea_id"),
            ("tareas_tarearelacion", "padre_id"),
            ("tareas_tarearelacion", "hija_id"),
        }
        unknown = [item for item in findings if item[:2] not in allowed]
        if unknown:
            raise HarnessCleanupError(
                f"Dependencias no incluidas en la limpieza: {unknown!r}"
            )

        cursor.execute(
            "SELECT id FROM tareas_documentotarea "
            f"WHERE tarea_id IN ({_marks(task_ids)})",
            task_ids,
        )
        document_ids = tuple(int(row[0]) for row in cursor.fetchall())
        if document_ids:
            cursor.execute(
                "DELETE FROM tareas_documentohistorial "
                f"WHERE documento_id IN ({_marks(document_ids)})",
                document_ids,
            )
            cursor.execute(
                "DELETE FROM tareas_documentotarea "
                f"WHERE id IN ({_marks(document_ids)})",
                document_ids,
            )
        cursor.execute(
            "DELETE FROM tareas_tarealectura "
            f"WHERE tarea_id IN ({_marks(task_ids)})",
            task_ids,
        )
        cursor.execute(
            "DELETE FROM tareas_tareaparticipante "
            f"WHERE tarea_id IN ({_marks(task_ids)})",
            task_ids,
        )
        cursor.execute(
            "DELETE FROM tareas_tarearelacion "
            f"WHERE padre_id IN ({_marks(task_ids)}) "
            f"OR hija_id IN ({_marks(task_ids)})",
            task_ids + task_ids,
        )
        cursor.execute(
            "DELETE FROM tareas_tareareasignacion "
            f"WHERE tarea_id IN ({_marks(task_ids)})",
            task_ids,
        )
        cursor.execute(
            "DELETE FROM tareas_tarea "
            f"WHERE id IN ({_marks(task_ids)})",
            task_ids,
        )
        cursor.execute(
            "UPDATE tareas_correlativoempresa SET siguiente_numero = %s "
            "WHERE empresa_id = %s",
            (state.initial_correlativo, COMPANY_ID),
        )
    finally:
        cursor.close()


def run_harness() -> dict[str, Any]:
    context = resolve_operational_backend("BASE_TAREAS")
    role = get_tarea_connection("BASE_TAREAS")
    _require_authorized_target(context)
    if role.get("empresa_codigo") != COMPANY_CODE:
        raise HarnessConfigurationError(
            "BASE_TAREAS no resuelve a la Empresa 00."
        )
    state = HarnessState()
    assignment_storage = resolve_assignment_storage()

    try:
        with open_mysql_connection(
            context.mysql_connection,
            database_name=context.database_name,
        ) as connection:
            actor_id, responsible_id = _existing_actor(connection)
            active_company = Empresa.objects.get(pk=COMPANY_ID)
            actor = User.objects.get(pk=actor_id)
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT siguiente_numero FROM tareas_correlativoempresa "
                    "WHERE empresa_id = %s",
                    (COMPANY_ID,),
                )
                row = cursor.fetchone()
            finally:
                cursor.close()
            if row is None:
                raise HarnessConfigurationError(
                    "No existe el correlativo de Empresa 00."
                )
            state.initial_correlativo = int(row[0])
            parent_id = _create_task(
                assignment_storage, actor_id, responsible_id, "PARENT"
            )
            child_id = _create_task(
                assignment_storage, actor_id, responsible_id, "CHILD"
            )
            grandchild_id = _create_task(
                assignment_storage, actor_id, responsible_id, "GRANDCHILD"
            )
            state.task_ids.extend((parent_id, child_id, grandchild_id))
            hierarchy_storage = resolve_hierarchy_lifecycle_storage()
            parent_relation = hierarchy_storage.create_relation(
                parent_id, child_id, company_id=COMPANY_ID
            )
            child_relation = hierarchy_storage.create_relation(
                child_id, grandchild_id, company_id=COMPANY_ID
            )
            state.relation_ids.extend(
                (int(parent_relation.id), int(child_relation.id))
            )
            _run_main_race(
                context,
                state,
                actor_id,
                responsible_id,
                active_company,
                actor,
                parent_id,
                child_id,
                grandchild_id,
            )
    finally:
        if state.task_ids:
            with open_mysql_connection(
                context.mysql_connection,
                database_name=context.database_name,
            ) as connection:
                connection.set_autocommit(False)
                try:
                    _cleanup(connection, state)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.set_autocommit(True)

    state.results["cleanup"] = {
        "task_ids": state.task_ids,
        "relation_ids": state.relation_ids,
        "status": "completed",
    }
    return {
        "authorization": "explicit",
        "database": DATABASE_NAME,
        "company": COMPANY_CODE,
        "results": state.results,
    }


def main() -> None:
    print(json.dumps(run_harness(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AppDocs.settings")
    import django

    django.setup()
    main()
