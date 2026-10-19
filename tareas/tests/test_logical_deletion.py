import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone
from access_control.models import Permiso

from auditoria.services import AuditoriaService
from tareas.models import (
    LOGICAL_DELETION_RESULT_CODE,
    Tarea,
    TareaEliminacionArchivo,
    TareaEliminacionElemento,
    TareaEliminacionOperacion,
    TareaRelacion,
)
from tareas.services.deletion_ledger import (
    DeletionLedgerError,
    DeletionLedgerStateError,
    DjangoDeletionLedgerStorage,
    DjangoDeletionLedgerUnitOfWork,
)
from tareas.services.logical_deletion import (
    LogicalDeletionAuditPending,
    LogicalDeletionAuditConflict,
    LogicalDeletionAuthorizationError,
    LogicalDeletionBlocked,
    LogicalDeletionCompanyError,
    LogicalDeletionConflict,
    LogicalDeletionAuthorizationUnavailable,
    LogicalDeletionHierarchyError,
    LogicalDeletionInvalidRequest,
    LogicalDeletionResult,
    _MySQLTaskAdapter,
    logically_delete_task_tree,
    reconcile_logical_deletion_audit,
)
from tareas.services.task_mutation_locks import (
    TaskMutationScopeError,
    lock_orm_task_rows,
)
from tareas.tests.factories import (
    assign_permission,
    configure_task_storage,
    create_empresa,
    create_tarea,
    create_user,
)


