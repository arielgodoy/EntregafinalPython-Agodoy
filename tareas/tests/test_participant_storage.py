"""Responsibility/participation contracts, without external service writes."""

from contextlib import ExitStack, nullcontext
from copy import deepcopy
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections, transaction
from django.test import TestCase
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from tareas.models import Comentario, Tarea, TareaConnectionRole, TareaLectura, TareaParticipante, TareaReasignacion, TareaRelacion
from tareas.services.connection_roles import BackendContext
from tareas.services import participant_storage as service
from tareas.services.task_storage import EditTaskNotFound, TaskStorageError, UpdateTaskCommand


class ParticipantStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="PS1", descripcion="Participants")
        cls.other_empresa = Empresa.objects.create(codigo="PS2", descripcion="Other")
        cls.creator = User.objects.create_user(username="ps-creator")
        cls.old = User.objects.create_user(username="ps-old")
        cls.target = User.objects.create_user(username="ps-target")
        cls.supervisor = User.objects.create_user(username="ps-supervisor")
        cls.outsider = User.objects.create_user(username="ps-outsider")
        cls.vista = Vista.objects.create(nombre="Tareas")
        for user in (cls.creator, cls.old, cls.target, cls.supervisor):
            Permiso.objects.create(
                usuario=user, empresa=cls.empresa, vista=cls.vista,
                modificar=True, supervisor=user == cls.supervisor,
            )
        cls.task = Tarea.objects.create(
            titulo="Original", empresa=cls.empresa, creada_por=cls.creator,
            responsable=cls.old, fecha_tope=date(2026, 12, 1),
        )
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS", source_type="DJANGO", django_alias="default",
        )

    def setUp(self):
        self.storage = service.DjangoParticipantStorage("default")

    def reassign(self, **kwargs):
        return service.ReassignResponsibleCommand(
            self.task.pk, self.empresa.pk, kwargs.pop("actor_id", self.creator.pk),
            kwargs.pop("new_responsible_id", self.target.pk), **kwargs,
        )

    def add(self, user_id=None, role="PARTICIPANTE", actor_id=None):
        return service.AddParticipantCommand(
            self.task.pk, self.empresa.pk, actor_id or self.creator.pk,
            self.target.pk if user_id is None else user_id, role,
        )

    def link(self, user=None, role="PARTICIPANTE"):
        return TareaParticipante.objects.create(
            tarea=self.task, usuario=user or self.target, rol=role
        )

    def assert_key(self, key, function, command):
        with self.assertRaises(ValidationError) as caught:
            function(command)
        self.assertEqual(caught.exception.messages, [f"tareas.assignment.errors.{key}"])

    def test_reassign_is_atomic_preserves_lifecycle_and_trims_reason(self):
        stamp = timezone.now()
        Tarea.objects.filter(pk=self.task.pk).update(
            estado="ACTIVA", fecha_publicacion=stamp, fecha_asignacion=stamp
        )
        with patch.object(service, "_notify") as notify, self.captureOnCommitCallbacks(execute=True):
            result = self.storage.reassign_responsible(self.reassign(reason="  Motivo  "))
        self.task.refresh_from_db()
        self.assertTrue(result.changed)
        self.assertEqual(result.old_responsible_id, self.old.pk)
        self.assertEqual(result.new_responsible_id, self.target.pk)
        history = TareaReasignacion.objects.get(pk=result.reassignment_id)
        self.assertEqual(history.motivo, "Motivo")
        self.assertEqual(self.task.responsable_id, self.target.pk)
        self.assertEqual(self.task.estado, "ACTIVA")
        self.assertEqual(self.task.fecha_publicacion, stamp)
        self.assertEqual(self.task.fecha_asignacion, stamp)
        self.assertEqual(self.task.fecha_tope, date(2026, 12, 1))
        self.assertFalse(TareaParticipante.objects.exists())
        notify.assert_called_once()

    def test_noop_has_no_ledger_cursor_or_notification(self):
        with patch.object(service, "_notify") as notify, self.captureOnCommitCallbacks(execute=True):
            result = self.storage.reassign_responsible(
                self.reassign(new_responsible_id=self.old.pk)
            )
        self.assertFalse(result.changed)
        self.assertFalse(TareaLectura.objects.exists())
        self.assertFalse(TareaReasignacion.objects.exists())
        notify.assert_not_called()

    def test_draft_null_has_no_ledger_but_notifies_previous(self):
        with patch.object(service, "_notify") as notify, self.captureOnCommitCallbacks(execute=True):
            result = self.storage.reassign_responsible(self.reassign(new_responsible_id=None))
        self.assertTrue(result.changed)
        self.assertIsNone(result.reassignment_id)
        self.task.refresh_from_db()
        self.assertIsNone(self.task.responsable_id)
        self.assertFalse(TareaReasignacion.objects.exists())
        notify.assert_called_once()

    def test_published_null_and_blank_reason_fail(self):
        for state in ("ACTIVA", "GESTION", "PENDIENTE_APROBACION_CIERRE"):
            with self.subTest(state=state):
                Tarea.objects.filter(pk=self.task.pk).update(estado=state)
                self.assert_key("invalid_user", self.storage.reassign_responsible,
                                self.reassign(new_responsible_id=None, reason="Motivo"))
                self.assert_key("reason_required", self.storage.reassign_responsible,
                                self.reassign(reason="  "))
        self.task.refresh_from_db()
        self.assertEqual(self.task.responsable_id, self.old.pk)

    def test_every_allowed_state_responsibility_and_participant_operations(self):
        for state in service.MUTABLE_STATES:
            with self.subTest(state=state):
                Tarea.objects.filter(pk=self.task.pk).update(
                    estado=state, responsable_id=self.old.pk
                )
                self.assertTrue(self.storage.reassign_responsible(
                    self.reassign(reason="Change")
                ).changed)
                self.assertTrue(self.storage.add_task_participant(
                    self.add(self.supervisor.pk, role="INVITADO_OBSERVADOR")
                ).changed)
                result = self.storage.change_participant_role(service.ChangeParticipantRoleCommand(
                    self.task.pk, self.empresa.pk, self.creator.pk,
                    self.supervisor.pk, "PARTICIPANTE",
                ))
                self.assertEqual(result.old_role, "INVITADO_OBSERVADOR")
                self.assertEqual(result.new_role, "PARTICIPANTE")
                self.storage.remove_task_participant(service.RemoveParticipantCommand(
                    self.task.pk, self.empresa.pk, self.creator.pk, self.supervisor.pk
                ))

    def test_active_eligible_targets_and_public_roles_only(self):
        self.assert_key("invalid_user", self.storage.add_task_participant,
                        self.add(self.outsider.pk))
        User.objects.filter(pk=self.target.pk).update(is_active=False)
        self.assert_key("invalid_user", self.storage.reassign_responsible, self.reassign())
        User.objects.filter(pk=self.target.pk).update(is_active=True)
        for role in ("CREADOR", "RESPONSABLE_LIDER", "SUPERVISOR", "AUTORIZADOR", "bad"):
            self.assert_key("invalid_role", self.storage.add_task_participant, self.add(role=role))
        self.assert_key("invalid_user", self.storage.add_task_participant, self.add(True))

    def test_add_rejects_implicit_users_and_duplicate_without_upsert(self):
        for user in (self.creator, self.old):
            self.assert_key("implicit_user", self.storage.add_task_participant, self.add(user.pk))
        link = self.link()
        self.assert_key("duplicate", self.storage.add_task_participant,
                        self.add(role="INVITADO_OBSERVADOR"))
        link.refresh_from_db()
        self.assertEqual(link.rol, "PARTICIPANTE")

    def test_cursor_latest_tie_break_and_preserved_on_every_return(self):
        first = Comentario.objects.create(tarea=self.task, autor=self.creator, contenido="one")
        latest = Comentario.objects.create(tarea=self.task, autor=self.creator, contenido="two")
        stamp = timezone.now()
        Comentario.objects.filter(tarea=self.task).update(created_at=stamp)
        result = self.storage.add_task_participant(self.add())
        self.assertIsNotNone(result.participant_id)
        reading = TareaLectura.objects.get(tarea=self.task, usuario=self.target)
        self.assertEqual(reading.comentario_leido_hasta_id, latest.pk)
        reading.comentario_leido_hasta = first
        reading.leido = True
        reading.fecha_lectura = stamp
        reading.save()
        self.storage.remove_task_participant(service.RemoveParticipantCommand(
            self.task.pk, self.empresa.pk, self.creator.pk, self.target.pk
        ))
        self.storage.add_task_participant(self.add())
        self.storage.reassign_responsible(self.reassign())
        reading.refresh_from_db()
        self.assertEqual(reading.comentario_leido_hasta_id, first.pk)
        self.assertTrue(reading.leido)
        self.assertEqual(reading.fecha_lectura, stamp)
        self.assertEqual(TareaLectura.objects.filter(usuario=self.target).count(), 1)

    def test_role_change_preserves_row_and_date_noop_and_existing_only(self):
        link = self.link()
        command = service.ChangeParticipantRoleCommand(
            self.task.pk, self.empresa.pk, self.creator.pk, self.target.pk,
            "INVITADO_OBSERVADOR",
        )
        with patch.object(service, "_notify") as notify, self.captureOnCommitCallbacks(execute=True):
            result = self.storage.change_participant_role(command)
            second = self.storage.change_participant_role(command)
        current = TareaParticipante.objects.get(pk=link.pk)
        self.assertEqual(current.fecha, link.fecha)
        self.assertEqual(result.participant_id, link.pk)
        self.assertEqual(result.old_role, "PARTICIPANTE")
        self.assertEqual(result.new_role, "INVITADO_OBSERVADOR")
        self.assertFalse(second.changed)
        notify.assert_called_once()
        self.assert_key("invalid_role", self.storage.change_participant_role,
                        replace(command, new_role="SUPERVISOR"))
        self.assert_key("missing", self.storage.change_participant_role,
                        replace(command, user_id=self.old.pk))

    def test_role_change_rejects_historical_nonpublic_role_but_removal_allowed(self):
        link = self.link(role="SUPERVISOR")
        command = service.ChangeParticipantRoleCommand(
            self.task.pk, self.empresa.pk, self.creator.pk, self.target.pk,
            "PARTICIPANTE",
        )
        self.assert_key("invalid_role", self.storage.change_role, command)
        link.refresh_from_db()
        self.assertEqual(link.rol, "SUPERVISOR")
        self.assertTrue(self.storage.remove(service.RemoveParticipantCommand(
            self.task.pk, self.empresa.pk, self.creator.pk, self.target.pk
        )).changed)

    def test_short_storage_method_aliases_return_the_same_dtos(self):
        added = self.storage.add(self.add())
        self.assertIsInstance(added, service.ParticipantMutationResult)
        changed = self.storage.change_role(service.ChangeParticipantRoleCommand(
            self.task.pk, self.empresa.pk, self.creator.pk, self.target.pk,
            "INVITADO_OBSERVADOR",
        ))
        self.assertEqual(changed.participant_id, added.participant_id)
        self.assertTrue(self.storage.remove(service.RemoveParticipantCommand(
            self.task.pk, self.empresa.pk, self.creator.pk, self.target.pk
        )).changed)
        self.assertTrue(self.storage.reassign(self.reassign()).changed)

    def test_removal_of_inactive_nonmember_preserves_reading_and_comments(self):
        self.link()
        comment = Comentario.objects.create(tarea=self.task, autor=self.target, contenido="history")
        reading, _ = TareaLectura.objects.update_or_create(
            tarea=self.task, usuario=self.target,
            defaults={"comentario_leido_hasta": comment},
        )
        User.objects.filter(pk=self.target.pk).update(is_active=False)
        Permiso.objects.filter(usuario=self.target).delete()
        command = service.RemoveParticipantCommand(
            self.task.pk, self.empresa.pk, self.creator.pk, self.target.pk
        )
        with patch.object(service, "_notify") as notify, self.captureOnCommitCallbacks(execute=True):
            result = self.storage.remove_task_participant(command)
        self.assertTrue(result.changed)
        self.assertTrue(TareaLectura.objects.filter(pk=reading.pk).exists())
        self.assertTrue(Comentario.objects.filter(pk=comment.pk).exists())
        self.assertFalse(TareaParticipante.objects.exists())
        notify.assert_called_once()
        self.assert_key("missing", self.storage.remove_task_participant, command)

    def test_auth_requires_creator_or_vicmeas_supervisor_not_operational_role(self):
        self.link(self.old, "SUPERVISOR")
        for actor in (self.old, self.target, self.outsider):
            with self.subTest(actor=actor.pk), self.assertRaises(PermissionDenied):
                self.storage.reassign_responsible(self.reassign(actor_id=actor.pk))
        result = self.storage.reassign_responsible(self.reassign(actor_id=self.supervisor.pk))
        self.assertTrue(result.changed)

    def test_actor_active_membership_and_modificar_are_required(self):
        command = self.reassign()
        User.objects.filter(pk=self.creator.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.storage.reassign_responsible(command)
        User.objects.filter(pk=self.creator.pk).update(is_active=True)
        Permiso.objects.filter(usuario=self.creator).update(modificar=False)
        with self.assertRaises(PermissionDenied):
            self.storage.reassign_responsible(command)
        Permiso.objects.filter(usuario=self.creator).delete()
        with self.assertRaises(PermissionDenied):
            self.storage.reassign_responsible(command)

    def test_scope_and_all_lifecycle_rejections(self):
        with self.assertRaises(EditTaskNotFound):
            self.storage.add_task_participant(replace(self.add(), empresa_id=self.other_empresa.pk))
        self.link()
        operations = [
            (self.storage.reassign_responsible, self.reassign()),
            (self.storage.add_task_participant, self.add(self.supervisor.pk)),
            (self.storage.remove_task_participant, service.RemoveParticipantCommand(
                self.task.pk, self.empresa.pk, self.creator.pk, self.target.pk)),
            (self.storage.change_participant_role, service.ChangeParticipantRoleCommand(
                self.task.pk, self.empresa.pk, self.creator.pk, self.target.pk,
                "INVITADO_OBSERVADOR")),
        ]
        for state in ("CERRADA", "unknown"):
            Tarea.objects.filter(pk=self.task.pk).update(estado=state)
            for function, command in operations:
                self.assert_key("state", function, command)
        Tarea.objects.filter(pk=self.task.pk).update(estado="BORRADOR", anulada=True)
        for function, command in operations:
            self.assert_key("annulled", function, command)

    def test_parent_grandparent_annulment_scope(self):
        parent = Tarea.objects.create(titulo="parent", empresa=self.empresa, creada_por=self.creator)
        grandparent = Tarea.objects.create(
            titulo="grandparent", empresa=self.empresa, creada_por=self.creator, anulada=True
        )
        TareaRelacion.objects.create(padre=parent, hija=self.task)
        TareaRelacion.objects.create(padre=grandparent, hija=parent)
        self.assert_key("annulled", self.storage.reassign_responsible, self.reassign())
        Tarea.objects.filter(pk=grandparent.pk).update(empresa=self.other_empresa)
        self.assertTrue(self.storage.reassign_responsible(self.reassign()).changed)

    def test_edit_atomic_reason_failure_and_non_draft_date_protected_under_lock(self):
        Tarea.objects.filter(pk=self.task.pk).update(estado="ACTIVA")
        edit = UpdateTaskCommand(
            self.task.pk, self.empresa.pk, "Changed", "Description", "URGENTE",
            self.target.pk, date(2027, 1, 1),
        )
        self.assert_key("reason_required", self.storage.reassign_responsible,
                        self.reassign(edit=edit))
        self.task.refresh_from_db()
        self.assertEqual(self.task.titulo, "Original")
        self.storage.edit_task(edit, actor_id=self.creator.pk, reason="Real reason")
        self.task.refresh_from_db()
        self.assertEqual(self.task.titulo, "Changed")
        self.assertEqual(self.task.descripcion, "Description")
        self.assertEqual(self.task.prioridad, "URGENTE")
        self.assertEqual(self.task.fecha_tope, date(2026, 12, 1))

    def test_general_edit_same_responsible_retains_closed_annulled_edit_behavior(self):
        Tarea.objects.filter(pk=self.task.pk).update(estado="CERRADA", anulada=True)
        edit = UpdateTaskCommand(
            self.task.pk, self.empresa.pk, "General edit", "", "NORMAL",
            self.old.pk, date(2027, 1, 1),
        )
        with patch.object(service, "_notify") as notify, self.captureOnCommitCallbacks(execute=True):
            result = self.storage.edit_task(edit, actor_id=self.creator.pk, reason="")
        self.task.refresh_from_db()
        self.assertFalse(result.changed)
        self.assertEqual(self.task.titulo, "General edit")
        self.assertEqual(self.task.fecha_tope, date(2026, 12, 1))
        notify.assert_not_called()

    def test_draft_edit_can_change_date_and_edit_identity_is_validated(self):
        edit = UpdateTaskCommand(
            self.task.pk, self.empresa.pk, "Draft edit", "", "NORMAL",
            self.target.pk, date(2027, 1, 1),
        )
        self.assert_key("invalid_edit", self.storage.reassign_responsible,
                        self.reassign(edit=replace(edit, empresa_id=self.other_empresa.pk)))
        self.storage.edit_task(edit, actor_id=self.creator.pk, reason="")
        self.task.refresh_from_db()
        self.assertEqual(self.task.fecha_tope, date(2027, 1, 1))

    def test_ledger_failure_rolls_back_general_fields_reading_and_responsible(self):
        edit = UpdateTaskCommand(
            self.task.pk, self.empresa.pk, "Do not persist", "", "CRITICA",
            self.target.pk, date(2027, 1, 1),
        )
        with patch.object(self.storage, "reassignment", side_effect=RuntimeError("sensitive")), \
                patch.object(service, "_notify") as notify:
            with self.assertRaises(TaskStorageError) as caught:
                self.storage.edit_task(edit, actor_id=self.creator.pk, reason="")
        self.assertEqual(str(caught.exception), "tareas.assignment.errors.storage")
        self.task.refresh_from_db()
        self.assertEqual(self.task.titulo, "Original")
        self.assertEqual(self.task.responsable_id, self.old.pk)
        self.assertFalse(TareaLectura.objects.exists())
        notify.assert_not_called()

    def test_enclosing_rollback_discards_notification(self):
        with patch.object(service, "_notify") as notify, self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    self.storage.add_task_participant(self.add())
                    raise RuntimeError
        self.assertFalse(TareaParticipante.objects.exists())
        notify.assert_not_called()

    def test_notifications_only_affected_active_nonself_unique_each_mutation(self):
        command = self.reassign()
        result = service.ParticipantMutationResult(
            True, self.task.pk, self.empresa.pk, self.target.pk,
            self.old.pk, self.target.pk,
        )
        with patch.object(service, "emit_task_event") as emit:
            service._notify(command, result, "CRITICA", "first")
            service._notify(command, result, "CRITICA", "second")
        self.assertEqual(emit.call_count, 4)
        calls = emit.call_args_list
        self.assertEqual({c.kwargs["recipients"][0].pk for c in calls},
                         {self.old.pk, self.target.pk})
        self.assertNotEqual(calls[0].kwargs["title"], calls[1].kwargs["title"])
        self.assertNotEqual(calls[0].kwargs["event"], calls[2].kwargs["event"])
        self.assertEqual(calls[0].kwargs["tarea"].prioridad, "CRITICA")
        User.objects.filter(pk=self.old.pk).update(is_active=False)
        with patch.object(service, "emit_task_event") as emit:
            service._notify(replace(command, actor_id=self.target.pk), result, "NORMAL", "third")
        emit.assert_not_called()

    def test_role_and_removal_notification_bodies_and_identity_failure_sanitized(self):
        commands = [
            self.add(),
            service.RemoveParticipantCommand(
                self.task.pk, self.empresa.pk, self.creator.pk, self.target.pk),
            service.ChangeParticipantRoleCommand(
                self.task.pk, self.empresa.pk, self.creator.pk, self.target.pk,
                "INVITADO_OBSERVADOR"),
        ]
        result = service.ParticipantMutationResult(
            True, self.task.pk, self.empresa.pk, self.target.pk,
            old_role="PARTICIPANTE", new_role="INVITADO_OBSERVADOR",
        )
        with patch.object(service, "emit_task_event") as emit:
            for index, command in enumerate(commands):
                service._notify(command, result, "NORMAL", str(index))
        self.assertEqual(emit.call_count, 3)
        self.assertIn("retirado", emit.call_args_list[1].kwargs["body"])
        self.assertIn("PARTICIPANTE → INVITADO_OBSERVADOR", emit.call_args_list[2].kwargs["body"])
        with patch.object(service.Empresa.objects, "using", side_effect=RuntimeError("secret")), \
                self.assertLogs(service.logger, level="ERROR") as logs:
            service._notify(commands[0], result, "NORMAL", "failure")
        self.assertNotIn("secret", "".join(logs.output))

    def test_critical_notification_uses_existing_email_adapter_after_commit(self):
        Tarea.objects.filter(pk=self.task.pk).update(prioridad="CRITICA")
        User.objects.filter(pk__in=(self.old.pk, self.target.pk)).update(email="recipient@example.test")
        with patch("tareas.services.notifications.notify_task_event") as in_app, \
                patch("tareas.services.notifications.send_task_email") as email, \
                self.captureOnCommitCallbacks(execute=True):
            self.storage.reassign_responsible(self.reassign())
            in_app.assert_not_called()
            email.assert_not_called()
        self.assertEqual(in_app.call_count, 2)
        self.assertEqual(email.call_count, 2)
        self.assertNotEqual(in_app.call_args_list[0].kwargs["dedupe_key"],
                            in_app.call_args_list[1].kwargs["dedupe_key"])
        self.assertTrue(all(call.kwargs["tarea"].prioridad == "CRITICA"
                            for call in email.call_args_list))

    def test_every_public_path_fails_closed_before_task_lookup(self):
        commands = [
            (service.reassign_responsible, self.reassign()),
            (service.add_task_participant, self.add()),
            (service.remove_task_participant, service.RemoveParticipantCommand(
                self.task.pk, self.empresa.pk, self.creator.pk, self.target.pk)),
            (service.change_participant_role, service.ChangeParticipantRoleCommand(
                self.task.pk, self.empresa.pk, self.creator.pk, self.target.pk, "PARTICIPANTE")),
        ]
        with patch.object(service, "resolve_operational_backend", side_effect=RuntimeError("secret")), \
                patch.object(service.Tarea.objects, "using") as lookup, \
                self.assertLogs(service.logger, level="ERROR") as logs:
            for function, command in commands:
                with self.assertRaises(TaskStorageError) as caught:
                    function(command)
                self.assertEqual(str(caught.exception), "tareas.assignment.errors.backend")
        lookup.assert_not_called()
        self.assertNotIn("secret", "".join(logs.output))
        self.task.refresh_from_db()
        self.assertEqual(self.task.responsable_id, self.old.pk)

    def test_resolver_routes_django_mysql_and_rejects_unknown(self):
        with patch.object(service, "resolve_operational_backend", return_value=BackendContext(
            logical_role="BASE_TAREAS", backend_type="DJANGO", django_alias="operational",
        )):
            self.assertEqual(service.resolve_participant_storage().alias, "operational")
        config = object()
        with patch.object(service, "resolve_operational_backend", return_value=BackendContext(
            logical_role="BASE_TAREAS", backend_type="MYSQL_CONFIG",
            mysql_connection=config, database_name="tasks",
        )):
            storage = service.resolve_participant_storage()
            self.assertIs(storage.connection_config, config)
            self.assertEqual(storage.database_name, "tasks")
        with patch.object(service, "resolve_operational_backend", return_value=BackendContext(
            logical_role="BASE_TAREAS", backend_type="unknown",
        )):
            with self.assertRaises(TaskStorageError):
                service.resolve_participant_storage()
        with patch.object(service, "resolve_participant_storage", side_effect=RuntimeError("secret")), \
                self.assertLogs(service.logger, level="ERROR") as logs:
            with self.assertRaises(TaskStorageError):
                service.reassign_responsible(self.reassign())
        self.assertNotIn("secret", "".join(logs.output))

    def test_nondefault_alias_is_explicit_for_all_operational_queries_and_commit(self):
        alias = "operational"
        storage = service.DjangoParticipantStorage(alias)
        models = (Tarea, TareaParticipante, TareaLectura, Comentario, TareaReasignacion, TareaRelacion)
        patches = [patch.object(model.objects, "using") for model in models]
        mocks = [p.start() for p in patches]
        self.addCleanup(lambda: [p.stop() for p in patches])
        task_q, part_q, read_q, comment_q, ledger_q, relation_q = [m.return_value for m in mocks]
        task_q.select_for_update.return_value.get.return_value = self.task
        relation_q.select_for_update.return_value.filter.return_value.values_list.return_value.first.return_value = None
        read_q.filter.return_value.exists.return_value = False
        comment_q.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = None
        part_q.select_for_update.return_value.filter.return_value.first.return_value = None
        with patch.object(service.transaction, "atomic", return_value=nullcontext()) as atomic, \
                patch.object(service.transaction, "on_commit") as on_commit, \
                patch.object(Tarea, "full_clean", side_effect=AssertionError("must not validate default")):
            storage.reassign_responsible(self.reassign())
            storage.add_task_participant(self.add())
        for mock in mocks:
            self.assertTrue(mock.called)
            self.assertTrue(all(call.args == (alias,) for call in mock.call_args_list))
        self.assertTrue(all(call.kwargs == {"using": alias} for call in atomic.call_args_list))
        self.assertTrue(all(call.kwargs["using"] == alias for call in on_commit.call_args_list))


class TransactionalMySQLFake:
    """Stateful SQL fake: commit persists; every rollback restores its snapshot."""

    def __init__(self, *, state="BORRADOR", responsible=2, participant=None, reading=None,
                 fail_sql=None, commit_error=False, annulled=False, parents=()):
        self.task = [10, 7, 1, responsible, state, annulled, "CRITICA", date(2026, 12, 1)]
        self.link = participant
        self.reading = reading
        self.history = []
        self.edits = {}
        self.parents = list(parents)
        self.calls = []
        self.lastrowid = 100
        self.result = None
        self.fail_sql = fail_sql
        self.commit_error = commit_error
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if self.fail_sql and self.fail_sql in sql:
            raise RuntimeError("private connection detail")
        if sql == "START TRANSACTION":
            self.snapshot = (list(self.task), self.link, self.reading, list(self.history), dict(self.edits))
        elif sql.startswith("SELECT id, empresa_id"):
            self.result = tuple(self.task) if params == (10, 7) else None
        elif sql.startswith("SELECT p.id"):
            self.result = self.parents.pop(0) if self.parents else None
        elif sql.startswith("SELECT id, rol"):
            self.result = self.link
        elif sql.startswith("SELECT id FROM tareas_tarealectura"):
            self.result = self.reading
        elif sql.startswith("SELECT id FROM tareas_comentario"):
            self.result = (88,)
        elif sql.startswith("UPDATE tareas_tarea "):
            names = sql.split(" SET ")[1].split(" WHERE ")[0].split(", ")
            self.edits.update(zip((name.split("=")[0] for name in names), params[:-2]))
            self.task[3] = self.edits.get("responsable_id", self.task[3])
        elif sql.startswith("INSERT INTO tareas_tareaparticipante"):
            self.link = (self.lastrowid, params[2])
        elif sql.startswith("INSERT INTO tareas_tarealectura"):
            self.reading = (params[-1],)
        elif sql.startswith("INSERT INTO tareas_tareareasignacion"):
            self.history.append(params)
        elif sql.startswith("UPDATE tareas_tareaparticipante"):
            self.link = (self.link[0], params[0])
        elif sql.startswith("DELETE FROM tareas_tareaparticipante"):
            self.link = None
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.result

    def commit(self):
        if self.commit_error:
            raise RuntimeError("private connection detail")
        self.committed = True

    def rollback(self):
        self.rolled_back = True
        self.task, self.link, self.reading, self.history, self.edits = self.snapshot

    def close(self):
        self.closed = True


class ParticipantOperationalAliasTests(TestCase):
    """Use an isolated in-memory alias, with deliberately colliding task IDs."""

    databases = {"default"}
    alias = "participant_storage_test"

    @classmethod
    def setUpClass(cls):
        default = connections["default"]
        if default.vendor != "sqlite":
            from unittest import SkipTest
            raise SkipTest("The isolated alias fixture uses SQLite's in-memory backup API.")
        config = deepcopy(default.settings_dict)
        config["NAME"] = ":memory:"
        config["TEST"]["MIRROR"] = None
        connections.databases[cls.alias] = config
        cls.databases = {"default", cls.alias}

        def cleanup():
            connections[cls.alias].close()
            del connections[cls.alias]
            connections.databases.pop(cls.alias, None)
            cls.databases = {"default"}

        cls.addClassCleanup(cleanup)
        default.ensure_connection()
        operational = connections[cls.alias]
        operational.ensure_connection()
        default.connection.backup(operational.connection)
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="ALIAS", descripcion="SYSTEM company")
        cls.creator = User.objects.create_user(username="alias-creator")
        cls.old = User.objects.create_user(username="alias-old")
        cls.target = User.objects.create_user(username="alias-target")
        vista = Vista.objects.create(nombre="Tareas")
        for user in (cls.creator, cls.old, cls.target):
            Permiso.objects.create(
                usuario=user, empresa=cls.empresa, vista=vista, modificar=True
            )
        Empresa.objects.using(cls.alias).bulk_create([
            Empresa(pk=cls.empresa.pk, codigo="ALIAS", descripcion="Operational")
        ])
        User.objects.using(cls.alias).bulk_create([
            User(pk=user.pk, username=f"operational-{user.pk}", is_active=False)
            for user in (cls.creator, cls.old, cls.target)
        ])
        stamp = timezone.now()
        cls.stamp = stamp
        for alias, title in (("default", "DEFAULT untouched"), (cls.alias, "Operational")):
            Tarea.objects.using(alias).bulk_create([Tarea(
                pk=100, correlativo="B0000100", titulo=title,
                empresa_id=cls.empresa.pk, creada_por_id=cls.creator.pk,
                responsable_id=cls.old.pk, estado="ACTIVA",
                fecha_publicacion=stamp, fecha_asignacion=stamp,
                fecha_tope=date(2026, 12, 1),
            )])

    def test_real_alias_responsibility_ledger_cursor_dates_and_on_commit(self):
        storage = service.DjangoParticipantStorage(self.alias)
        command = service.ReassignResponsibleCommand(
            100, self.empresa.pk, self.creator.pk, self.target.pk, "Reason"
        )
        with patch.object(service, "_notify") as notify, \
                self.captureOnCommitCallbacks(using=self.alias, execute=True), \
                patch.object(Tarea, "full_clean", side_effect=AssertionError("no full_clean")):
            result = storage.reassign_responsible(command)
            self.assertEqual(notify.call_count, 0)
        notify.assert_called_once()
        self.assertEqual(Tarea.objects.get(pk=100).responsable_id, self.old.pk)
        operational = Tarea.objects.using(self.alias).get(pk=100)
        self.assertEqual(operational.responsable_id, self.target.pk)
        self.assertEqual(operational.fecha_publicacion, self.stamp)
        self.assertEqual(operational.fecha_asignacion, self.stamp)
        self.assertTrue(TareaReasignacion.objects.using(self.alias).filter(pk=result.reassignment_id).exists())
        self.assertTrue(TareaLectura.objects.using(self.alias).filter(usuario_id=self.target.pk).exists())
        self.assertFalse(TareaReasignacion.objects.exists())
        self.assertFalse(TareaLectura.objects.exists())

    def test_real_alias_participation_role_cursor_removal_and_default_untouched(self):
        storage = service.DjangoParticipantStorage(self.alias)
        add = service.AddParticipantCommand(100, self.empresa.pk, self.creator.pk, self.target.pk)
        result = storage.add_task_participant(add)
        original = TareaParticipante.objects.using(self.alias).get(pk=result.participant_id)
        change = service.ChangeParticipantRoleCommand(
            100, self.empresa.pk, self.creator.pk, self.target.pk, "INVITADO_OBSERVADOR"
        )
        storage.change_participant_role(change)
        row = TareaParticipante.objects.using(self.alias).get(pk=original.pk)
        self.assertEqual(row.fecha, original.fecha)
        self.assertEqual(row.rol, "INVITADO_OBSERVADOR")
        storage.remove_task_participant(service.RemoveParticipantCommand(
            100, self.empresa.pk, self.creator.pk, self.target.pk
        ))
        self.assertFalse(TareaParticipante.objects.using(self.alias).exists())
        self.assertTrue(TareaLectura.objects.using(self.alias).exists())
        self.assertFalse(TareaParticipante.objects.exists())
        self.assertFalse(TareaLectura.objects.exists())

    def test_real_alias_ancestor_annulment_and_transaction_rollback(self):
        Tarea.objects.using(self.alias).bulk_create([
            Tarea(pk=101, correlativo="B0000101", titulo="Parent",
                  empresa_id=self.empresa.pk, creada_por_id=self.creator.pk, anulada=True)
        ])
        TareaRelacion.objects.using(self.alias).bulk_create([
            TareaRelacion(padre_id=101, hija_id=100)
        ])
        storage = service.DjangoParticipantStorage(self.alias)
        command = service.ReassignResponsibleCommand(
            100, self.empresa.pk, self.creator.pk, self.target.pk, "Reason"
        )
        with self.assertRaises(ValidationError):
            storage.reassign_responsible(command)
        Tarea.objects.using(self.alias).filter(pk=101).update(anulada=False)
        with patch.object(storage, "reassignment", side_effect=RuntimeError("secret")):
            with self.assertRaises(TaskStorageError):
                storage.reassign_responsible(command)
        self.assertEqual(Tarea.objects.using(self.alias).get(pk=100).responsable_id, self.old.pk)
        self.assertFalse(TareaLectura.objects.using(self.alias).exists())


