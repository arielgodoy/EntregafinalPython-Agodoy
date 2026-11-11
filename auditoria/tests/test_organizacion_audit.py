from unittest.mock import patch
from uuid import uuid4

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, migrations, router, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse

from auditoria.models import (
    AuditoriaBibliotecaEvent,
    AuditoriaGestionDTEEvent,
    AuditoriaOrganizacionEvent,
    AuditoriaTareasEvent,
)
from auditoria.services import AuditIdempotencyInputError, AuditoriaService
from auditoria.tests.test_admin_models import SENSITIVE_ADMIN_FIELDS


User = get_user_model()
OPERATION_ID = "5f0c8a1e9d0b4c3e8a7f6b5c4d3e2f10"


class _AbortOperation(Exception):
    pass


def organization_payload(actor, **overrides):
    values = {
        "user": actor,
        "empresa_id": 11,
        "action": "UPDATE",
        "object_type": "MembresiaDepartamental",
        "object_id": "42",
        "method": "INTERNAL",
        "path": "internal/organizacion/membresias",
        "vista_nombre": "Tareas - Maestro de departamentos",
        "message_key": "organizacion.memberships.updated",
        "meta": {"reason": "Cambio aprobado", "operation_id": OPERATION_ID, "token": "x"},
        "before": {"rol": "STAFF", "estado": "ACTIVA", "version": 1},
        "after": {"rol": "SUPERVISOR", "estado": "ACTIVA", "version": 2},
    }
    values.update(overrides)
    return values


def other_audit_counts():
    return (
        AuditoriaBibliotecaEvent.objects.count(),
        AuditoriaGestionDTEEvent.objects.count(),
        AuditoriaTareasEvent.objects.count(),
    )


def log_organization_event(actor, **overrides) -> AuditoriaOrganizacionEvent:
    event = AuditoriaService.log_event("organizacion", **organization_payload(actor, **overrides))
    assert isinstance(event, AuditoriaOrganizacionEvent)
    return event


def technical_superuser():
    return User(username="org-audit-technical", is_active=True, is_staff=True, is_superuser=True)


class OrganizationAuditServiceTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(username="org-audit-actor")

    def test_public_registry_resolves_dedicated_model_and_keeps_existing_apps(self):
        registry = AuditoriaService.APP_MODEL_MAP
        self.assertIs(registry["organizacion"], AuditoriaOrganizacionEvent)
        self.assertEqual(
            {label: model for label, model in registry.items() if label != "organizacion"},
            {
                "biblioteca": AuditoriaBibliotecaEvent,
                "gestiondte": AuditoriaGestionDTEEvent,
                "tareas": AuditoriaTareasEvent,
            },
        )
        self.assertEqual(AuditoriaOrganizacionEvent._meta.db_table, "auditoria_organizacion_event")
        field_names = {field.name for field in AuditoriaOrganizacionEvent._meta.get_fields()}
        self.assertFalse({"idempotency_key", "idempotency_payload_hash"} & field_names)

    def test_valid_event_persists_identifiable_and_sanitized_evidence(self):
        event = log_organization_event(self.actor)

        self.assertEqual(event._state.db, "default")
        stored = AuditoriaOrganizacionEvent.objects.get(pk=event.pk)
        self.assertEqual(stored.empresa_id, 11)
        self.assertEqual(stored.user, self.actor)
        self.assertEqual(stored.action, "UPDATE")
        self.assertEqual((stored.object_type, stored.object_id), ("MembresiaDepartamental", "42"))
        self.assertIsNotNone(stored.created_at)
        self.assertEqual(stored.vista_nombre, "Tareas - Maestro de departamentos")
        self.assertEqual(stored.message_key, "organizacion.memberships.updated")
        self.assertEqual(stored.meta, {"reason": "Cambio aprobado", "operation_id": OPERATION_ID})
        self.assertEqual(stored.before, {"rol": "STAFF", "estado": "ACTIVA", "version": 1})
        self.assertEqual(stored.after, {"rol": "SUPERVISOR", "estado": "ACTIVA", "version": 2})

    def test_events_are_queryable_by_company_actor_and_object(self):
        AuditoriaService.log_event("organizacion", **organization_payload(self.actor))
        AuditoriaService.log_event("organizacion", **organization_payload(self.actor, empresa_id=12))

        matches = AuditoriaOrganizacionEvent.objects.filter(
            empresa_id=11, user=self.actor, object_type="MembresiaDepartamental", object_id="42"
        )
        self.assertEqual(matches.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.filter(empresa_id=12).count(), 1)

    def test_organization_events_are_not_written_to_other_audit_tables(self):
        AuditoriaService.log_event("organizacion", **organization_payload(self.actor))

        self.assertEqual(other_audit_counts(), (0, 0, 0))
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)

    def test_existing_consumers_keep_their_own_tables(self):
        expected = (
            ("biblioteca", AuditoriaBibliotecaEvent, "/biblioteca/"),
            ("gestiondte", AuditoriaGestionDTEEvent, "/gestiondte/"),
            ("tareas", AuditoriaTareasEvent, "/tareas/"),
        )
        for app_label, model, path in expected:
            with self.subTest(app_label=app_label):
                event = AuditoriaService.log_event(
                    app_label, action="VIEW", user=self.actor, empresa_id=11, path=path
                )
                assert isinstance(event, model)
                self.assertTrue(model.objects.filter(pk=event.pk).exists())
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 0)

    def test_unknown_app_still_returns_none_without_rows(self):
        event = AuditoriaService.log_event("desconocida", action="VIEW", path="/desconocida/")

        self.assertIsNone(event)
        self.assertEqual(other_audit_counts(), (0, 0, 0))
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 0)

    def test_idempotent_api_remains_exclusive_to_tasks(self):
        with self.assertRaises(AuditIdempotencyInputError):
            AuditoriaService.log_event_idempotent(
                "organizacion", idempotency_key=uuid4(), **organization_payload(self.actor)
            )
        with self.assertRaises(AuditIdempotencyInputError):
            AuditoriaService.get_event_by_idempotency_key("organizacion", uuid4())
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 0)

        result = AuditoriaService.log_event_idempotent(
            "tareas", idempotency_key=uuid4(), action="DELETE", empresa_id=11, path="internal/tareas"
        )
        self.assertTrue(result.created)
        self.assertIsInstance(result.event, AuditoriaTareasEvent)

    def test_storage_error_keeps_public_none_contract_without_rows(self):
        with patch.object(
            AuditoriaOrganizacionEvent.objects, "create", side_effect=DatabaseError("detalle interno")
        ):
            with self.assertLogs("auditoria.services", level="ERROR") as logged:
                event = AuditoriaService.log_event("organizacion", **organization_payload(self.actor))

        self.assertIsNone(event)
        self.assertIn("app=organizacion", "\n".join(logged.output))
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 0)

    def test_router_resolves_default_connection_for_reads_and_writes(self):
        self.assertEqual(router.db_for_write(AuditoriaOrganizacionEvent), "default")
        self.assertEqual(router.db_for_read(AuditoriaOrganizacionEvent), "default")


class OrganizationAuditTransactionTests(TransactionTestCase):
    def setUp(self):
        self.actor = User.objects.create_user(username="org-audit-transaction-actor")

    def test_outer_commit_persists_event(self):
        with transaction.atomic(using="default", durable=True):
            event = log_organization_event(self.actor)
            self.assertTrue(connection.in_atomic_block)

        self.assertTrue(AuditoriaOrganizacionEvent.objects.filter(pk=event.pk).exists())

    def test_outer_rollback_discards_event(self):
        with self.assertRaises(_AbortOperation):
            with transaction.atomic(using="default", durable=True):
                event = log_organization_event(self.actor)
                self.assertTrue(AuditoriaOrganizacionEvent.objects.filter(pk=event.pk).exists())
                raise _AbortOperation

        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 0)

    def test_consumer_detects_none_and_rolls_back_previous_writes(self):
        with self.assertRaises(_AbortOperation):
            with transaction.atomic(using="default", durable=True):
                first = AuditoriaService.log_event("organizacion", **organization_payload(self.actor))
                self.assertIsNotNone(first)
                with patch.object(
                    AuditoriaOrganizacionEvent.objects, "create", side_effect=DatabaseError("falla")
                ), self.assertLogs("auditoria.services", level="ERROR"):
                    second = AuditoriaService.log_event(
                        "organizacion", **organization_payload(self.actor, object_id="43")
                    )
                if second is None:
                    raise _AbortOperation

        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 0)

    def test_real_storage_failure_marks_outer_transaction_for_rollback(self):
        with self.assertRaises(_AbortOperation):
            with transaction.atomic(using="default", durable=True):
                first = AuditoriaService.log_event("organizacion", **organization_payload(self.actor))
                self.assertIsNotNone(first)
                with self.assertLogs("auditoria.services", level="ERROR"):
                    failed = AuditoriaService.log_event(
                        "organizacion", **organization_payload(self.actor, action=None)
                    )
                self.assertIsNone(failed)
                self.assertTrue(transaction.get_rollback(using="default"))
                raise _AbortOperation

        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 0)


