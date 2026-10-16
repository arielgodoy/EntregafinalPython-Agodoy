from contextlib import nullcontext
from datetime import date
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.test import TestCase, TransactionTestCase

from tareas.models import CorrelativoEmpresa, Tarea
from tareas.services.hierarchy_lifecycle_storage import (
    DjangoHierarchyLifecycleStorage,
    MySQLHierarchyLifecycleStorage,
)
from tareas.services.task_mutation_locks import (
    TaskMutationLockError,
    TaskMutationLockUnsupported,
    is_task_mutation_conflict,
    lock_mysql_task_rows,
    lock_orm_task_rows,
)
from tareas.tests.factories import create_empresa, create_tarea, create_user


class _MySQLCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = ()
        self.row = None
        self.lastrowid = 0

    def execute(self, sql, params=()):
        self.connection.statements.append((sql, params))
        if "SELECT @@SESSION.innodb_lock_wait_timeout" in sql:
            self.row = (30,)
        elif "INSERT INTO `tareas_correlativoempresa`" in sql:
            if params[1:] != (1,):
                raise AssertionError((sql, params))
            if self.connection.duplicate_sequence_insert:
                raise Exception(1062, "duplicate key")
            self.row = None
        elif "FROM `tareas_correlativoempresa`" in sql and "FOR UPDATE" in sql:
            self.row = (params[0],)
        elif "FROM `tareas_tarea`" in sql and "FOR UPDATE" in sql:
            company_id = params[0]
            if "estado, anulada" in sql:
                task_id = params[0]
                task_company = params[1]
                if self.connection.tasks.get(task_id) == task_company:
                    self.row = (task_id, task_company, Tarea.Estado.GESTION, 0)
                else:
                    self.row = None
            else:
                self.rows = tuple(
                    (task_id,)
                    for task_id, task_company in sorted(self.connection.tasks.items())
                    if task_company == company_id
                )
        elif "FROM tareas_tarearelacion AS relation" in sql:
            self.rows = self.connection.relations
        elif sql.startswith("INSERT INTO tareas_tarearelacion"):
            self.lastrowid = 44
        else:
            self.rows = ()

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows

    def close(self):
        return None


class _MySQLConnection:
    def __init__(self, tasks, relations=()):
        self.tasks = tasks
        self.relations = relations
        self.duplicate_sequence_insert = False
        self.statements = []
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self):
        return _MySQLCursor(self)

    def begin(self):
        self.begin_count += 1

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


class DjangoTaskMutationLockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = create_empresa("LK1", "Empresa locks")
        cls.other_company = create_empresa("LK2", "Otra empresa")
        cls.user = create_user("mutation-lock-user")
        cls.task_a = create_tarea(
            cls.company,
            cls.user,
            titulo="Tarea A",
            correlativo="K0000001",
            fecha_tope=date.today(),
        )
        cls.task_b = create_tarea(
            cls.company,
            cls.user,
            titulo="Tarea B",
            correlativo="K0000002",
            fecha_tope=date.today(),
        )
        cls.foreign_task = create_tarea(
            cls.other_company,
            cls.user,
            titulo="Tarea externa",
            correlativo="K0000003",
            fecha_tope=date.today(),
        )

    def test_orm_task_set_is_scoped_and_returned_in_lock_order(self):
        with transaction.atomic(using="default"):
            locked = lock_orm_task_rows(
                "default",
                self.company.pk,
                (self.task_b.pk, self.task_a.pk),
            )

        self.assertEqual(
            tuple(task.pk for task in locked),
            tuple(sorted((self.task_a.pk, self.task_b.pk))),
        )
        self.assertNotIn(self.foreign_task.pk, {task.pk for task in locked})

    def test_empty_company_gets_a_persistent_coordination_row(self):
        company = create_empresa("LK3", "Empresa sin tareas")

        with transaction.atomic(using="default"):
            locked = lock_orm_task_rows("default", company.pk, ())

        self.assertEqual(locked, ())
        self.assertTrue(
            CorrelativoEmpresa.objects.filter(empresa_id=company.pk).exists()
        )

    def test_explicit_correlativo_creation_materializes_coordination_row(self):
        company = create_empresa("LK4", "Empresa correlativo explícito")
        task = create_tarea(
            company,
            self.user,
            titulo="Correlativo explícito",
            correlativo="B0000099",
            fecha_tope=date.today(),
        )

        self.assertTrue(
            CorrelativoEmpresa.objects.filter(empresa_id=company.pk).exists()
        )
        self.assertEqual(task.correlativo, "B0000099")

    def test_stale_task_save_does_not_reinsert_deleted_row(self):
        stale_task = create_tarea(
            self.company,
            self.user,
            titulo="Eliminada",
            correlativo="B0000100",
            fecha_tope=date.today(),
        )
        Tarea.objects.filter(pk=stale_task.pk).delete()

        with self.assertRaises(Tarea.DoesNotExist):
            stale_task.save()

        self.assertFalse(Tarea.objects.filter(pk=stale_task.pk).exists())

    def test_model_publication_revalidates_state_after_lock(self):
        stale_task = create_tarea(
            self.company,
            self.user,
            titulo="Publicación obsoleta",
            correlativo="B0000101",
            fecha_tope=date.today(),
        )
        Tarea.objects.filter(pk=stale_task.pk).update(estado=Tarea.Estado.ACTIVA)

        with self.assertRaisesMessage(ValidationError, "ya está publicada"):
            stale_task.publicar(self.user)

        stale_task.refresh_from_db()
        self.assertEqual(stale_task.estado, Tarea.Estado.ACTIVA)

    def test_sqlite_does_not_claim_row_lock_guarantees(self):
        connection = connections["default"]
        if connection.features.has_select_for_update:
            self.skipTest("El backend actual proporciona SELECT FOR UPDATE.")
        with transaction.atomic(using="default"):
            with self.assertRaises(TaskMutationLockUnsupported):
                lock_orm_task_rows(
                    "default",
                    self.company.pk,
                    (self.task_a.pk,),
                    require_row_locks=True,
                )

    def test_hierarchy_validation_runs_inside_the_locking_transaction(self):
        storage = DjangoHierarchyLifecycleStorage("default")
        observed = {}

        def validate(parent, child, *, parent_resolver):
            observed["in_transaction"] = connections["default"].in_atomic_block
            observed["parent"] = parent.pk
            observed["child"] = child.pk
            self.assertIsNone(parent_resolver(child))

        with patch(
            "tareas.services.hierarchy.validate_relation",
            side_effect=validate,
        ) as validate_relation:
            relation = storage.create_relation(
                self.task_a.pk,
                self.task_b.pk,
                company_id=self.company.pk,
            )

        self.assertTrue(observed["in_transaction"])
        self.assertEqual(observed["parent"], self.task_a.pk)
        self.assertEqual(observed["child"], self.task_b.pk)
        validate_relation.assert_called_once()
        self.assertEqual(relation.padre_id, self.task_a.pk)


class DjangoTaskMutationTransactionTests(TransactionTestCase):
    def test_orm_lock_helper_requires_an_active_transaction(self):
        with self.assertRaises(TaskMutationLockError):
            lock_orm_task_rows("default", 1)


