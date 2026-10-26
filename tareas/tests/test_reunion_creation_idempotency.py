from datetime import timedelta
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import (
    SimpleTestCase,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from django.utils import timezone

from access_control.models import Empresa
from tareas.models import (
    EvaluacionSimilitud,
    ReunionCreationRequest,
    ReunionRevision,
    Tarea,
)
from tareas.services.connection_roles import BackendContext
from tareas.services.reunion_creation_idempotency import (
    REVIEW_FINGERPRINT_SALT,
    ReunionCreationRequestConflict,
    ReunionCreationRequestExpired,
    ReunionCreationRequestNotFound,
    ReunionCreationRequestOutcomeUnknown,
    ReunionCreationRequestStateError,
    ReunionCreationRequestUnauthorized,
    ReunionCreationResult,
    cancel_creation_request,
    create_review_request,
    execute_idempotent_creation,
    expire_creation_request,
    fingerprint_matches,
    fingerprint_payload,
    get_completed_result,
    get_creation_request,
    new_creation_request_id,
    new_request_expiration,
    record_audit_delivery,
    refresh_review_request,
)
from tareas.tests.factories import assign_permission
from tareas.services.reunion_creation_idempotency_storage import (
    CreationRequestRecord,
    DjangoReunionCreationRequestStorage,
    MySQLReunionCreationRequestStorage,
    MySQLReunionCreationRequestUnit,
    ReunionCreationRequestStorageError,
    resolve_reunion_creation_request_storage,
)


class ReunionCreationIdempotencyServiceTests(TestCase):
    def setUp(self):
        self.storage_patch = patch(
            "tareas.services.reunion_creation_idempotency."
            "resolve_reunion_creation_request_storage",
            return_value=DjangoReunionCreationRequestStorage("default"),
        )
        self.storage_patch.start()
        self.addCleanup(self.storage_patch.stop)
        self.empresa = Empresa.objects.create(
            codigo=f"RI{uuid4().hex[:6].upper()}",
            descripcion="Reunion idempotency tests",
        )
        self.actor = User.objects.create_user(
            username=f"reunion-idempotency-{uuid4().hex}"
        )
        assign_permission(
            self.actor,
            self.empresa,
            "Tareas",
            crear=True,
        )
        self.request_id = new_creation_request_id()
        self.empresa_id = self.empresa.pk
        self.actor_id = self.actor.pk
        self.payload_hash = fingerprint_payload(
            {
                "title": "Reunión sintética",
                "scope": {"type": "LOCAL", "id": 17},
            }
        )
        self.review_fingerprint = fingerprint_payload(
            {"threshold": "80.00", "candidates": []},
            purpose=REVIEW_FINGERPRINT_SALT,
        )
        self.expires_at = new_request_expiration()

    def _create_review(self, **changes):
        values = {
            "request_id": self.request_id,
            "empresa_id": self.empresa_id,
            "actor_id": self.actor_id,
            "payload_hash": self.payload_hash,
            "review_fingerprint": self.review_fingerprint,
            "expires_at": self.expires_at,
        }
        values.update(changes)
        return create_review_request(**values)

    def _execute(self, callback, **changes):
        values = {
            "request_id": self.request_id,
            "empresa_id": self.empresa_id,
            "actor_id": self.actor_id,
            "payload_hash": self.payload_hash,
            "review_fingerprint": self.review_fingerprint,
            "expires_at": self.expires_at,
            "create_callback": callback,
            "confirmation_validated": True,
        }
        values.update(changes)
        return execute_idempotent_creation(**values)

    def test_review_request_persists_technical_metadata_only(self):
        record = self._create_review()

        self.assertEqual(record.status, ReunionCreationRequest.Estado.REVISION_PENDIENTE)
        self.assertIsNone(record.task_id)
        self.assertIsNone(record.meeting_id)
        self.assertIsNone(record.completed_at)
        self.assertEqual(ReunionCreationRequest.objects.count(), 1)
        self.assertFalse(Tarea.objects.exists())
        self.assertFalse(ReunionRevision.objects.exists())
        self.assertFalse(EvaluacionSimilitud.objects.exists())

    def test_same_review_request_replays_without_overwriting_it(self):
        original = self._create_review()
        replay = self._create_review()

        self.assertEqual(replay.request_id, original.request_id)
        self.assertEqual(replay.created_at, original.created_at)
        self.assertEqual(ReunionCreationRequest.objects.count(), 1)

    def test_same_request_id_with_different_actor_company_or_payload_conflicts(self):
        self._create_review()

        for changes in (
            {"actor_id": self.actor_id + 1},
            {"empresa_id": self.empresa_id + 1},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ReunionCreationRequestUnauthorized):
                    self._create_review(**changes)
        with self.assertRaises(ReunionCreationRequestConflict):
            self._create_review(payload_hash="a" * 64)

    def test_actor_without_create_permission_cannot_reserve_request(self):
        unauthorized = User.objects.create_user(
            username=f"reunion-no-create-{uuid4().hex}"
        )
        assign_permission(
            unauthorized,
            self.empresa,
            "Tareas",
            ingresar=True,
        )

        with self.assertRaises(ReunionCreationRequestUnauthorized):
            create_review_request(
                request_id=self.request_id,
                empresa_id=self.empresa_id,
                actor_id=unauthorized.pk,
                payload_hash=self.payload_hash,
                review_fingerprint=self.review_fingerprint,
                expires_at=self.expires_at,
            )

        self.assertFalse(ReunionCreationRequest.objects.exists())

    def test_review_fingerprint_can_refresh_only_while_pending(self):
        self._create_review()
        refreshed_fingerprint = fingerprint_payload(
            {"threshold": "75.00", "candidates": []},
            purpose=REVIEW_FINGERPRINT_SALT,
        )
        refreshed = refresh_review_request(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
            payload_hash=self.payload_hash,
            review_fingerprint=refreshed_fingerprint,
            expires_at=new_request_expiration(),
        )

        self.assertEqual(refreshed.review_fingerprint, refreshed_fingerprint)
        with self.assertRaises(ReunionCreationRequestConflict):
            self._execute(
                lambda _unit: (101, 202),
                review_fingerprint=self.review_fingerprint,
            )

    def test_review_confirmation_cannot_create_without_reserved_review(self):
        with self.assertRaises(ReunionCreationRequestNotFound):
            self._execute(lambda _unit: (101, 202))
        self.assertFalse(ReunionCreationRequest.objects.exists())
        self.assertFalse(Tarea.objects.exists())
        self.assertFalse(ReunionRevision.objects.exists())

    def test_initial_no_review_creation_is_idempotent(self):
        self._create_review()
        calls = []

        def callback(unit):
            self.assertTrue(connections["default"].in_atomic_block)
            calls.append(unit)
            return 111, 222

        first = execute_idempotent_creation(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
            payload_hash=self.payload_hash,
            review_fingerprint=self.review_fingerprint,
            expires_at=self.expires_at,
            create_callback=callback,
            confirmation_validated=True,
        )
        replay = execute_idempotent_creation(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
            payload_hash=self.payload_hash,
            review_fingerprint=self.review_fingerprint,
            expires_at=self.expires_at,
            create_callback=callback,
            confirmation_validated=True,
        )

        self.assertEqual((first.task_id, first.meeting_id), (111, 222))
        self.assertFalse(first.replayed)
        self.assertEqual((replay.task_id, replay.meeting_id), (111, 222))
        self.assertTrue(replay.replayed)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            ReunionCreationRequest.objects.get().status,
            ReunionCreationRequest.Estado.COMPLETADA,
        )

    def test_confirmed_review_completes_and_duplicate_does_not_call_callback(self):
        self._create_review()
        calls = []

        def callback(unit):
            self.assertTrue(connections["default"].in_atomic_block)
            calls.append(unit)
            return 123, 456

        completed = self._execute(callback)
        replay = self._execute(callback)

        self.assertEqual((completed.task_id, completed.meeting_id), (123, 456))
        self.assertFalse(completed.replayed)
        self.assertEqual((replay.task_id, replay.meeting_id), (123, 456))
        self.assertTrue(replay.replayed)
        self.assertEqual(len(calls), 1)
        stored = ReunionCreationRequest.objects.get(request_id=self.request_id)
        self.assertEqual(stored.status, ReunionCreationRequest.Estado.COMPLETADA)
        self.assertIsNotNone(stored.completed_at)
        self.assertFalse(Tarea.objects.exists())
        self.assertFalse(ReunionRevision.objects.exists())
        self.assertFalse(EvaluacionSimilitud.objects.exists())

    def test_callback_failure_rolls_back_to_review_pending(self):
        self._create_review()

        def callback(_unit):
            raise RuntimeError("controlled pre-commit failure")

        with self.assertRaisesRegex(RuntimeError, "controlled pre-commit"):
            self._execute(callback)

        stored = ReunionCreationRequest.objects.get(request_id=self.request_id)
        self.assertEqual(stored.status, ReunionCreationRequest.Estado.REVISION_PENDIENTE)
        self.assertIsNone(stored.task_id)
        self.assertIsNone(stored.meeting_id)
        self.assertIsNone(stored.completed_at)

    def test_invalid_callback_result_rolls_back(self):
        self._create_review()
        with self.assertRaises(ValueError):
            execute_idempotent_creation(
                request_id=self.request_id,
                empresa_id=self.empresa_id,
                actor_id=self.actor_id,
                payload_hash=self.payload_hash,
                review_fingerprint=self.review_fingerprint,
                expires_at=self.expires_at,
                create_callback=lambda _unit: (100, None),
                confirmation_validated=True,
            )

        request = ReunionCreationRequest.objects.get(request_id=self.request_id)
        self.assertEqual(
            request.status,
            ReunionCreationRequest.Estado.REVISION_PENDIENTE,
        )
        self.assertIsNone(request.task_id)
        self.assertIsNone(request.meeting_id)

    def test_cancelled_request_cannot_be_completed(self):
        self._create_review()
        cancelled = cancel_creation_request(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
        )

        self.assertEqual(cancelled.status, ReunionCreationRequest.Estado.CANCELADA)
        self.assertIsNone(cancelled.task_id)
        self.assertIsNone(cancelled.meeting_id)
        with self.assertRaises(ReunionCreationRequestStateError):
            self._execute(lambda _unit: (101, 202))

    def test_cancel_is_idempotent_and_cannot_cancel_completed_request(self):
        self._create_review()
        first_cancel = cancel_creation_request(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
        )
        second_cancel = cancel_creation_request(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
        )
        self.assertEqual(first_cancel.status, second_cancel.status)

        completed_id = uuid4()
        create_review_request(
            request_id=completed_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
            payload_hash=self.payload_hash,
            review_fingerprint=self.review_fingerprint,
            expires_at=self.expires_at,
        )
        execute_idempotent_creation(
            request_id=completed_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
            payload_hash=self.payload_hash,
            review_fingerprint=self.review_fingerprint,
            expires_at=self.expires_at,
            create_callback=lambda _unit: (333, 444),
            confirmation_validated=True,
        )
        with self.assertRaises(ReunionCreationRequestStateError):
            cancel_creation_request(
                request_id=completed_id,
                empresa_id=self.empresa_id,
                actor_id=self.actor_id,
            )

    def test_expired_request_is_marked_and_cannot_be_completed(self):
        self._create_review()
        expired = expire_creation_request(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
            now=self.expires_at + timedelta(seconds=1),
        )

        self.assertEqual(expired.status, ReunionCreationRequest.Estado.EXPIRADA)
        with self.assertRaises(ReunionCreationRequestExpired):
            self._execute(lambda _unit: (101, 202))

    def test_expiration_cannot_be_applied_before_deadline(self):
        self._create_review()
        with self.assertRaises(ReunionCreationRequestStateError):
            expire_creation_request(
                request_id=self.request_id,
                empresa_id=self.empresa_id,
                actor_id=self.actor_id,
                now=timezone.now(),
            )

    def test_result_lookup_is_scoped_to_company_and_actor(self):
        self._create_review()
        self._execute(lambda _unit: (101, 202))
        result = get_completed_result(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
        )

        self.assertEqual((result.task_id, result.meeting_id), (101, 202))
        with self.assertRaises(ReunionCreationRequestUnauthorized):
            get_completed_result(
                request_id=self.request_id,
                empresa_id=self.empresa_id + 1,
                actor_id=self.actor_id,
            )
        with self.assertRaises(ReunionCreationRequestUnauthorized):
            get_completed_result(
                request_id=self.request_id,
                empresa_id=self.empresa_id,
                actor_id=self.actor_id + 1,
            )

    def test_audit_delivery_metadata_updates_only_terminal_requests(self):
        self._create_review()
        self._execute(lambda _unit: (101, 202))
        updated = record_audit_delivery(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
            audit_status=ReunionCreationRequest.EstadoAuditoria.CONFIRMADA,
            audit_event_id=987,
        )

        self.assertEqual(
            updated.audit_status,
            ReunionCreationRequest.EstadoAuditoria.CONFIRMADA,
        )
        self.assertEqual(updated.audit_event_id, 987)
        replay = record_audit_delivery(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
            audit_status=ReunionCreationRequest.EstadoAuditoria.CONFIRMADA,
            audit_event_id=987,
        )
        self.assertEqual(replay.audit_event_id, 987)

    def test_fingerprint_is_canonical_and_payload_is_not_stored(self):
        left = fingerprint_payload({"title": "Test", "schedule": {"hour": 9}})
        right = fingerprint_payload({"schedule": {"hour": 9}, "title": "Test"})
        changed = fingerprint_payload({"title": "Test 2", "schedule": {"hour": 9}})

        self.assertEqual(left, right)
        self.assertNotEqual(left, changed)
        self.assertTrue(
            fingerprint_matches(
                {"title": "Test", "schedule": {"hour": 9}},
                left,
                purpose="tareas.reunion_creation.payload.v1",
            )
        )
        record = self._create_review(payload_hash=left)
        self.assertFalse(hasattr(record, "payload"))

    @override_settings(
        SECRET_KEY="rotated-key",
        SECRET_KEY_FALLBACKS=["previous-key"],
    )
    def test_fingerprint_verifies_using_configured_secret_fallback(self):
        with override_settings(SECRET_KEY="previous-key", SECRET_KEY_FALLBACKS=[]):
            old_hash = fingerprint_payload({"title": "Reunión"})

        self.assertTrue(
            fingerprint_matches(
                {"title": "Reunión"},
                old_hash,
                purpose="tareas.reunion_creation.payload.v1",
            )
        )


