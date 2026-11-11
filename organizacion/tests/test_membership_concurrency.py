from dataclasses import dataclass
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DEFAULT_DB_ALIAS, close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from access_control.models import Empresa, PerfilAcceso, Permiso, UsuarioPerfilEmpresa, Vista
from auditoria.models import AuditoriaOrganizacionEvent
from auditoria.services import AuditoriaService
from organizacion.models import (
    ControlOrganizacionEmpresa,
    Departamento,
    EventoMembresia,
    MembresiaDepartamental,
    OrganizationalSource,
)
from organizacion.services.coordination import (
    OrganizationCoordinationUnavailableError,
    is_sqlite_busy_locked_error,
    organization_guard,
)
from organizacion.services.memberships import (
    MembershipCommand,
    MembershipCommandResult,
    MembershipConflict,
    MembershipOperation,
    MembershipPermissionDenied,
    OrganizationUnavailableError,
    change_membership,
)


User = get_user_model()
MASTER_VIEW = "Tareas - Maestro de departamentos"


@dataclass(frozen=True)
class WorkerOutcome:
    result: MembershipCommandResult | None
    error: Exception | None
    connection_id: int


class MembershipConcurrencyTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        database = connections[DEFAULT_DB_ALIAS]
        name = database.settings_dict["NAME"]
        if database.vendor != "sqlite":
            raise unittest.SkipTest("T177 concurrency certification is SQLite-only")
        if not isinstance(name, str) or name == ":memory:" or "mode=memory" in name:
            raise unittest.SkipTest(
                "T177 concurrency tests require an isolated file-backed SQLite test database"
            )
        resolved_name = os.path.abspath(name)
        resolved_temp = os.path.abspath(tempfile.gettempdir())
        if os.path.commonpath((resolved_name, resolved_temp)) != resolved_temp:
            raise unittest.SkipTest("T177 SQLite test database must be under the system temp directory")
        if not os.path.isfile(resolved_name):
            raise unittest.SkipTest("T177 file-backed SQLite test database is not present")

    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="91", descripcion="Empresa concurrente A")
        self.otra_empresa = Empresa.objects.create(codigo="92", descripcion="Empresa concurrente B")
        self.departamento = self._department(self.empresa, "C1")
        self.otro_departamento = self._department(self.empresa, "C2")
        self.departamento_otra_empresa = self._department(self.otra_empresa, "C3")

        self.actor = User.objects.create_user(username="t177-actor-a", password="test")
        self.actor_otra_empresa = User.objects.create_user(
            username="t177-actor-b", password="test"
        )
        self.usuario = User.objects.create_user(username="t177-user-a", password="test")
        self.segundo_usuario = User.objects.create_user(
            username="t177-user-b", password="test"
        )
        self.tercer_usuario = User.objects.create_user(
            username="t177-user-c", password="test"
        )
        self.usuario_otra_empresa = User.objects.create_user(
            username="t177-user-other", password="test"
        )

        for user in (self.actor, self.usuario, self.segundo_usuario, self.tercer_usuario):
            self._grant_company(user, self.empresa)
        for user in (self.actor_otra_empresa, self.usuario_otra_empresa):
            self._grant_company(user, self.otra_empresa)

        vista = Vista.objects.create(nombre=MASTER_VIEW)
        self._grant_actions(self.actor, self.empresa, vista)
        self._grant_actions(self.actor_otra_empresa, self.otra_empresa, vista)

    @staticmethod
    def _department(company, code):
        return Departamento.objects.create(
            empresa=company,
            codigo=code,
            nombre=f"Departamento {code}",
            source=OrganizationalSource.LOCAL,
        )

    @staticmethod
    def _grant_company(user, company):
        profile = PerfilAcceso.objects.create(
            nombre=f"T177 {company.codigo} user {user.pk}"
        )
        UsuarioPerfilEmpresa.objects.create(
            usuario=user,
            empresa=company,
            perfil=profile,
            asignado_por=user,
        )

    @staticmethod
    def _grant_actions(user, company, vista):
        Permiso.objects.create(
            usuario=user,
            empresa=company,
            vista=vista,
            crear=True,
            modificar=True,
            eliminar=True,
            ingresar=True,
        )

    def command(
        self,
        *,
        user=None,
        department=None,
        company=None,
        actor=None,
        operation_id=None,
        reason="Alta concurrente",
        role="STAFF",
        action=MembershipOperation.CREATE,
        expected_membership_version=None,
        expected_organization_revision=None,
    ):
        company = company or self.empresa
        return MembershipCommand(
            company_id=company.pk,
            actor_id=(actor or self.actor).pk,
            user_id=(user or self.usuario).pk,
            department_id=(department or self.departamento).pk,
            operation_id=operation_id or uuid4(),
            action=action,
            reason=reason,
            target_role=role,
            expected_membership_version=expected_membership_version,
            expected_organization_revision=expected_organization_revision,
        )

    @staticmethod
    def _worker(command, *, barrier=None, busy_timeout_ms=None):
        close_old_connections()
        database = connections[DEFAULT_DB_ALIAS]
        database.ensure_connection()
        connection_id = id(database.connection)
        if busy_timeout_ms is not None:
            with database.cursor() as cursor:
                cursor.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        try:
            if barrier is not None:
                barrier.wait(timeout=10)
            return WorkerOutcome(change_membership(command), None, connection_id)
        except (MembershipConflict, MembershipPermissionDenied, OrganizationUnavailableError) as exc:
            return WorkerOutcome(None, exc, connection_id)
        finally:
            close_old_connections()

    def _run_pair(self, first, second) -> tuple[WorkerOutcome, WorkerOutcome]:
        barrier = Barrier(3)
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(self._worker, first, barrier=barrier)
            two = pool.submit(self._worker, second, barrier=barrier)
            barrier.wait(timeout=10)
            results = (one.result(timeout=15), two.result(timeout=15))
        self.assertEqual(len({result.connection_id for result in results}), 2)
        return results

    def _success_result(self, outcome: WorkerOutcome) -> MembershipCommandResult:
        self.assertIsNone(outcome.error)
        assert outcome.result is not None
        return outcome.result

    def test_writer_guard_executes_update_before_business_reads_even_without_control_row(self):
        self.assertFalse(ControlOrganizacionEmpresa.objects.filter(empresa=self.empresa).exists())
        with CaptureQueriesContext(connection) as captured:
            with organization_guard(company_id=self.empresa.pk):
                self.assertFalse(
                    ControlOrganizacionEmpresa.objects.filter(empresa=self.empresa).exists()
                )

        statements = [
            item["sql"].strip().upper()
            for item in captured.captured_queries
            if item["sql"].strip()
        ]
        business_statements = [
            statement
            for statement in statements
            if not statement.startswith(("BEGIN", "COMMIT", "SAVEPOINT", "RELEASE"))
        ]
        self.assertTrue(business_statements[0].startswith("UPDATE"))
        self.assertTrue(any(statement.startswith("SELECT") for statement in business_statements[1:]))
        self.assertFalse(ControlOrganizacionEmpresa.objects.filter(empresa=self.empresa).exists())

    def test_only_sqlite_busy_and_locked_codes_are_classified_as_contention(self):
        class SQLiteFailure(Exception):
            def __init__(self, code):
                super().__init__("not parsed from the text")
                self.sqlite_errorcode = code

        self.assertTrue(is_sqlite_busy_locked_error(SQLiteFailure(5)))
        self.assertTrue(is_sqlite_busy_locked_error(SQLiteFailure(6)))
        self.assertFalse(is_sqlite_busy_locked_error(SQLiteFailure(10)))
        self.assertFalse(is_sqlite_busy_locked_error(RuntimeError("database is locked")))

    def test_unverified_default_backend_fails_closed(self):
        fake_connection = SimpleNamespace(vendor="postgresql")
        with patch(
            "organizacion.services.coordination.connections",
            {"default": fake_connection},
        ):
            with self.assertRaises(OrganizationCoordinationUnavailableError):
                with organization_guard(company_id=self.empresa.pk):
                    self.fail("unsupported backend must not enter the guarded body")

    def test_command_refuses_to_start_inside_an_outer_transaction(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic(using=DEFAULT_DB_ALIAS):
                change_membership(self.command())

        self.assertFalse(MembresiaDepartamental.objects.exists())
        self.assertFalse(EventoMembresia.objects.exists())
        self.assertFalse(ControlOrganizacionEmpresa.objects.exists())
        self.assertFalse(AuditoriaOrganizacionEvent.objects.exists())

    def test_simultaneous_same_uuid_replays_once_and_initializes_one_control(self):
        command = self.command()
        first, second = self._run_pair(command, command)

        results = (self._success_result(first), self._success_result(second))
        self.assertEqual({result.membership_id for result in results}, {results[0].membership_id})
        self.assertEqual({result.event_id for result in results}, {results[0].event_id})
        self.assertEqual({result.organization_revision for result in results}, {2})
        self.assertEqual(sum(result.replayed for result in results), 1)
        self.assertEqual(MembresiaDepartamental.objects.count(), 1)
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)
        self.assertEqual(ControlOrganizacionEmpresa.objects.get(empresa=self.empresa).version, 2)

    def test_distinct_uuids_for_same_membership_create_only_one_row(self):
        first_command = self.command(operation_id=uuid4())
        second_command = self.command(operation_id=uuid4())
        results = self._run_pair(first_command, second_command)

        self.assertEqual(sum(result.error is None for result in results), 1)
        self.assertEqual(sum(isinstance(result.error, MembershipConflict) for result in results), 1)
        self.assertEqual(MembresiaDepartamental.objects.count(), 1)
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 2)

    def test_different_commands_at_same_revision_serialize_first_control_creation(self):
        first_command = self.command(user=self.usuario, department=self.departamento)
        second_command = self.command(
            user=self.segundo_usuario,
            department=self.otro_departamento,
            operation_id=uuid4(),
        )
        results = self._run_pair(first_command, second_command)

        self.assertEqual(sum(result.error is None for result in results), 1)
        self.assertEqual(sum(isinstance(result.error, MembershipConflict) for result in results), 1)
        self.assertEqual(MembresiaDepartamental.objects.count(), 1)
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)
        self.assertEqual(ControlOrganizacionEmpresa.objects.count(), 1)
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 2)

    def test_same_company_different_departments_do_not_lose_revision(self):
        first_command = self.command(user=self.usuario, department=self.departamento)
        second_command = self.command(
            user=self.segundo_usuario,
            department=self.otro_departamento,
            operation_id=uuid4(),
        )
        results = self._run_pair(first_command, second_command)

        self.assertEqual(sum(result.error is None for result in results), 1)
        self.assertEqual(sum(isinstance(result.error, MembershipConflict) for result in results), 1)
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 2)
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)

    def test_two_companies_serialize_globally_but_keep_independent_revisions(self):
        first_command = self.command(
            user=self.usuario,
            department=self.departamento,
            company=self.empresa,
            actor=self.actor,
        )
        second_command = self.command(
            user=self.usuario_otra_empresa,
            department=self.departamento_otra_empresa,
            company=self.otra_empresa,
            actor=self.actor_otra_empresa,
        )
        results = self._run_pair(first_command, second_command)

        success_results = tuple(self._success_result(result) for result in results)
        self.assertEqual({result.organization_revision for result in success_results}, {2})
        self.assertEqual(
            set(ControlOrganizacionEmpresa.objects.order_by("empresa_id").values_list(
                "empresa_id", "version"
            )),
            {(self.empresa.pk, 2), (self.otra_empresa.pk, 2)},
        )
        self.assertEqual(MembresiaDepartamental.objects.count(), 2)
        self.assertEqual(EventoMembresia.objects.count(), 2)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 2)

    def test_same_uuid_different_payload_has_one_winner_and_one_conflict(self):
        operation_id = uuid4()
        first_command = self.command(operation_id=operation_id, reason="Payload A")
        second_command = self.command(operation_id=operation_id, reason="Payload B")
        results = self._run_pair(first_command, second_command)

        self.assertEqual(sum(result.error is None for result in results), 1)
        self.assertEqual(sum(isinstance(result.error, MembershipConflict) for result in results), 1)
        self.assertEqual(MembresiaDepartamental.objects.count(), 1)
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 2)

    def test_two_concurrent_jefe_assignments_leave_at_most_one_active_head(self):
        first_command = self.command(
            user=self.usuario,
            role="JEFE",
        )
        second_command = self.command(
            user=self.segundo_usuario,
            role="JEFE",
            operation_id=uuid4(),
        )
        results = self._run_pair(first_command, second_command)

        self.assertEqual(sum(result.error is None for result in results), 1)
        self.assertEqual(
            MembresiaDepartamental.objects.filter(
                departamento=self.departamento,
                rol="JEFE",
                estado="ACTIVA",
            ).count(),
            1,
        )
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 2)

    def test_sqlite_writer_contention_is_global_and_same_command_recovers(self):
        command = self.command(
            user=self.usuario_otra_empresa,
            department=self.departamento_otra_empresa,
            company=self.otra_empresa,
            actor=self.actor_otra_empresa,
        )
        main_database = connections[DEFAULT_DB_ALIAS]
        main_database.ensure_connection()
        main_connection_id = id(main_database.connection)
        with organization_guard(company_id=self.empresa.pk):
            with ThreadPoolExecutor(max_workers=1) as pool:
                outcome = pool.submit(
                    self._worker,
                    command,
                    busy_timeout_ms=100,
                ).result(timeout=5)

            self.assertNotEqual(outcome.connection_id, main_connection_id)
            self.assertIsNone(outcome.result)
            self.assertIsInstance(outcome.error, OrganizationUnavailableError)
            assert outcome.error is not None
            self.assertIn("sqlite_writer_busy", str(outcome.error))
            self.assertFalse(MembresiaDepartamental.objects.exists())
            self.assertFalse(EventoMembresia.objects.exists())
            self.assertFalse(ControlOrganizacionEmpresa.objects.exists())
            self.assertFalse(AuditoriaOrganizacionEvent.objects.exists())

        recovered = change_membership(command)
        self.assertFalse(recovered.replayed)
        self.assertEqual(MembresiaDepartamental.objects.count(), 1)
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)
        self.assertEqual(
            ControlOrganizacionEmpresa.objects.get(empresa=self.otra_empresa).version,
            2,
        )

    def test_concurrent_audit_failure_rolls_back_before_the_next_writer_commits(self):
        failed_command = self.command(reason="Falla central controlada")
        succeeding_command = self.command(
            user=self.segundo_usuario,
            department=self.otro_departamento,
            operation_id=uuid4(),
            reason="Alta posterior al rollback",
        )
        audit_reached = Event()
        allow_audit_return = Event()
        real_log_event = AuditoriaService.log_event

        def audit_side_effect(app_label, **event_data):
            if event_data["meta"]["operation_id"] == str(failed_command.operation_id):
                audit_reached.set()
                if not allow_audit_return.wait(timeout=5):
                    raise TimeoutError("test synchronization timed out")
                return None
            return real_log_event(app_label, **event_data)

        with patch.object(AuditoriaService, "log_event", side_effect=audit_side_effect):
            with ThreadPoolExecutor(max_workers=2) as pool:
                failed_future = pool.submit(self._worker, failed_command)
                self.assertTrue(audit_reached.wait(timeout=5))
                succeeding_future = pool.submit(self._worker, succeeding_command)
                allow_audit_return.set()
                failed = failed_future.result(timeout=10)
                succeeding = succeeding_future.result(timeout=10)

        self.assertNotEqual(failed.connection_id, succeeding.connection_id)
        self.assertIsNone(failed.result)
        self.assertIsInstance(failed.error, OrganizationUnavailableError)
        self._success_result(succeeding)
        self.assertEqual(MembresiaDepartamental.objects.count(), 1)
        self.assertEqual(MembresiaDepartamental.objects.get().usuario_id, self.segundo_usuario.pk)
        self.assertEqual(EventoMembresia.objects.count(), 1)
        self.assertEqual(AuditoriaOrganizacionEvent.objects.count(), 1)
        self.assertEqual(ControlOrganizacionEmpresa.objects.get().version, 2)