class MySQLParticipantStorageTests(TestCase):
    def setUp(self):
        self.storage = service.MySQLParticipantStorage(object(), "tasks")
        self.authorize = patch.object(service, "_authorize", return_value=SimpleNamespace(pk=7))
        self.eligible = patch.object(service, "_eligible")
        self.authorize.start()
        self.eligible.start()
        self.addCleanup(self.authorize.stop)
        self.addCleanup(self.eligible.stop)

    def run_fake(self, fake, method, command):
        with ExitStack() as stack:
            stack.enter_context(patch.object(
                service, "open_mysql_connection", return_value=nullcontext(fake)
            ))
            notify = stack.enter_context(patch.object(service, "_notify"))
            for model in (Tarea, TareaParticipante, TareaLectura, TareaReasignacion, TareaRelacion, Comentario):
                stack.enter_context(patch.object(
                    model.objects, "using", side_effect=AssertionError("ORM fallback")
                ))
            result = getattr(self.storage, method)(command)
        return result, notify

    def test_mysql_every_operation_leaves_real_same_pk_default_records_intact(self):
        empresa = Empresa.objects.create(pk=7, codigo="MYSQLPK", descripcion="Same PK")
        users = [User.objects.create_user(pk=pk, username=f"mysql-pk-{pk}") for pk in (1, 2, 3)]
        task = Tarea.objects.create(
            pk=10, empresa=empresa, creada_por=users[0], responsable=users[1],
            titulo="Default protected",
        )
        link = TareaParticipante.objects.create(tarea=task, usuario=users[2], rol="PARTICIPANTE")
        reading = TareaLectura.objects.create(tarea=task, usuario=users[2])
        fake = TransactionalMySQLFake()
        operations = [
            ("add_task_participant", service.AddParticipantCommand(10, 7, 1, 3)),
            ("change_participant_role", service.ChangeParticipantRoleCommand(
                10, 7, 1, 3, "INVITADO_OBSERVADOR")),
            ("remove_task_participant", service.RemoveParticipantCommand(10, 7, 1, 3)),
            ("reassign_responsible", service.ReassignResponsibleCommand(10, 7, 1, 3)),
        ]
        for method, command in operations:
            with self.subTest(operation=method):
                self.run_fake(fake, method, command)
                task.refresh_from_db()
                link.refresh_from_db()
                reading.refresh_from_db()
                self.assertEqual(task.responsable_id, users[1].pk)
                self.assertEqual(task.titulo, "Default protected")
                self.assertEqual(link.rol, "PARTICIPANTE")
                self.assertIsNone(reading.comentario_leido_hasta_id)
                self.assertFalse(TareaReasignacion.objects.exists())

    def test_mysql_domain_rejections_are_atomic(self):
        add = service.AddParticipantCommand(10, 7, 1, 3)
        role = service.ChangeParticipantRoleCommand(10, 7, 1, 3, "INVITADO_OBSERVADOR")
        reassignment = service.ReassignResponsibleCommand(10, 7, 1, 3)
        cases = [
            ("add_task_participant", replace(add, role="AUTORIZADOR"), {}, "invalid_role"),
            ("add_task_participant", replace(add, user_id=1), {}, "implicit_user"),
            ("add_task_participant", replace(add, user_id=2), {}, "implicit_user"),
            ("add_task_participant", add, {"participant": (90, "PARTICIPANTE")}, "duplicate"),
            ("change_participant_role", role, {}, "missing"),
            ("change_participant_role", replace(role, new_role="SUPERVISOR"),
             {"participant": (90, "PARTICIPANTE")}, "invalid_role"),
            ("change_participant_role", role,
             {"participant": (90, "SUPERVISOR")}, "invalid_role"),
            ("remove_task_participant", service.RemoveParticipantCommand(10, 7, 1, 3), {}, "missing"),
            ("reassign_responsible", reassignment, {"state": "GESTION"}, "reason_required"),
            ("reassign_responsible", replace(reassignment, new_responsible_id=None),
             {"state": "ACTIVA"}, "invalid_user"),
        ]
        for method, command, kwargs, key in cases:
            fake = TransactionalMySQLFake(**kwargs)
            with self.subTest(key=key), \
                    patch.object(service, "open_mysql_connection", return_value=nullcontext(fake)), \
                    patch.object(service, "_notify") as notify:
                with self.assertRaises(ValidationError) as caught:
                    getattr(self.storage, method)(command)
            self.assertEqual(caught.exception.messages, [f"tareas.assignment.errors.{key}"])
            self.assertTrue(fake.rolled_back)
            self.assertFalse(fake.committed)
            notify.assert_not_called()

    def test_reassign_parameterized_locked_transaction_and_notification_after_commit(self):
        fake = TransactionalMySQLFake(state="ACTIVA")
        command = service.ReassignResponsibleCommand(10, 7, 1, 3, "  Real reason  ")
        with patch.object(service, "open_mysql_connection", return_value=nullcontext(fake)), \
                patch.object(service, "_notify", side_effect=lambda *args: self.assertTrue(fake.committed)):
            result = self.storage.reassign_responsible(command)
        self.assertTrue(result.changed)
        self.assertEqual(result.old_responsible_id, 2)
        self.assertEqual(fake.task[3], 3)
        self.assertEqual(fake.reading, (88,))
        self.assertEqual(fake.history[0][-1], "Real reason")
        self.assertEqual(fake.calls[0], ("START TRANSACTION", ()))
        self.assertIn("empresa_id=%s FOR UPDATE", fake.calls[1][0])
        self.assertEqual(fake.calls[1][1], (10, 7))
        self.assertTrue(fake.closed)
        self.assertFalse(fake.rolled_back)
        self.assertTrue(all("%s" in sql for sql, params in fake.calls if params))

    def test_noop_and_draft_null_have_no_ledger(self):
        for responsible in (2, None):
            fake = TransactionalMySQLFake()
            result, notify = self.run_fake(fake, "reassign_responsible",
                                          service.ReassignResponsibleCommand(10, 7, 1, responsible))
            self.assertEqual(result.changed, responsible is None)
            self.assertFalse(fake.history)
            self.assertEqual(notify.call_count, int(result.changed))
            self.assertTrue(fake.committed)

    def test_add_role_change_remove_preserve_history_and_only_role_update(self):
        fake = TransactionalMySQLFake(reading=(42,))
        result, _ = self.run_fake(fake, "add_task_participant",
                                 service.AddParticipantCommand(10, 7, 1, 3))
        self.assertEqual(result.participant_id, 100)
        self.assertEqual(fake.reading, (42,))
        fake.calls.clear()
        result, _ = self.run_fake(fake, "change_participant_role",
                                 service.ChangeParticipantRoleCommand(10, 7, 1, 3, "INVITADO_OBSERVADOR"))
        self.assertEqual(result.participant_id, 100)
        self.assertFalse(any(sql.startswith(("DELETE", "INSERT")) for sql, _ in fake.calls))
        result, notify = self.run_fake(fake, "change_participant_role",
                                      service.ChangeParticipantRoleCommand(10, 7, 1, 3, "INVITADO_OBSERVADOR"))
        self.assertFalse(result.changed)
        notify.assert_not_called()
        result, _ = self.run_fake(fake, "remove_task_participant",
                                 service.RemoveParticipantCommand(10, 7, 1, 3))
        self.assertTrue(result.changed)
        self.assertIsNone(fake.link)
        self.assertEqual(fake.reading, (42,))

    def test_every_reassignment_write_and_commit_boundary_rolls_back(self):
        boundaries = [
            "UPDATE tareas_tarea", "INSERT INTO tareas_tarealectura",
            "INSERT INTO tareas_tareareasignacion", None,
        ]
        edit = UpdateTaskCommand(10, 7, "New", "", "NORMAL", 3, date(2027, 1, 1))
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                fake = TransactionalMySQLFake(fail_sql=boundary, commit_error=boundary is None)
                with patch.object(service, "open_mysql_connection", return_value=nullcontext(fake)), \
                        patch.object(service, "_notify") as notify:
                    with self.assertRaises(TaskStorageError) as caught:
                        self.storage.edit_task(edit, actor_id=1, reason="")
                self.assertEqual(str(caught.exception), "tareas.assignment.errors.storage")
                self.assertTrue(fake.rolled_back)
                self.assertEqual(fake.task[3], 2)
                self.assertEqual(fake.edits, {})
                self.assertIsNone(fake.reading)
                self.assertEqual(fake.history, [])
                notify.assert_not_called()

    def test_every_participant_write_boundary_rolls_back(self):
        cases = [
            ("add_task_participant", service.AddParticipantCommand(10, 7, 1, 3),
             None, "INSERT INTO tareas_tareaparticipante"),
            ("add_task_participant", service.AddParticipantCommand(10, 7, 1, 3),
             None, "INSERT INTO tareas_tarealectura"),
            ("remove_task_participant", service.RemoveParticipantCommand(10, 7, 1, 3),
             (90, "PARTICIPANTE"), "DELETE FROM tareas_tareaparticipante"),
            ("change_participant_role", service.ChangeParticipantRoleCommand(10, 7, 1, 3, "INVITADO_OBSERVADOR"),
             (90, "PARTICIPANTE"), "UPDATE tareas_tareaparticipante"),
        ]
        for method, command, link, boundary in cases:
            with self.subTest(boundary=boundary):
                fake = TransactionalMySQLFake(participant=link, fail_sql=boundary)
                with patch.object(service, "open_mysql_connection", return_value=nullcontext(fake)), \
                        patch.object(service, "_notify") as notify:
                    with self.assertRaises(TaskStorageError):
                        getattr(self.storage, method)(command)
                self.assertTrue(fake.rolled_back)
                self.assertEqual(fake.link, link)
                self.assertIsNone(fake.reading)
                notify.assert_not_called()

    def test_scoped_missing_task_never_falls_back_to_same_pk_default(self):
        fake = TransactionalMySQLFake()
        with patch.object(service, "open_mysql_connection", return_value=nullcontext(fake)), \
                patch.object(service.Tarea.objects, "using") as orm:
            with self.assertRaises(EditTaskNotFound):
                self.storage.add_task_participant(service.AddParticipantCommand(10, 999, 1, 3))
        orm.assert_not_called()
        self.assertTrue(fake.rolled_back)

    def test_mysql_authorization_denial_and_lifecycle_roll_back(self):
        fake = TransactionalMySQLFake()
        with patch.object(service, "open_mysql_connection", return_value=nullcontext(fake)), \
                patch.object(service, "_authorize", side_effect=PermissionDenied):
            with self.assertRaises(PermissionDenied):
                self.storage.add_task_participant(service.AddParticipantCommand(10, 7, 1, 3))
        self.assertTrue(fake.rolled_back)
        for kwargs in ({"state": "CERRADA"}, {"annulled": True},
                       {"parents": ((11, False), (12, True))}):
            fake = TransactionalMySQLFake(**kwargs)
            with patch.object(service, "open_mysql_connection", return_value=nullcontext(fake)):
                with self.assertRaises(ValidationError):
                    self.storage.add_task_participant(service.AddParticipantCommand(10, 7, 1, 3))
            self.assertTrue(fake.rolled_back)
            for sql, params in fake.calls:
                if sql.startswith("SELECT p.id"):
                    self.assertEqual(params[1:], (7, 7))
                    self.assertIn("FOR UPDATE", sql)

    def test_mysql_general_edit_preserves_locked_non_draft_deadline(self):
        fake = TransactionalMySQLFake(state="ACTIVA")
        edit = UpdateTaskCommand(10, 7, "New", "Text", "URGENTE", 2, date(2027, 1, 1))
        result, notify = self.run_fake(
            fake, "reassign_responsible",
            service.ReassignResponsibleCommand(10, 7, 1, 2, edit=edit),
        )
        self.assertFalse(result.changed)
        self.assertEqual(fake.edits, {"titulo": "New", "descripcion": "Text", "prioridad": "URGENTE"})
        self.assertEqual(fake.task[7], date(2026, 12, 1))
        notify.assert_not_called()