class LogicalDeletionServiceTests(TestCase):
    def setUp(self):
        self.company = create_empresa("00", "Base 00")
        self.other_company = create_empresa("01", "Otra empresa")
        self.actor = create_user("logical-deletion-supervisor")
        assign_permission(
            self.actor,
            self.company,
            "Tareas",
            supervisor=True,
        )
        configure_task_storage("default")
        self.operation_id = uuid4()
        self.root, self.child, self.grandchild, self.branch = self._create_tree()

    def _create_tree(self):
        root = create_tarea(
            self.company,
            self.actor,
            correlativo="L0000001",
            titulo="Raíz conservada",
            anulada=True,
        )
        child = create_tarea(
            self.company,
            self.actor,
            correlativo="L0000002",
            titulo="Hija conservada",
            estado=Tarea.Estado.GESTION,
        )
        grandchild = create_tarea(
            self.company,
            self.actor,
            correlativo="L0000003",
            titulo="Nieto conservado",
            estado=Tarea.Estado.CERRADA,
        )
        branch = create_tarea(
            self.company,
            self.actor,
            correlativo="L0000004",
            titulo="Rama conservada",
        )
        TareaRelacion.objects.create(padre=root, hija=child)
        TareaRelacion.objects.create(padre=child, hija=grandchild)
        TareaRelacion.objects.create(padre=root, hija=branch)
        return root, child, grandchild, branch

    def _execute(self, **overrides):
        values = {
            "actor": self.actor,
            "empresa_id": self.company.pk,
            "root_task_id": self.root.pk,
            "motivo": "  Resguardo administrativo confirmado  ",
            "operation_id": self.operation_id,
        }
        values.update(overrides)
        return logically_delete_task_tree(**values)

    def _create_committed_audit_operation(self, actor_id):
        operation_id = uuid4()
        root_task_id = self.root.pk + 100000
        dependency_summary = {Tarea._meta.label_lower: 1}
        operation = TareaEliminacionOperacion.objects.create(
            operation_id=operation_id.hex,
            actor_id=actor_id,
            empresa_id=self.company.pk,
            root_task_id=root_task_id,
            root_correlativo="L0099999",
            backend_type="MYSQL_CONFIG",
            backend_identity="mysql:BASE_TAREAS",
            fingerprint="a" * 64,
            dependency_summary=json.dumps(dependency_summary),
            motivo="Reconciliación de auditoría",
            status=TareaEliminacionOperacion.Estado.COMMITTED,
            result_code=LOGICAL_DELETION_RESULT_CODE,
            audit_status=TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
            committed_at=timezone.now(),
        )
        TareaEliminacionElemento.objects.create(
            operacion=operation,
            tipo=Tarea._meta.label_lower,
            object_id=root_task_id,
        )
        return operation, operation_id, dependency_summary

    @patch(
        "tareas.services.logical_deletion.log_logical_deletion_operation",
        return_value=SimpleNamespace(pk=9901),
    )
    def test_marks_entire_recursive_tree_and_preserves_lifecycle_and_relations(
        self,
        audit,
    ):
        original_states = {
            task.pk: (task.estado, task.anulada)
            for task in (self.root, self.child, self.grandchild, self.branch)
        }

        result = self._execute()

        self.assertIsInstance(result, LogicalDeletionResult)
        self.assertEqual(
            result.task_ids,
            tuple(
                sorted(
                    (
                        self.root.pk,
                        self.child.pk,
                        self.grandchild.pk,
                        self.branch.pk,
                    )
                )
            ),
        )
        self.assertEqual(result.result_code, LOGICAL_DELETION_RESULT_CODE)
        self.assertEqual(result.status, TareaEliminacionOperacion.Estado.COMMITTED)
        self.assertEqual(
            result.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )
        self.assertFalse(result.replayed)
        self.assertEqual(Tarea.all_objects.count(), 4)
        self.assertEqual(TareaRelacion.objects.count(), 3)

        stored_tasks = Tarea.all_objects.filter(pk__in=result.task_ids).order_by("pk")
        for task in stored_tasks:
            self.assertTrue(task.eliminada)
            self.assertIsNotNone(task.eliminada_en)
            self.assertEqual(task.eliminada_por_id, self.actor.pk)
            self.assertEqual(task.eliminacion_operacion_id, self.operation_id)
            self.assertEqual(
                (task.estado, task.anulada),
                original_states[task.pk],
            )

        operation = TareaEliminacionOperacion.objects.get(
            operation_id=self.operation_id.hex
        )
        self.assertEqual(operation.motivo, "Resguardo administrativo confirmado")
        self.assertEqual(operation.result_code, LOGICAL_DELETION_RESULT_CODE)
        self.assertEqual(
            operation.file_cleanup_status,
            TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA,
        )
        self.assertEqual(
            json.loads(operation.dependency_summary),
            {"tareas.tarea": 4},
        )
        self.assertEqual(
            set(
                TareaEliminacionElemento.objects.filter(
                    operacion=operation
                ).values_list("object_id", flat=True)
            ),
            set(result.task_ids),
        )
        self.assertFalse(TareaEliminacionArchivo.objects.exists())
        audit.assert_called_once()

    @patch(
        "tareas.services.logical_deletion.log_logical_deletion_operation",
        return_value=SimpleNamespace(pk=9904),
    )
    def test_logically_deleted_tasks_are_hidden_from_operational_access(self, _audit):
        result = self._execute()

        self.assertFalse(
            Tarea.objects.filter(pk__in=result.task_ids).exists()
        )
        self.assertEqual(
            Tarea.all_objects.filter(pk__in=result.task_ids).count(),
            len(result.task_ids),
        )
        with self.assertRaises(TaskMutationScopeError):
            lock_orm_task_rows(
                "default",
                self.company.pk,
                (self.root.pk,),
            )
        self.root.titulo = "No debe modificarse"
        with self.assertRaises(ValidationError):
            self.root.save()

    @patch(
        "tareas.services.logical_deletion.log_logical_deletion_operation",
        return_value=SimpleNamespace(pk=9905),
    )
    def test_model_writes_cannot_bypass_logical_deletion(self, _audit):
        task = Tarea.all_objects.get(pk=self.root.pk)
        task.eliminada = True
        task.eliminada_en = task.fecha_creacion
        task.eliminada_por_id = self.actor.pk
        task.eliminacion_operacion_id = uuid4()
        with self.assertRaises(ValidationError):
            task.save()
        self.assertFalse(
            Tarea.all_objects.get(pk=self.root.pk).eliminada
        )

        self._execute()
        with self.assertRaises(ValidationError):
            TareaRelacion.objects.create(
                padre=self.root,
                hija=self.branch,
            )

    @patch(
        "tareas.services.logical_deletion.log_logical_deletion_operation",
        return_value=SimpleNamespace(pk=9902),
    )
    def test_same_operation_is_idempotent_and_does_not_duplicate_audit(self, audit):
        first = self._execute()
        second = self._execute()

        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(first.operation_id, second.operation_id)
        self.assertEqual(first.task_ids, second.task_ids)
        self.assertEqual(
            TareaEliminacionOperacion.objects.filter(
                empresa_id=self.company.pk,
                root_task_id=self.root.pk,
            ).count(),
            1,
        )
        self.assertEqual(
            TareaEliminacionElemento.objects.filter(
                operacion_id=self.operation_id.hex
            ).count(),
            4,
        )
        audit.assert_called_once()

    @patch(
        "tareas.services.logical_deletion.log_logical_deletion_operation",
        return_value=SimpleNamespace(pk=9903),
    )
    def test_changed_reason_or_operation_id_is_rejected_without_overwrite(self, _audit):
        self._execute()

        with self.assertRaises(LogicalDeletionConflict):
            self._execute(motivo="Motivo distinto")
        with self.assertRaises(LogicalDeletionConflict):
            self._execute(operation_id=uuid4())

        operation = TareaEliminacionOperacion.objects.get(
            operation_id=self.operation_id.hex
        )
        self.assertEqual(operation.motivo, "Resguardo administrativo confirmado")
        self.assertEqual(
            Tarea.all_objects.filter(
                pk__in=(self.root.pk, self.child.pk, self.grandchild.pk, self.branch.pk),
                eliminacion_operacion_id=self.operation_id,
            ).count(),
            4,
        )

    def test_empty_or_whitespace_reason_is_rejected_before_writes(self):
        for reason in (None, "", " ", " \t\r\n "):
            with self.subTest(reason=reason):
                with self.assertRaises(LogicalDeletionInvalidRequest):
                    self._execute(motivo=reason)
        self.assertFalse(Tarea.all_objects.filter(eliminada=True).exists())
        self.assertFalse(TareaEliminacionOperacion.objects.exists())

    def test_unicode_reason_is_trimmed_and_persisted(self):
        with patch(
            "tareas.services.logical_deletion.log_logical_deletion_operation",
            return_value=SimpleNamespace(pk=9904),
        ):
            result = self._execute(motivo="  Resguardo ñandú — revisión № 2  ")

        operation = TareaEliminacionOperacion.objects.get(
            operation_id=result.operation_id.hex
        )
        self.assertEqual(operation.motivo, "Resguardo ñandú — revisión № 2")

    def test_permission_is_explicit_and_does_not_bypass_staff_or_superuser(self):
        denied_users = (
            User.objects.create_user(
                username="logical-deletion-staff",
                password="test-password",
                is_staff=True,
            ),
            User.objects.create_superuser(
                username="logical-deletion-superuser",
                email="logical-deletion-superuser@example.invalid",
                password="test-password",
            ),
            create_user("logical-deletion-ingress-only"),
        )
        assign_permission(
            denied_users[2],
            self.company,
            "Tareas",
            ingresar=True,
        )

        for actor in denied_users:
            with self.subTest(actor=actor.pk):
                with self.assertRaises(LogicalDeletionAuthorizationError):
                    self._execute(actor=actor, operation_id=uuid4())
        self.assertFalse(Tarea.all_objects.filter(eliminada=True).exists())
        self.assertFalse(TareaEliminacionOperacion.objects.exists())

    def test_active_company_must_be_base_00(self):
        with self.assertRaises(LogicalDeletionCompanyError):
            self._execute(empresa_id=self.other_company.pk)
        self.assertFalse(Tarea.all_objects.filter(eliminada=True).exists())

    def test_descendant_from_another_company_blocks_the_operation(self):
        foreign_task = create_tarea(
            self.other_company,
            self.actor,
            correlativo="L0000005",
            titulo="Tarea fuera de Base 00",
        )
        TareaRelacion.objects.create(padre=self.root, hija=foreign_task)

        with self.assertRaises(LogicalDeletionHierarchyError):
            self._execute()
        self.assertFalse(Tarea.all_objects.filter(eliminada=True).exists())

    def test_non_root_and_previously_deleted_branch_are_rejected(self):
        with self.assertRaises(LogicalDeletionHierarchyError):
            self._execute(root_task_id=self.child.pk, operation_id=uuid4())

        prior_operation = uuid4()
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE tareas_tarea SET eliminada=%s, eliminada_en=%s, "
                "eliminada_por_id=%s, eliminacion_operacion_id=%s WHERE id=%s",
                (
                    True,
                    self.root.fecha_creacion,
                    self.actor.pk,
                    prior_operation.hex,
                    self.branch.pk,
                ),
            )
        with self.assertRaises(LogicalDeletionConflict):
            self._execute(operation_id=uuid4())
        self.assertFalse(
            Tarea.objects.filter(
                pk=self.root.pk,
                eliminada=True,
            ).exists()
        )

    def test_external_task_origin_reference_blocks_the_operation(self):
        create_tarea(
            self.company,
            self.actor,
            correlativo="L0000005",
            titulo="Referencia externa",
            tarea_origen=self.child,
        )

        with self.assertRaises(LogicalDeletionBlocked):
            self._execute()
        self.assertFalse(Tarea.all_objects.filter(eliminada=True).exists())
        self.assertFalse(TareaEliminacionOperacion.objects.exists())

    @patch.object(
        DjangoDeletionLedgerUnitOfWork,
        "mark_logically_deleted",
        side_effect=DeletionLedgerStateError("controlled failure"),
    )
    def test_failure_after_marking_rolls_back_tasks_and_ledger(self, _mark):
        with self.assertRaises(DeletionLedgerError):
            self._execute()

        self.assertFalse(Tarea.objects.filter(eliminada=True).exists())
        self.assertFalse(TareaEliminacionOperacion.objects.exists())
        self.assertFalse(TareaEliminacionElemento.objects.exists())
        self.assertFalse(TareaEliminacionArchivo.objects.exists())

    @patch(
        "tareas.services.logical_deletion.log_logical_deletion_operation",
        return_value=None,
    )
    def test_audit_failure_is_reported_after_committed_operation(self, _audit):
        with self.assertRaises(LogicalDeletionAuditPending) as raised:
            self._execute()

        self.assertEqual(raised.exception.operation_id, self.operation_id)
        self.assertEqual(
            Tarea.all_objects.filter(
                pk__in=(self.root.pk, self.child.pk, self.grandchild.pk, self.branch.pk),
                eliminada=True,
            ).count(),
            4,
        )
        operation = TareaEliminacionOperacion.objects.get(
            operation_id=self.operation_id.hex
        )
        self.assertEqual(
            operation.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.ERROR,
        )

    def test_reconciler_recovers_event_persisted_before_acknowledgement_loss(self):
        from tareas.services.audit import log_logical_deletion_operation

        def persist_then_lose_acknowledgement(**kwargs):
            log_logical_deletion_operation(**kwargs)
            raise RuntimeError("simulated acknowledgement loss")

        with patch(
            "tareas.services.logical_deletion.log_logical_deletion_operation",
            side_effect=persist_then_lose_acknowledgement,
        ):
            with self.assertRaises(LogicalDeletionAuditPending):
                self._execute()

        first_event = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            self.operation_id,
        )
        self.assertIsNotNone(first_event)
        self.assertEqual(first_event.meta["actor_id"], self.actor.pk)
        self.assertEqual(
            first_event.meta["operation_id"],
            self.operation_id.hex,
        )
        self.assertEqual(
            TareaEliminacionOperacion.objects.get(
                operation_id=self.operation_id.hex
            ).audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.ERROR,
        )

        result = reconcile_logical_deletion_audit(
            actor=self.actor,
            empresa_id=self.company.pk,
            operation_id=self.operation_id,
        )

        second_event = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            self.operation_id,
        )
        self.assertTrue(result.replayed)
        self.assertEqual(
            result.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )
        self.assertEqual(second_event.pk, first_event.pk)
        self.assertEqual(
            TareaEliminacionOperacion.objects.get(
                operation_id=self.operation_id.hex
            ).audit_event_id,
            first_event.pk,
        )

    def test_reconciler_creates_event_when_initial_audit_never_persisted(self):
        with patch(
            "tareas.services.logical_deletion.log_logical_deletion_operation",
            side_effect=RuntimeError("simulated failure before persist"),
        ):
            with self.assertRaises(LogicalDeletionAuditPending):
                self._execute()

        self.assertIsNone(
            AuditoriaService.get_event_by_idempotency_key(
                "tareas",
                self.operation_id,
            )
        )
        result = reconcile_logical_deletion_audit(
            actor=self.actor,
            empresa_id=self.company.pk,
            operation_id=self.operation_id,
        )

        event = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            self.operation_id,
        )
        self.assertIsNotNone(event)
        self.assertTrue(result.replayed)
        self.assertEqual(
            result.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )

    def test_reconciler_preserves_identity_when_original_actor_was_deleted(self):
        deleted_actor = create_user("logical-deletion-removed-actor")
        deleted_actor_id = deleted_actor.pk
        operation, operation_id, _ = (
            self._create_committed_audit_operation(deleted_actor_id)
        )
        deleted_actor.delete()

        result = reconcile_logical_deletion_audit(
            actor=self.actor,
            empresa_id=self.company.pk,
            operation_id=operation_id,
        )

        event = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            operation_id,
        )
        operation.refresh_from_db()
        self.assertIsNotNone(event)
        self.assertIsNone(event.user_id)
        self.assertEqual(event.meta["actor_id"], deleted_actor_id)
        self.assertEqual(event.meta["operation_id"], operation_id.hex)
        initial_payload_hash = event.idempotency_payload_hash
        self.assertEqual(len(initial_payload_hash), 64)
        self.assertTrue(result.replayed)
        self.assertEqual(
            operation.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )
        self.assertEqual(operation.audit_event_id, event.pk)

        replay = reconcile_logical_deletion_audit(
            actor=self.actor,
            empresa_id=self.company.pk,
            operation_id=operation_id,
        )
        operation.refresh_from_db()
        self.assertEqual(
            replay.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )
        self.assertEqual(operation.audit_event_id, event.pk)
        self.assertEqual(
            AuditoriaService.get_event_by_idempotency_key(
                "tareas",
                operation_id,
            ).pk,
            event.pk,
        )
        self.assertEqual(
            AuditoriaService.get_event_by_idempotency_key(
                "tareas",
                operation_id,
            ).idempotency_payload_hash,
            initial_payload_hash,
        )

    def test_reconciler_recovers_existing_event_after_actor_is_deleted(self):
        from tareas.services.audit import log_logical_deletion_operation

        deleted_actor = create_user("logical-deletion-removed-after-audit")
        deleted_actor_id = deleted_actor.pk
        operation, operation_id, dependency_summary = (
            self._create_committed_audit_operation(deleted_actor_id)
        )
        first_event = log_logical_deletion_operation(
            actor=deleted_actor,
            actor_id=deleted_actor_id,
            allow_inactive_actor=True,
            empresa_id=self.company.pk,
            task_id=operation.root_task_id,
            operation_id=operation_id.hex,
            fingerprint=operation.fingerprint,
            backend_type=operation.backend_type,
            dependency_summary=dependency_summary,
        )
        initial_payload_hash = first_event.idempotency_payload_hash
        deleted_actor.delete()

        event_after_user_delete = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            operation_id,
        )
        self.assertIsNone(event_after_user_delete.user_id)
        self.assertEqual(event_after_user_delete.meta["actor_id"], deleted_actor_id)
        self.assertEqual(
            event_after_user_delete.idempotency_payload_hash,
            initial_payload_hash,
        )

        result = reconcile_logical_deletion_audit(
            actor=self.actor,
            empresa_id=self.company.pk,
            operation_id=operation_id,
        )

        operation.refresh_from_db()
        self.assertTrue(result.replayed)
        self.assertEqual(
            operation.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )
        self.assertEqual(operation.audit_event_id, first_event.pk)
        self.assertEqual(
            AuditoriaService.get_event_by_idempotency_key(
                "tareas",
                operation_id,
            ).pk,
            first_event.pk,
        )

    def test_reconciler_accepts_inactive_actor_without_current_company_permission(self):
        original_actor = create_user("logical-deletion-moved-actor")
        assign_permission(
            original_actor,
            self.company,
            "Tareas",
            supervisor=True,
        )
        operation, operation_id, _ = (
            self._create_committed_audit_operation(original_actor.pk)
        )
        Permiso.objects.filter(
            usuario=original_actor,
            empresa=self.company,
            vista__nombre="Tareas",
        ).delete()
        assign_permission(
            original_actor,
            self.other_company,
            "Tareas",
            supervisor=True,
        )
        original_actor.is_active = False
        original_actor.save(update_fields=("is_active",))

        result = reconcile_logical_deletion_audit(
            actor=self.actor,
            empresa_id=self.company.pk,
            operation_id=operation_id,
        )

        event = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            operation_id,
        )
        operation.refresh_from_db()
        self.assertTrue(result.replayed)
        self.assertEqual(event.user_id, original_actor.pk)
        self.assertEqual(event.empresa_id, self.company.pk)
        self.assertEqual(event.meta["actor_id"], original_actor.pk)
        self.assertEqual(
            operation.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )

    def test_reconciler_keeps_audit_pending_when_actor_lookup_is_unavailable(self):
        original_actor = create_user("logical-deletion-lookup-outage")
        operation, operation_id, _ = (
            self._create_committed_audit_operation(original_actor.pk)
        )

        with patch("tareas.services.logical_deletion.get_user_model") as model:
            model.return_value._default_manager.filter.side_effect = DatabaseError(
                "temporary SYSTEM outage"
            )
            with self.assertRaises(LogicalDeletionAuditPending):
                reconcile_logical_deletion_audit(
                    actor=self.actor,
                    empresa_id=self.company.pk,
                    operation_id=operation_id,
                )

        operation.refresh_from_db()
        self.assertEqual(
            operation.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.ERROR,
        )
        self.assertEqual(operation.audit_error_code, "AUDIT_ACTOR_LOOKUP_FAILED")

        result = reconcile_logical_deletion_audit(
            actor=self.actor,
            empresa_id=self.company.pk,
            operation_id=operation_id,
        )
        self.assertEqual(
            result.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )

    def test_reconciler_rejects_a_central_key_with_conflicting_payload(self):
        with patch(
            "tareas.services.logical_deletion.log_logical_deletion_operation",
            side_effect=RuntimeError("simulated failure before persist"),
        ):
            with self.assertRaises(LogicalDeletionAuditPending):
                self._execute()

        AuditoriaService.log_event_idempotent(
            "tareas",
            idempotency_key=self.operation_id,
            user=self.actor,
            empresa_id=self.company.pk,
            action="UPDATE",
            object_type="Tarea",
            object_id=str(self.root.pk),
            method="INTERNAL",
            path="internal/unrelated-operation",
            vista_nombre="Tareas",
            meta={"operation_id": self.operation_id.hex},
        )
        with self.assertRaises(LogicalDeletionAuditConflict):
            reconcile_logical_deletion_audit(
                actor=self.actor,
                empresa_id=self.company.pk,
                operation_id=self.operation_id,
            )

        operation = TareaEliminacionOperacion.objects.get(
            operation_id=self.operation_id.hex
        )
        self.assertEqual(
            operation.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.ERROR,
        )
        self.assertEqual(
            operation.audit_error_code,
            "AUDIT_PAYLOAD_CONFLICT",
        )
        self.assertTrue(
            Tarea.all_objects.filter(
                pk__in=(self.root.pk, self.child.pk, self.grandchild.pk, self.branch.pk),
                eliminada=True,
                eliminacion_operacion_id=self.operation_id,
            ).exists()
        )

    def test_database_failure_during_authorization_is_controlled(self):
        with patch(
            "tareas.services.logical_deletion.user_has_permission_for_empresa",
            side_effect=DatabaseError("permission database unavailable"),
        ):
            with self.assertRaises(LogicalDeletionAuthorizationUnavailable):
                self._execute(operation_id=uuid4())