class ReunionCreationIdempotencyMySQLUnitTests(SimpleTestCase):
    def test_completed_model_requires_both_result_ids_and_completion_time(self):
        record = ReunionCreationRequest(
            request_id=uuid4(),
            empresa_id=12,
            actor_id=34,
            payload_hash="a" * 64,
            review_fingerprint="b" * 64,
            status=ReunionCreationRequest.Estado.COMPLETADA,
            expires_at=timezone.now() + timedelta(minutes=15),
            audit_status=ReunionCreationRequest.EstadoAuditoria.NO_ENCOLADA,
        )

        with self.assertRaises(ValidationError):
            record.full_clean(
                validate_unique=False,
                validate_constraints=False,
            )

    def test_mysql_reservation_uses_unique_request_key_and_parameterized_values(self):
        now = timezone.now()
        request_id = uuid4()
        record = CreationRequestRecord(
            request_id=request_id,
            empresa_id=12,
            actor_id=34,
            payload_hash="a" * 64,
            review_fingerprint="b" * 64,
            status=ReunionCreationRequest.Estado.REVISION_PENDIENTE,
            expires_at=now + timedelta(minutes=15),
            task_id=None,
            meeting_id=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
            audit_status=ReunionCreationRequest.EstadoAuditoria.NO_ENCOLADA,
            audit_event_id=None,
            audit_error_code="",
        )
        cursor = MagicMock()
        cursor.fetchone.return_value = (
            request_id.hex,
            12,
            34,
            "a" * 64,
            "b" * 64,
            ReunionCreationRequest.Estado.REVISION_PENDIENTE,
            now,
            None,
            None,
            now,
            now,
            None,
            ReunionCreationRequest.EstadoAuditoria.NO_ENCOLADA,
            None,
            "",
        )
        unit = MySQLReunionCreationRequestUnit(object(), cursor)

        persisted = unit.insert_or_get_request(record)

        insert_sql, insert_params = cursor.execute.call_args_list[0].args
        select_sql = cursor.execute.call_args_list[1].args[0]
        self.assertIn("ON DUPLICATE KEY UPDATE", insert_sql)
        self.assertNotIn("PRIMARY KEY", insert_sql)
        self.assertIn("FOR UPDATE", select_sql)
        self.assertEqual(insert_params[0], request_id.hex)
        self.assertNotIn("a" * 64, insert_sql)
        self.assertEqual(persisted.request_id, request_id)

    def test_mysql_transition_is_scoped_by_request_and_expected_state(self):
        cursor = MagicMock()
        cursor.rowcount = 1
        unit = MySQLReunionCreationRequestUnit(object(), cursor)
        request_id = uuid4()

        changed = unit.transition_request(
            request_id,
            expected_status=ReunionCreationRequest.Estado.REVISION_PENDIENTE,
            values={
                "status": ReunionCreationRequest.Estado.CANCELADA,
            },
        )

        sql, params = cursor.execute.call_args.args
        self.assertTrue(changed)
        self.assertIn("WHERE `request_id`=%s AND `status`=%s", sql)
        self.assertEqual(params[-2:], (request_id.hex, "REVIEW_PENDING"))
        self.assertNotIn("task_id", sql)