class MySQLTaskMutationLockTests(TestCase):
    def test_mysql_lock_timeout_and_deadlock_codes_are_conflicts(self):
        self.assertTrue(is_task_mutation_conflict(Exception(1205, "timeout")))
        self.assertTrue(is_task_mutation_conflict(Exception(1213, "deadlock")))
        self.assertTrue(is_task_mutation_conflict(Exception(1062, "duplicate")))
        self.assertFalse(is_task_mutation_conflict(Exception(1146, "missing table")))

    def test_mysql_lock_query_scopes_company_and_orders_task_ids(self):
        connection = _MySQLConnection(
            {8: 10, 2: 10, 4: 11},
        )
        connection.duplicate_sequence_insert = True
        connection.begin()
        locked_ids = lock_mysql_task_rows(connection, 10)

        self.assertEqual(locked_ids, (2, 8))
        sql, params = next(
            item
            for item in connection.statements
            if "FROM `tareas_tarea`" in item[0] and "FOR UPDATE" in item[0]
        )
        self.assertIn("WHERE `empresa_id` = %s", sql)
        self.assertIn("ORDER BY `id` FOR UPDATE", sql)
        self.assertEqual(params, (10,))
        sequence_lock = next(
            call for call in connection.statements
            if "INSERT INTO `tareas_correlativoempresa`" in call[0]
        )
        self.assertIn("VALUES (%s, %s)", sequence_lock[0])
        self.assertNotIn("UPDATE", sequence_lock[0])
        self.assertEqual(sequence_lock[1], (10, 1))
        sequence_lock_index = next(
            index
            for index, (statement, _params) in enumerate(connection.statements)
            if "INSERT INTO `tareas_correlativoempresa`" in statement
        )
        company_lock_index = next(
            index
            for index, (statement, _params) in enumerate(connection.statements)
            if "FROM `tareas_correlativoempresa`" in statement
            and "FOR UPDATE" in statement
        )
        task_lock_index = next(
            index
            for index, (statement, _params) in enumerate(connection.statements)
            if "FROM `tareas_tarea`" in statement and "FOR UPDATE" in statement
        )
        self.assertLess(sequence_lock_index, company_lock_index)
        self.assertLess(company_lock_index, task_lock_index)

    @patch("tareas.services.hierarchy_lifecycle_storage.open_mysql_connection")
    def test_mysql_relation_uses_one_transaction_and_same_connection(
        self,
        open_connection,
    ):
        company_id = 20
        connection = _MySQLConnection({1: company_id, 2: company_id})
        connection.duplicate_sequence_insert = True
        open_connection.return_value = nullcontext(connection)

        relation = MySQLHierarchyLifecycleStorage(
            object(),
            "tareas",
        ).create_relation(1, 2, company_id=company_id)

        self.assertEqual(relation.id, 44)
        self.assertEqual(connection.begin_count, 1)
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        sql_statements = [statement for statement, _params in connection.statements]
        relation_insert = next(
            (statement, params)
            for statement, params in connection.statements
            if statement.startswith("INSERT INTO tareas_tarearelacion")
        )
        self.assertEqual(
            relation_insert[0],
            "INSERT INTO tareas_tarearelacion "
            "(padre_id,hija_id,fecha) VALUES (%s,%s,%s)",
        )
        self.assertEqual(relation_insert[1][:2], (1, 2))
        self.assertIsNotNone(relation_insert[1][2])
        self.assertTrue(
            any(
                "ORDER BY `id` FOR UPDATE" in statement
                for statement in sql_statements
            )
        )
        self.assertTrue(
            any(
                statement == "SET SESSION innodb_lock_wait_timeout = 5"
                for statement in sql_statements
            )
        )
        self.assertTrue(
            any(
                statement == "SET SESSION innodb_lock_wait_timeout = 30"
                for statement in sql_statements
            )
        )

    @patch("tareas.services.hierarchy_lifecycle_storage.open_mysql_connection")
    def test_mysql_cycle_validation_rolls_back_before_insert(self, open_connection):
        company_id = 21
        connection = _MySQLConnection(
            {1: company_id, 2: company_id},
            relations=((1, 2, company_id, company_id),),
        )
        open_connection.return_value = nullcontext(connection)

        with self.assertRaises(ValidationError):
            MySQLHierarchyLifecycleStorage(
                object(),
                "tareas",
            ).create_relation(2, 1, company_id=company_id)

        self.assertEqual(connection.begin_count, 1)
        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(connection.commit_count, 0)
        self.assertFalse(
            any(
                statement.startswith("INSERT INTO tareas_tarearelacion")
                for statement, _params in connection.statements
            )
        )