class OrganizationAuditAdminTests(TestCase):
    def setUp(self):
        self.model_admin = admin.site._registry[AuditoriaOrganizacionEvent]
        self.request = RequestFactory().get("/admin/")
        self.request.user = technical_superuser()

    def test_registered_without_mutation_capabilities(self):
        self.assertFalse(self.model_admin.has_add_permission(self.request))
        self.assertFalse(self.model_admin.has_change_permission(self.request))
        self.assertFalse(self.model_admin.has_delete_permission(self.request))
        self.assertIsNone(self.model_admin.actions)
        self.assertEqual(self.model_admin.get_inline_instances(self.request), [])
        self.assertEqual(
            set(self.model_admin.get_readonly_fields(self.request)),
            set(self.model_admin.get_fields(self.request)),
        )

    def test_sensitive_data_is_not_exposed(self):
        list_display = set(self.model_admin.get_list_display(self.request))
        detail_fields = set(self.model_admin.get_fields(self.request))
        self.assertTrue(list_display.isdisjoint(SENSITIVE_ADMIN_FIELDS))
        self.assertTrue(detail_fields.isdisjoint(SENSITIVE_ADMIN_FIELDS))

    def test_superuser_can_read_but_not_mutate(self):
        superuser = User.objects.create_superuser(
            username="org-audit-admin", email="org-audit-admin@example.invalid", password=None
        )
        event = log_organization_event(superuser)
        self.client.force_login(superuser)

        changelist = reverse("admin:auditoria_auditoriaorganizacionevent_changelist")
        change = reverse("admin:auditoria_auditoriaorganizacionevent_change", args=[event.pk])
        add = reverse("admin:auditoria_auditoriaorganizacionevent_add")
        delete = reverse("admin:auditoria_auditoriaorganizacionevent_delete", args=[event.pk])

        self.assertEqual(self.client.get(changelist).status_code, 200)
        self.assertEqual(self.client.get(change).status_code, 200)
        self.assertEqual(self.client.get(add).status_code, 403)
        self.assertEqual(self.client.post(change, {"action": "DELETE"}).status_code, 403)
        self.assertEqual(self.client.post(delete, {"post": "yes"}).status_code, 403)
        event.refresh_from_db()
        self.assertEqual(event.action, "UPDATE")

    def test_staff_without_view_permission_cannot_read(self):
        staff = User.objects.create_user(username="org-audit-staff", is_staff=True)
        request = RequestFactory().get("/admin/")
        request.user = staff
        self.assertFalse(self.model_admin.has_view_permission(request))


class OrganizationAuditMigrationTests(TransactionTestCase):
    previous = [("auditoria", "0014_idempotent_tareas_audit")]
    target = [("auditoria", "0015_auditoriaorganizacionevent")]

    def test_migration_is_additive_and_preserves_existing_audit_rows(self):
        executor = MigrationExecutor(connection)
        migration = executor.loader.get_migration(*self.target[0])
        self.assertEqual(executor.loader.graph.leaf_nodes("auditoria"), self.target)
        self.assertEqual(len(migration.operations), 1)
        self.assertEqual(
            [op.name for op in migration.operations if isinstance(op, migrations.CreateModel)],
            ["AuditoriaOrganizacionEvent"],
        )
        try:
            executor.migrate(self.previous)
            self.assertNotIn("auditoria_organizacion_event", connection.introspection.table_names())
            apps = executor.loader.project_state(self.previous).apps
            tareas_event = apps.get_model("auditoria", "AuditoriaTareasEvent").objects.create(
                action="VIEW", path="/tareas/", empresa_id=5
            )

            executor = MigrationExecutor(connection)
            executor.migrate(self.target)
            self.assertIn("auditoria_organizacion_event", connection.introspection.table_names())
            apps = executor.loader.project_state(self.target).apps
            self.assertTrue(
                apps.get_model("auditoria", "AuditoriaTareasEvent").objects.filter(
                    pk=tareas_event.pk, path="/tareas/"
                ).exists()
            )
            self.assertEqual(
                apps.get_model("auditoria", "AuditoriaOrganizacionEvent").objects.count(), 0
            )
        finally:
            MigrationExecutor(connection).migrate(self.target)
