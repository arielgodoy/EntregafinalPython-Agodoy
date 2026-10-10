from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import date
import json
import re
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections, transaction
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa
from tareas.models import (
    Comentario, ComentarioAdjunto, ComentarioPausaLectura, ComentarioVersion,
    ComentarioVersionDocumento, DocumentoHistorial, DocumentoTarea, Hito,
    MiniTarea, MiniTareaEvento, Tarea, TareaConnectionRole, TareaLectura,
    TareaParticipante, TareaRelacion,
)
from tareas.services import minitask_storage as storage
from tareas.services.connection_roles import BackendContext
from tareas.services.closure import validate_closure_requirements
from tareas.services.task_storage import TaskStorageError
from tareas.tests.factories import activate_company, assign_permission


class MiniSQLConnection:
    """Stateful SQL fake: applies bound values and restores its tables on rollback."""

    def __init__(self, task):
        self.tables = {model._meta.db_table: {} for model in (
            MiniTarea, MiniTareaEvento, Comentario, ComentarioVersion, DocumentoTarea,
            DocumentoHistorial, ComentarioAdjunto, ComentarioVersionDocumento,
            TareaLectura, ComentarioPausaLectura,
        )}
        self.task = task
        self.commands = []
        self.commits = 0
        self.rollbacks = 0
        self.lastrowid = 0
        self.rows = []
        self.fail_table = None
        self.annulled_parent = False
        self.existing_effective = set()

    def cursor(self):
        return self

    def close(self):
        pass

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1
        self.tables = self.snapshot

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        params = tuple(params)
        self.commands.append((sql, params))
        self.rows = []
        if sql == "START TRANSACTION":
            self.snapshot = deepcopy(self.tables)
        elif sql.startswith("INSERT INTO "):
            match = re.match(r"INSERT INTO (\w+) \((.*?)\) VALUES", sql)
            table, columns = match.groups()
            if table == self.fail_table:
                raise RuntimeError("injected persistence failure")
            self.lastrowid = max(self.tables[table], default=0) + 1
            row = dict(zip(columns.split(", "), params))
            row["id"] = self.lastrowid
            self.tables[table][self.lastrowid] = row
        elif sql.startswith("SELECT id, empresa_id"):
            task = self.task
            if params == (task.pk, task.empresa_id):
                self.rows = [(
                    task.pk, task.empresa_id, task.creada_por_id, task.responsable_id,
                    task.estado, task.anulada, task.prioridad, task.titulo,
                )]
        elif sql.startswith("SELECT p.id"):
            if self.annulled_parent and params[0] == self.task.pk:
                self.rows = [(999, True)]
        elif sql.startswith("SELECT id, persona_id"):
            row = self.tables["tareas_minitarea"].get(params[0])
            if row and row["tarea_id"] == params[1]:
                self.rows = [(row["id"], row["persona_id"], row["descripcion"], row["hecho"])]
        elif sql.startswith("SELECT usuario_id"):
            ids = self.existing_effective | {
                row["persona_id"] for row in self.tables["tareas_minitarea"].values()
                if row["tarea_id"] == params[0]
            }
            self.rows = [(value,) for value in sorted(ids)]
        elif sql.startswith("SELECT id FROM tareas_comentario"):
            rows = [row for row in self.tables["tareas_comentario"].values() if row["tarea_id"] == params[0]]
            if rows:
                self.rows = [(max(rows, key=lambda row: (row["created_at"], row["id"]))["id"],)]
        elif sql.startswith("SELECT id FROM tareas_tarealectura"):
            self.rows = [(row["id"],) for row in self.tables["tareas_tarealectura"].values()
                         if (row["tarea_id"], row["usuario_id"]) == params]
        elif sql.startswith("SELECT id FROM tareas_minitareaevento"):
            self.rows = [(row["id"],) for row in self.tables["tareas_minitareaevento"].values()
                         if row["mini_tarea_id"] == params[0]][:1]
        elif sql.startswith("SELECT m.id, m.descripcion"):
            task = self.task
            if params[1] == task.empresa_id and not task.anulada and task.estado in params[2:]:
                self.rows = [
                    (row["id"], row["descripcion"], row["hecho"], task.pk,
                     task.correlativo, task.titulo, task.responsable_id)
                    for row in self.tables["tareas_minitarea"].values()
                    if row["persona_id"] == params[0] and row["tarea_id"] == task.pk
                ]
        elif sql.startswith("UPDATE tareas_minitarea"):
            row = self.tables["tareas_minitarea"].get(params[2])
            if row and row["tarea_id"] == params[3]:
                row.update(hecho=params[0], fecha_completado=params[1])
        elif sql.startswith("DELETE FROM tareas_minitarea"):
            row = self.tables["tareas_minitarea"].get(params[0])
            if row and row["tarea_id"] == params[1]:
                del self.tables["tareas_minitarea"][params[0]]
        else:
            raise AssertionError(f"Unhandled fake SQL: {sql}")

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class MiniTaskParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Empresa.objects.create(codigo="00")
        cls.other = Empresa.objects.create(codigo="02")
        cls.responsible = User.objects.create_user("mini-responsible", email="responsible@example.test")
        cls.assigned = User.objects.create_user("mini-assigned", email="assigned@example.test")
        cls.supervisor = User.objects.create_user("mini-supervisor", email="supervisor@example.test")
        cls.outsider = User.objects.create_user("mini-outsider")
        cls.inactive = User.objects.create_user("mini-inactive", is_active=False)
        for user in (cls.responsible, cls.assigned, cls.supervisor, cls.outsider, cls.inactive):
            assign_permission(user, cls.company, "Tareas", ingresar=True, crear=True,
                              modificar=True, supervisor=user == cls.supervisor)
        assign_permission(cls.assigned, cls.company, "Tareas - Dashboard personal", ingresar=True)
        cls.role = TareaConnectionRole.objects.create(
            role="BASE_TAREAS", source_type="DJANGO", django_alias="default",
        )

    def setUp(self):
        self.task = Tarea.objects.create(
            empresa=self.company, creada_por=self.responsible, responsable=self.responsible,
            titulo="Mini parity", fecha_tope=date.today(), estado=Tarea.Estado.GESTION,
        )
        self.scope = dict(task_id=self.task.pk, empresa_id=self.company.pk, actor_id=self.responsible.pk)
        self.django = storage.DjangoMiniTaskStorage("default")
        self.sql = MiniSQLConnection(self.task)
        self.mysql = storage.MySQLMiniTaskStorage(object(), "test_operational")
        self.file_storage = InMemoryStorage()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(DocumentoTarea._meta.get_field("archivo"), "storage", self.file_storage))
        self.stack.enter_context(patch.object(storage, "open_mysql_connection", self.open_fake))

    @contextmanager
    def open_fake(self, *args, **kwargs):
        yield self.sql

    def create(self, backend, **overrides):
        values = dict(self.scope, persona_id=self.assigned.pk, descripcion="Complete work")
        values.update(overrides)
        return backend.create(storage.CreateMiniTaskCommand(**values))

    def close(self, backend, mini_id, **overrides):
        values = dict(self.scope, mini_task_id=mini_id, comentario="Ready")
        values.update(overrides)
        return backend.close(storage.CloseMiniTaskCommand(**values))

    def reopen(self, backend, mini_id, **overrides):
        values = dict(self.scope, mini_task_id=mini_id, comentario="One more step")
        values.update(overrides)
        return backend.reopen(storage.ReopenMiniTaskCommand(**values))

    def delete(self, backend, mini_id):
        return backend.delete(storage.DeleteMiniTaskCommand(**self.scope, mini_task_id=mini_id))

    def test_django_complete_cycle_and_event_snapshots(self):
        mini_id = self.create(self.django).mini_task_id
        self.assertFalse(MiniTareaEvento.objects.exists())
        close = self.close(self.django, mini_id, actor_id=self.assigned.pk)
        mini = MiniTarea.objects.get(pk=mini_id)
        self.assertTrue(mini.hecho)
        self.assertIsNotNone(mini.fecha_completado)
        self.assertIsNotNone(close.comentario_feed_id)
        reopen = self.reopen(self.django, mini_id)
        self.assertIsNone(reopen.comentario_feed_id)
        mini.refresh_from_db()
        self.assertFalse(mini.hecho)
        self.assertIsNone(mini.fecha_completado)
        second = self.close(self.django, mini_id)
        self.assertNotEqual(second.event_id, close.event_id)
        self.assertEqual(list(MiniTareaEvento.objects.values_list("tipo", flat=True)),
                         ["CIERRE", "REAPERTURA", "CIERRE"])
        self.assertEqual(Comentario.objects.count(), 2)

    def test_django_close_full_document_aggregate_and_preserved_cursor(self):
        previous = Comentario.objects.create(tarea=self.task, autor=self.responsible, contenido="previous")
        reading = TareaLectura.objects.create(tarea=self.task, usuario=self.assigned)
        cursor = reading.comentario_leido_hasta_id
        mini_id = self.create(self.django).mini_task_id
        TareaParticipante.objects.create(tarea=self.task, usuario=self.inactive)
        result = self.close(self.django, mini_id, uploaded_files=(
            SimpleUploadedFile("proof.pdf", b"%PDF-1.4\nproof"),))
        feed = Comentario.objects.get(pk=result.comentario_feed_id)
        self.assertEqual(feed.autor_id, self.responsible.pk)
        self.assertIn('Ha completado la MiniTarea "Complete work".', feed.contenido)
        self.assertEqual(feed.versiones.get().numero_version, 1)
        document = feed.adjuntos.get().documento
        self.assertEqual(document.tipo, "OTRO")
        self.assertEqual(document.historial.get().accion, "CREADO")
        self.assertEqual(feed.versiones.get().documentos.get().documento_id, document.pk)
        self.assertTrue(self.file_storage.exists(document.archivo.name))
        reading.refresh_from_db()
        self.assertEqual(reading.comentario_leido_hasta_id, cursor)
        new_reading = TareaLectura.objects.get(tarea=self.task, usuario=self.inactive)
        self.assertEqual(new_reading.comentario_leido_hasta_id, previous.pk)
        self.assertTrue(new_reading.pausas_comentarios.filter(hasta__isnull=True).exists())

    def test_mysql_complete_cycle_full_aggregate_and_parameterized_scope(self):
        mini_id = self.create(self.mysql).mini_task_id
        self.assertEqual(self.sql.tables["tareas_minitareaevento"], {})
        close = self.close(self.mysql, mini_id, actor_id=self.assigned.pk,
                           uploaded_files=(SimpleUploadedFile("proof.pdf", b"%PDF-1.4\nproof"),))
        for table in ("tareas_comentario", "tareas_comentarioversion", "tareas_documentotarea",
                      "tareas_documentohistorial", "tareas_comentarioadjunto",
                      "tareas_comentarioversiondocumento", "tareas_tarealectura"):
            self.assertTrue(self.sql.tables[table], table)
        self.assertTrue(self.sql.tables["tareas_minitarea"][mini_id]["hecho"])
        self.reopen(self.mysql, mini_id)
        self.assertIsNone(self.sql.tables["tareas_minitarea"][mini_id]["fecha_completado"])
        second = self.close(self.mysql, mini_id)
        self.assertNotEqual(close.event_id, second.event_id)
        events = list(self.sql.tables["tareas_minitareaevento"].values())
        self.assertEqual([row["tipo"] for row in events], ["CIERRE", "REAPERTURA", "CIERRE"])
        self.assertIsNone(events[1]["comentario_feed_id"])
        self.assertEqual(json.loads(events[1]["destinatarios_email"]), [])
        self.assertEqual(self.sql.commits, 4)
        self.assertEqual(self.sql.rollbacks, 0)
        locks = [(sql, params) for sql, params in self.sql.commands if "FOR UPDATE" in sql]
        self.assertTrue(any("empresa_id=%s" in sql and params == (
            self.task.pk, self.company.pk) for sql, params in locks))
        self.assertTrue(any("tarea_id=%s" in sql and params == (mini_id, self.task.pk)
                            for sql, params in locks))

    def test_both_backends_delete_only_pending_without_any_events(self):
        for backend in (self.django, self.mysql):
            with self.subTest(backend=type(backend).__name__):
                mini_id = self.create(backend).mini_task_id
                self.delete(backend, mini_id)
                mini_id = self.create(backend).mini_task_id
                self.close(backend, mini_id)
                with self.assertRaises(ValidationError):
                    self.delete(backend, mini_id)
                self.reopen(backend, mini_id)
                with self.assertRaises(ValidationError):
                    self.delete(backend, mini_id)

    def test_both_backends_reject_frozen_states_and_direct_annulment(self):
        for backend in (self.django, self.mysql):
            for state in ("BORRADOR", "PENDIENTE_APROBACION_CIERRE", "CERRADA"):
                self.task.estado = state
                Tarea.objects.filter(pk=self.task.pk).update(estado=state)
                with self.subTest(backend=type(backend).__name__, state=state):
                    with self.assertRaises(ValidationError):
                        self.create(backend)
            self.task.estado = "GESTION"
            self.task.anulada = True
            Tarea.objects.filter(pk=self.task.pk).update(estado="GESTION", anulada=True)
            with self.assertRaises(ValidationError):
                self.create(backend)
            self.task.anulada = False
            Tarea.objects.filter(pk=self.task.pk).update(anulada=False)

    def test_both_backends_reject_wrong_company_persona_and_actor(self):
        foreign = User.objects.create_user("foreign-mini")
        for backend in (self.django, self.mysql):
            for persona in (foreign.pk, self.inactive.pk, 987654):
                with self.assertRaises(ValidationError):
                    self.create(backend, persona_id=persona)
            with self.assertRaises(storage.MiniTaskNotFound):
                self.create(backend, task_id=987654)
            with self.assertRaises(PermissionDenied):
                self.create(backend, actor_id=self.inactive.pk)
            with self.assertRaises(PermissionDenied):
                self.create(backend, actor_id=self.outsider.pk)

    def test_parent_and_grandparent_annulment(self):
        parent = Tarea.objects.create(empresa=self.company, creada_por=self.responsible, titulo="parent")
        grandparent = Tarea.objects.create(empresa=self.company, creada_por=self.responsible, titulo="grandparent")
        TareaRelacion.objects.create(padre=parent, hija=self.task)
        TareaRelacion.objects.create(padre=grandparent, hija=parent)
        for ancestor in (parent, grandparent):
            Tarea.objects.filter(pk=ancestor.pk).update(anulada=True)
            with self.assertRaises(ValidationError):
                self.create(self.django)
            Tarea.objects.filter(pk=ancestor.pk).update(anulada=False)
        self.sql.annulled_parent = True
        with self.assertRaises(ValidationError):
            self.create(self.mysql)

    def test_supervisor_but_not_operational_supervisor_has_contextual_authority(self):
        TareaParticipante.objects.create(tarea=self.task, usuario=self.outsider, rol="SUPERVISOR")
        for backend in (self.django, self.mysql):
            mini_id = self.create(backend, actor_id=self.supervisor.pk).mini_task_id
            with self.assertRaises(PermissionDenied):
                self.close(backend, mini_id, actor_id=self.outsider.pk)
            self.close(backend, mini_id, actor_id=self.assigned.pk)
            with self.assertRaises(PermissionDenied):
                self.reopen(backend, mini_id, actor_id=self.assigned.pk)
            self.reopen(backend, mini_id, actor_id=self.supervisor.pk)

    def test_empty_comment_duplicate_transitions_and_file_limit(self):
        for backend in (self.django, self.mysql):
            mini_id = self.create(backend).mini_task_id
            with self.assertRaises(ValidationError):
                self.close(backend, mini_id, comentario="  ")
            with self.assertRaises(ValidationError):
                self.reopen(backend, mini_id)
            with self.assertRaises(ValidationError):
                self.close(backend, mini_id, uploaded_files=tuple(
                    SimpleUploadedFile(f"{number}.pdf", b"x") for number in range(6)))
            self.close(backend, mini_id)
            with self.assertRaises(ValidationError):
                self.close(backend, mini_id)

    def test_mysql_rollback_each_close_write_boundary_and_new_file_cleanup(self):
        mini_id = self.create(self.mysql).mini_task_id
        before = deepcopy(self.sql.tables)
        for table in ("tareas_comentario", "tareas_comentarioversion", "tareas_documentotarea",
                      "tareas_documentohistorial", "tareas_comentarioadjunto",
                      "tareas_comentarioversiondocumento", "tareas_tarealectura",
                      "tareas_minitareaevento"):
            self.sql.fail_table = table
            with self.subTest(table=table), patch.object(storage, "_dispatch") as dispatch:
                with self.assertRaises(TaskStorageError):
                    self.close(self.mysql, mini_id, uploaded_files=(
                        SimpleUploadedFile("new.pdf", b"%PDF-1.4"),))
                self.assertEqual(self.sql.tables, before)
                self.assertFalse(self.file_storage.exists("tareas/documentos/new.pdf"))
                dispatch.assert_not_called()
        self.assertEqual(self.sql.rollbacks, 8)

    def test_django_rollback_and_only_new_file_cleanup(self):
        self.file_storage.save("historical.pdf", SimpleUploadedFile("historical.pdf", b"x"))
        mini_id = self.create(self.django).mini_task_id
        original = storage._DjangoMutation.insert

        def fail(adapter, model, values):
            if model is MiniTareaEvento:
                raise RuntimeError("injected")
            return original(adapter, model, values)

        with patch.object(storage._DjangoMutation, "insert", fail):
            with self.assertRaises(TaskStorageError):
                self.close(self.django, mini_id, uploaded_files=(SimpleUploadedFile("new.pdf", b"x"),))
        self.assertFalse(MiniTarea.objects.get(pk=mini_id).hecho)
        self.assertFalse(Comentario.objects.exists())
        self.assertTrue(self.file_storage.exists("historical.pdf"))
        self.assertEqual(self.file_storage.listdir("tareas/documentos")[1], [])

    def test_postcommit_independent_channels_actor_exclusion_and_event_dedupe(self):
        self.sql.existing_effective.add(self.supervisor.pk)
        for backend in (self.django, self.mysql):
            mini_id = self.create(backend).mini_task_id
            TareaParticipante.objects.get_or_create(tarea=self.task, usuario=self.supervisor)
            with patch.object(storage, "emit_task_event") as emit, patch.object(storage, "send_task_email") as email:
                with self.captureOnCommitCallbacks(execute=True):
                    first = self.close(
                        backend, mini_id,
                        notification_recipient_ids=(self.assigned.pk, self.assigned.pk, self.responsible.pk),
                        email_recipient_ids=(self.supervisor.pk,),
                    )
                    if backend is self.django:
                        emit.assert_not_called()
                self.assertEqual(len(emit.call_args.kwargs["recipients"]), 1)
                self.assertFalse(emit.call_args.kwargs["send_email"])
                self.assertEqual(email.call_args.kwargs["to_emails"], [self.supervisor.email])
                self.reopen(backend, mini_id)
                with self.captureOnCommitCallbacks(execute=True):
                    second = self.close(backend, mini_id, notification_recipient_ids=(self.assigned.pk,))
                self.assertEqual([call.kwargs["event"] for call in emit.call_args_list],
                                 [f"mini_tarea_cierre:{first.event_id}", f"mini_tarea_cierre:{second.event_id}"])
                self.assertNotEqual(first.event_id, second.event_id)
                self.assertEqual(email.call_count, 1)

    def test_inactive_and_nonfunctional_recipients_rejected(self):
        for backend in (self.django, self.mysql):
            mini_id = self.create(backend).mini_task_id
            for user in (self.inactive, self.outsider):
                with self.assertRaises(ValidationError):
                    self.close(backend, mini_id, notification_recipient_ids=(user.pk,))

    def test_communication_failure_does_not_rollback(self):
        for backend in (self.django, self.mysql):
            mini_id = self.create(backend).mini_task_id
            with patch.object(storage, "emit_task_event", side_effect=RuntimeError("secret")):
                with self.captureOnCommitCallbacks(execute=True):
                    result = self.close(backend, mini_id, notification_recipient_ids=(self.assigned.pk,))
            self.assertTrue(result.delivery.failed)
            if backend is self.django:
                self.assertTrue(MiniTarea.objects.get(pk=mini_id).hecho)
            else:
                self.assertTrue(self.sql.tables["tareas_minitarea"][mini_id]["hecho"])

    def test_mysql_no_operational_orm_same_pk_unchanged(self):
        mini = MiniTarea.objects.create(tarea=self.task, persona=self.assigned, descripcion="default untouched")
        snapshot = list(MiniTarea.objects.values())

        def system_only(execute, sql, params, many, context):
            if '"tareas_' in sql:
                raise AssertionError("Operational ORM escape")
            return execute(sql, params, many, context)

        with connections["default"].execute_wrapper(system_only):
            created = self.create(self.mysql)
            self.assertEqual(created.mini_task_id, mini.pk)
            self.close(self.mysql, created.mini_task_id)
            self.reopen(self.mysql, created.mini_task_id)
            another = self.create(self.mysql)
            self.delete(self.mysql, another.mini_task_id)
        self.assertEqual(list(MiniTarea.objects.values()), snapshot)

    def test_nondefault_alias_propagates_entire_close_aggregate_controlled_fake(self):
        TareaParticipante.objects.create(tarea=self.task, usuario=self.inactive)
        models = (Tarea, TareaRelacion, MiniTarea, MiniTareaEvento, Comentario,
                  ComentarioVersion, DocumentoTarea, DocumentoHistorial, ComentarioAdjunto,
                  ComentarioVersionDocumento, TareaLectura, ComentarioPausaLectura,
                  TareaParticipante, Hito)
        aliases = []
        atomic = transaction.atomic
        on_commit = transaction.on_commit
        with ExitStack() as stack:
            for model in models:
                original = model.objects.using

                def using(alias, original=original, model=model):
                    aliases.append((model, alias))
                    return original("default")

                stack.enter_context(patch.object(model.objects, "using", using))
            atomic_aliases = []

            def begin(using=None, **kwargs):
                if using != "default":
                    atomic_aliases.append(using)
                return atomic(using="default", **kwargs)

            stack.enter_context(patch.object(transaction, "atomic", begin))
            callback_aliases = []

            def commit(callback, using):
                callback_aliases.append(using)
                return on_commit(callback, using="default")

            stack.enter_context(patch.object(transaction, "on_commit", commit))
            backend = storage.DjangoMiniTaskStorage("operational_alias")
            mini_id = self.create(backend).mini_task_id
            self.close(backend, mini_id, uploaded_files=(SimpleUploadedFile("alias.pdf", b"x"),))
            self.reopen(backend, mini_id)
            another = self.create(backend).mini_task_id
            self.delete(backend, another)
        self.assertEqual({alias for model, alias in aliases}, {"operational_alias"})
        for model in models[:-2]:
            self.assertIn(model, {item[0] for item in aliases})
        self.assertEqual(set(atomic_aliases), {"operational_alias"})
        self.assertEqual(callback_aliases, ["operational_alias"])

    def test_five_files_and_image_validation_both_backends(self):
        for backend in (self.django, self.mysql):
            mini_id = self.create(backend).mini_task_id
            with self.assertRaises(ValidationError):
                self.close(backend, mini_id, uploaded_files=(
                    SimpleUploadedFile("invalid.jpg", b"not an image"),))
            result = self.close(backend, mini_id, uploaded_files=tuple(
                SimpleUploadedFile(f"proof-{number}.pdf", b"%PDF-1.4")
                for number in range(5)))
            if backend is self.django:
                self.assertEqual(ComentarioAdjunto.objects.filter(
                    comentario_id=result.comentario_feed_id).count(), 5)
                self.assertEqual(DocumentoHistorial.objects.count(), 5)
            else:
                self.assertEqual(len(self.sql.tables["tareas_comentarioadjunto"]), 5)
                self.assertEqual(len(self.sql.tables["tareas_documentohistorial"]), 5)

    def test_every_mutation_rechecks_frozen_task_and_annulment(self):
        for backend in (self.django, self.mysql):
            pending_id = self.create(backend).mini_task_id
            done_id = self.create(backend).mini_task_id
            self.close(backend, done_id)
            for state in ("BORRADOR", "PENDIENTE_APROBACION_CIERRE", "CERRADA"):
                self.task.estado = state
                Tarea.objects.filter(pk=self.task.pk).update(estado=state)
                for operation in (
                    lambda: self.close(backend, pending_id),
                    lambda: self.reopen(backend, done_id),
                    lambda: self.delete(backend, pending_id),
                ):
                    with self.subTest(backend=type(backend).__name__, state=state):
                        with self.assertRaises(ValidationError):
                            operation()
            self.task.estado = "GESTION"
            Tarea.objects.filter(pk=self.task.pk).update(estado="GESTION", anulada=True)
            self.task.anulada = True
            for operation in (
                lambda: self.close(backend, pending_id),
                lambda: self.reopen(backend, done_id),
                lambda: self.delete(backend, pending_id),
            ):
                with self.assertRaises(ValidationError):
                    operation()
            Tarea.objects.filter(pk=self.task.pk).update(anulada=False)
            self.task.anulada = False

    def test_dto_effective_sources_never_query_default_and_delete_removes_only_source(self):
        from tareas.services.participants import effective_participant_ids, is_effective_participant
        from tareas.views import _detail_task_presentation, _detail_effective_participant_ids
        mini_id = self.create(self.django).mini_task_id
        detail = self.django.detail(task_id=self.task.pk, empresa_id=self.company.pk)
        task = _detail_task_presentation(
            detail.core, self.company, _detail_effective_participant_ids(detail))
        with patch.object(MiniTarea.objects, "using", side_effect=AssertionError("default lookup")):
            self.assertIn(self.assigned.pk, effective_participant_ids(task))
            self.assertTrue(is_effective_participant(task, self.assigned))
        self.delete(self.django, mini_id)
        self.assertNotIn(self.assigned.pk, self.django.detail(
            task_id=self.task.pk, empresa_id=self.company.pk).effective_user_ids)

    def test_assignee_needs_company_membership_but_not_tareas_permission(self):
        user = User.objects.create_user("mini-dashboard-only")
        assign_permission(user, self.company, "Tareas - Dashboard personal", ingresar=True)
        for backend in (self.django, self.mysql):
            created = self.create(backend, persona_id=user.pk)
            with self.assertRaises(PermissionDenied):
                self.close(backend, created.mini_task_id, actor_id=user.pk)
            self.close(backend, created.mini_task_id)

    def test_mutation_missing_scoped_mini_does_not_touch_another_task(self):
        for backend in (self.django, self.mysql):
            mini_id = self.create(backend).mini_task_id
            for operation in (
                lambda: self.close(backend, mini_id + 5000),
                lambda: self.reopen(backend, mini_id + 5000),
                lambda: self.delete(backend, mini_id + 5000),
            ):
                with self.assertRaises(storage.MiniTaskNotFound):
                    operation()

    def test_mysql_assigned_read_scopes_user_company_and_keeps_done(self):
        mini_id = self.create(self.mysql).mini_task_id
        self.close(self.mysql, mini_id)
        own = self.mysql.assigned(empresa_id=self.company.pk, actor_id=self.assigned.pk)
        self.assertEqual([item.pk for item in own], [mini_id])
        self.assertTrue(own[0].hecho)
        self.assertEqual(own[0].tarea.responsable.username, self.responsible.username)
        self.assertEqual(self.mysql.assigned(empresa_id=self.other.pk, actor_id=self.assigned.pk), ())
        self.assertEqual(self.mysql.assigned(empresa_id=self.company.pk, actor_id=self.outsider.pk), ())
        self.task.anulada = True
        self.assertEqual(self.mysql.assigned(empresa_id=self.company.pk, actor_id=self.assigned.pk), ())
        query = next(sql for sql, params in self.sql.commands if sql.startswith("SELECT m.id"))
        self.assertIn("m.persona_id=%s", query)
        self.assertIn("t.empresa_id=%s", query)

    def test_uncertain_commit_retains_new_file_and_dispatch_is_not_run(self):
        mini_id = self.create(self.mysql).mini_task_id
        with patch.object(self.sql, "commit", side_effect=RuntimeError("lost acknowledgement")):
            with patch.object(storage, "_dispatch") as dispatch:
                with self.assertRaises(TaskStorageError):
                    self.close(self.mysql, mini_id, uploaded_files=(
                        SimpleUploadedFile("new.pdf", b"x"),))
                dispatch.assert_not_called()
        self.assertTrue(self.file_storage.exists("tareas/documentos/new.pdf"))

    def test_resolver_errors_fail_closed_and_http_no_operational_lookup(self):
        self.client.force_login(self.responsible)
        activate_company(self.client, self.company)
        for error in (RuntimeError("secret"), storage.ValidationError("invalid alias")):
            with patch.object(storage, "resolve_operational_backend", side_effect=error):
                with self.assertRaises(TaskStorageError):
                    storage.resolve_minitask_storage()
                with patch.object(Tarea.objects, "get", side_effect=AssertionError("fallback")):
                    response = self.client.post(reverse("tareas:minitareas_tarea", args=[self.task.pk]),
                                                {"descripcion": "x", "persona": self.assigned.pk})
                self.assertEqual(response.status_code, 503)
                self.assertNotContains(response, "secret", status_code=503)

    def test_history_detail_assigned_participation_and_closure(self):
        mini_id = self.create(self.django).mini_task_id
        detail = self.django.detail(task_id=self.task.pk, empresa_id=self.company.pk)
        self.assertIn(self.assigned.pk, detail.effective_user_ids)
        with self.assertRaises(ValidationError):
            validate_closure_requirements(self.task)
        result = self.close(self.django, mini_id)
        validate_closure_requirements(self.task)
        detail, mini = self.django.history(
            task_id=self.task.pk, empresa_id=self.company.pk, mini_task_id=mini_id,
            actor_id=self.assigned.pk,
        )
        event = mini.eventos_t104[0]
        self.assertEqual(event.actor_username, self.responsible.username)
        self.assertEqual(event.comentario_feed_id, result.comentario_feed_id)
        self.assertIn(self.assigned.pk, detail.effective_user_ids)
        assigned = self.django.assigned(empresa_id=self.company.pk, actor_id=self.assigned.pk)
        self.assertEqual([row.pk for row in assigned], [mini_id])
        self.assertTrue(assigned[0].hecho)
        second = self.create(self.django).mini_task_id
        self.delete(self.django, second)
        self.assertIn(self.assigned.pk, self.django.detail(
            task_id=self.task.pk, empresa_id=self.company.pk).effective_user_ids)
        self.client.force_login(self.assigned)
        activate_company(self.client, self.company)
        response = self.client.get(reverse("tareas:historial_minitarea", args=[self.task.pk, mini_id]))
        self.assertContains(response, self.responsible.username)
        self.assertContains(self.client.get(reverse("tareas:mis_tareas")), "Complete work")
