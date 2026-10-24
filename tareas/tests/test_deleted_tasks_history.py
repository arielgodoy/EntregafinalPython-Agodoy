from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.test import SimpleTestCase, override_settings

from tareas.models import (
    LOGICAL_DELETION_RESULT_CODE,
    LOGICAL_RESTORATION_RESULT_CODE,
)
from tareas.services.deleted_tasks_history import (
    TASK_ITEM_LABEL,
    DeletedTaskHistoryFilters,
    DeletedTaskHistoryInvalidFilter,
    _history_item,
    _project_deletion_status,
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
            "source_created_at",
            "source_committed_at",
            "backend_type",
            "backend_identity",
            "backend_config_version",
            "restoration_operation_id",
            "restoration_source_operation_id",
            "restoration_empresa_id",
            "restoration_root_task_id",
            "restoration_actor_id",
            "restoration_motivo",
            "restoration_status",
            "restoration_result_code",
            "restoration_audit_status",
            "restoration_audit_event_id",
            "restoration_audit_error_code",
            "restoration_file_cleanup_status",
            "restoration_created_at",
            "restoration_committed_at",
            "restoration_backend_type",
            "restoration_backend_identity",
            "restoration_backend_config_version",
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
        source_operation_id = "25ffcbcf525746ea8b4b9a5e29ebe7e0"
        missing_task = {
            "operation_id": source_operation_id,
            "empresa_id": 1,
            "root_task_id": 84,
            "root_correlativo": "B0000084",
            "actor_id": 8,
            "motivo": "Motivo de prueba",
            "operation_status": "COMMITTED",
            "result_code": LOGICAL_DELETION_RESULT_CODE,
            "audit_status": "CONFIRMED",
            "audit_event_id": 6,
            "source_created_at": datetime(2026, 10, 19, 11, 0),
            "source_committed_at": datetime(2026, 10, 19, 11, 30),
            "backend_type": "MYSQL_CONFIG",
            "backend_identity": "mysql:BASE_TAREAS",
            "backend_config_version": "",
            "restoration_operation_id": None,
            "restoration_source_operation_id": None,
            "restoration_empresa_id": None,
            "restoration_root_task_id": None,
            "restoration_actor_id": None,
            "restoration_motivo": None,
            "restoration_status": None,
            "restoration_result_code": None,
            "restoration_audit_status": None,
            "restoration_audit_event_id": None,
            "restoration_audit_error_code": None,
            "restoration_file_cleanup_status": None,
            "restoration_created_at": None,
            "restoration_committed_at": None,
            "restoration_backend_type": None,
            "restoration_backend_identity": None,
            "restoration_backend_config_version": None,
            "task_id": 85,
            "physical_task_id": None,
            "task_correlativo": None,
            "task_title": None,
            "task_state": None,
            "task_deleted": None,
            "task_deleted_at": None,
            "task_deleted_by_id": None,
            "task_operation_id": None,
            "deleted_at": datetime(2026, 10, 19, 12, 0),
        }

        def respond(sql, params):
            if "COUNT(*)" in sql:
                return (), (4,), ()
            if "AS item_type" in sql and "tareas_eliminacion_elemento" in sql:
                return (
                    _description("operation_id", "item_type", "object_id"),
                    None,
                    ((source_operation_id, TASK_ITEM_LABEL, 85),),
                )
            if "source_item" in sql:
                return (
                    _description(
                        "source_operation_id",
                        "manifest_task_id",
                        "physical_task_id",
                        "empresa_id",
                        "eliminada",
                        "eliminada_en",
                        "eliminada_por",
                        "eliminacion_operacion_id",
                    ),
                    None,
                    ((source_operation_id, 85, None, None, None, None, None, None),),
                )
            return _description(*returned), None, (
                tuple(missing_task[name] for name in returned),
            )

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
        self.assertEqual(item.deletion_status, "INCONSISTENT")
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
            "source_created_at",
            "source_committed_at",
            "backend_type",
            "backend_identity",
            "backend_config_version",
            "restoration_operation_id",
            "restoration_source_operation_id",
            "restoration_empresa_id",
            "restoration_root_task_id",
            "restoration_actor_id",
            "restoration_motivo",
            "restoration_status",
            "restoration_result_code",
            "restoration_audit_status",
            "restoration_audit_event_id",
            "restoration_audit_error_code",
            "restoration_file_cleanup_status",
            "restoration_created_at",
            "restoration_committed_at",
            "restoration_backend_type",
            "restoration_backend_identity",
            "restoration_backend_config_version",
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
            datetime(2026, 10, 19, 11, 0),
            datetime(2026, 10, 19, 11, 30),
            "MYSQL_CONFIG",
            "mysql:BASE_TAREAS",
            "base-config",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
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
            source_operation_id = inconsistent[0]
            if "AS item_type" in sql and "tareas_eliminacion_elemento" in sql:
                return (
                    _description("operation_id", "item_type", "object_id"),
                    None,
                    ((source_operation_id, TASK_ITEM_LABEL, 84),),
                )
            if "source_item" in sql:
                return (
                    _description(
                        "source_operation_id",
                        "manifest_task_id",
                        "physical_task_id",
                        "empresa_id",
                        "eliminada",
                        "eliminada_en",
                        "eliminada_por",
                        "eliminacion_operacion_id",
                    ),
                    None,
                    ((
                        source_operation_id,
                        84,
                        84,
                        1,
                        False,
                        None,
                        None,
                        None,
                    ),),
                )
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
        self.assertEqual(result.items[0].deletion_status, "INCONSISTENT")


class DeletedTaskRestorationProjectionTests(SimpleTestCase):
    operation_id = UUID("25ffcbcf-5257-46ea-8b4b-9a5e29ebe7e0")
    restoration_id = UUID("76a4cf0a-b972-4b25-9e61-11db893dc35f")

    def setUp(self):
        self.source = {
            "operation_id": self.operation_id.hex,
            "empresa_id": 1,
            "root_task_id": 84,
            "actor_id": 8,
            "created_at": datetime(2026, 10, 19, 11, 0),
            "committed_at": datetime(2026, 10, 19, 11, 30),
            "backend_type": "MYSQL_CONFIG",
            "backend_identity": "mysql:BASE_TAREAS",
            "backend_config_version": "base-config",
        }
        self.manifest = ({"item_type": TASK_ITEM_LABEL, "object_id": 84},)
        self.deleted_tasks = {
            84: {
                "empresa_id": 1,
                "eliminada": True,
                "eliminada_en": datetime(2026, 10, 19, 12, 0),
                "eliminada_por": 8,
                "eliminacion_operacion_id": self.operation_id.hex,
            }
        }
        self.restored_tasks = {
            84: {
                "empresa_id": 1,
                "eliminada": False,
                "eliminada_en": None,
                "eliminada_por": None,
                "eliminacion_operacion_id": None,
            }
        }
        self.restoration = {
            "operation_id": self.restoration_id.hex,
            "reverses_operation_id": self.operation_id.hex,
            "empresa_id": 1,
            "root_task_id": 84,
            "actor_id": 9,
            "motivo": "Restauración autorizada",
            "backend_type": "MYSQL_CONFIG",
            "backend_identity": "mysql:BASE_TAREAS",
            "backend_config_version": "base-config",
            "status": "COMMITTED",
            "result_code": LOGICAL_RESTORATION_RESULT_CODE,
            "audit_status": "PENDING",
            "audit_event_id": None,
            "audit_error_code": "AUDIT_DELIVERY_FAILED",
            "file_cleanup_status": "NOT_REQUIRED",
            "created_at": datetime(2026, 10, 20, 9, 0),
            "committed_at": datetime(2026, 10, 20, 9, 1),
        }

    def _project(
        self,
        *,
        restoration=None,
        tasks=None,
        restore_manifest=(),
        current_operations=None,
    ):
        return _project_deletion_status(
            source=self.source,
            source_manifest=self.manifest,
            task_rows=tasks if tasks is not None else self.deleted_tasks,
            restoration_row=restoration,
            restoration_manifest=restore_manifest,
            current_operations=current_operations,
        )

    def test_original_deletion_remains_current_when_no_restoration_exists(self):
        status, restoration = self._project()

        self.assertEqual(status, "CURRENTLY_DELETED")
        self.assertIsNone(restoration)

    def test_committed_linked_restoration_is_restored_even_when_audit_is_pending(self):
        status, restoration = self._project(
            restoration=self.restoration,
            tasks=self.restored_tasks,
            restore_manifest=self.manifest,
        )

        self.assertEqual(status, "RESTORED")
        self.assertEqual(restoration.operation_id, self.restoration_id)
        self.assertEqual(restoration.actor_id, 9)
        self.assertEqual(restoration.audit_status, "PENDING")
        self.assertTrue(restoration.manifest_matches)
        self.assertTrue(restoration.metadata_matches)

    def test_committed_restoration_with_commit_before_creation_is_inconsistent(self):
        restoration = {
            **self.restoration,
            "committed_at": datetime(2026, 10, 20, 8, 59),
        }

        status, _restoration = self._project(
            restoration=restoration,
            tasks=self.restored_tasks,
            restore_manifest=self.manifest,
        )

        self.assertEqual(status, "INCONSISTENT")

    def test_committed_restoration_requires_complete_ordered_timestamps(self):
        cases = (
            (
                self.source,
                {**self.restoration, "committed_at": None},
            ),
            (
                {
                    **self.source,
                    "committed_at": datetime(2026, 10, 20, 9, 30),
                },
                {
                    **self.restoration,
                    "created_at": datetime(2026, 10, 20, 9, 0),
                    "committed_at": datetime(2026, 10, 20, 9, 40),
                },
            ),
            (
                {
                    **self.source,
                    "committed_at": datetime(2026, 10, 19, 10, 59),
                },
                self.restoration,
            ),
        )

        for source, restoration in cases:
            with self.subTest(
                source_committed_at=source["committed_at"],
                restoration_created_at=restoration["created_at"],
                restoration_committed_at=restoration["committed_at"],
            ):
                status, _restoration = _project_deletion_status(
                    source=source,
                    source_manifest=self.manifest,
                    task_rows=self.restored_tasks,
                    restoration_row=restoration,
                    restoration_manifest=self.manifest,
                )
                self.assertEqual(status, "INCONSISTENT")

    def test_restored_cycle_stays_restored_while_a_later_deletion_is_current(self):
        later_id = "b8a1a88534744a1b93716acba49d246d"
        later_operation = {
            "operation_id": later_id,
            "reverses_operation_id": None,
            "empresa_id": 1,
            "root_task_id": 84,
            "root_correlativo": "B0000084",
            "actor_id": 10,
            "motivo": "Segunda eliminación",
            "backend_type": "MYSQL_CONFIG",
            "backend_identity": "mysql:BASE_TAREAS",
            "backend_config_version": "base-config",
            "status": "COMMITTED",
            "result_code": LOGICAL_DELETION_RESULT_CODE,
            "audit_status": "PENDING",
            "file_cleanup_status": "NOT_REQUIRED",
            "created_at": datetime(2026, 10, 20, 9, 2),
            "committed_at": datetime(2026, 10, 20, 9, 3),
            "manifest_entries": self.manifest,
            "marked_tasks": {
                84: {
                    "empresa_id": 1,
                    "eliminada": True,
                    "eliminada_en": datetime(2026, 10, 20, 9, 3),
                    "eliminada_por": 10,
                    "eliminacion_operacion_id": later_id,
                }
            },
            "restoration": None,
        }
        later_deleted_task = {
            84: {
                "empresa_id": 1,
                "eliminada": True,
                "eliminada_en": datetime(2026, 10, 20, 9, 3),
                "eliminada_por": 10,
                "eliminacion_operacion_id": later_id,
            }
        }

        status, restoration = self._project(
            restoration=self.restoration,
            tasks=later_deleted_task,
            restore_manifest=self.manifest,
            current_operations={later_id: later_operation},
        )

        self.assertEqual(status, "RESTORED")
        self.assertEqual(restoration.operation_id, self.restoration_id)

        later_operation["committed_at"] = datetime(2026, 10, 20, 9, 1)
        invalid_later_status, _restoration = self._project(
            restoration=self.restoration,
            tasks=later_deleted_task,
            restore_manifest=self.manifest,
            current_operations={later_id: later_operation},
        )
        self.assertEqual(invalid_later_status, "INCONSISTENT")

    def test_unverified_later_deletion_does_not_hide_an_inconsistent_chain(self):
        later_id = "b8a1a88534744a1b93716acba49d246d"
        later_operation = {
            "operation_id": later_id,
            "reverses_operation_id": None,
            "empresa_id": 1,
            "root_task_id": 999,
            "root_correlativo": "B0000999",
            "actor_id": 10,
            "motivo": "Operación de otra raíz",
            "backend_type": "MYSQL_CONFIG",
            "backend_identity": "mysql:BASE_TAREAS",
            "backend_config_version": "base-config",
            "status": "COMMITTED",
            "result_code": LOGICAL_DELETION_RESULT_CODE,
            "audit_status": "CONFIRMED",
            "file_cleanup_status": "NOT_REQUIRED",
            "created_at": datetime(2026, 10, 20, 9, 2),
            "committed_at": datetime(2026, 10, 20, 9, 3),
            "manifest_entries": self.manifest,
            "marked_tasks": {
                84: {
                    "empresa_id": 1,
                    "eliminada": True,
                    "eliminada_en": datetime(2026, 10, 20, 9, 3),
                    "eliminada_por": 10,
                    "eliminacion_operacion_id": later_id,
                }
            },
            "restoration": None,
        }
        later_deleted_task = {
            84: {
                "empresa_id": 1,
                "eliminada": True,
                "eliminada_en": datetime(2026, 10, 20, 9, 3),
                "eliminada_por": 10,
                "eliminacion_operacion_id": later_id,
            }
        }

        status, _restoration = self._project(
            restoration=self.restoration,
            tasks=later_deleted_task,
            restore_manifest=self.manifest,
            current_operations={later_id: later_operation},
        )

        self.assertEqual(status, "INCONSISTENT")

    def test_pending_restoration_does_not_change_current_deleted_projection(self):
        pending = {
            **self.restoration,
            "status": "PENDING",
            "result_code": "",
        }

        status, restoration = self._project(
            restoration=pending,
            restore_manifest=self.manifest,
        )

        self.assertEqual(status, "CURRENTLY_DELETED")
        self.assertEqual(restoration.status, "PENDING")

    def test_restoration_linked_to_another_deletion_is_not_counted(self):
        unrelated = {
            **self.restoration,
            "reverses_operation_id": UUID(
                "fe4d1478-a78e-41ca-ad8c-3497dc35b487"
            ).hex,
        }

        status, restoration = self._project(restoration=unrelated)

        self.assertEqual(status, "CURRENTLY_DELETED")
        self.assertIsNone(restoration)

    def test_restoration_for_another_company_is_not_counted(self):
        other_company = {
            **self.restoration,
            "empresa_id": 2,
        }

        status, restoration = self._project(restoration=other_company)

        self.assertEqual(status, "CURRENTLY_DELETED")
        self.assertIsNone(restoration)

    def test_committed_restoration_with_mismatched_manifest_is_inconsistent(self):
        mismatched_manifest = (
            {"item_type": TASK_ITEM_LABEL, "object_id": 85},
        )

        status, restoration = self._project(
            restoration=self.restoration,
            tasks=self.restored_tasks,
            restore_manifest=mismatched_manifest,
        )

        self.assertEqual(status, "INCONSISTENT")
        self.assertFalse(restoration.manifest_matches)

    def test_missing_task_remains_physically_absent_and_inconsistent(self):
        status, _restoration = self._project(tasks={})
        item = _history_item(
            {
                "operation_id": self.operation_id.hex,
                "empresa_id": 1,
                "task_id": 84,
                "root_task_id": 84,
                "root_correlativo": "B0000084",
                "actor_id": 8,
                "motivo": "Motivo original",
                "operation_status": "COMMITTED",
                "result_code": LOGICAL_DELETION_RESULT_CODE,
                "audit_status": "CONFIRMED",
                "audit_event_id": 6,
                "physical_task_id": None,
                "deletion_status": status,
            }
        )

        self.assertEqual(status, "INCONSISTENT")
        self.assertEqual(item.deletion_status, "INCONSISTENT")
        self.assertEqual(item.physical_status, "PHYSICALLY_ABSENT")


class DeletedTaskHistoryOperationTests(SimpleTestCase):
    def _operation_cursor(
        self,
        *,
        restoration=None,
        source_manifest=None,
        restoration_manifest=None,
        task_rows=(),
        relations=(),
        files=(),
    ):
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
            "backend_config_version",
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
            "base-config",
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
        source_manifest = source_manifest or (
            ("tareas.tarea", 84),
            ("tareas.tarea", 85),
            ("tareas.tarea", 86),
        )
        restoration_manifest = restoration_manifest or source_manifest
        task_columns = (
            "id", "empresa", "correlativo", "titulo", "descripcion",
            "prioridad", "estado", "anulada", "eliminada", "eliminada_en",
            "eliminada_por", "eliminacion_operacion_id", "creada_por",
            "responsable", "fecha_creacion", "fecha_publicacion",
            "fecha_asignacion", "fecha_tope", "fecha_cumplimiento",
            "local", "departamento",
        )
        restoration_columns = (
            "operation_id", "empresa_id", "root_task_id", "actor_id",
            "motivo", "backend_type", "backend_identity",
            "backend_config_version", "status", "result_code", "audit_status",
            "audit_event_id", "audit_error_code", "file_cleanup_status",
            "created_at", "committed_at", "reverses_operation_id",
        )

        def respond(sql, params):
            if "FROM `tareas_eliminacion_operacion` op" in sql:
                return _description(*operation_columns), None, (operation,)
            if "FROM `tareas_eliminacion_operacion` restoration" in sql:
                return (
                    _description(*restoration_columns),
                    None,
                    (tuple(restoration[name] for name in restoration_columns),)
                    if restoration is not None
                    else (),
                )
            if "FROM `tareas_eliminacion_elemento`" in sql:
                rows = (
                    restoration_manifest
                    if restoration is not None
                    and params
                    and str(params[0]) == str(restoration["operation_id"])
                    else source_manifest
                )
                return _description("item_type", "object_id"), None, (
                    *rows,
                )
            if "FROM `tareas_tarea` task" in sql:
                return (
                    _description(*task_columns),
                    None,
                    tuple(tuple(row.get(name) for name in task_columns) for row in task_rows),
                )
            if "FROM `tareas_eliminacion_archivo`" in sql:
                return (
                    _description(
                        "storage_key",
                        "file_name",
                        "status",
                        "attempts",
                        "last_attempt_at",
                        "error_code",
                    ),
                    None,
                    tuple(files),
                )
            if "FROM `tareas_tarearelacion`" in sql:
                return _description("parent_id", "child_id"), None, tuple(relations)
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
        self.assertEqual(operation.deletion_status, "INCONSISTENT")
        self.assertTrue(all(sql.lstrip().startswith("SELECT") for sql, _ in cursor.statements))

    def test_committed_restoration_trace_does_not_expose_current_task_values(self):
        operation_id = "25ffcbcf525746ea8b4b9a5e29ebe7e0"
        restoration_id = "76a4cf0ab9724b259e6111db893dc35f"
        created_at = datetime(2026, 10, 20, 9, 0)
        committed_at = datetime(2026, 10, 20, 9, 1)
        restoration = {
            "operation_id": restoration_id,
            "empresa_id": 1,
            "root_task_id": 84,
            "actor_id": 9,
            "motivo": "Restauración autorizada",
            "backend_type": "MYSQL_CONFIG",
            "backend_identity": "mysql:BASE_TAREAS",
            "backend_config_version": "base-config",
            "status": "COMMITTED",
            "result_code": LOGICAL_RESTORATION_RESULT_CODE,
            "audit_status": "PENDING",
            "audit_event_id": None,
            "audit_error_code": "AUDIT_DELIVERY_FAILED",
            "file_cleanup_status": "NOT_REQUIRED",
            "created_at": created_at,
            "committed_at": committed_at,
            "reverses_operation_id": operation_id,
        }
        manifest = (("tareas.tarea", 84), ("tareas.tarea", 85), ("tareas.tarea", 86))
        rows = tuple(
            {
                "id": task_id,
                "empresa": 1,
                "correlativo": f"B00000{task_id}",
                "titulo": f"Current title {task_id}",
                "descripcion": "Current description",
                "prioridad": "NORMAL",
                "estado": "ACTIVA",
                "anulada": False,
                "eliminada": False,
                "eliminada_en": None,
                "eliminada_por": None,
                "eliminacion_operacion_id": None,
                "creada_por": 8,
                "responsable": 8,
                "fecha_creacion": datetime(2026, 10, 1, 9, 0),
                "fecha_publicacion": None,
                "fecha_asignacion": None,
                "fecha_tope": None,
                "fecha_cumplimiento": None,
                "local": None,
                "departamento": None,
            }
            for task_id in (84, 85, 86)
        )
        cursor = self._operation_cursor(
            restoration=restoration,
            source_manifest=manifest,
            restoration_manifest=manifest,
            task_rows=rows,
            relations=((84, 85), (85, 86)),
        )

        @contextmanager
        def opened():
            yield cursor, "mysql", lambda identifier: f"`{identifier}`"

        audit_event = SimpleNamespace(
            pk=6,
            idempotency_key=operation_id,
            empresa_id=1,
            action="DELETE",
            object_type="Tarea",
            object_id="84",
            user_id=8,
            created_at=datetime(2026, 10, 19, 12, 0),
            message_key=None,
            meta={"operation_id": operation_id, "backend_type": "MYSQL_CONFIG"},
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
                operation_id=UUID(hex=operation_id),
            )

        self.assertEqual(operation.deletion_status, "RESTORED")
        self.assertEqual(operation.restoration.operation_id.hex, restoration_id)
        self.assertEqual(operation.restoration.actor_id, 9)
        self.assertEqual(operation.restoration.motivo, "Restauración autorizada")
        self.assertEqual(operation.restoration.audit_status, "PENDING")
        self.assertTrue(operation.restoration.manifest_matches)
        self.assertTrue(operation.restoration.metadata_matches)
        self.assertEqual(operation.relations, ())
        self.assertEqual(
            operation.hierarchy_status,
            "HISTORICAL_RELATIONS_UNAVAILABLE",
        )
        self.assertTrue(all(item.task.titulo is None for item in operation.items))
        self.assertTrue(
            all(item.physical_status == "PHYSICALLY_RETAINED" for item in operation.items)
        )
        restoration_lookup = next(
            (sql, params)
            for sql, params in cursor.statements
            if "reverses_operation_id" in sql
        )
        self.assertEqual(restoration_lookup[1], (operation_id, 1))

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
