from datetime import timedelta
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connections, transaction
from django.test import (
    SimpleTestCase,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from django.utils import timezone

from access_control.models import Empresa, Permiso
from organizacion.models import Local, OrganizationalSource
from tareas.models import (
    EvaluacionSimilitud,
    ReunionCreationRequest,
    ReunionRevision,
    Tarea,
)
from tareas.services.connection_roles import BackendContext
from tareas.services.reunion_creation_idempotency import (
    REVIEW_FINGERPRINT_SALT,
    REVIEW_TOKEN_TTL_SECONDS,
    ReunionCreationRequestConflict,
    ReunionCreationRequestExpired,
    ReunionCreationRequestNotFound,
    ReunionCreationRequestOutcomeUnknown,
    ReunionCreationRequestRetryable,
    ReunionCreationRequestStateError,
    ReunionCreationRequestStorageFailure,
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
    issue_creation_confirmation,
    new_creation_request_id,
    new_request_expiration,
    record_audit_delivery,
    refresh_review_request,
)
from tareas.tests.factories import assign_permission
from tareas.services.reunion_creation_idempotency_storage import (
    CreationRequestRecord,
    DjangoReunionCreationRequestUnit,
    DjangoReunionCreationRequestStorage,
    MySQLReunionCreationRequestStorage,
    MySQLReunionCreationRequestUnit,
    ReunionCreationRequestStorageError,
    resolve_reunion_creation_request_storage,
    _TrackedTransactionConnection,
    _database_error_category,
    _transaction_storage_error,
)
from tareas.services.task_mutation_locks import TaskMutationLockError, mysql_mutation_transaction
from tareas.services.meeting_storage import DjangoMeetingStorage


def _create_test_meeting(empresa, actor, local):
    from tareas.services.meetings import create_meeting

    with (
        patch(
            "tareas.services.meetings.resolve_meeting_storage",
            return_value=DjangoMeetingStorage("default"),
        ),
        patch("tareas.services.meetings.publish_task"),
    ):
        meeting = create_meeting(
            empresa=empresa,
            creada_por=actor,
            titulo=f"Revisión {uuid4().hex[:8]}",
            descripcion="Fixture de idempotencia",
            fecha_hora_programada=timezone.now() + timedelta(days=1),
            modalidad=ReunionRevision.Modalidad.ZOOM,
            lugar_o_enlace="https://example.test/meeting",
            tipo_ambito=ReunionRevision.TipoAmbito.LOCAL,
            local=local,
        )
    return meeting.tarea_planificada_id, meeting.pk


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
        assign_permission(
            self.actor,
            self.empresa,
            "Tareas - Reuniones",
            ingresar=True,
            crear=True,
            modificar=True,
        )
        self.local = Local.objects.create(
            empresa=self.empresa,
            codigo=f"LOC-{uuid4().hex[:8]}",
            nombre="Local de idempotencia",
            source=OrganizationalSource.LOCAL,
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

    def _execute(self, callback=None, **changes):
        values = {
            "request_id": self.request_id,
            "empresa_id": self.empresa_id,
            "actor_id": self.actor_id,
            "payload_hash": self.payload_hash,
            "review_fingerprint": self.review_fingerprint,
            "create_callback": callback or self._create_meeting_callback,
        }
        values.update(changes)
        if "confirmation_token" not in values:
            record = get_creation_request(
                request_id=values["request_id"],
                empresa_id=values["empresa_id"],
                actor_id=values["actor_id"],
            )
            values["confirmation_token"] = (
                issue_creation_confirmation(
                    request_id=values["request_id"],
                    empresa_id=values["empresa_id"],
                    actor_id=values["actor_id"],
                    payload_hash=values["payload_hash"],
                    review_fingerprint=values["review_fingerprint"],
                    confirmed=True,
                )
                if record.status == ReunionCreationRequest.Estado.REVISION_PENDIENTE
                else ""
            )
        return execute_idempotent_creation(**values)

    def _create_meeting_callback(self, unit):
        self.assertTrue(unit.transaction_active)
        return _create_test_meeting(self.empresa, self.actor, self.local)

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

    def test_review_reservation_requires_both_create_permissions(self):
        for missing_view in ("Tareas - Reuniones", "Tareas"):
            with self.subTest(missing_view=missing_view):
                actor = User.objects.create_user(
                    username=f"reunion-one-permission-{uuid4().hex}"
                )
                assign_permission(
                    actor,
                    self.empresa,
                    "Tareas",
                    crear=missing_view != "Tareas",
                    ingresar=True,
                )
                assign_permission(
                    actor,
                    self.empresa,
                    "Tareas - Reuniones",
                    crear=missing_view != "Tareas - Reuniones",
                    ingresar=True,
                )
                with self.assertRaises(ReunionCreationRequestUnauthorized):
                    create_review_request(
                        request_id=uuid4(),
                        empresa_id=self.empresa_id,
                        actor_id=actor.pk,
                        payload_hash=self.payload_hash,
                        review_fingerprint=self.review_fingerprint,
                        expires_at=new_request_expiration(),
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
                review_fingerprint=self.review_fingerprint,
            )

    def test_confirmation_requires_a_signed_current_review(self):
        self._create_review()
        with self.assertRaises(ReunionCreationRequestStateError):
            issue_creation_confirmation(
                request_id=self.request_id,
                empresa_id=self.empresa_id,
                actor_id=self.actor_id,
                payload_hash=self.payload_hash,
                review_fingerprint=self.review_fingerprint,
                confirmed=False,
            )

    def test_confirmation_revalidates_both_create_permissions(self):
        self._create_review()
        token = issue_creation_confirmation(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
            payload_hash=self.payload_hash,
            review_fingerprint=self.review_fingerprint,
            confirmed=True,
        )
        callback_calls = []
        for view_name in ("Tareas - Reuniones", "Tareas"):
            with self.subTest(view_name=view_name):
                Permiso.objects.filter(
                    usuario=self.actor,
                    empresa=self.empresa,
                    vista__nombre=view_name,
                ).update(crear=False)
                with self.assertRaises(ReunionCreationRequestUnauthorized):
                    execute_idempotent_creation(
                        request_id=self.request_id,
                        empresa_id=self.empresa_id,
                        actor_id=self.actor_id,
                        payload_hash=self.payload_hash,
                        review_fingerprint=self.review_fingerprint,
                        create_callback=lambda _unit: callback_calls.append(True),
                        confirmation_token=token,
                    )
                Permiso.objects.filter(
                    usuario=self.actor,
                    empresa=self.empresa,
                    vista__nombre=view_name,
                ).update(crear=True)
        self.assertEqual(callback_calls, [])
        self.assertEqual(
            ReunionCreationRequest.objects.get(request_id=self.request_id).status,
            ReunionCreationRequest.Estado.REVISION_PENDIENTE,
        )

    def test_completed_result_is_readable_after_create_permission_revocation(self):
        self._create_review()
        token = issue_creation_confirmation(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
            payload_hash=self.payload_hash,
            review_fingerprint=self.review_fingerprint,
            confirmed=True,
        )
        with self.assertRaises(ReunionCreationRequestStateError):
            self._execute(confirmation_token=token + "tampered")

        completed = self._execute(confirmation_token=token)
        Permiso.objects.filter(
            usuario=self.actor,
            empresa=self.empresa,
            vista__nombre__in=("Tareas", "Tareas - Reuniones"),
        ).update(crear=False)

        recovered = get_completed_result(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
        )

        self.assertEqual(
            (recovered.task_id, recovered.meeting_id),
            (completed.task_id, completed.meeting_id),
        )

    def test_commit_confirmed_cleanup_failure_preserves_uuid_and_replays(self):
        self._create_review()
        token = issue_creation_confirmation(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
            payload_hash=self.payload_hash,
            review_fingerprint=self.review_fingerprint,
            confirmed=True,
        )
        callback_calls = []

        def create_callback(unit):
            callback_calls.append(True)
            return self._create_meeting_callback(unit)

        class CommitConfirmedCleanupFailureStorage:
            def __init__(self, storage):
                self.storage = storage

            @contextmanager
            def atomic(self):
                with self.storage.atomic() as unit:
                    yield unit
                raise ReunionCreationRequestStorageError(
                    "timeout restoration failed after commit",
                    commit_confirmed=True,
                )

        storage = CommitConfirmedCleanupFailureStorage(
            DjangoReunionCreationRequestStorage("default")
        )
        with patch(
            "tareas.services.reunion_creation_idempotency."
            "resolve_reunion_creation_request_storage",
            return_value=storage,
        ):
            with self.assertRaises(
                ReunionCreationRequestStorageFailure
            ) as raised:
                self._execute(
                    create_callback,
                    confirmation_token=token,
                )

        self.assertTrue(raised.exception.commit_confirmed)
        self.assertEqual(raised.exception.request_id, self.request_id)
        completed_record = ReunionCreationRequest.objects.get(
            request_id=self.request_id
        )
        self.assertEqual(
            completed_record.status,
            ReunionCreationRequest.Estado.COMPLETADA,
        )

        replay = self._execute(
            create_callback,
            confirmation_token=token,
        )

        self.assertTrue(replay.replayed)
        self.assertEqual(
            (replay.task_id, replay.meeting_id),
            (completed_record.task_id, completed_record.meeting_id),
        )
        self.assertEqual(callback_calls, [True])

    def test_review_ttl_cannot_exceed_configured_maximum(self):
        with self.assertRaises(ValueError):
            self._create_review(
                expires_at=timezone.now() + timedelta(
                    seconds=REVIEW_TOKEN_TTL_SECONDS + 1
                )
            )

    def test_storage_transition_allowlist_matches_for_both_adapters(self):
        django_unit = DjangoReunionCreationRequestUnit("default")
        mysql_unit = MySQLReunionCreationRequestUnit(
            object(),
            MagicMock(),
            transaction_active=True,
        )
        forbidden_updates = (
            {"empresa_id": self.empresa_id + 1},
            {"actor_id": self.actor_id + 1},
            {"payload_hash": "c" * 64},
            {"request_id": uuid4()},
            {"created_at": timezone.now()},
        )

        for unit in (django_unit, mysql_unit):
            with self.subTest(unit=unit.backend_type, allowed=True):
                unit.transition_request(
                    self.request_id,
                    expected_status=ReunionCreationRequest.Estado.REVISION_PENDIENTE,
                    values={"status": ReunionCreationRequest.Estado.CANCELADA},
                )
            for values in forbidden_updates:
                with self.subTest(unit=unit.backend_type, values=values):
                    with self.assertRaises(ValueError):
                        unit.transition_request(
                            self.request_id,
                            expected_status=ReunionCreationRequest.Estado.REVISION_PENDIENTE,
                            values=values,
                        )
            with self.subTest(unit=unit.backend_type, invalid_status=True):
                with self.assertRaises(ValueError):
                    unit.transition_request(
                        self.request_id,
                        expected_status=ReunionCreationRequest.Estado.COMPLETADA,
                        values={
                            "status": ReunionCreationRequest.Estado.REVISION_PENDIENTE,
                        },
                    )
            with self.subTest(unit=unit.backend_type, unvalidated_completion=True):
                with self.assertRaises(ValueError):
                    unit.transition_request(
                        self.request_id,
                        expected_status=ReunionCreationRequest.Estado.REVISION_PENDIENTE,
                        values={
                            "status": ReunionCreationRequest.Estado.COMPLETADA,
                            "task_id": 901,
                            "meeting_id": 902,
                            "completed_at": timezone.now(),
                        },
                    )

    def test_in_progress_cannot_be_committed(self):
        self._create_review()
        storage = DjangoReunionCreationRequestStorage("default")

        with self.assertRaises(ReunionCreationRequestStorageError):
            with storage.atomic() as unit:
                unit.transition_request(
                    self.request_id,
                    expected_status=ReunionCreationRequest.Estado.REVISION_PENDIENTE,
                    values={"status": ReunionCreationRequest.Estado.EN_PROGRESO},
                )

        record = ReunionCreationRequest.objects.get(request_id=self.request_id)
        self.assertEqual(
            record.status,
            ReunionCreationRequest.Estado.REVISION_PENDIENTE,
        )

    def test_callback_cannot_complete_with_nonexistent_result_ids(self):
        self._create_review()

        with self.assertRaises(ReunionCreationRequestStateError):
            self._execute(lambda _unit: (901, 902))

        record = ReunionCreationRequest.objects.get(request_id=self.request_id)
        self.assertEqual(
            record.status,
            ReunionCreationRequest.Estado.REVISION_PENDIENTE,
        )
        self.assertFalse(Tarea.objects.exists())
        self.assertFalse(ReunionRevision.objects.exists())

    def test_database_rejects_invalid_hashes_and_audit_status(self):
        self._create_review()

        for values in (
            {"payload_hash": "short"},
            {"review_fingerprint": "g" * 64},
            {"payload_hash": "A" * 64},
            {"audit_status": "UNKNOWN"},
        ):
            with self.subTest(values=values):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        ReunionCreationRequest.objects.filter(
                            request_id=self.request_id,
                        ).update(**values)

        record = ReunionCreationRequest.objects.get(request_id=self.request_id)
        self.assertEqual(record.payload_hash, self.payload_hash)
        self.assertEqual(record.review_fingerprint, self.review_fingerprint)

    def test_unknown_commit_result_is_distinct_from_storage_failure(self):
        request_id = new_creation_request_id()
        callback_calls = []

        @contextmanager
        def unknown_commit():
            raise ReunionCreationRequestStorageError(
                "sanitized unknown commit",
                category="UNKNOWN_COMMIT_RESULT",
                outcome_unknown=True,
            )
            yield

        with patch(
            "tareas.services.reunion_creation_idempotency."
            "resolve_reunion_creation_request_storage",
            return_value=MagicMock(atomic=unknown_commit),
        ):
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
                        create_callback=lambda _unit: callback_calls.append(True),
                        confirmation_token="not-read-before-storage-error",
                    )
        self.assertEqual(raised.exception.request_id, request_id)
        self.assertEqual(callback_calls, [])

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
            return self._create_meeting_callback(unit)

        first = self._execute(callback)
        replay = self._execute(callback)

        self.assertTrue(
            Tarea.objects.filter(pk=first.task_id, empresa=self.empresa).exists()
        )
        self.assertTrue(
            ReunionRevision.objects.filter(
                pk=first.meeting_id,
                tarea_planificada_id=first.task_id,
                empresa=self.empresa,
            ).exists()
        )
        self.assertFalse(first.replayed)
        self.assertEqual((replay.task_id, replay.meeting_id), (first.task_id, first.meeting_id))
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
            return self._create_meeting_callback(unit)

        completed = self._execute(callback)
        replay = self._execute(callback)

        self.assertTrue(Tarea.objects.filter(pk=completed.task_id).exists())
        self.assertTrue(ReunionRevision.objects.filter(pk=completed.meeting_id).exists())
        self.assertFalse(completed.replayed)
        self.assertEqual(
            (replay.task_id, replay.meeting_id),
            (completed.task_id, completed.meeting_id),
        )
        self.assertTrue(replay.replayed)
        self.assertEqual(len(calls), 1)
        stored = ReunionCreationRequest.objects.get(request_id=self.request_id)
        self.assertEqual(stored.status, ReunionCreationRequest.Estado.COMPLETADA)
        self.assertIsNotNone(stored.completed_at)
        self.assertTrue(Tarea.objects.filter(pk=completed.task_id).exists())
        self.assertTrue(ReunionRevision.objects.filter(pk=completed.meeting_id).exists())
        self.assertFalse(EvaluacionSimilitud.objects.exists())

    def test_callback_failure_rolls_back_to_review_pending(self):
        self._create_review()

        def callback(unit):
            self._create_meeting_callback(unit)
            raise RuntimeError("controlled pre-commit failure")

        with self.assertRaisesRegex(RuntimeError, "controlled pre-commit"):
            self._execute(callback)

        stored = ReunionCreationRequest.objects.get(request_id=self.request_id)
        self.assertEqual(stored.status, ReunionCreationRequest.Estado.REVISION_PENDIENTE)
        self.assertIsNone(stored.task_id)
        self.assertIsNone(stored.meeting_id)
        self.assertIsNone(stored.completed_at)
        self.assertFalse(Tarea.objects.exists())
        self.assertFalse(ReunionRevision.objects.exists())

    def test_invalid_callback_result_rolls_back(self):
        self._create_review()
        with self.assertRaises(ValueError):
            self._execute(lambda _unit: (100, None))

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
        self._create_review(request_id=completed_id)
        self._execute(request_id=completed_id)
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
        completed = self._execute()
        result = get_completed_result(
            request_id=self.request_id,
            empresa_id=self.empresa_id,
            actor_id=self.actor_id,
        )

        self.assertEqual(
            (result.task_id, result.meeting_id),
            (completed.task_id, completed.meeting_id),
        )
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
        self._execute()
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
    def test_timeout_restore_failure_preserves_confirmed_commit(self):
        class FakeCursor:
            def __init__(self):
                self.row = None

            def execute(self, sql, params=()):
                if sql == "SELECT DATABASE()":
                    self.row = ("tareas",)
                elif "SELECT @@SESSION.innodb_lock_wait_timeout" in sql:
                    self.row = (30,)
                elif sql == "SET SESSION innodb_lock_wait_timeout = 30":
                    raise RuntimeError("timeout restore failed")
                else:
                    self.row = None

            def fetchone(self):
                return self.row

            def close(self):
                return None

        connection = MagicMock()
        connection.alias = None
        connection.cursor.side_effect = FakeCursor

        @contextmanager
        def open_fake_mysql_connection(*args, **kwargs):
            yield connection

        storage = MySQLReunionCreationRequestStorage(
            SimpleNamespace(nombre_logico="django_tareas"),
            "tareas",
        )
        with patch(
            "tareas.services.reunion_creation_idempotency_storage."
            "open_mysql_connection",
            side_effect=open_fake_mysql_connection,
        ):
            with self.assertRaises(
                ReunionCreationRequestStorageError
            ) as raised:
                with storage.atomic() as unit:
                    unit.mutated = True

        self.assertTrue(raised.exception.commit_confirmed)
        self.assertFalse(raised.exception.outcome_unknown)
        connection.begin.assert_called_once()
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()

    def test_transaction_phases_preserve_commit_uncertainty(self):
        begin_connection = MagicMock()
        begin_connection.begin.side_effect = RuntimeError("begin failure")
        begin_tracker = _TrackedTransactionConnection(begin_connection)
        with self.assertRaises(TaskMutationLockError) as begin_error:
            with mysql_mutation_transaction(begin_tracker):
                pass
        begin_storage_error = _transaction_storage_error(
            begin_error.exception,
            begin_tracker,
        )
        self.assertEqual(begin_storage_error.category, "STORAGE_FAILURE")
        self.assertFalse(begin_storage_error.outcome_unknown)

        commit_connection = MagicMock()
        commit_connection.commit.side_effect = RuntimeError("commit failure")
        commit_tracker = _TrackedTransactionConnection(commit_connection)
        with self.assertRaises(TaskMutationLockError) as commit_error:
            with mysql_mutation_transaction(commit_tracker):
                pass
        commit_storage_error = _transaction_storage_error(
            commit_error.exception,
            commit_tracker,
        )
        self.assertEqual(commit_storage_error.category, "UNKNOWN_COMMIT_RESULT")
        self.assertTrue(commit_storage_error.outcome_unknown)

        rollback_connection = MagicMock()
        rollback_connection.rollback.side_effect = RuntimeError("rollback failure")
        rollback_tracker = _TrackedTransactionConnection(rollback_connection)
        with self.assertRaises(TaskMutationLockError) as rollback_error:
            with mysql_mutation_transaction(rollback_tracker):
                raise RuntimeError("controlled operation failure")
        rollback_storage_error = _transaction_storage_error(
            rollback_error.exception,
            rollback_tracker,
        )
        self.assertEqual(rollback_storage_error.category, "UNKNOWN_COMMIT_RESULT")
        self.assertTrue(rollback_storage_error.outcome_unknown)

    def test_mysql_driver_error_codes_are_normalized(self):
        class PyMySQLIntegrityError(Exception):
            __module__ = "pymysql.err"

        duplicate_error = PyMySQLIntegrityError(1062, "duplicate")
        deadlock_error = PyMySQLIntegrityError(1213, "deadlock")
        check_error = PyMySQLIntegrityError(4025, "constraint")

        self.assertEqual(_database_error_category(duplicate_error), "CONFLICT")
        self.assertEqual(_database_error_category(deadlock_error), "RETRYABLE")
        self.assertEqual(_database_error_category(check_error), "INVALID_STATE")

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
        unit = MySQLReunionCreationRequestUnit(
            object(),
            cursor,
            transaction_active=True,
        )

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
        unit = MySQLReunionCreationRequestUnit(
            object(),
            cursor,
            transaction_active=True,
        )
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
        mysql_connection = SimpleNamespace(nombre_logico="django_tareas")
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
            raise ReunionCreationRequestStorageError(
                "connection unavailable before commit"
            )
            yield

        resolve_storage.return_value = MagicMock(
            atomic=unavailable_transaction,
        )
        request_id = uuid4()
        callback_calls = []

        with patch(
            "tareas.services.reunion_creation_idempotency._authorize_actor_company"
        ):
            with self.assertRaises(
                ReunionCreationRequestStorageFailure
            ) as raised:
                execute_idempotent_creation(
                    request_id=request_id,
                    empresa_id=12,
                    actor_id=34,
                    payload_hash="a" * 64,
                    review_fingerprint="b" * 64,
                    create_callback=lambda _unit: callback_calls.append(True),
                    confirmation_token="unused-before-storage-fails",
                )
        self.assertFalse(raised.exception.commit_confirmed)
        self.assertEqual(raised.exception.request_id, request_id)
        self.assertEqual(callback_calls, [])


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
        assign_permission(
            self.actor,
            self.company,
            "Tareas - Reuniones",
            ingresar=True,
            crear=True,
            modificar=True,
        )
        local = Local.objects.create(
            empresa=self.company,
            codigo=f"LOC-{uuid4().hex[:8]}",
            nombre="Local de concurrencia",
            source=OrganizationalSource.LOCAL,
        )
        self.task_id, self.meeting_id = _create_test_meeting(
            self.company,
            self.actor,
            local,
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
        self.confirmation_token = issue_creation_confirmation(
            request_id=self.request_id,
            empresa_id=self.company.pk,
            actor_id=self.actor.pk,
            payload_hash=self.payload_hash,
            review_fingerprint=self.review_fingerprint,
            confirmed=True,
        )

    def test_concurrent_completion_is_recoverable_without_duplicate_result(self):
        barrier = Barrier(2)
        callback_lock = Lock()
        callback_calls = []

        def create_result(_unit):
            with callback_lock:
                callback_calls.append(True)
            time.sleep(0.03)
            return self.task_id, self.meeting_id

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
                        create_callback=create_result,
                        confirmation_token=self.confirmation_token,
                    )
                except ReunionCreationRequestOutcomeUnknown:
                    return "outcome_unknown"
                except ReunionCreationRequestRetryable:
                    return "retryable"
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
                create_callback=create_result,
                confirmation_token=self.confirmation_token,
            )
        completed = get_completed_result(
            request_id=self.request_id,
            empresa_id=self.company.pk,
            actor_id=self.actor.pk,
        )
        self.assertEqual(
            (completed.task_id, completed.meeting_id),
            (self.task_id, self.meeting_id),
        )
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
                or result in {"outcome_unknown", "retryable"}
                for result in results
            )
        )
