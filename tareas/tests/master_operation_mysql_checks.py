import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AppDocs.settings")
import django

django.setup()

from tareas.services.master_catalog_common import (
    MasterCatalogDatabaseError,
)
from tareas.services.master_operation_store import (
    MasterOperationConflict,
    MasterOperationNotFound,
    get_operation,
    list_pending_reconciliation,
    master_operation_transaction,
    mark_audit_status,
    mark_unknown_operation,
    reserve_operation,
    verified_master_operation_connection,
    complete_operation,
)


@unittest.skipUnless(
    os.environ.get("RUN_TAREAS_MYSQL_TESTS") == "1",
    "requiere RUN_TAREAS_MYSQL_TESTS=1 y BASE_TAREAS verificado",
)
class MasterOperationMySQLTests(unittest.TestCase):
    def _cleanup(self, operation_ids):
        with verified_master_operation_connection() as connection:
            cursor = connection.cursor()
            try:
                for operation_id in operation_ids:
                    cursor.execute(
                        "DELETE FROM tareas_master_operation WHERE operation_id = %s",
                        (str(operation_id),),
                    )
                connection.commit()
            finally:
                cursor.close()

    def test_replay_conflict_durable_result_and_reconciliation(self):
        operation_id = uuid4()
        try:
            with verified_master_operation_connection() as connection:
                with master_operation_transaction(connection):
                    cursor = connection.cursor()
                    try:
                        reservation = reserve_operation(
                            cursor,
                            operation_id=operation_id,
                            entity_type="PROVEEDOR",
                            action="CREATE",
                            empresa_id=910001,
                            actor_id=1,
                            payload={"nombre": "Certificación"},
                        )
                        self.assertFalse(reservation.replayed)
                        committed = complete_operation(
                            cursor,
                            operation_id,
                            result_id=700001,
                            result_payload={"id": 700001, "nombre": "Certificación"},
                        )
                        self.assertEqual(committed.status, "COMMITTED")
                    finally:
                        cursor.close()

            with verified_master_operation_connection() as connection:
                cursor = connection.cursor()
                try:
                    replay = reserve_operation(
                        cursor,
                        operation_id=operation_id,
                        entity_type="PROVEEDOR",
                        action="CREATE",
                        empresa_id=910001,
                        actor_id=1,
                        payload={"nombre": "Certificación"},
                    )
                    self.assertTrue(replay.replayed)
                    self.assertEqual(replay.record.result_id, 700001)
                    self.assertEqual(len(list_pending_reconciliation(cursor)), 1)
                finally:
                    cursor.close()

            with verified_master_operation_connection() as connection:
                with master_operation_transaction(connection):
                    cursor = connection.cursor()
                    try:
                        mark_audit_status(
                            cursor,
                            operation_id,
                            audit_status="CONFIRMED",
                            audit_event_id=800001,
                        )
                    finally:
                        cursor.close()

            with verified_master_operation_connection() as connection:
                cursor = connection.cursor()
                try:
                    self.assertEqual(list_pending_reconciliation(cursor), ())
                    with self.assertRaises(MasterOperationConflict):
                        reserve_operation(
                            cursor,
                            operation_id=operation_id,
                            entity_type="PROVEEDOR",
                            action="UPDATE",
                            empresa_id=910001,
                            actor_id=1,
                            payload={"nombre": "Certificación"},
                        )
                finally:
                    cursor.close()
        finally:
            self._cleanup((operation_id,))

    def test_rollback_removes_uncommitted_reservation(self):
        operation_id = uuid4()
        try:
            with self.assertRaises(MasterCatalogDatabaseError):
                with verified_master_operation_connection() as connection:
                    with master_operation_transaction(connection):
                        cursor = connection.cursor()
                        try:
                            reserve_operation(
                                cursor,
                                operation_id=operation_id,
                                entity_type="LOCAL",
                                action="CREATE",
                                empresa_id=910002,
                                actor_id=1,
                                payload={"codigo": "ROLLBACK"},
                            )
                            raise MasterCatalogDatabaseError("rollback de prueba")
                        finally:
                            cursor.close()

            with verified_master_operation_connection() as connection:
                cursor = connection.cursor()
                try:
                    with self.assertRaises(MasterOperationNotFound):
                        get_operation(cursor, operation_id)
                finally:
                    cursor.close()
        finally:
            self._cleanup((operation_id,))

    def test_concurrent_same_uuid_reserves_once(self):
        operation_id = uuid4()

        def reserve_one():
            with verified_master_operation_connection() as connection:
                with master_operation_transaction(connection):
                    cursor = connection.cursor()
                    try:
                        reservation = reserve_operation(
                            cursor,
                            operation_id=operation_id,
                            entity_type="DEPARTAMENTO",
                            action="CREATE",
                            empresa_id=910003,
                            actor_id=1,
                            payload={"codigo": "CONCURRENT"},
                        )
                        if not reservation.replayed:
                            complete_operation(
                                cursor,
                                operation_id,
                                result_id=700003,
                                result_payload={"id": 700003},
                            )
                        return reservation.replayed
                    finally:
                        cursor.close()

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: reserve_one(), range(2)))
            self.assertEqual(sorted(results), [False, True])
        finally:
            self._cleanup((operation_id,))

    def test_unknown_status_is_reconcilable(self):
        operation_id = uuid4()
        try:
            with verified_master_operation_connection() as connection:
                with master_operation_transaction(connection):
                    cursor = connection.cursor()
                    try:
                        reserve_operation(
                            cursor,
                            operation_id=operation_id,
                            entity_type="LOCAL",
                            action="UPDATE",
                            empresa_id=910004,
                            actor_id=1,
                            payload={"codigo": "UNKNOWN"},
                        )
                        mark_unknown_operation(cursor, operation_id)
                    finally:
                        cursor.close()

            with verified_master_operation_connection() as connection:
                cursor = connection.cursor()
                try:
                    record = get_operation(cursor, operation_id)
                    self.assertEqual(record.status, "UNKNOWN")
                    self.assertEqual(len(list_pending_reconciliation(cursor)), 1)
                finally:
                    cursor.close()
        finally:
            self._cleanup((operation_id,))