class ReunionCreationIdempotencyResolverTests(SimpleTestCase):
    @patch(
        "tareas.services.reunion_creation_idempotency_storage."
        "resolve_operational_backend"
    )
    def test_resolver_returns_django_storage_for_configured_alias(self, resolver):
        resolver.return_value = BackendContext(
            logical_role="BASE_TAREAS",
            backend_type="DJANGO",
            django_alias="default",
        )

        self.assertIsInstance(
            resolve_reunion_creation_request_storage(),
            DjangoReunionCreationRequestStorage,
        )

    @patch(
        "tareas.services.reunion_creation_idempotency_storage."
        "resolve_operational_backend"
    )
    def test_resolver_returns_mysql_storage_for_tareas_database(self, resolver):
        mysql_connection = object()
        resolver.return_value = BackendContext(
            logical_role="BASE_TAREAS",
            backend_type="MYSQL_CONFIG",
            mysql_connection=mysql_connection,
            database_name="tareas",
        )

        storage = resolve_reunion_creation_request_storage()

        self.assertIsInstance(storage, MySQLReunionCreationRequestStorage)
        self.assertIs(storage.connection_config, mysql_connection)
        self.assertEqual(storage.database_name, "tareas")

    @patch(
        "tareas.services.reunion_creation_idempotency_storage."
        "resolve_operational_backend"
    )
    def test_resolver_fails_closed_for_wrong_mysql_database(self, resolver):
        resolver.return_value = BackendContext(
            logical_role="BASE_TAREAS",
            backend_type="MYSQL_CONFIG",
            mysql_connection=object(),
            database_name="other",
        )

        with self.assertRaises(ReunionCreationRequestStorageError):
            resolve_reunion_creation_request_storage()

    @patch(
        "tareas.services.reunion_creation_idempotency."
        "resolve_reunion_creation_request_storage"
    )
    def test_transaction_error_requires_reconciling_with_the_same_request_id(
        self,
        resolve_storage,
    ):
        @contextmanager
        def unavailable_transaction():
            raise ReunionCreationRequestStorageError("connection outcome unknown")
            yield

        resolve_storage.return_value = MagicMock(
            atomic=unavailable_transaction,
        )
        request_id = uuid4()

        with patch(
            "tareas.services.reunion_creation_idempotency._authorize_actor_company"
        ):
            with self.assertRaises(
                ReunionCreationRequestOutcomeUnknown
            ) as raised:
                execute_idempotent_creation(
                    request_id=request_id,
                    empresa_id=12,
                    actor_id=34,
                    payload_hash="a" * 64,
                    review_fingerprint="b" * 64,
                    expires_at=new_request_expiration(),
                    create_callback=lambda _unit: (1, 2),
                    confirmation_validated=True,
                )

        self.assertEqual(raised.exception.request_id, request_id)


