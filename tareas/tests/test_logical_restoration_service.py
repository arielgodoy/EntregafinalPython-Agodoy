from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.db import connections
from django.test import TestCase

from auditoria.services import AuditIdempotencyStorageError, AuditoriaService
from tareas.models import (
    LOGICAL_DELETION_RESULT_CODE,
    LOGICAL_RESTORATION_RESULT_CODE,
    DocumentoTarea,
    Tarea,
    TareaEliminacionElemento,
    TareaEliminacionOperacion,
    TareaRelacion,
)
from tareas.services.deletion_ledger import (
    DeletionLedgerStateError,
    DjangoDeletionLedgerStorage,
    RestorationOperationInput,
)
from tareas.services.logical_deletion import logically_delete_task_tree
from tareas.services.logical_restoration import (
    LogicalRestorationError,
    _DjangoRestorationAdapter,
    _MySQLRestorationAdapter,
    build_logical_restoration_preview,
    reconcile_logical_restoration_audit,
    restore_logical_task_tree,
)
from tareas.services.task_mutation_locks import (
    TaskMutationConflict,
    TaskMutationScopeError,
)
from tareas.tests.factories import (
    assign_permission,
    create_empresa,
    create_tarea,
    create_user,
)


class LogicalRestorationServiceTests(TestCase):
    def setUp(self):
        self.company = create_empresa("00", "Base 00")
        self.actor = create_user("logical-restoration-supervisor")
        assign_permission(
            self.actor,
            self.company,
            "Tareas",
            supervisor=True,
        )
        self.storage = DjangoDeletionLedgerStorage("default", "test-config")
        self.root = create_tarea(
            self.company,
            self.actor,
            correlativo="S0000001",
            titulo="Raíz restaurable",
            estado=Tarea.Estado.GESTION,
            fecha_tope=date(2026, 12, 31),
            responsable=self.actor,
        )
        self.child = create_tarea(
            self.company,
            self.actor,
            correlativo="S0000002",
            titulo="Hija restaurable",
            estado=Tarea.Estado.CERRADA,
        )
        TareaRelacion.objects.create(padre=self.root, hija=self.child)
        self.document = DocumentoTarea.objects.create(
            tarea=self.child,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo="PDF",
            archivo="tareas/documentos/restoration-retained.pdf",
            usuario=self.actor,
        )
        self.deletion_operation_id = uuid4()
        with patch(
            "tareas.services.logical_deletion.resolve_deletion_ledger_storage",
            return_value=self.storage,
        ):
            logically_delete_task_tree(
                actor=self.actor,
                empresa_id=self.company.pk,
                root_task_id=self.root.pk,
                motivo="Eliminación lógica de prueba",
                operation_id=self.deletion_operation_id,
            )

    def _preview(self):
        with patch(
            "tareas.services.logical_restoration.resolve_deletion_ledger_storage",
            return_value=self.storage,
        ):
            return build_logical_restoration_preview(
                actor=self.actor,
                empresa_id=self.company.pk,
                deletion_operation_id=self.deletion_operation_id,
            )

    def _restore(self, preview, *, operation_id=None, motivo="Restauración de prueba"):
        with patch(
            "tareas.services.logical_restoration.resolve_deletion_ledger_storage",
            return_value=self.storage,
        ):
            return restore_logical_task_tree(
                actor=self.actor,
                empresa_id=self.company.pk,
                deletion_operation_id=self.deletion_operation_id,
                restoration_operation_id=operation_id or uuid4(),
                motivo=motivo,
                expected_fingerprint=preview.fingerprint,
            )

    def test_preview_is_read_only_and_reports_exact_retained_data(self):
        markers_before = tuple(
            Tarea.all_objects.filter(pk__in=(self.root.pk, self.child.pk))
            .order_by("pk")
            .values_list(
                "eliminada",
                "eliminada_en",
                "eliminada_por_id",
                "eliminacion_operacion_id",
            )
        )

        preview = self._preview()

        self.assertTrue(preview.can_restore)
        self.assertEqual(preview.task_ids, (self.root.pk, self.child.pk))
        self.assertEqual(preview.hierarchy, ((self.root.pk, self.child.pk),))
        self.assertEqual(len(preview.documents), 1)
        self.assertEqual(preview.documents[0].document_id, self.document.pk)
        self.assertTrue(preview.documents[0].has_file)
        self.assertFalse(preview.documents[0].has_url)
        self.assertTrue(preview.fingerprint)
        self.assertEqual(
            tuple(
                Tarea.all_objects.filter(pk__in=(self.root.pk, self.child.pk))
                .order_by("pk")
                .values_list(
                    "eliminada",
                    "eliminada_en",
                    "eliminada_por_id",
                    "eliminacion_operacion_id",
                )
            ),
            markers_before,
        )
        self.assertFalse(
            TareaEliminacionOperacion.objects.filter(
                reverses_operation_id=self.deletion_operation_id.hex,
            ).exists()
        )

    def test_restore_commits_exact_manifest_and_preserves_business_data(self):
        source_before = TareaEliminacionOperacion.objects.get(
            operation_id=self.deletion_operation_id.hex
        )
        TareaEliminacionOperacion.objects.filter(
            operation_id=self.deletion_operation_id.hex,
        ).update(
            audit_status=TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
        )
        preview = self._preview()
        self.assertIn("SOURCE_AUDIT_UNCONFIRMED", {item.code for item in preview.warnings})

        restoration_operation_id = uuid4()
        result = self._restore(preview, operation_id=restoration_operation_id)

        self.assertEqual(result.operation_id, restoration_operation_id)
        self.assertEqual(result.reverses_operation_id, self.deletion_operation_id)
        self.assertEqual(result.task_ids, (self.root.pk, self.child.pk))
        self.assertEqual(result.status, TareaEliminacionOperacion.Estado.COMMITTED)
        self.assertEqual(result.result_code, LOGICAL_RESTORATION_RESULT_CODE)
        self.assertEqual(
            result.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )
        restored = tuple(
            Tarea.all_objects.filter(pk__in=result.task_ids)
            .order_by("pk")
            .values_list(
                "eliminada",
                "eliminada_en",
                "eliminada_por_id",
                "eliminacion_operacion_id",
            )
        )
        self.assertEqual(restored, ((False, None, None, None),) * 2)
        self.root.refresh_from_db()
        self.assertEqual(self.root.estado, Tarea.Estado.GESTION)
        self.assertEqual(self.root.fecha_tope, date(2026, 12, 31))
        self.assertEqual(getattr(self.root, "responsable_id"), self.actor.pk)
        self.assertEqual(
            TareaRelacion.objects.filter(
                padre_id=self.root.pk,
                hija_id=self.child.pk,
            ).count(),
            1,
        )
        self.document.refresh_from_db()
        self.assertEqual(
            self.document.archivo.name,
            "tareas/documentos/restoration-retained.pdf",
        )
        self.assertEqual(
            TareaEliminacionElemento.objects.filter(
                operacion_id=restoration_operation_id.hex,
                tipo="tareas.tarea",
            ).values_list("object_id", flat=True).order_by("object_id").count(),
            2,
        )
        source_after = TareaEliminacionOperacion.objects.get(
            operation_id=self.deletion_operation_id.hex
        )
        self.assertEqual(source_after.status, source_before.status)
        self.assertEqual(source_after.result_code, LOGICAL_DELETION_RESULT_CODE)
        self.assertIsNone(getattr(source_after, "reverses_operation_id"))
        self.assertEqual(
            getattr(
                TareaEliminacionOperacion.objects.get(
                    operation_id=restoration_operation_id.hex
                ),
                "reverses_operation_id",
            ),
            self.deletion_operation_id.hex,
        )
        event = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            restoration_operation_id.hex,
        )
        if event is None:
            raise AssertionError("La auditoría de restauración no se registró.")
        self.assertEqual(event.action, "UPDATE")
        if event.meta is None:
            raise AssertionError("La auditoría de restauración no tiene metadata.")
        self.assertEqual(event.meta["operation"], "logical_restore_tree")

    def test_same_request_replays_without_second_mutation_or_audit_event(self):
        preview = self._preview()
        restoration_operation_id = uuid4()
        first = self._restore(preview, operation_id=restoration_operation_id)
        second = self._restore(preview, operation_id=restoration_operation_id)

        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(first.operation_id, second.operation_id)
        self.assertEqual(
            TareaEliminacionOperacion.objects.filter(
                reverses_operation_id=self.deletion_operation_id.hex,
            ).count(),
            1,
        )
        event = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            restoration_operation_id.hex,
        )
        if event is None:
            raise AssertionError("No se encontró el evento idempotente.")
        self.assertEqual(event.idempotency_key, restoration_operation_id.hex)

        next_preview = self._preview()
        with self.assertRaises(LogicalRestorationError) as error:
            self._restore(next_preview, operation_id=uuid4())
        self.assertEqual(error.exception.code, "RESTORATION_ALREADY_COMPLETED")

    def test_pending_ledger_registration_can_resume_with_the_same_uuid(self):
        preview = self._preview()
        restoration_operation_id = uuid4()
        motivo = "Restauración de prueba"
        with self.storage.atomic() as unit:
            unit.create_restoration_pending(
                RestorationOperationInput(
                    actor_id=self.actor.pk,
                    empresa_id=self.company.pk,
                    reverses_operation_id=self.deletion_operation_id,
                    fingerprint=preview.fingerprint,
                    manifest=preview.manifest,
                    operation_id=restoration_operation_id,
                    motivo=motivo,
                )
            )

        result = self._restore(
            preview,
            operation_id=restoration_operation_id,
            motivo=motivo,
        )

        self.assertEqual(result.operation_id, restoration_operation_id)
        self.assertFalse(result.replayed)
        self.assertEqual(result.result_code, LOGICAL_RESTORATION_RESULT_CODE)
        self.assertFalse(
            Tarea.all_objects.filter(
                pk__in=(self.root.pk, self.child.pk),
                eliminada=True,
            ).exists()
        )

    def test_user_with_delete_but_without_supervisor_cannot_preview_or_restore(self):
        delete_only = create_user("logical-restoration-delete-only")
        assign_permission(
            delete_only,
            self.company,
            "Tareas",
            eliminar=True,
        )
        with patch(
            "tareas.services.logical_restoration.resolve_deletion_ledger_storage",
            return_value=self.storage,
        ):
            with self.assertRaises(LogicalRestorationError) as preview_error:
                build_logical_restoration_preview(
                    actor=delete_only,
                    empresa_id=self.company.pk,
                    deletion_operation_id=self.deletion_operation_id,
                )
        self.assertEqual(preview_error.exception.code, "RESTORATION_UNAUTHORIZED")

        with patch(
            "tareas.services.logical_restoration.resolve_deletion_ledger_storage",
            return_value=self.storage,
        ):
            with self.assertRaises(LogicalRestorationError) as restore_error:
                restore_logical_task_tree(
                    actor=delete_only,
                    empresa_id=self.company.pk,
                    deletion_operation_id=self.deletion_operation_id,
                    restoration_operation_id=uuid4(),
                    motivo="Sin supervisor",
                    expected_fingerprint="a" * 64,
                )
        self.assertEqual(restore_error.exception.code, "RESTORATION_UNAUTHORIZED")
        self.assertTrue(
            Tarea.all_objects.filter(
                pk=self.root.pk,
                eliminada=True,
                eliminacion_operacion_id=self.deletion_operation_id,
            ).exists()
        )

    def test_operation_from_another_company_is_not_disclosed(self):
        other_company = create_empresa("01", "Otra empresa")
        other_task = create_tarea(
            other_company,
            self.actor,
            correlativo="X0000001",
            titulo="Tarea fuera del alcance",
        )
        foreign_operation_id = uuid4()
        foreign_operation = TareaEliminacionOperacion.objects.create(
            operation_id=foreign_operation_id.hex,
            actor_id=self.actor.pk,
            empresa_id=other_company.pk,
            root_task_id=other_task.pk,
            root_correlativo=other_task.correlativo,
            backend_type="DJANGO",
            backend_identity=self.storage.backend_identity,
            backend_config_version=self.storage.config_version,
            fingerprint="c" * 64,
            dependency_summary='{"tareas.tarea":1}',
            motivo="Operación de otra empresa",
            status=TareaEliminacionOperacion.Estado.COMMITTED,
            result_code=LOGICAL_DELETION_RESULT_CODE,
            audit_status=TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
            file_cleanup_status=TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA,
        )
        TareaEliminacionElemento.objects.create(
            operacion=foreign_operation,
            tipo="tareas.tarea",
            object_id=other_task.pk,
        )

        with patch(
            "tareas.services.logical_restoration.resolve_deletion_ledger_storage",
            return_value=self.storage,
        ):
            with self.assertRaises(LogicalRestorationError) as error:
                build_logical_restoration_preview(
                    actor=self.actor,
                    empresa_id=self.company.pk,
                    deletion_operation_id=foreign_operation_id,
                )

        self.assertEqual(error.exception.code, "RESTORATION_NOT_FOUND")

    def test_changed_task_markers_invalidate_preview_without_writes(self):
        preview = self._preview()
        other_operation_id = uuid4()
        quote = connections["default"].ops.quote_name
        with connections["default"].cursor() as cursor:
            cursor.execute(
                f"UPDATE {quote(Tarea._meta.db_table)} "
                f"SET {quote(getattr(Tarea._meta.get_field('eliminacion_operacion_id'), 'column'))} = %s "
                f"WHERE {quote(getattr(Tarea._meta.pk, 'column'))} = %s",
                (other_operation_id.hex, self.child.pk),
            )

        with self.assertRaises(LogicalRestorationError) as error:
            self._restore(preview)

        self.assertEqual(error.exception.code, "RESTORATION_PREVIEW_STALE")
        self.assertFalse(
            TareaEliminacionOperacion.objects.filter(
                reverses_operation_id=self.deletion_operation_id.hex,
            ).exists()
        )

    def test_foreign_task_in_manifest_blocks_before_related_metadata_is_read(self):
        other_company = create_empresa("02", "Otra empresa del manifiesto")
        foreign_task = create_tarea(
            other_company,
            self.actor,
            correlativo="F0000001",
            titulo="No debe aparecer en preview",
        )
        DocumentoTarea.objects.create(
            tarea=foreign_task,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo="PDF",
            archivo="private/foreign-document.pdf",
            usuario=self.actor,
        )
        TareaEliminacionElemento.objects.filter(
            operacion_id=self.deletion_operation_id.hex,
            tipo="tareas.tarea",
            object_id=self.child.pk,
        ).update(object_id=foreign_task.pk)

        with (
            patch.object(
                _DjangoRestorationAdapter,
                "hierarchy_edges",
                side_effect=AssertionError("La jerarquía no debe leerse."),
            ),
            patch.object(
                _DjangoRestorationAdapter,
                "documents",
                side_effect=AssertionError("Los documentos no deben leerse."),
            ),
            patch.object(
                _DjangoRestorationAdapter,
                "external_origin_reference_count",
                side_effect=AssertionError("Las referencias no deben leerse."),
            ),
        ):
            preview = self._preview()

        self.assertFalse(preview.can_restore)
        self.assertEqual(preview.documents, ())
        self.assertIn(
            "RESTORATION_TASK_MISSING",
            {item.code for item in preview.blockers},
        )
        self.assertNotIn(
            "No debe aparecer en preview",
            {task.titulo for task in preview.tasks if task.titulo},
        )

    def test_external_origin_reference_count_is_company_scoped(self):
        other_company = create_empresa("03", "Otra empresa referenciante")
        foreign_reference = create_tarea(
            other_company,
            self.actor,
            correlativo="F0000002",
            titulo="Referencia de otra empresa",
        )
        quote = connections["default"].ops.quote_name
        with connections["default"].cursor() as cursor:
            cursor.execute(
                f"UPDATE {quote(Tarea._meta.db_table)} "
                f"SET {quote(getattr(Tarea._meta.get_field('tarea_origen'), 'column'))} = %s "
                f"WHERE {quote(getattr(Tarea._meta.pk, 'column'))} = %s",
                (self.child.pk, foreign_reference.pk),
            )

        preview = self._preview()

        self.assertEqual(preview.external_origin_reference_count, 0)
        self.assertNotIn(
            "EXTERNAL_ORIGIN_REFERENCES",
            {item.code for item in preview.warnings},
        )

    def test_mysql_related_queries_include_the_active_company_scope(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchall.return_value = ()
        adapter = _MySQLRestorationAdapter(connection, self.company.pk)

        adapter.documents((self.child.pk,), lock=False)
        document_sql, document_params = cursor.execute.call_args.args
        self.assertIn("JOIN `tareas_tarea`", document_sql)
        self.assertIn("`empresa_id` = %s", document_sql)
        self.assertEqual(document_params[0], self.company.pk)

        cursor.execute.reset_mock()
        cursor.fetchall.return_value = ((0,),)
        self.assertEqual(
            adapter.external_origin_reference_count((self.child.pk,)),
            0,
        )
        reference_sql, reference_params = cursor.execute.call_args.args
        self.assertIn("`empresa_id` = %s", reference_sql)
        self.assertEqual(reference_params[0], self.company.pk)

    def test_mysql_task_scope_error_after_preview_keeps_typed_failure(self):
        preview = self._preview()
        connection = MagicMock()
        adapter = _MySQLRestorationAdapter(connection, self.company.pk)
        preview_adapter = _DjangoRestorationAdapter("default", self.company.pk)
        with patch(
            "tareas.services.logical_restoration._task_adapter",
            side_effect=[preview_adapter, adapter],
        ), patch.object(
            adapter,
            "tasks",
            side_effect=TaskMutationScopeError("simulated missing MySQL row"),
        ):
            with self.assertRaises(LogicalRestorationError) as error:
                self._restore(preview)

        self.assertEqual(error.exception.code, "RESTORATION_TASK_MISSING")

    def test_task_scope_error_after_preview_keeps_typed_failure_and_rolls_back(self):
        preview = self._preview()
        original_tasks = _DjangoRestorationAdapter.tasks

        def fail_when_locked(adapter, task_ids, *, lock):
            if lock:
                raise TaskMutationScopeError("simulated missing row")
            return original_tasks(adapter, task_ids, lock=lock)

        with patch.object(
            _DjangoRestorationAdapter,
            "tasks",
            new=fail_when_locked,
        ):
            with self.assertRaises(LogicalRestorationError) as error:
                self._restore(preview)

        self.assertEqual(error.exception.code, "RESTORATION_TASK_MISSING")
        self.assertTrue(
            Tarea.all_objects.filter(
                pk__in=(self.root.pk, self.child.pk),
                eliminada=True,
                eliminacion_operacion_id=self.deletion_operation_id,
            ).count()
            == 2
        )
        self.assertFalse(
            TareaEliminacionOperacion.objects.filter(
                reverses_operation_id=self.deletion_operation_id.hex,
            ).exists()
        )

    def test_task_lock_conflict_after_preview_keeps_typed_failure_and_rolls_back(self):
        preview = self._preview()
        original_tasks = _DjangoRestorationAdapter.tasks

        def conflict_when_locked(adapter, task_ids, *, lock):
            if lock:
                raise TaskMutationConflict("simulated concurrent mutation")
            return original_tasks(adapter, task_ids, lock=lock)

        with patch.object(
            _DjangoRestorationAdapter,
            "tasks",
            new=conflict_when_locked,
        ):
            with self.assertRaises(LogicalRestorationError) as error:
                self._restore(preview)

        self.assertEqual(error.exception.code, "RESTORATION_STATE_CONFLICT")
        self.assertTrue(
            Tarea.all_objects.filter(
                pk__in=(self.root.pk, self.child.pk),
                eliminada=True,
                eliminacion_operacion_id=self.deletion_operation_id,
            ).count()
            == 2
        )

    def test_transaction_rolls_back_markers_operation_and_manifest_on_failure(self):
        preview = self._preview()
        with patch(
            "tareas.services.deletion_ledger.DjangoDeletionLedgerUnitOfWork."
            "mark_logically_restored",
            side_effect=DeletionLedgerStateError("simulated transition failure"),
        ):
            with self.assertRaises(LogicalRestorationError):
                self._restore(preview)

        self.assertTrue(
            Tarea.all_objects.filter(
                pk__in=(self.root.pk, self.child.pk),
                eliminada=True,
                eliminacion_operacion_id=self.deletion_operation_id,
            ).count()
            == 2
        )
        self.assertFalse(
            TareaEliminacionOperacion.objects.filter(
                reverses_operation_id=self.deletion_operation_id.hex,
            ).exists()
        )

    def test_audit_failure_is_reconciled_idempotently_after_commit(self):
        preview = self._preview()
        restoration_operation_id = uuid4()
        with patch.object(
            AuditoriaService,
            "log_event_idempotent",
            side_effect=AuditIdempotencyStorageError("simulated audit outage"),
        ):
            with self.assertRaises(LogicalRestorationError) as error:
                self._restore(preview, operation_id=restoration_operation_id)

        self.assertEqual(error.exception.code, "RESTORATION_AUDIT_PENDING")
        operation = TareaEliminacionOperacion.objects.get(
            operation_id=restoration_operation_id.hex,
        )
        self.assertEqual(operation.status, TareaEliminacionOperacion.Estado.COMMITTED)
        self.assertEqual(
            operation.result_code,
            LOGICAL_RESTORATION_RESULT_CODE,
        )
        self.assertEqual(
            operation.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.ERROR,
        )
        self.assertFalse(
            AuditoriaService.get_event_by_idempotency_key(
                "tareas",
                restoration_operation_id.hex,
            )
        )

        with patch(
            "tareas.services.logical_restoration.resolve_deletion_ledger_storage",
            return_value=self.storage,
        ):
            first = reconcile_logical_restoration_audit(
                actor=self.actor,
                empresa_id=self.company.pk,
                restoration_operation_id=restoration_operation_id,
            )
            second = reconcile_logical_restoration_audit(
                actor=self.actor,
                empresa_id=self.company.pk,
                restoration_operation_id=restoration_operation_id,
            )

        self.assertEqual(
            first.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )
        self.assertEqual(first.operation_id, second.operation_id)
        event = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            restoration_operation_id.hex,
        )
        if event is None:
            raise AssertionError("La reconciliación no conservó el evento.")
        self.assertEqual(event.idempotency_key, restoration_operation_id.hex)

    def test_external_origin_reference_is_a_warning_not_a_blocker(self):
        external = create_tarea(
            self.company,
            self.actor,
            correlativo="S0000003",
            titulo="Referencia externa",
        )
        quote = connections["default"].ops.quote_name
        with connections["default"].cursor() as cursor:
            cursor.execute(
                f"UPDATE {quote(Tarea._meta.db_table)} "
                f"SET {quote(getattr(Tarea._meta.get_field('tarea_origen'), 'column'))} = %s "
                f"WHERE {quote(getattr(Tarea._meta.pk, 'column'))} = %s",
                (self.child.pk, external.pk),
            )

        preview = self._preview()

        self.assertTrue(preview.can_restore)
        self.assertIn(
            "EXTERNAL_ORIGIN_REFERENCES",
            {item.code for item in preview.warnings},
        )
        self.assertFalse(preview.blockers)

    def test_hierarchy_edge_outside_manifest_blocks_without_expanding_scope(self):
        external = create_tarea(
            self.company,
            self.actor,
            correlativo="S0000005",
            titulo="Tarea fuera del manifiesto",
        )
        TareaRelacion.objects.bulk_create(
            [TareaRelacion(padre=self.child, hija=external)]
        )

        preview = self._preview()

        self.assertFalse(preview.can_restore)
        self.assertEqual(preview.task_ids, (self.root.pk, self.child.pk))
        self.assertIn(
            "RESTORATION_HIERARCHY_CONFLICT",
            {item.code for item in preview.blockers},
        )
        with self.assertRaises(LogicalRestorationError) as error:
            self._restore(preview)
        self.assertEqual(error.exception.code, "RESTORATION_HIERARCHY_CONFLICT")
        self.assertTrue(
            Tarea.all_objects.filter(pk=external.pk, eliminada=False).exists()
        )

    def test_mysql_marker_update_is_parameterized_and_limited_to_deletion_fields(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.rowcount = 2
        adapter = _MySQLRestorationAdapter(connection, self.company.pk)

        affected = adapter.clear_deletion_markers(
            (self.root.pk, self.child.pk),
            self.deletion_operation_id,
        )

        self.assertEqual(affected, 2)
        sql, params = cursor.execute.call_args.args
        self.assertIn("UPDATE `tareas_tarea` SET", sql)
        self.assertIn("`eliminada_en` = NULL", sql)
        self.assertIn("`eliminada_por_id` = NULL", sql)
        self.assertIn("`eliminacion_operacion_id` = NULL", sql)
        self.assertIn("AND `eliminada` = %s", sql)
        self.assertIn("AND `eliminacion_operacion_id` = %s", sql)
        self.assertEqual(params[-1], self.deletion_operation_id.hex)

    def test_absent_manifest_task_blocks_the_whole_restore(self):
        root = create_tarea(
            self.company,
            self.actor,
            correlativo="S0000004",
            titulo="Fila ausente",
        )
        operation_id = uuid4()
        with patch(
            "tareas.services.logical_deletion.resolve_deletion_ledger_storage",
            return_value=self.storage,
        ):
            logically_delete_task_tree(
                actor=self.actor,
                empresa_id=self.company.pk,
                root_task_id=root.pk,
                motivo="Eliminación para prueba de ausencia",
                operation_id=operation_id,
            )
        quote = connections["default"].ops.quote_name
        with connections["default"].cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {quote(Tarea._meta.db_table)} "
                f"WHERE {quote(getattr(Tarea._meta.pk, 'column'))} = %s",
                (root.pk,),
            )

        with patch(
            "tareas.services.logical_restoration.resolve_deletion_ledger_storage",
            return_value=self.storage,
        ):
            preview = build_logical_restoration_preview(
                actor=self.actor,
                empresa_id=self.company.pk,
                deletion_operation_id=operation_id,
            )

        self.assertFalse(preview.can_restore)
        self.assertIn(
            "RESTORATION_TASK_MISSING",
            {item.code for item in preview.blockers},
        )
        with patch(
            "tareas.services.logical_restoration.resolve_deletion_ledger_storage",
            return_value=self.storage,
        ):
            with self.assertRaises(LogicalRestorationError) as error:
                restore_logical_task_tree(
                    actor=self.actor,
                    empresa_id=self.company.pk,
                    deletion_operation_id=operation_id,
                    restoration_operation_id=uuid4(),
                    motivo="No reconstruir la fila",
                    expected_fingerprint=preview.fingerprint,
                )

        self.assertEqual(error.exception.code, "RESTORATION_TASK_MISSING")
        self.assertFalse(
            TareaEliminacionOperacion.objects.filter(
                reverses_operation_id=operation_id.hex,
            ).exists()
        )
