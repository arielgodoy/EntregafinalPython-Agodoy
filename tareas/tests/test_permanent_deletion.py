from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

from access_control.models import Empresa, Permiso, Vista
from django.contrib.auth.models import User
from django.core import signing
from django.db import connections
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tareas.models import (
    Avance,
    Hito,
    HitoEvidencia,
    HitoHistorial,
    Tarea,
    TareaConnectionRole,
    TareaEliminacionElemento,
    TareaEliminacionOperacion,
    TareaParticipante,
    TareaRelacion,
    Todo,
    TodoEvento,
)
from tareas.services.base_tareas_schema import (
    get_deletion_item_models,
    get_operational_models,
)
from tareas.services.deletion_ledger import (
    DeletionInventoryItem,
    MySQLDeletionLedgerStorage,
)
from tareas.services.permanent_deletion import (
    PermanentDeletionAuthorizationError,
    PermanentDeletionBlocked,
    PermanentDeletionCommitUnresolved,
    _resolve_backend,
    _DjangoReader,
    _foreign_key_rows,
    _field_column,
    _mysql_fk_snapshot,
    _orm_fk_contract,
    _primary_key_column,
    _MySQLReader,
    _topological_deletion_order,
    build_deletion_inventory,
    execute_permanent_deletion,
    issue_permanent_deletion_confirmation,
    reconcile_permanent_deletion_operation,
)
from tareas.services.task_mutation_locks import TaskMutationLockUnsupported


class PermanentDeletionInventoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(
            codigo="00",
            descripcion="Empresa Base",
        )
        cls.user = User.objects.create_user(
            username="permanent-deletion-owner",
            password="test-password",
        )
        cls.vista = Vista.objects.create(nombre="Tareas")
        Permiso.objects.create(
            usuario=cls.user,
            empresa=cls.empresa,
            vista=cls.vista,
            ver=False,
            ingresar=False,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=True,
        )
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="DJANGO",
            django_alias="default",
        )

    def _task(self, *, correlativo, **kwargs):
        return Tarea.objects.create(
            titulo=f"Tarea {correlativo}",
            correlativo=correlativo,
            empresa=self.empresa,
            creada_por=self.user,
            **kwargs,
        )

    def _inventory(self, task):
        return build_deletion_inventory(
            actor=self.user,
            empresa_id=self.empresa.pk,
            task_id=task.pk,
        )

    def test_inventory_is_exact_deterministic_and_topologically_ordered(self):
        root = self._task(correlativo="T0000001")
        child = self._task(correlativo="T0000002")
        relation = TareaRelacion.objects.create(padre=root, hija=child)
        avance = Avance.objects.create(tarea=root)
        hito = Hito.objects.create(
            tarea=root,
            nombre="Verificación",
            responsable=self.user,
            cumplimiento=0,
            peso=Decimal("1.00"),
        )
        historial = HitoHistorial.objects.create(
            hito=hito,
            tipo_evento=HitoHistorial.Evento.CREACION,
            usuario=self.user,
        )

        first = self._inventory(root)
        second = self._inventory(root)
        manifest = {(item.model_label, item.object_id) for item in first.items}
        order = {
            (item.model_label, item.object_id): index
            for index, item in enumerate(first.deletion_order)
        }
        relation_parent_column = _field_column(TareaRelacion, "padre")

        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(len(first.fingerprint), 64)
        self.assertEqual(first.task_ids, tuple(sorted((root.pk, child.pk))))
        self.assertIn((Tarea._meta.label_lower, child.pk), manifest)
        self.assertIn((TareaRelacion._meta.label_lower, relation.pk), manifest)
        self.assertIn((Avance._meta.label_lower, avance.pk), manifest)
        self.assertIn((Hito._meta.label_lower, hito.pk), manifest)
        self.assertIn((HitoHistorial._meta.label_lower, historial.pk), manifest)
        self.assertIn(
            (
                TareaRelacion._meta.db_table,
                relation_parent_column,
                Tarea._meta.db_table,
                _primary_key_column(Tarea),
                "PROTECT",
            ),
            first.orm_constraints,
        )
        self.assertIn(("UNVERIFIED", "sqlite"), first.physical_constraints)
        self.assertLess(
            order[(HitoHistorial._meta.label_lower, historial.pk)],
            order[(Hito._meta.label_lower, hito.pk)],
        )
        self.assertLess(
            order[(Hito._meta.label_lower, hito.pk)],
            order[(Tarea._meta.label_lower, root.pk)],
        )
        self.assertTrue(any("referencias lógicas" in item for item in first.blockers))
        self.assertTrue(any("FK físicas" in item for item in first.blockers))

    def test_manifest_changes_when_an_owned_dependency_is_added(self):
        task = self._task(correlativo="T0000001")
        initial = self._inventory(task)

        participant = TareaParticipante.objects.create(
            tarea=task,
            usuario=self.user,
        )
        updated = self._inventory(task)

        self.assertNotEqual(initial.fingerprint, updated.fingerprint)
        self.assertIn(
            (TareaParticipante._meta.label_lower, participant.pk),
            {(item.model_label, item.object_id) for item in updated.items},
        )

    def test_shared_hierarchy_and_external_origin_are_blockers(self):
        external_parent = self._task(correlativo="T0000001")
        selected = self._task(correlativo="T0000002")
        TareaRelacion.objects.create(padre=external_parent, hija=selected)
        external_origin = self._task(
            correlativo="T0000003",
            tarea_origen=selected,
        )

        inventory = self._inventory(selected)

        self.assertTrue(inventory.blockers)
        self.assertTrue(
            any("fuera del árbol" in blocker for blocker in inventory.blockers)
            or any("externa" in blocker for blocker in inventory.blockers)
        )
        self.assertNotIn(
            (Tarea._meta.label_lower, external_parent.pk),
            {(item.model_label, item.object_id) for item in inventory.items},
        )
        self.assertNotIn(
            (Tarea._meta.label_lower, external_origin.pk),
            {(item.model_label, item.object_id) for item in inventory.items},
        )

    def test_todo_origin_is_preserved_and_file_reference_blocks(self):
        todo = Todo.objects.create(
            empresa=self.empresa,
            correlativo="TD0000001",
            titulo="TO-DO conservado",
            creada_por=self.user,
        )
        task = self._task(correlativo="T0000001", todo_origen=todo)
        TodoEvento.objects.create(
            todo=todo,
            tipo=TodoEvento.Tipo.TAREA_CREADA,
            usuario=self.user,
            tarea=task,
        )
        hito = Hito.objects.create(
            tarea=task,
            nombre="Evidencia",
            responsable=self.user,
            cumplimiento=0,
            peso=Decimal("1.00"),
        )
        HitoEvidencia.objects.create(
            hito=hito,
            formato_archivo=HitoEvidencia.FormatoArchivo.PDF,
            archivo="tareas/hitos/evidencias/documento.pdf",
            usuario=self.user,
        )

        inventory = self._inventory(task)

        item_labels = {item.model_label for item in inventory.items}
        self.assertNotIn(Todo._meta.label_lower, item_labels)
        self.assertIn(TodoEvento._meta.label_lower, item_labels)
        self.assertTrue(
            any("TO-DO preservado" in blocker for blocker in inventory.blockers)
        )
        self.assertEqual(len(inventory.files), 1)
        self.assertEqual(inventory.files[0].storage_key, "default")
        self.assertEqual(
            inventory.file_classifications,
            (
                (
                    "default",
                    "tareas/hitos/evidencias/documento.pdf",
                    "BLOQUEADO",
                ),
            ),
        )
        self.assertTrue(
            any("exclusividad de los archivos" in item for item in inventory.blockers)
        )

    def test_permission_is_checked_before_operational_inventory(self):
        user_without_supervisor = User.objects.create_user(
            username="without-supervisor",
            password="test-password",
        )
        task = self._task(correlativo="T0000001")

        with patch(
            "tareas.services.permanent_deletion._resolve_backend",
            side_effect=AssertionError("operational inventory must not run"),
        ):
            with self.assertRaises(PermanentDeletionAuthorizationError):
                build_deletion_inventory(
                    actor=user_without_supervisor,
                    empresa_id=self.empresa.pk,
                    task_id=task.pk,
                )

    def test_confirmation_is_refused_when_inventory_has_any_blocker(self):
        task = self._task(correlativo="T0000001")
        inventory = self._inventory(task)

        with self.assertRaises(PermanentDeletionBlocked):
            issue_permanent_deletion_confirmation(
                actor=self.user,
                empresa_id=self.empresa.pk,
                task_id=task.pk,
                expected_fingerprint=inventory.fingerprint,
                confirmation_phrase=f"ELIMINAR {task.correlativo}",
            )

        self.assertTrue(Tarea.objects.filter(pk=task.pk).exists())
        self.assertFalse(TareaEliminacionOperacion.objects.exists())

    def test_sqlite_executor_fails_closed_without_persisting_or_deleting(self):
        task = self._task(correlativo="T0000001")
        backend = _resolve_backend()
        token = signing.dumps(
            {
                "actor_id": self.user.pk,
                "empresa_id": self.empresa.pk,
                "root_task_id": task.pk,
                "root_correlativo": task.correlativo,
                "backend_type": backend.backend_type,
                "backend_identity": backend.backend_identity,
                "backend_config_version": backend.config_version,
                "fingerprint": "a" * 64,
                "operation_id": uuid4().hex,
            },
            salt="tareas.permanent-deletion.v1",
            compress=True,
        )

        with self.assertRaises(TaskMutationLockUnsupported):
            execute_permanent_deletion(confirmation_token=token)

        self.assertTrue(Tarea.objects.filter(pk=task.pk).exists())
        self.assertFalse(TareaEliminacionOperacion.objects.exists())

    def test_reconciliation_reports_committed_without_replaying_audit_or_delete(self):
        backend = _resolve_backend()
        operation_id = uuid4()
        fingerprint = "b" * 64
        operation = TareaEliminacionOperacion.objects.create(
            operation_id=operation_id.hex,
            actor_id=self.user.pk,
            empresa_id=self.empresa.pk,
            root_task_id=999999,
            root_correlativo="T0999999",
            backend_type=backend.backend_type,
            backend_identity=backend.backend_identity,
            backend_config_version=backend.config_version,
            fingerprint=fingerprint,
            status=TareaEliminacionOperacion.Estado.COMMITTED,
            result_code="DELETED",
            audit_status=TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
        )
        TareaEliminacionElemento.objects.create(
            operacion=operation,
            tipo=Tarea._meta.label_lower,
            object_id=operation.root_task_id,
        )

        result = reconcile_permanent_deletion_operation(
            actor=self.user,
            empresa_id=self.empresa.pk,
            root_task_id=operation.root_task_id,
            operation_id=operation_id,
            fingerprint=fingerprint,
        )

        self.assertEqual(result.status, TareaEliminacionOperacion.Estado.COMMITTED)
        self.assertEqual(
            result.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
        )
        self.assertFalse(Tarea.objects.filter(pk=operation.root_task_id).exists())

    def test_reconciliation_never_retries_missing_or_pending_operation(self):
        backend = _resolve_backend()
        missing_id = uuid4()

        with self.assertRaises(PermanentDeletionCommitUnresolved):
            reconcile_permanent_deletion_operation(
                actor=self.user,
                empresa_id=self.empresa.pk,
                root_task_id=999998,
                operation_id=missing_id,
                fingerprint="c" * 64,
            )

        operation_id = uuid4()
        TareaEliminacionOperacion.objects.create(
            operation_id=operation_id.hex,
            actor_id=self.user.pk,
            empresa_id=self.empresa.pk,
            root_task_id=999997,
            root_correlativo="T0999997",
            backend_type=backend.backend_type,
            backend_identity=backend.backend_identity,
            backend_config_version=backend.config_version,
            fingerprint="d" * 64,
            status=TareaEliminacionOperacion.Estado.PENDIENTE,
        )

        with self.assertRaises(PermanentDeletionCommitUnresolved):
            reconcile_permanent_deletion_operation(
                actor=self.user,
                empresa_id=self.empresa.pk,
                root_task_id=999997,
                operation_id=operation_id,
                fingerprint="d" * 64,
            )

    def test_mysql_config_django_wrapper_uses_atomic_without_dbapi_begin(self):
        storage = MySQLDeletionLedgerStorage(
            SimpleNamespace(pk=17, updated_at=timezone.now()),
            "test_tasks",
        )
        django_connection = connections["default"]

        with (
            patch(
                "tareas.services.deletion_ledger.open_mysql_connection",
                return_value=nullcontext(django_connection),
            ),
            patch(
                "tareas.services.deletion_ledger._check_mysql_transactional_tables"
            ),
        ):
            with storage.atomic() as unit:
                self.assertIs(unit.connection, django_connection)

    def test_django_and_mysql_inventory_readers_return_same_foreign_keys(self):
        task = self._task(correlativo="T0000001")
        participant = TareaParticipante.objects.create(
            tarea=task,
            usuario=self.user,
        )
        django_reader = _DjangoReader("default")
        django_rows = _foreign_key_rows(
            django_reader,
            TareaParticipante,
            (participant.pk,),
        )

        class Cursor:
            def __init__(self):
                self.current_sql = ""
                self.statements = []
                self.closed = False

            def execute(self, sql, params=()):
                self.current_sql = sql
                self.statements.append((sql, params))

            def fetchall(self):
                if "INFORMATION_SCHEMA.TABLES" in self.current_sql:
                    return [
                        (model._meta.db_table,)
                        for model in get_operational_models()
                    ]
                return [(participant.pk, task.pk, self_user)]

            def fetchone(self):
                return None

            def close(self):
                self.closed = True

        class Connection:
            def __init__(self, cursor):
                self._cursor = cursor

            def cursor(self):
                return self._cursor

        self_user = self.user.pk
        cursor = Cursor()
        mysql_reader = _MySQLReader(Connection(cursor), "test_tasks")
        mysql_rows = _foreign_key_rows(
            mysql_reader,
            TareaParticipante,
            (participant.pk,),
        )
        mysql_reader.close()

        self.assertEqual(mysql_rows, django_rows)
        for sql, params in cursor.statements:
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"))
            self.assertIsInstance(params, tuple)

    @patch("tareas.services.audit.AuditoriaService.log_event")
    def test_audit_adapter_links_the_ledger_uuid_after_commit(
        self,
        log_event,
    ):
        from tareas.services.audit import log_permanent_deletion_operation

        event = type("AuditEvent", (), {"pk": 42})()
        log_event.return_value = event
        operation_id = uuid4().hex

        result = log_permanent_deletion_operation(
            actor=self.user,
            empresa_id=self.empresa.pk,
            task_id=123,
            operation_id=operation_id,
            fingerprint="e" * 64,
            backend_type="DJANGO",
            dependency_summary={"tareas.tarea": 1},
        )

        self.assertIs(result, event)
        self.assertEqual(log_event.call_args.kwargs["meta"]["operation_id"], operation_id)
        self.assertEqual(log_event.call_args.kwargs["action"], "DELETE")


