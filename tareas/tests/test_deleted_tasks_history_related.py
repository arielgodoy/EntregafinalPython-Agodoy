from contextlib import contextmanager
from datetime import datetime
import re
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.test import SimpleTestCase

from tareas.models import (
    Comentario,
    DocumentoTarea,
    Hito,
    LOGICAL_DELETION_RESULT_CODE,
    Tarea,
    TareaParticipante,
    TareaEliminacionOperacion,
)
from tareas.services.deleted_tasks_history import (
    TASK_ITEM_LABEL,
    DeletedTaskHistoryItem,
    DeletionHistoryManifestItem,
    get_deleted_task_history_detail,
)


def _description(*names):
    return tuple((name,) for name in names)


class RelatedHistoryCursor:
    def __init__(self, records_by_table):
        self.records_by_table = records_by_table
        self.description = ()
        self.rows = ()
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        table_match = re.search(r"FROM `([^`]+)`", sql)
        alias_matches = re.findall(
            r"\s+AS\s+(?:`([^`]+)`|\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*))",
            sql,
            re.IGNORECASE,
        )
        if table_match is None or not alias_matches:
            raise AssertionError(f"Unexpected SELECT shape: {sql}")
        table = table_match.group(1)
        aliases = tuple(next(part for part in match if part) for match in alias_matches)
        self.description = _description(*aliases)
        self.rows = tuple(
            tuple(record.get(alias) for alias in aliases)
            for record in self.records_by_table.get(table, ())
        )

    def fetchall(self):
        return self.rows


class DeletedTaskHistoryRelatedTests(SimpleTestCase):
    def setUp(self):
        self.operation_id = UUID("25ffcbcf-5257-46ea-8b4b-9a5e29ebe7e0")
        self.task = DeletedTaskHistoryItem(
            operation_id=self.operation_id,
            empresa_id=1,
            task_id=84,
            root_task_id=84,
            is_root=True,
            root_correlativo="B0000084",
            correlativo="B0000084",
            titulo="Tarea conservada",
            estado="CERRADA",
            deleted_at=datetime(2026, 10, 19, 12, 0),
            actor_id=8,
            motivo="Motivo de prueba",
            operation_status=TareaEliminacionOperacion.Estado.COMMITTED,
            result_code=LOGICAL_DELETION_RESULT_CODE,
            audit_status=TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
            audit_event_id=6,
            physical_status="PHYSICALLY_RETAINED",
        )
        self.operation = SimpleNamespace(
            operation_id=self.operation_id,
            items=(
                DeletionHistoryManifestItem(
                    item_type=TASK_ITEM_LABEL,
                    object_id=84,
                    physical_status="PHYSICALLY_RETAINED",
                    task=self.task,
                ),
            ),
        )

    def _cursor(self):
        created_at = datetime(2026, 10, 10, 9, 0)
        records = {
            Tarea._meta.db_table: (
                {
                    "id": 84,
                    "descripcion": "Descripción conservada",
                    "prioridad": "NORMAL",
                    "fecha_creacion": created_at,
                    "fecha_publicacion": created_at,
                    "fecha_asignacion": None,
                    "fecha_tope": None,
                    "fecha_cumplimiento": None,
                    "creada_por": 8,
                    "responsable": 8,
                    "local": None,
                    "departamento": None,
                },
            ),
            TareaParticipante._meta.db_table: (
                {
                    "id": 1,
                    "usuario_id": 8,
                    "rol": "CREADOR",
                    "fecha": created_at,
                },
            ),
        }
        return RelatedHistoryCursor(records)

    def _detail(self, cursor, **permissions):
        @contextmanager
        def opened():
            yield cursor, "mysql", lambda identifier: f"`{identifier}`"

        with (
            patch(
                "tareas.services.deleted_tasks_history.get_deleted_task_history_operation",
                return_value=self.operation,
            ),
            patch(
                "tareas.services.deleted_tasks_history._history_cursor",
                side_effect=opened,
            ),
        ):
            return get_deleted_task_history_detail(
                empresa_id=1,
                operation_id=self.operation_id,
                task_id=84,
                **permissions,
            )

    def test_related_data_is_unavailable_without_operational_task_permission(self):
        cursor = self._cursor()

        detail = self._detail(cursor)

        self.assertEqual(detail.related.related_status, "ACCESS_RESTRICTED")
        self.assertEqual(detail.related.participants, ())
        self.assertEqual(len(cursor.statements), 1)
        self.assertTrue(all(sql.lstrip().startswith("SELECT") for sql, _ in cursor.statements))

    def test_related_rows_are_projected_without_file_urls_or_hidden_comment_content(self):
        cursor = self._cursor()
        records = cursor.records_by_table
        records[Hito._meta.db_table] = (
            {
                "id": 2,
                "nombre": "Hito conservado",
                "responsable_id": 8,
                "anulado": False,
                "completado": True,
                "completado_por_id": 8,
                "fecha_completado": datetime(2026, 10, 11, 10, 0),
                "resena_cierre": "Cierre conservado",
                "cumplimiento": 100,
                "peso": 1,
                "fecha_creacion": datetime(2026, 10, 10, 10, 0),
            },
        )
        records[DocumentoTarea._meta.db_table] = (
            {
                "id": 3,
                "tipo": "INFORME",
                "formato_archivo": "PDF",
                "archivo": "",
                "url": "https://example.test/resource?token=secret",
                "fecha_documento": datetime(2026, 10, 12).date(),
                "fecha_vencimiento": None,
                "usuario_id": 8,
                "estado": "",
            },
        )
        records[Comentario._meta.db_table] = (
            {
                "id": 4,
                "autor_id": 8,
                "contenido": "Comentario visible",
                "created_at": datetime(2026, 10, 13, 10, 0),
                "oculto": False,
            },
            {
                "id": 5,
                "autor_id": 9,
                "contenido": "CONTENIDO PRIVADO",
                "created_at": datetime(2026, 10, 14, 10, 0),
                "oculto": True,
            },
        )

        detail = self._detail(
            cursor,
            can_read_related=True,
            can_read_comments=True,
            can_read_hidden_comments=False,
        )

        self.assertEqual(detail.related.related_status, "AVAILABLE")
        self.assertEqual(detail.related.participants[0].state, "CREADOR")
        self.assertEqual(detail.related.milestones[0].label, "Hito conservado")
        self.assertEqual(detail.related.documents[0].label, "EXTERNAL_LINK")
        self.assertNotIn("secret", repr(detail.related.documents))
        self.assertIn("Comentario visible", repr(detail.related.comments))
        self.assertNotIn("CONTENIDO PRIVADO", repr(detail.related.comments))
        hidden = next(
            record
            for record in detail.related.comments
            if record.kind == "comment_tombstone"
        )
        self.assertIsNone(hidden.actor_id)
        self.assertIsNone(hidden.label)
        self.assertTrue(all(sql.lstrip().startswith("SELECT") for sql, _ in cursor.statements))