class MySQLLogicalDeletionAdapterTests(SimpleTestCase):
   class Cursor:
       rowcount = 2

       def __init__(self):
           self.sql = None
           self.params = None
           self.closed = False

       def execute(self, sql, params):
           self.sql = sql
           self.params = params

       def close(self):
           self.closed = True

   def test_mark_tasks_uses_company_scoped_parameterized_sql(self):
       cursor = self.Cursor()
       connection = SimpleNamespace(cursor=lambda: cursor)
       adapter = _MySQLTaskAdapter(connection, empresa_id=7)
       operation_id = uuid4()
       deleted_at = timezone.now()

       affected = adapter.mark_tasks(
           (11, 12),
           actor_id=23,
           operation_id=operation_id,
           deleted_at=deleted_at,
       )

       self.assertEqual(affected, 2)
       self.assertTrue(cursor.closed)
       self.assertIn("UPDATE `tareas_tarea` SET", cursor.sql)
       self.assertIn("`empresa_id` = %s", cursor.sql)
       self.assertIn("`eliminada` = %s", cursor.sql)
       self.assertEqual(cursor.params[:4], (True, deleted_at, 23, operation_id.hex))
       self.assertEqual(cursor.params[4:7], (7, 11, 12))
       self.assertIs(cursor.params[7], False)


class LogicalDeletionAuditReconciliationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.company = create_empresa("00", "Base 00 reconciliación")
        self.actor = create_user("logical-deletion-reconciler")
        assign_permission(
            self.actor,
            self.company,
            "Tareas",
            supervisor=True,
        )
        configure_task_storage("default")
        self.root = create_tarea(
            self.company,
            self.actor,
            correlativo="R0000001",
            titulo="Raíz de reconciliación concurrente",
        )
        self.child = create_tarea(
            self.company,
            self.actor,
            correlativo="R0000002",
            titulo="Hija de reconciliación concurrente",
        )
        TareaRelacion.objects.create(padre=self.root, hija=self.child)
        self.operation_id = uuid4()

        with patch(
            "tareas.services.logical_deletion.log_logical_deletion_operation",
            side_effect=RuntimeError("simulated audit outage"),
        ):
            with self.assertRaises(LogicalDeletionAuditPending):
                logically_delete_task_tree(
                    actor=self.actor,
                    empresa_id=self.company.pk,
                    root_task_id=self.root.pk,
                    motivo="Reconciliación concurrente",
                    operation_id=self.operation_id,
                )

    def test_two_reconcilers_do_not_duplicate_the_central_event(self):
        barrier = threading.Barrier(2)

        def reconcile():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return reconcile_logical_deletion_audit(
                    actor=self.actor,
                    empresa_id=self.company.pk,
                    operation_id=self.operation_id,
                )
            except Exception as exc:
                return exc
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: reconcile(), range(2)))

        self.assertTrue(
            all(
                isinstance(result, (LogicalDeletionResult, LogicalDeletionAuditPending))
                for result in results
            ),
            [type(result).__name__ for result in results],
        )
        event = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            self.operation_id,
        )
        self.assertIsNotNone(event)

        final_result = reconcile_logical_deletion_audit(
            actor=self.actor,
            empresa_id=self.company.pk,
            operation_id=self.operation_id,
        )
        self.assertEqual(
            final_result.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )
        operation = TareaEliminacionOperacion.objects.get(
            operation_id=self.operation_id.hex
        )
        self.assertEqual(operation.audit_event_id, event.pk)
        self.assertEqual(
            Tarea.all_objects.filter(
                pk__in=(self.root.pk, self.child.pk),
                eliminada=True,
                eliminacion_operacion_id=self.operation_id,
            ).count(),
            2,
        )

    def test_two_reconcilers_do_not_duplicate_when_original_actor_is_absent(self):
        original_actor = create_user("logical-deletion-missing-concurrent-actor")
        original_actor_id = original_actor.pk
        original_actor.delete()

        operation_id = uuid4()
        root_task_id = self.root.pk + 200000
        dependency_summary = {Tarea._meta.label_lower: 1}
        operation = TareaEliminacionOperacion.objects.create(
            operation_id=operation_id.hex,
            actor_id=original_actor_id,
            empresa_id=self.company.pk,
            root_task_id=root_task_id,
            root_correlativo="R0099999",
            backend_type="MYSQL_CONFIG",
            backend_identity="mysql:BASE_TAREAS",
            fingerprint="b" * 64,
            dependency_summary=json.dumps(dependency_summary),
            motivo="Reconciliación concurrente",
            status=TareaEliminacionOperacion.Estado.COMMITTED,
            result_code=LOGICAL_DELETION_RESULT_CODE,
            audit_status=TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
            committed_at=timezone.now(),
        )
        TareaEliminacionElemento.objects.create(
            operacion=operation,
            tipo=Tarea._meta.label_lower,
            object_id=root_task_id,
        )
        barrier = threading.Barrier(2)

        def reconcile():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return reconcile_logical_deletion_audit(
                    actor=self.actor,
                    empresa_id=self.company.pk,
                    operation_id=operation_id,
                )
            except Exception as exc:
                return exc
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: reconcile(), range(2)))

        self.assertTrue(
            all(
                isinstance(result, (LogicalDeletionResult, LogicalDeletionAuditPending))
                for result in results
            ),
            [type(result).__name__ for result in results],
        )
        event = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            operation_id,
        )
        self.assertIsNotNone(event)
        self.assertIsNone(event.user_id)
        self.assertEqual(event.meta["actor_id"], original_actor_id)
        self.assertEqual(
            AuditoriaService.get_event_by_idempotency_key(
                "tareas",
                operation_id,
            ).pk,
            event.pk,
        )

        result = reconcile_logical_deletion_audit(
            actor=self.actor,
            empresa_id=self.company.pk,
            operation_id=operation_id,
        )
        operation.refresh_from_db()
        self.assertEqual(
            result.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )
        self.assertEqual(operation.audit_event_id, event.pk)
        self.assertEqual(
            AuditoriaService.get_event_by_idempotency_key(
                "tareas",
                operation_id,
            ).idempotency_payload_hash,
            event.idempotency_payload_hash,
        )