class PermanentDeletionOrderTests(TestCase):
    def test_cycle_is_rejected_and_children_precede_parents(self):
        task = DeletionInventoryItem(Tarea._meta.label_lower, 1)
        child = DeletionInventoryItem("tareas.hito", 2)
        history = DeletionInventoryItem("tareas.hitohistorial", 3)
        items = (task, child, history)

        ordered, has_cycle = _topological_deletion_order(
            items,
            (
                ("tareas.hitohistorial", 3, "hito", "tareas.hito", 2),
                ("tareas.hito", 2, "tarea", "tareas.tarea", 1),
            ),
        )
        positions = {item: index for index, item in enumerate(ordered)}

        self.assertFalse(has_cycle)
        self.assertLess(positions[history], positions[child])
        self.assertLess(positions[child], positions[task])

        cyclic_order, has_cycle = _topological_deletion_order(
            (child, history),
            (
                ("tareas.hito", 2, "historial", "tareas.hitohistorial", 3),
                ("tareas.hitohistorial", 3, "hito", "tareas.hito", 2),
            ),
        )

        self.assertTrue(has_cycle)
        self.assertEqual(cyclic_order, ())


class PermanentDeletionMySQLMetadataTests(SimpleTestCase):
    class Cursor:
        def __init__(self, rows):
            self.rows = rows
            self.statements = []
            self.current_sql = ""

        def execute(self, sql, params=()):
            self.current_sql = sql
            self.statements.append((sql, params))

        def fetchall(self):
            if "KEY_COLUMN_USAGE" in self.current_sql:
                return list(self.rows)
            return []

        def fetchone(self):
            return None

        def close(self):
            pass

    class Connection:
        def __init__(self, rows):
            self._cursor = PermanentDeletionMySQLMetadataTests.Cursor(rows)

        def cursor(self):
            return self._cursor

    def _models_and_rows(self, *, rule="RESTRICT", omit_last=False):
        models = tuple(get_deletion_item_models())
        constraints = _orm_fk_contract(models)
        rows = [
            (
                "test_tasks",
                constraint[0],
                constraint[1],
                "test_tasks",
                constraint[2],
                constraint[3],
                rule,
            )
            for constraint in constraints
        ]
        if omit_last and rows:
            rows.pop()
        return models, rows

    def test_mysql_fk_verifier_requires_explicit_restrict_rules(self):
        models, rows = self._models_and_rows()
        item_ids = {model: set() for model in models}
        connection = self.Connection(rows)

        snapshot, blockers = _mysql_fk_snapshot(
            connection,
            "test_tasks",
            models,
            item_ids,
        )

        self.assertEqual(blockers, ())
        self.assertTrue(snapshot)
        for sql, params in connection._cursor.statements:
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"))
            self.assertIsInstance(params, tuple)

        models, cascade_rows = self._models_and_rows(rule="CASCADE")
        cascade_connection = self.Connection(cascade_rows)
        cascade_snapshot, blockers = _mysql_fk_snapshot(
            cascade_connection,
            "test_tasks",
            models,
            {model: set() for model in models},
        )

        self.assertTrue(cascade_snapshot)
        self.assertTrue(any("RESTRICT/NO ACTION" in blocker for blocker in blockers))

    def test_mysql_fk_verifier_rejects_missing_physical_constraints(self):
        models, rows = self._models_and_rows(omit_last=True)

        snapshot, blockers = _mysql_fk_snapshot(
            self.Connection(rows),
            "test_tasks",
            models,
            {model: set() for model in models},
        )

        self.assertTrue(snapshot)
        self.assertTrue(any("no contiene todas las FK" in blocker for blocker in blockers))
