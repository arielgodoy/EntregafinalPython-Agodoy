from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.test import SimpleTestCase, override_settings

from tareas.models import LOGICAL_DELETION_RESULT_CODE
from tareas.services.deleted_tasks_history import (
    TASK_ITEM_LABEL,
    DeletedTaskHistoryFilters,
    DeletedTaskHistoryInvalidFilter,
    get_deleted_task_history_operation,
    list_deleted_task_history,
)


class _Cursor:
    def __init__(self, handler):
        self.handler = handler
        self.description = ()
        self.rows = ()
        self.row = None
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        self.description, self.row, self.rows = self.handler(sql, params)

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows

    def close(self):
        return None


def _description(*names):
    return tuple((name,) for name in names)


class DeletedTaskHistoryQueryTests(SimpleTestCase):
    @override_settings(SYSTEM_LOCAL_TIME_ZONE="America/Santiago")
    def test_list_filters_are_parameterized_and_pagination_is_sql_side(self):
        returned = (
            "operation_id",
            "empresa_id",
            "root_task_id",
            "root_correlativo",
            "actor_id",
            "motivo",
            "operation_status",
            "result_code",
            "audit_status",
            "audit_event_id",
            "task_id",
            "physical_task_id",
            "task_correlativo",
            "task_title",
            "task_state",
            "task_deleted",
            "task_deleted_at",
            "task_deleted_by_id",
            "task_operation_id",
            "deleted_at",
        )
        missing_task = (
            "25ffcbcf525746ea8b4b9a5e29ebe7e0",
            1,
            84,
            "B0000084",
            8,
            "Motivo de prueba",
            "COMMITTED",
            LOGICAL_DELETION_RESULT_CODE,
            "CONFIRMED",
            6,
            85,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            datetime(2026, 10, 19, 12, 0),
        )

        def respond(sql, params):
            if "COUNT(*)" in sql:
                return (), (4,), ()
            return _description(*returned), None, (missing_task,)

        cursor = _Cursor(respond)

        @contextmanager
        def opened():
            yield cursor, "mysql", lambda identifier: f"`{identifier}`"

        filters = DeletedTaskHistoryFilters(
            search="NietA",
            date_from=date(2026, 10, 19),
            date_to=date(2026, 10, 20),
            actor_id=8,
            motive="prueba",
            task_state="ACTIVA",
            audit_status="CONFIRMED",
            order_by="deleted_desc",
            page=2,
            page_size=2,
        )
        with patch(
            "tareas.services.deleted_tasks_history._history_cursor",
            side_effect=opened,
        ):
            result = list_deleted_task_history(empresa_id=1, filters=filters)

        self.assertEqual(result.total, 4)
        self.assertEqual(result.total_pages, 2)
        self.assertEqual((result.page, result.page_size), (2, 2))
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.task_id, 85)
        self.assertEqual(item.physical_status, "PHYSICALLY_ABSENT")
        self.assertIsNone(item.titulo)
        self.assertEqual(item.historical_reference, "Tarea ID 85")

        count_sql, count_params = cursor.statements[0]
        data_sql, data_params = cursor.statements[1]
        self.assertTrue(count_sql.lstrip().startswith("SELECT"))
        self.assertTrue(data_sql.lstrip().startswith("SELECT"))
        self.assertNotIn("NietA", data_sql)
        self.assertIn("LIMIT %s OFFSET %s", data_sql)
        self.assertEqual(count_params[:4], (1, "COMMITTED", LOGICAL_DELETION_RESULT_CODE, TASK_ITEM_LABEL))
        self.assertIn("%nieta%", count_params)
        self.assertIn("%prueba%", count_params)
        self.assertEqual(data_params[-2:], (2, 2))

    def test_filters_reject_unbounded_or_unknown_values(self):
        for filters in (
            DeletedTaskHistoryFilters(page=0),
            DeletedTaskHistoryFilters(page_size=101),
            DeletedTaskHistoryFilters(order_by="task_id DESC"),
            DeletedTaskHistoryFilters(audit_status="DROP TABLE"),
            DeletedTaskHistoryFilters(task_state="NOT_A_STATE"),
            DeletedTaskHistoryFilters(search="x" * 201),
            DeletedTaskHistoryFilters(date_from=date(2026, 10, 20), date_to=date(2026, 10, 19)),
        ):
            with self.subTest(filters=filters):
                with self.assertRaises(DeletedTaskHistoryInvalidFilter):
                    list_deleted_task_history(empresa_id=1, filters=filters)

    def test_list_sql_is_read_only_and_filters_on_company_and_committed_logical_result(self):
        cursor = _Cursor(
            lambda sql, params: (
                (),
                (0,),
                (),
            )
            if "COUNT(*)" in sql
            else ((), None, ()),
        )

        @contextmanager
        def opened():
            yield cursor, "mysql", lambda identifier: f"`{identifier}`"

        with patch(
            "tareas.services.deleted_tasks_history._history_cursor",
            side_effect=opened,
        ):
            list_deleted_task_history(empresa_id=4)

        self.assertTrue(cursor.statements)
        for sql, _params in cursor.statements:
            self.assertTrue(sql.lstrip().startswith("SELECT"))
            self.assertNotRegex(sql, r"\b(INSERT|UPDATE|DELETE|ALTER|CREATE|DROP)\b")
        self.assertIn("op.`empresa_id` = %s", cursor.statements[0][0])
        self.assertIn("op.`status` = %s", cursor.statements[0][0])
        self.assertIn("op.`result_code` = %s", cursor.statements[0][0])
        self.assertEqual(cursor.statements[0][1][0], 4)

    def test_inconsistent_live_row_does_not_leak_its_current_task_fields(self):
        returned = (
            "operation_id",
            "empresa_id",
            "root_task_id",
            "root_correlativo",
            "actor_id",
            "motivo",
            "operation_status",
            "result_code",
            "audit_status",
            "audit_event_id",
            "task_id",
            "physical_task_id",
            "task_correlativo",
            "task_title",
            "task_state",
            "task_deleted",
            "task_deleted_at",
            "task_deleted_by_id",
            "task_operation_id",
            "deleted_at",
        )
        inconsistent = (
            "25ffcbcf525746ea8b4b9a5e29ebe7e0",
            1,
            84,
            "B0000084",
            8,
            "Motivo de prueba",
            "COMMITTED",
            LOGICAL_DELETION_RESULT_CODE,
            "CONFIRMED",
            6,
            84,
            84,
            "B0000084",
            "No mostrar este estado actual",
            "ACTIVA",
            False,
            None,
            None,
            None,
            datetime(2026, 10, 19, 12, 0),
        )

        def respond(sql, params):
            if "COUNT(*)" in sql:
                return (), (1,), ()
            return _description(*returned), None, (inconsistent,)

        cursor = _Cursor(respond)

        @contextmanager
        def opened():
            yield cursor, "mysql", lambda identifier: f"`{identifier}`"

        with patch(
            "tareas.services.deleted_tasks_history._history_cursor",
            side_effect=opened,
        ):
            result = list_deleted_task_history(empresa_id=1)

        self.assertEqual(result.items[0].physical_status, "INCONSISTENT")
        self.assertIsNone(result.items[0].titulo)
        self.assertIsNone(result.items[0].correlativo)
        self.assertEqual(
            result.items[0].deleted_at,
            datetime(2026, 10, 19, 12, 0),
        )


