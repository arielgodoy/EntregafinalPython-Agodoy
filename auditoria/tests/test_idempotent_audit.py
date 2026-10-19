from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, close_old_connections
from django.test import TestCase, TransactionTestCase

from auditoria.models import AuditoriaTareasEvent
from auditoria.services import (
    AuditIdempotencyConflict,
    AuditIdempotencyInputError,
    AuditIdempotencyStorageError,
    AuditoriaService,
)


User = get_user_model()


class IdempotentAuditServiceTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(
            username="audit-idempotency-actor",
            password="test-password",
        )
        self.operation_id = uuid4()

    def payload(self, **overrides):
        values = {
            "user": self.actor,
            "empresa_id": 7,
            "action": "DELETE",
            "object_type": "Tarea",
            "object_id": "42",
            "method": "INTERNAL",
            "path": "internal/logical-task-deletion",
            "vista_nombre": "Tareas",
            "meta": {
                "operation_id": self.operation_id.hex,
                "reason": "Resguardo administrativo",
            },
        }
        values.update(overrides)
        return values

    def log_once(self, **overrides):
        return AuditoriaService.log_event_idempotent(
            "tareas",
            idempotency_key=self.operation_id,
            **self.payload(**overrides),
        )

    def test_first_write_and_same_payload_replay_return_one_event(self):
        created = self.log_once()
        replay = self.log_once(
            meta={
                "reason": "Resguardo administrativo",
                "operation_id": self.operation_id.hex,
            }
        )

        self.assertTrue(created.created)
        self.assertFalse(replay.created)
        self.assertEqual(created.event.pk, replay.event.pk)
        self.assertEqual(created.event.idempotency_key, self.operation_id.hex)
        self.assertEqual(len(created.event.idempotency_payload_hash), 64)
        self.assertEqual(
            AuditoriaTareasEvent.objects.filter(
                idempotency_key=self.operation_id.hex
            ).count(),
            1,
        )

    def test_reused_key_with_different_payload_is_rejected_without_mutation(self):
        first = self.log_once()

        with self.assertRaises(AuditIdempotencyConflict):
            self.log_once(object_id="43")

        stored = AuditoriaTareasEvent.objects.get(pk=first.event.pk)
        self.assertEqual(stored.object_id, "42")
        self.assertEqual(
            AuditoriaTareasEvent.objects.filter(
                idempotency_key=self.operation_id.hex
            ).count(),
            1,
        )

    def test_public_lookup_distinguishes_missing_and_existing_events(self):
        self.assertIsNone(
            AuditoriaService.get_event_by_idempotency_key(
                "tareas",
                self.operation_id,
            )
        )
        created = self.log_once()

        found = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            self.operation_id.hex,
        )

        self.assertEqual(found.pk, created.event.pk)

    def test_ambiguous_ack_can_be_replayed_without_duplicate_event(self):
        manager = AuditoriaTareasEvent._default_manager.db_manager("default")

        class _PersistThenRaise:
            def get_or_create(self, **kwargs):
                manager.get_or_create(**kwargs)
                raise DatabaseError("simulated lost acknowledgement")

        with patch.object(
            AuditoriaTareasEvent._default_manager,
            "db_manager",
            return_value=_PersistThenRaise(),
        ):
            with self.assertRaises(AuditIdempotencyStorageError):
                self.log_once()

        found = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            self.operation_id,
        )
        replay = self.log_once()

        self.assertIsNotNone(found)
        self.assertFalse(replay.created)
        self.assertEqual(found.pk, replay.event.pk)
        self.assertEqual(
            AuditoriaTareasEvent.objects.filter(
                idempotency_key=self.operation_id.hex
            ).count(),
            1,
        )

    def test_write_and_lookup_database_errors_are_explicit(self):
        class _FailingManager:
            def get_or_create(self, **kwargs):
                raise DatabaseError("simulated write failure")

            def filter(self, **kwargs):
                raise DatabaseError("simulated lookup failure")

        with patch.object(
            AuditoriaTareasEvent._default_manager,
            "db_manager",
            return_value=_FailingManager(),
        ):
            with self.assertRaises(AuditIdempotencyStorageError):
                self.log_once()
            with self.assertRaises(AuditIdempotencyStorageError):
                AuditoriaService.get_event_by_idempotency_key(
                    "tareas",
                    self.operation_id,
                )

    def test_key_and_app_scope_are_validated(self):
        with self.assertRaises(AuditIdempotencyInputError):
            AuditoriaService.log_event_idempotent(
                "tareas",
                idempotency_key="not-a-uuid",
                **self.payload(),
            )
        with self.assertRaises(AuditIdempotencyInputError):
            AuditoriaService.log_event_idempotent(
                "biblioteca",
                idempotency_key=self.operation_id,
                **self.payload(),
            )
        self.assertFalse(AuditoriaTareasEvent.objects.exists())

    def test_legacy_log_event_remains_non_idempotent_and_compatible(self):
        first = AuditoriaService.log_event("tareas", **self.payload())
        second = AuditoriaService.log_event("tareas", **self.payload())

        self.assertIsInstance(first, AuditoriaTareasEvent)
        self.assertIsInstance(second, AuditoriaTareasEvent)
        self.assertNotEqual(first.pk, second.pk)
        self.assertIsNone(first.idempotency_key)
        self.assertIsNone(second.idempotency_payload_hash)
        self.assertEqual(AuditoriaTareasEvent.objects.count(), 2)


class IdempotentAuditConcurrencyTests(TransactionTestCase):
    def test_concurrent_same_key_writes_create_one_event(self):
        actor = User.objects.create_user(
            username="audit-idempotency-concurrent",
            password="test-password",
        )
        operation_id = uuid4()
        barrier = Barrier(2)

        def write_event():
            close_old_connections()
            try:
                thread_actor = User.objects.get(pk=actor.pk)
                barrier.wait(timeout=10)
                return AuditoriaService.log_event_idempotent(
                    "tareas",
                    idempotency_key=operation_id,
                    user=thread_actor,
                    empresa_id=7,
                    action="DELETE",
                    object_type="Tarea",
                    object_id="99",
                    method="INTERNAL",
                    path="internal/logical-task-deletion",
                    vista_nombre="Tareas",
                    meta={"operation_id": operation_id.hex},
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: write_event(), range(2)))

        self.assertEqual(sorted(result.created for result in results), [False, True])
        self.assertEqual(results[0].event.pk, results[1].event.pk)
        self.assertEqual(
            AuditoriaTareasEvent.objects.filter(
                idempotency_key=operation_id.hex
            ).count(),
            1,
        )