class ReunionCreationIdempotencyConcurrencyTests(TransactionTestCase):
    reset_sequences = False

    def setUp(self):
        self.company = Empresa.objects.create(
            codigo=f"RC{uuid4().hex[:6].upper()}",
            descripcion="Reunion idempotency concurrency",
        )
        self.actor = User.objects.create_user(
            username=f"reunion-idempotency-concurrent-{uuid4().hex}"
        )
        assign_permission(
            self.actor,
            self.company,
            "Tareas",
            crear=True,
        )
        self.request_id = new_creation_request_id()
        self.payload_hash = fingerprint_payload({"title": "Concurrency"})
        self.review_fingerprint = fingerprint_payload(
            {"candidates": []},
            purpose=REVIEW_FINGERPRINT_SALT,
        )
        self.expires_at = new_request_expiration()
        self.storage_patch = patch(
            "tareas.services.reunion_creation_idempotency."
            "resolve_reunion_creation_request_storage",
            return_value=DjangoReunionCreationRequestStorage("default"),
        )
        self.storage_patch.start()
        self.addCleanup(self.storage_patch.stop)
        create_review_request(
            request_id=self.request_id,
            empresa_id=self.company.pk,
            actor_id=self.actor.pk,
            payload_hash=self.payload_hash,
            review_fingerprint=self.review_fingerprint,
            expires_at=self.expires_at,
        )

    def test_concurrent_completion_is_recoverable_without_duplicate_result(self):
        barrier = Barrier(2)
        callback_lock = Lock()
        callback_calls = []

        def create_result(_unit):
            with callback_lock:
                callback_calls.append(True)
            time.sleep(0.03)
            return 701, 702

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    return execute_idempotent_creation(
                        request_id=self.request_id,
                        empresa_id=self.company.pk,
                        actor_id=self.actor.pk,
                        payload_hash=self.payload_hash,
                        review_fingerprint=self.review_fingerprint,
                        expires_at=self.expires_at,
                        create_callback=create_result,
                        confirmation_validated=True,
                    )
                except ReunionCreationRequestOutcomeUnknown:
                    return "outcome_unknown"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(lambda _index: worker(), range(2)))

        record = get_creation_request(
            request_id=self.request_id,
            empresa_id=self.company.pk,
            actor_id=self.actor.pk,
        )
        if record.status == ReunionCreationRequest.Estado.REVISION_PENDIENTE:
            execute_idempotent_creation(
                request_id=self.request_id,
                empresa_id=self.company.pk,
                actor_id=self.actor.pk,
                payload_hash=self.payload_hash,
                review_fingerprint=self.review_fingerprint,
                expires_at=self.expires_at,
                create_callback=create_result,
                confirmation_validated=True,
            )
        completed = get_completed_result(
            request_id=self.request_id,
            empresa_id=self.company.pk,
            actor_id=self.actor.pk,
        )
        self.assertEqual((completed.task_id, completed.meeting_id), (701, 702))
        self.assertEqual(
            ReunionCreationRequest.objects.filter(
                request_id=self.request_id,
                status=ReunionCreationRequest.Estado.COMPLETADA,
            ).count(),
            1,
        )
        self.assertGreaterEqual(len(callback_calls), 1)
        self.assertEqual(len(results), 2)
        self.assertTrue(
            all(
                isinstance(result, ReunionCreationResult)
                or result == "outcome_unknown"
                for result in results
            )
        )