class DeletedTaskHistoryOperationTests(SimpleTestCase):
    def _operation_cursor(self):
        operation_id = "25ffcbcf525746ea8b4b9a5e29ebe7e0"
        operation_columns = (
            "operation_id",
            "empresa_id",
            "root_task_id",
            "root_correlativo",
            "actor_id",
            "motivo",
            "backend_type",
            "backend_identity",
            "status",
            "result_code",
            "audit_status",
            "audit_event_id",
            "audit_error_code",
            "file_cleanup_status",
            "created_at",
            "committed_at",
            "dependency_summary",
        )
        operation = (
            operation_id,
            1,
            84,
            "B0000084",
            8,
            "Motivo de prueba",
            "MYSQL_CONFIG",
            "mysql:BASE_TAREAS",
            "COMMITTED",
            LOGICAL_DELETION_RESULT_CODE,
            "CONFIRMED",
            6,
            "",
            "NOT_REQUIRED",
            datetime(2026, 10, 19, 12, 0),
            datetime(2026, 10, 19, 12, 0),
            '{"tareas.tarea": 3}',
        )

        def respond(sql, params):
            if "FROM `tareas_eliminacion_operacion` op" in sql:
                return _description(*operation_columns), None, (operation,)
            if "FROM `tareas_eliminacion_elemento`" in sql:
                return _description("item_type", "object_id"), None, (
                    ("tareas.tarea", 84),
                    ("tareas.tarea", 85),
                    ("tareas.tarea", 86),
                )
            if "FROM `tareas_tarea` task" in sql:
                return _description("id"), None, ()
            if "FROM `tareas_eliminacion_archivo`" in sql:
                return _description("storage_key"), None, ()
            if "FROM `tareas_tarearelacion`" in sql:
                return _description("parent_id", "child_id"), None, ()
            raise AssertionError(f"Unexpected read query: {sql}")

        return _Cursor(respond)

    def test_operation_detail_preserves_type_and_missing_task_state(self):
        cursor = self._operation_cursor()

        @contextmanager
        def opened():
            yield cursor, "mysql", lambda identifier: f"`{identifier}`"

        audit_event = SimpleNamespace(
            pk=6,
            idempotency_key="25ffcbcf525746ea8b4b9a5e29ebe7e0",
            empresa_id=1,
            action="DELETE",
            object_type="Tarea",
            object_id="84",
            user_id=8,
            created_at=datetime(2026, 10, 19, 12, 0),
            message_key=None,
            meta={
                "operation_id": "25ffcbcf525746ea8b4b9a5e29ebe7e0",
                "backend_type": "MYSQL_CONFIG",
            },
        )
        with (
            patch(
                "tareas.services.deleted_tasks_history._history_cursor",
                side_effect=opened,
            ),
            patch(
                "tareas.services.deleted_tasks_history.AuditoriaService.get_event_by_idempotency_key",
                return_value=audit_event,
            ),
        ):
            operation = get_deleted_task_history_operation(
                empresa_id=1,
                operation_id=UUID(hex="25ffcbcf525746ea8b4b9a5e29ebe7e0"),
            )

        self.assertEqual(operation.audit_consistency, "CONSISTENT")
        self.assertEqual(operation.audit.event_id, 6)
        self.assertEqual(len(operation.items), 3)
        self.assertTrue(all(item.item_type == TASK_ITEM_LABEL for item in operation.items))
        self.assertTrue(all(item.task is not None for item in operation.items))
        self.assertTrue(
            all(item.physical_status == "PHYSICALLY_ABSENT" for item in operation.items)
        )
        self.assertTrue(all(item.task.titulo is None for item in operation.items))
        self.assertEqual(operation.hierarchy_status, "HISTORICAL_RELATIONS_UNAVAILABLE")
        self.assertTrue(all(sql.lstrip().startswith("SELECT") for sql, _ in cursor.statements))

    def test_unknown_manifest_type_is_not_misrepresented_as_a_task(self):
        cursor = self._operation_cursor()
        original_handler = cursor.handler

        def respond(sql, params):
            if "FROM `tareas_eliminacion_elemento`" in sql:
                return _description("item_type", "object_id"), None, (
                    ("tareas.documentotarea", 9001),
                )
            if "FROM `tareas_tarea` task" in sql or "FROM `tareas_tarearelacion`" in sql:
                return _description("id"), None, ()
            return original_handler(sql, params)

        cursor.handler = respond

        @contextmanager
        def opened():
            yield cursor, "mysql", lambda identifier: f"`{identifier}`"

        audit_event = SimpleNamespace(
            pk=6,
            idempotency_key="25ffcbcf525746ea8b4b9a5e29ebe7e0",
            empresa_id=1,
            action="DELETE",
            object_type="Tarea",
            object_id="84",
            user_id=8,
            created_at=datetime(2026, 10, 19, 12, 0),
            message_key=None,
            meta={"operation_id": "25ffcbcf525746ea8b4b9a5e29ebe7e0"},
        )
        with (
            patch(
                "tareas.services.deleted_tasks_history._history_cursor",
                side_effect=opened,
            ),
            patch(
                "tareas.services.deleted_tasks_history.AuditoriaService.get_event_by_idempotency_key",
                return_value=audit_event,
            ),
        ):
            operation = get_deleted_task_history_operation(
                empresa_id=1,
                operation_id=UUID(hex="25ffcbcf525746ea8b4b9a5e29ebe7e0"),
            )

        self.assertEqual(len(operation.items), 1)
        self.assertEqual(operation.items[0].item_type, "tareas.documentotarea")
        self.assertEqual(operation.items[0].object_id, 9001)
        self.assertIsNone(operation.items[0].task)
        self.assertEqual(operation.items[0].physical_status, "NOT_VERIFIED")
