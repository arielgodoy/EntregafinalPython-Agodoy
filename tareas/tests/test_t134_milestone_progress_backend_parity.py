from contextlib import ExitStack, contextmanager
from datetime import date
from decimal import Decimal
import sqlite3
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase

from access_control.models import Empresa, Permiso
from tareas.models import (
    Avance, Hito, HitoEvidencia, HitoHistorial, Tarea, TareaConnectionRole,
    TareaParticipante, TareaRelacion,
)
from tareas.services import milestone_storage as storage
from tareas.services.task_storage import TaskStorageError
from tareas.tests.factories import assign_permission


class ControlledMilestoneSQL:
    """Bound SQL executes against separate tables, not mocked return values."""

    def __init__(self, task):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.executescript("""
            CREATE TABLE tareas_tarea (
                id INTEGER PRIMARY KEY, empresa_id INTEGER, creada_por_id INTEGER,
                responsable_id INTEGER, estado TEXT, anulada INTEGER, correlativo TEXT,
                titulo TEXT, prioridad TEXT);
            CREATE TABLE tareas_tarearelacion (padre_id INTEGER, hija_id INTEGER);
            CREATE TABLE tareas_tareaparticipante (
                id INTEGER PRIMARY KEY, tarea_id INTEGER, usuario_id INTEGER, rol TEXT);
            CREATE TABLE tareas_hito (
                id INTEGER PRIMARY KEY AUTOINCREMENT, tarea_id INTEGER, nombre TEXT,
                responsable_id INTEGER, anulado INTEGER, completado INTEGER,
                completado_por_id INTEGER, fecha_completado TEXT, resena_cierre TEXT,
                cumplimiento NUMERIC, peso NUMERIC, fecha_creacion TEXT);
            CREATE TABLE tareas_hitohistorial (
                id INTEGER PRIMARY KEY AUTOINCREMENT, hito_id INTEGER, tipo_evento TEXT,
                usuario_id INTEGER, fecha TEXT, datos_anteriores TEXT,
                datos_nuevos TEXT, motivo TEXT);
            CREATE TABLE tareas_hitoevidencia (
                id INTEGER PRIMARY KEY AUTOINCREMENT, hito_id INTEGER, usuario_id INTEGER,
                formato_archivo TEXT, archivo TEXT, url TEXT, fecha TEXT);
            CREATE TABLE tareas_avance (
                id INTEGER PRIMARY KEY AUTOINCREMENT, tarea_id INTEGER UNIQUE,
                modo TEXT, porcentaje NUMERIC, fecha_actualizacion TEXT);
        """)
        self.db.execute(
            "INSERT INTO tareas_tarea VALUES (?,?,?,?,?,?,?,?,?)",
            (task.pk, task.empresa_id, task.creada_por_id, task.responsable_id,
             task.estado, task.anulada, task.correlativo, task.titulo, task.prioridad),
        )
        self.commands = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_sql = None
        self.fail_commit = False
        self.description = ()
        self.lastrowid = None
        self.rows = []

    def cursor(self):
        return self

    def close(self):
        pass

    def execute(self, sql, params=()):
        self.commands.append((sql, tuple(params)))
        if self.fail_sql and self.fail_sql in sql:
            raise RuntimeError("injected storage failure")
        translated = sql.replace("%s", "?").replace(" FOR UPDATE", "")
        if sql == "START TRANSACTION":
            translated = "BEGIN"
        bound = tuple(
            str(value) if isinstance(value, Decimal) else
            value.isoformat() if hasattr(value, "isoformat") else value for value in params
        )
        cursor = self.db.execute(translated, bound)
        self.description = cursor.description or ()
        self.lastrowid = cursor.lastrowid
        self.rows = cursor.fetchall()
        numeric = {
            index for index, column in enumerate(self.description)
            if column[0] in {"cumplimiento", "peso", "porcentaje"}
        }
        self.rows = [tuple(Decimal(str(value)).quantize(Decimal(".01")) if i in numeric else value
                           for i, value in enumerate(row)) for row in self.rows]

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("commit acknowledgement lost")
        self.db.commit()
        self.commits += 1

    def rollback(self):
        self.db.rollback()
        self.rollbacks += 1


class MilestoneProgressParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Empresa.objects.create(codigo="HITOPARITY")
        cls.other = Empresa.objects.create(codigo="HITOOTHER")
        cls.manager = User.objects.create_user("hito-parity-manager")
        cls.owner = User.objects.create_user("hito-parity-owner")
        cls.next_owner = User.objects.create_user("hito-parity-next")
        cls.observer = User.objects.create_user("hito-parity-observer")
        cls.inactive = User.objects.create_user("hito-parity-inactive", is_active=False)
        for actor in (cls.manager, cls.owner, cls.next_owner, cls.observer, cls.inactive):
            assign_permission(actor, cls.company, "Tareas - Hitos",
                              ingresar=True, crear=True, modificar=True, eliminar=True)
            assign_permission(actor, cls.company, "Tareas - Dashboard personal", ingresar=True)
        cls.role = TareaConnectionRole.objects.create(
            role="BASE_TAREAS", source_type="DJANGO", django_alias="default",
        )

    def setUp(self):
        self.task = Tarea.objects.create(
            empresa=self.company, creada_por=self.manager, responsable=self.manager,
            titulo="Hito parity", correlativo="B8900000", fecha_tope=date.today(),
            estado=Tarea.Estado.GESTION,
        )
        self.scope = dict(task_id=self.task.pk, empresa_id=self.company.pk, actor_id=self.manager.pk)
        self.django = storage.DjangoMilestoneStorage("default")
        self.sql = ControlledMilestoneSQL(self.task)
        self.mysql = storage.MySQLMilestoneStorage(object(), "operational_test")
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(self.sql.db.close)
        self.stack.enter_context(patch.object(storage, "open_mysql_connection", self.open_sql))
        self.files = InMemoryStorage()
        self.stack.enter_context(patch.object(HitoEvidencia._meta.get_field("archivo"), "storage", self.files))

    @contextmanager
    def open_sql(self, *args, **kwargs):
        yield self.sql

    def create(self, backend, **values):
        return backend.execute(storage.CreateMilestoneCommand(
            **self.scope, nombre=values.pop("nombre", "Milestone"),
            responsable_id=values.pop("responsable_id", self.owner.pk), **values,
        )).milestone_id

    def command(self, cls, hito_id=None, **values):
        scope = dict(self.scope)
        if "actor_id" in values:
            scope["actor_id"] = values.pop("actor_id")
        if hito_id is not None:
            scope["milestone_id"] = hito_id
        return cls(**scope, **values)

    def history(self, backend, hito_id):
        return backend.history(**self.scope, milestone_id=hito_id)

    def row(self, backend, hito_id):
        return backend._read(lambda adapter: adapter.hito(hito_id, self.task.pk))

    def progress(self, backend):
        return backend._read(lambda adapter: adapter.progress(self.task.pk))

    def complete(self, backend, hito_id, **values):
        args = dict(resena_cierre="Closure evidence", formato_archivo="PDF",
                    url="https://example.test/evidence.pdf")
        args.update(values)
        return backend.execute(self.command(storage.CompleteMilestoneCommand, hito_id, **args))

    def state(self, backend, **values):
        if backend is self.django:
            Tarea.objects.filter(pk=self.task.pk).update(**values)
        else:
            setters = ",".join(f"{key}=?" for key in values)
            self.sql.db.execute(f"UPDATE tareas_tarea SET {setters} WHERE id=?",
                                (*values.values(), self.task.pk))

    def test_create_edit_history_both_backends(self):
        for backend in (self.django, self.mysql):
            with self.subTest(backend=type(backend).__name__):
                hito_id = self.create(backend, cumplimiento=20, peso=2)
                backend.execute(self.command(storage.UpdateMilestoneCommand, hito_id,
                                             nombre="Changed", cumplimiento=40, peso=3))
                row = self.row(backend, hito_id)
                self.assertEqual((row.nombre, row.cumplimiento, row.peso), ("Changed", 40, 3))
                events = self.history(backend, hito_id)
                self.assertEqual([event.tipo_evento for event in events], [
                    "CREACION", "CAMBIO_NOMBRE", "CAMBIO_CUMPLIMIENTO", "CAMBIO_PESO",
                ])
                self.assertEqual(events[2].datos_anteriores["cumplimiento"], "20.00")
                self.assertEqual(events[2].datos_nuevos["cumplimiento"], "40")

    def test_noop_has_no_false_history_both_backends(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend)
            result = backend.execute(self.command(storage.UpdateMilestoneCommand, hito_id,
                                                  nombre="Milestone", cumplimiento=0, peso=1))
            self.assertFalse(result.changed)
            self.assertEqual(len(self.history(backend, hito_id)), 1)

    def test_persisted_before_not_mutated_model_instance(self):
        from tareas.services.progress import update_milestone
        hito_id = self.create(self.django, cumplimiento=20)
        hito = Hito.objects.get(pk=hito_id)
        hito.nombre, hito.cumplimiento = "Changed", Decimal("40")
        update_milestone(hito, self.manager, nombre="Changed", cumplimiento=40)
        persisted = Hito.objects.get(pk=hito_id)
        self.assertEqual((persisted.nombre, persisted.cumplimiento), ("Changed", 40))
        events = self.history(self.django, hito_id)
        self.assertEqual(events[2].datos_anteriores["cumplimiento"], "20.00")

    def test_complete_is_formal_preserves_owner_and_history_both(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend, cumplimiento=30)
            self.complete(backend, hito_id, actor_id=self.owner.pk)
            row = self.row(backend, hito_id)
            self.assertTrue(row.completado)
            self.assertEqual((row.cumplimiento, row.responsable_id), (100, self.owner.pk))
            history = self.history(backend, hito_id)
            self.assertEqual(history[-1].tipo_evento, "COMPLETADO")
            self.assertEqual(history[-1].usuario_id, self.owner.pk)
            self.assertIn("evidencia_id", history[-1].datos_nuevos)
            self.task.refresh_from_db()
            self.assertEqual(self.task.estado, Tarea.Estado.GESTION)

    def test_second_complete_stale_command_cannot_duplicate(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend)
            self.complete(backend, hito_id)
            with self.assertRaises(ValidationError):
                self.complete(backend, hito_id)
            self.assertEqual([e.tipo_evento for e in self.history(backend, hito_id)].count("COMPLETADO"), 1)

    def test_completed_frozen_for_edit_and_reassignment_both(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend)
            self.complete(backend, hito_id)
            for cmd in (
                self.command(storage.UpdateMilestoneCommand, hito_id, nombre="Forbidden"),
                self.command(storage.ReassignMilestoneCommand, hito_id,
                             responsable_id=self.next_owner.pk, motivo="Reason"),
            ):
                with self.assertRaises(ValidationError):
                    backend.execute(cmd)
            self.assertEqual(self.row(backend, hito_id).nombre, "Milestone")

    def test_reassignment_requires_reason_updates_participation_both(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend)
            with self.assertRaises(ValidationError):
                backend.execute(self.command(storage.ReassignMilestoneCommand, hito_id,
                                             responsable_id=self.next_owner.pk, motivo=" "))
            backend.execute(self.command(storage.ReassignMilestoneCommand, hito_id,
                                         responsable_id=self.next_owner.pk, motivo=" Reason "))
            self.assertFalse(backend.assigned(empresa_id=self.company.pk, actor_id=self.owner.pk))
            self.assertEqual(len(backend.assigned(empresa_id=self.company.pk, actor_id=self.next_owner.pk)), 1)
            self.assertEqual(self.history(backend, hito_id)[-1].motivo, "Reason")

    def test_annul_reactivate_preserves_completed_state_both(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend)
            self.complete(backend, hito_id)
            for annulled in (True, False):
                backend.execute(self.command(storage.SetMilestoneAnnulledCommand, hito_id, anulado=annulled))
                row = self.row(backend, hito_id)
                self.assertEqual(bool(row.anulado), annulled)
                self.assertTrue(row.completado)
                self.assertEqual(row.cumplimiento, 100)
                self.assertEqual(len(backend.assigned(empresa_id=self.company.pk, actor_id=self.owner.pk)),
                                 0 if annulled else 1)

    def test_delete_clean_hito_physically_both(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend)
            result = backend.execute(self.command(storage.DeleteMilestoneCommand, hito_id))
            self.assertTrue(result.deleted)
            with self.assertRaises(storage.MilestoneNotFound):
                self.row(backend, hito_id)

    def test_delete_history_turns_into_logical_annul_both(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend)
            backend.execute(self.command(storage.UpdateMilestoneCommand, hito_id, cumplimiento=20))
            result = backend.execute(self.command(storage.DeleteMilestoneCommand, hito_id))
            self.assertFalse(result.deleted)
            self.assertTrue(self.row(backend, hito_id).anulado)
            self.assertEqual(len(self.history(backend, hito_id)), 3)

    def test_delete_evidence_preserves_hito_and_evidence_both(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend)
            if backend is self.django:
                HitoEvidencia.objects.create(hito_id=hito_id, usuario=self.manager,
                                            formato_archivo="PDF", url="https://example.test/a.pdf")
            else:
                self.sql.db.execute(
                    "INSERT INTO tareas_hitoevidencia (hito_id,usuario_id,formato_archivo,url) VALUES (?,?,?,?)",
                    (hito_id, self.manager.pk, "PDF", "https://example.test/a.pdf"),
                )
            result = backend.execute(self.command(storage.DeleteMilestoneCommand, hito_id))
            self.assertFalse(result.deleted)
            self.assertTrue(backend._read(lambda adapter: adapter.has_evidence(hito_id)))

    def test_simple_progress_range_downward_and_no_auto_close_both(self):
        for backend in (self.django, self.mysql):
            for value in (100, 42.5, 0):
                backend.execute(self.command(storage.UpdateManualProgressCommand, porcentaje=value))
                self.assertEqual(self.progress(backend).porcentaje, value)
            for value in (-1, 101, "NaN"):
                with self.assertRaises(ValidationError):
                    backend.execute(self.command(storage.UpdateManualProgressCommand, porcentaje=value))
            self.task.refresh_from_db()
            self.assertEqual(self.task.estado, Tarea.Estado.GESTION)

    def test_invalid_manual_does_not_leave_initial_row_both(self):
        for backend in (self.django, self.mysql):
            with self.assertRaises(ValidationError):
                backend.execute(self.command(storage.UpdateManualProgressCommand, porcentaje=101))
            self.assertIsNone(self.progress(backend))

    def test_weighted_formula_and_mode_refresh_both(self):
        for backend in (self.django, self.mysql):
            backend.execute(self.command(storage.UpdateManualProgressCommand, porcentaje=20))
            first = self.create(backend, nombre="First", cumplimiento=50, peso=1)
            second = self.create(backend, nombre="Second", cumplimiento=100, peso=3)
            backend.execute(self.command(storage.SetWeightedProgressModeCommand))
            self.assertEqual(self.progress(backend).porcentaje, Decimal("87.50"))
            backend.execute(self.command(storage.UpdateMilestoneCommand, first, cumplimiento=0, peso=5))
            self.assertEqual(self.progress(backend).porcentaje, Decimal("37.50"))
            backend.execute(self.command(storage.SetMilestoneAnnulledCommand, second, anulado=True))
            self.assertEqual(self.progress(backend).porcentaje, 0)
            with self.assertRaises(ValidationError):
                backend.execute(self.command(storage.UpdateManualProgressCommand, porcentaje=20))

    def test_weighted_examples_redistribute_both(self):
        for backend in (self.django, self.mysql):
            backend.execute(self.command(storage.SetWeightedProgressModeCommand))
            self.create(backend, cumplimiento=100, peso=4)
            second = self.create(backend, cumplimiento=0, peso=1)
            self.assertEqual(self.progress(backend).porcentaje, 80)
            backend.execute(self.command(storage.UpdateMilestoneCommand, second, cumplimiento=50))
            self.assertEqual(self.progress(backend).porcentaje, 90)
            self.create(backend, cumplimiento=0, peso=2)
            self.assertEqual(self.progress(backend).porcentaje, Decimal("64.29"))

    def test_contextual_roles_do_not_replace_action_permissions(self):
        hito_id = self.create(self.django)
        permission = Permiso.objects.get(usuario=self.manager, empresa=self.company,
                                         vista__nombre="Tareas - Hitos")
        for flag, command in (
            ("crear", storage.CreateMilestoneCommand(**self.scope, nombre="Denied", responsable_id=self.owner.pk)),
            ("modificar", self.command(storage.UpdateMilestoneCommand, hito_id, cumplimiento=30)),
            ("eliminar", self.command(storage.DeleteMilestoneCommand, hito_id)),
        ):
            setattr(permission, flag, False)
            permission.save(update_fields=[flag])
            for backend in (self.django, self.mysql):
                with self.assertRaises(PermissionDenied):
                    backend.execute(command)
            setattr(permission, flag, True)
            permission.save(update_fields=[flag])

    def test_owner_compliance_only_and_observer_read_only_both(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend)
            backend.execute(self.command(storage.UpdateMilestoneCommand, hito_id,
                                         actor_id=self.owner.pk, cumplimiento=100))
            self.assertFalse(self.row(backend, hito_id).completado)
            for actor_id, changes in ((self.owner.pk, {"peso": 3}),
                                       (self.observer.pk, {"cumplimiento": 30})):
                with self.assertRaises(PermissionDenied):
                    backend.execute(self.command(storage.UpdateMilestoneCommand, hito_id,
                                                 actor_id=actor_id, **changes))

    def test_state_matrix_all_writes_both(self):
        for backend in (self.django, self.mysql):
            for state in ("BORRADOR", "ACTIVA", "GESTION"):
                self.state(backend, estado=state)
                self.create(backend)
            for state in ("PENDIENTE_APROBACION_CIERRE", "CERRADA"):
                self.state(backend, estado=state)
                for command in (
                    storage.CreateMilestoneCommand(**self.scope, nombre="Denied", responsable_id=self.owner.pk),
                    self.command(storage.UpdateManualProgressCommand, porcentaje=20),
                ):
                    with self.assertRaises(ValidationError):
                        backend.execute(command)

    def test_pending_closed_annulled_block_every_milestone_action_both(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend)
            commands = (
                self.command(storage.UpdateMilestoneCommand, hito_id, cumplimiento=70),
                self.command(storage.CompleteMilestoneCommand, hito_id,
                             resena_cierre="Closure", formato_archivo="PDF", url="https://example.test/a.pdf"),
                self.command(storage.ReassignMilestoneCommand, hito_id,
                             responsable_id=self.next_owner.pk, motivo="Reason"),
                self.command(storage.SetMilestoneAnnulledCommand, hito_id, anulado=True),
                self.command(storage.SetMilestoneAnnulledCommand, hito_id, anulado=False),
                self.command(storage.DeleteMilestoneCommand, hito_id),
                self.command(storage.UpdateManualProgressCommand, porcentaje=30),
                self.command(storage.SetWeightedProgressModeCommand),
            )
            for state, annulled in (
                ("PENDIENTE_APROBACION_CIERRE", False), ("CERRADA", False), ("GESTION", True),
            ):
                self.state(backend, estado=state, anulada=annulled)
                for command in commands:
                    with self.assertRaises(ValidationError):
                        backend.execute(command)
            self.assertEqual(len(self.history(backend, hito_id)), 1)

    def test_strict_ingresar_history_and_detail_before_read_both(self):
        ids = [(backend, self.create(backend)) for backend in (self.django, self.mysql)]
        Permiso.objects.filter(usuario=self.manager, empresa=self.company,
                               vista__nombre="Tareas - Hitos").update(ingresar=False)
        for backend, hito_id in ids:
            with self.assertRaises(PermissionDenied):
                self.history(backend, hito_id)
            with self.assertRaises(PermissionDenied):
                backend.detail(**self.scope)

    def test_mysql_legacy_object_is_rejected_before_relation_lookup(self):
        from tareas.services import progress
        hito_id = self.create(self.django)
        hito = Hito.objects.get(pk=hito_id)
        with patch.object(progress, "resolve_milestone_storage", return_value=self.mysql):
            with patch.object(Tarea.objects, "using", side_effect=AssertionError("operational lookup")):
                with self.assertRaises(TaskStorageError):
                    progress.update_milestone(hito, self.manager, cumplimiento=60)
                with self.assertRaises(TaskStorageError):
                    progress.create_milestone(self.task, "Wrong backend", responsable=self.owner, actor=self.manager)
        self.assertEqual(Hito.objects.get(pk=hito_id).cumplimiento, 0)
        self.assertFalse(self.sql.commands)

    def test_evidence_validation_keeps_completion_atomic_both(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend)
            for values in (
                {"resena_cierre": " "}, {"url": ""},
                {"archivo": SimpleUploadedFile("both.pdf", b"pdf")},
                {"url": "", "archivo": SimpleUploadedFile("bad.exe", b"bad")},
            ):
                with self.assertRaises(ValidationError):
                    self.complete(backend, hito_id, **values)
                self.assertFalse(self.row(backend, hito_id).completado)
                self.assertFalse(backend._read(lambda adapter: adapter.has_evidence(hito_id)))
                self.assertEqual(len(self.history(backend, hito_id)), 1)

    def test_annul_reactivate_and_clean_delete_recalculate_weighted_both(self):
        for backend in (self.django, self.mysql):
            backend.execute(self.command(storage.SetWeightedProgressModeCommand))
            first = self.create(backend, cumplimiento=100, peso=1)
            second = self.create(backend, cumplimiento=0, peso=1)
            backend.execute(self.command(storage.SetMilestoneAnnulledCommand, second, anulado=True))
            self.assertEqual(self.progress(backend).porcentaje, 100)
            backend.execute(self.command(storage.SetMilestoneAnnulledCommand, second, anulado=False))
            self.assertEqual(self.progress(backend).porcentaje, 50)
            backend.execute(self.command(storage.DeleteMilestoneCommand, first))
            self.assertEqual(self.progress(backend).porcentaje, 0)

    def test_annul_idempotent_no_false_history_both(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend)
            cmd = self.command(storage.SetMilestoneAnnulledCommand, hito_id, anulado=True)
            backend.execute(cmd)
            self.assertFalse(backend.execute(cmd).changed)
            self.assertEqual(len(self.history(backend, hito_id)), 2)

    def test_participant_contextual_manager_with_strict_flags_both(self):
        TareaParticipante.objects.create(
            tarea=self.task, usuario=self.observer, rol=TareaParticipante.Rol.RESPONSABLE_LIDER,
        )
        self.sql.db.execute("INSERT INTO tareas_tareaparticipante (tarea_id,usuario_id,rol) VALUES (?,?,?)",
                            (self.task.pk, self.observer.pk, "RESPONSABLE_LIDER"))
        for backend in (self.django, self.mysql):
            result = backend.execute(storage.CreateMilestoneCommand(
                task_id=self.task.pk, empresa_id=self.company.pk, actor_id=self.observer.pk,
                nombre="Leader owned", responsable_id=self.owner.pk,
            ))
            self.assertEqual(self.row(backend, result.milestone_id).nombre, "Leader owned")

    def test_effective_annulment_parent_blocks_both(self):
        parent = Tarea.objects.create(empresa=self.company, creada_por=self.manager,
                                     titulo="Parent", correlativo="B8900001", anulada=True)
        TareaRelacion.objects.create(padre=parent, hija=self.task)
        self.sql.db.execute("INSERT INTO tareas_tarea VALUES (?,?,?,?,?,?,?,?,?)",
                            (parent.pk, self.company.pk, self.manager.pk, self.manager.pk,
                             "ACTIVA", True, parent.correlativo, parent.titulo, parent.prioridad))
        self.sql.db.execute("INSERT INTO tareas_tarearelacion VALUES (?,?)", (parent.pk, self.task.pk))
        for backend in (self.django, self.mysql):
            with self.assertRaises(ValidationError):
                self.create(backend)

    def test_cross_company_and_invalid_targets_rejected_both(self):
        assign_permission(self.manager, self.other, "Tareas - Hitos", crear=True)
        for backend in (self.django, self.mysql):
            with self.assertRaises(storage.MilestoneNotFound):
                backend.execute(storage.CreateMilestoneCommand(
                    task_id=self.task.pk, empresa_id=self.other.pk, actor_id=self.manager.pk,
                    nombre="Denied", responsable_id=self.owner.pk,
                ))
            for values in ({"responsable_id": self.inactive.pk}, {"peso": 0}, {"cumplimiento": 101}):
                with self.assertRaises(ValidationError):
                    self.create(backend, **values)

    def test_same_pk_mysql_does_not_read_write_default_operational_models(self):
        default_id = self.create(self.django, nombre="Default sentinel", cumplimiento=17)
        before = {model: list(model.objects.values()) for model in (Tarea, Hito, Avance, HitoHistorial, HitoEvidencia)}
        with ExitStack() as stack:
            for model in (Tarea, Hito, Avance, HitoHistorial, HitoEvidencia, TareaParticipante, TareaRelacion):
                stack.enter_context(patch.object(model.objects, "using", side_effect=AssertionError("default escape")))
            self.state(self.mysql, estado="ACTIVA")
            hito_id = self.create(self.mysql, nombre="MySQL only")
            self.assertEqual(hito_id, default_id)
            self.complete(self.mysql, hito_id)
            self.mysql.execute(self.command(storage.UpdateManualProgressCommand, porcentaje=48))
            self.mysql.execute(self.command(storage.SetWeightedProgressModeCommand))
        for model, snapshot in before.items():
            self.assertEqual(list(model.objects.values()), snapshot)

    def test_sql_parametrized_scoped_locks_and_commit(self):
        hito_id = self.create(self.mysql, nombre="'); DELETE FROM tareas_tarea; --")
        self.mysql.execute(self.command(storage.UpdateMilestoneCommand, hito_id, cumplimiento=30))
        sqls = [sql for sql, params in self.sql.commands]
        self.assertTrue(any("WHERE id=%s AND empresa_id=%s FOR UPDATE" in sql for sql in sqls))
        self.assertTrue(any("WHERE id=%s AND tarea_id=%s FOR UPDATE" in sql for sql in sqls))
        self.assertTrue(all("DELETE FROM tareas_tarea;" not in sql for sql in sqls))
        self.assertEqual(self.sql.commits, 2)

    def test_history_failure_rolls_back_aggregate_and_new_file_both(self):
        for backend in (self.django, self.mysql):
            hito_id = self.create(backend)
            with patch.object(storage, "_history", side_effect=RuntimeError("failure")):
                with self.assertRaises(TaskStorageError):
                    self.complete(backend, hito_id, archivo=SimpleUploadedFile("rollback.pdf", b"pdf"), url="")
            self.assertFalse(self.row(backend, hito_id).completado)
            self.assertFalse(backend._read(lambda adapter: adapter.has_evidence(hito_id)))
            self.assertEqual(self.files.listdir("tareas/hitos/evidencias")[1], [])

    def test_uncertain_commit_retains_new_file(self):
        hito_id = self.create(self.mysql)
        self.sql.fail_commit = True
        with self.assertRaises(TaskStorageError):
            self.complete(self.mysql, hito_id, archivo=SimpleUploadedFile("uncertain.pdf", b"pdf"), url="")
        self.assertTrue(self.files.listdir("tareas/hitos/evidencias")[1])

    def test_resolver_fail_closed_without_operational_lookup(self):
        for error in (RuntimeError("secret"), ValidationError("inactive")):
            with patch.object(storage, "get_tarea_connection", side_effect=error):
                with patch.object(Tarea.objects, "using", side_effect=AssertionError("fallback")):
                    with self.assertRaises(TaskStorageError):
                        storage.resolve_milestone_storage()

    def test_resolver_selects_configured_source_not_default(self):
        with patch.object(storage, "get_tarea_connection", return_value={
            "type": "DJANGO", "alias": "company_tasks",
        }):
            self.assertEqual(storage.resolve_milestone_storage().alias, "company_tasks")
        config = object()
        with patch.object(storage, "get_tarea_connection", return_value={
            "type": "MYSQL_CONFIG", "database_name": "configured_tasks",
        }):
            with patch.object(storage, "get_tarea_mysql_connection", return_value=config):
                resolved = storage.resolve_milestone_storage()
                self.assertIs(resolved.connection_config, config)
                self.assertEqual(resolved.database_name, "configured_tasks")

    def test_mysql_connection_failure_sanitized_and_no_default_fallback(self):
        @contextmanager
        def unavailable(*args, **kwargs):
            raise RuntimeError("credential-sensitive diagnostic")
            yield
        with patch.object(storage, "open_mysql_connection", unavailable):
            with self.assertRaises(TaskStorageError) as failure:
                self.create(self.mysql)
            self.assertNotIn("credential-sensitive", str(failure.exception))
        self.assertFalse(Hito.objects.exists())
        self.assertFalse(Avance.objects.exists())

    def test_milestone_of_sibling_task_cannot_be_targeted_both(self):
        sibling = Tarea.objects.create(empresa=self.company, creada_por=self.manager,
                                      titulo="Sibling", correlativo="B8900002")
        Hito.objects.create(tarea=sibling, nombre="Foreign hito", responsable=self.owner, peso=1)
        self.sql.db.execute(
            "INSERT INTO tareas_hito (tarea_id,nombre,responsable_id,anulado,completado,cumplimiento,peso)"
            " VALUES (?,?,?,?,?,?,?)",
            (sibling.pk, "Foreign hito", self.owner.pk, False, False, 0, 1),
        )
        for backend in (self.django, self.mysql):
            with self.assertRaises(storage.MilestoneNotFound):
                backend.execute(self.command(storage.UpdateMilestoneCommand, 1, cumplimiento=30))

    def test_nondefault_alias_propagates_every_operational_access(self):
        aliases = []
        atomic = transaction.atomic
        with ExitStack() as stack:
            for model in (Tarea, TareaRelacion, TareaParticipante, Hito, Avance, HitoHistorial, HitoEvidencia):
                original = model.objects.using
                def using(alias, original=original):
                    aliases.append(alias)
                    return original("default")
                stack.enter_context(patch.object(model.objects, "using", using))
            transaction_aliases = []
            def begin(using=None, **kwargs):
                if using == "operational_alias":
                    transaction_aliases.append(using)
                return atomic(using="default", **kwargs)
            stack.enter_context(patch.object(transaction, "atomic", begin))
            backend = storage.DjangoMilestoneStorage("operational_alias")
            hito_id = self.create(backend)
            backend.execute(self.command(storage.SetWeightedProgressModeCommand))
            self.complete(backend, hito_id)
            self.history(backend, hito_id)
            backend.execute(self.command(storage.SetMilestoneAnnulledCommand, hito_id, anulado=True))
        self.assertEqual(set(aliases), {"operational_alias"})
        self.assertEqual(set(transaction_aliases), {"operational_alias"})
        self.assertEqual(len(transaction_aliases), 4)
