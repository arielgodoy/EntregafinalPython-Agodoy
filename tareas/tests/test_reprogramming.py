from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa
from tareas.forms import ReprogramTaskForm
from tareas.models import (
    Avance, CausaAtraso, Reprogramacion, Tarea, TareaConnectionRole,
    TareaParticipante, TareaRelacion, TareaTransicion,
)
from tareas.services.detail_storage import (
    DjangoTaskDetailStorage, MySQLTaskDetailStorage, TaskDetailSections, resolve_detail_storage,
)
from tareas.services.reprogramming_storage import (
    DjangoReprogrammingStorage, MySQLReprogrammingStorage,
    ReprogramTaskCommand, django_reprogramming_detail, mysql_reprogramming_detail,
    reprogram_task, resolve_reprogramming_storage,
)
from tareas.services.connection_roles import BackendContext, TareaConnectionRoleNotFoundError
from tareas.services.task_storage import EditTaskNotFound, TaskStorageError
from tareas.tests.factories import activate_company, assign_permission, create_user


class ReprogrammingFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="RPG", descripcion="Reprogramming")
        cls.other_empresa = Empresa.objects.create(codigo="RPO", descripcion="Other")
        cls.actor = create_user("reprogrammer")
        cls.creator = create_user("rp-creator")
        cls.responsible = create_user("rp-responsible")
        cls.participant = create_user("rp-participant")
        cls.role = TareaConnectionRole.objects.create(
            role="BASE_TAREAS", source_type="DJANGO", django_alias="default"
        )
        for codigo, nombre in (
            ("IMPOSIBILIDAD_TECNICA", "Imposibilidad técnica"),
            ("ATRASO_IMPORTACION", "Atraso importación"),
        ):
            CausaAtraso.objects.create(codigo=codigo, nombre=nombre)
        cls.inactive = create_user("rp-inactive")
        cls.inactive.is_active = False
        cls.inactive.save(update_fields=["is_active"])
        assign_permission(cls.actor, cls.empresa, "Tareas", ingresar=True, modificar=True)
        cls.causes = tuple(CausaAtraso.objects.order_by("codigo")[:2])

    def setUp(self):
        self.task = Tarea.objects.create(
            titulo="RP test", empresa=self.empresa, creada_por=self.creator,
            responsable=self.responsible, estado=Tarea.Estado.GESTION,
            fecha_tope=timezone.localdate() + timedelta(days=8),
            fecha_publicacion=timezone.now(), fecha_asignacion=timezone.now(),
            fecha_cumplimiento=timezone.now(), cierre_completado=True,
            fechas_pendientes_confirmacion=True,
        )
        self.command = ReprogramTaskCommand(
            self.task.pk, self.empresa.pk, self.actor.pk,
            timezone.localdate() + timedelta(days=12), "  TEST reason  ",
            tuple(item.pk for item in self.causes),
        )


class ReprogrammingTests(ReprogrammingFixture):
    def assert_unchanged(self):
        self.task.refresh_from_db()
        self.assertEqual(self.task.fecha_tope, timezone.localdate() + timedelta(days=8))
        self.assertFalse(self.task.reprogramaciones.exists())

    def test_states_and_field_preservation(self):
        before = Tarea.objects.filter(pk=self.task.pk).values().get()
        Avance.objects.create(tarea=self.task)
        for state in (*Tarea.Estado.values, "UNKNOWN"):
            with self.subTest(state=state):
                Tarea.objects.filter(pk=self.task.pk).update(
                    estado=state, fecha_tope=before["fecha_tope"]
                )
                if state in {Tarea.Estado.ACTIVA, Tarea.Estado.GESTION}:
                    result = reprogram_task(self.command)
                    self.assertEqual(result.fecha_tope_anterior, before["fecha_tope"])
                else:
                    count = Reprogramacion.objects.count()
                    with self.assertRaisesMessage(ValidationError, "invalid_state"):
                        reprogram_task(self.command)
                    self.assertEqual(Reprogramacion.objects.count(), count)
                    self.task.refresh_from_db()
                    self.assertEqual(self.task.fecha_tope, before["fecha_tope"])
        after = Tarea.objects.filter(pk=self.task.pk).values().get()
        for key in before.keys() - {"estado", "fecha_tope"}:
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(Avance.objects.filter(tarea=self.task).count(), 1)
        self.assertFalse(TareaTransicion.objects.filter(tarea=self.task).exists())

    @patch("tareas.services.reprogramming_storage._notify")
    def test_direct_parent_and_grandparent_annulment(self, notify):
        parent = Tarea.objects.create(
            titulo="parent", empresa=self.empresa, creada_por=self.creator
        )
        grandparent = Tarea.objects.create(
            titulo="grandparent", empresa=self.empresa, creada_por=self.creator
        )
        TareaRelacion.objects.create(padre=parent, hija=self.task)
        TareaRelacion.objects.create(padre=grandparent, hija=parent)
        for node in (self.task, parent, grandparent):
            with self.subTest(node=node.pk):
                Tarea.objects.filter(pk=node.pk).update(anulada=True)
                with self.assertRaisesMessage(ValidationError, "annulled"):
                    reprogram_task(self.command)
                self.assert_unchanged()
                Tarea.objects.filter(pk=node.pk).update(anulada=False)
        notify.assert_not_called()
        reprogram_task(self.command)
        parent.refresh_from_db()
        grandparent.refresh_from_db()
        self.assertIsNone(parent.fecha_tope)
        self.assertIsNone(grandparent.fecha_tope)

    def test_dates_and_normalization(self):
        for value in (self.task.fecha_tope, timezone.localdate() - timedelta(days=1), None, "bad"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    reprogram_task(replace(self.command, fecha_tope_nueva=value))
                self.assert_unchanged()
        aware = timezone.make_aware(datetime.combine(
            timezone.localdate(), datetime.min.time()
        ))
        result = reprogram_task(replace(self.command, fecha_tope_nueva=aware))
        self.assertEqual(result.fecha_tope_nueva, timezone.localdate())
        naive = datetime.combine(timezone.localdate() + timedelta(days=1), datetime.min.time())
        result = reprogram_task(replace(self.command, fecha_tope_nueva=naive))
        self.assertEqual(result.fecha_tope_anterior, timezone.localdate())
        Tarea.objects.filter(pk=self.task.pk).update(fecha_tope=None)
        with self.assertRaisesMessage(ValidationError, "missing_current_date"):
            reprogram_task(self.command)

    def test_justification_and_causes(self):
        for reason in ("", "   "):
            with self.assertRaisesMessage(ValidationError, "justification_required"):
                reprogram_task(replace(self.command, justificacion=reason))
        cause_id = self.causes[0].pk
        for ids in ((), (None,), (cause_id, cause_id), (999999,), ("bad",)):
            with self.subTest(ids=ids):
                with self.assertRaises(ValidationError):
                    reprogram_task(replace(self.command, causa_ids=ids))
                self.assert_unchanged()
        result = reprogram_task(replace(self.command, causa_ids=(cause_id,)))
        history = Reprogramacion.objects.get(pk=result.reprogramacion_id)
        self.assertEqual(history.justificacion, "TEST reason")
        self.assertEqual(list(history.causas.values_list("pk", flat=True)), [cause_id])

    def test_history_reads_locked_date_not_stale_object(self):
        first = reprogram_task(self.command)
        second = reprogram_task(replace(
            self.command, fecha_tope_nueva=self.command.fecha_tope_nueva + timedelta(days=1)
        ))
        self.assertEqual(second.fecha_tope_anterior, first.fecha_tope_nueva)
        causes, history = django_reprogramming_detail("default", self.task.pk, self.empresa.pk)
        self.assertEqual([item.id for item in history], [
            second.reprogramacion_id, first.reprogramacion_id
        ])
        self.assertEqual(len(history[0].causas), 2)
        self.assertEqual([item.codigo for item in causes], sorted(item.codigo for item in causes))
        detail = DjangoTaskDetailStorage("default").get_task_detail(
            task_id=self.task.pk, empresa_id=self.empresa.pk, sections=TaskDetailSections()
        )
        self.assertEqual(detail.reprogramming_history[0].usuario_username, self.actor.username)

    def test_company_actor_and_permission_isolation(self):
        with self.assertRaises(EditTaskNotFound):
            DjangoReprogrammingStorage("default").reprogram(
                replace(self.command, empresa_id=self.other_empresa.pk)
            )
        for actor in (self.creator, self.inactive):
            with self.assertRaises(PermissionDenied):
                reprogram_task(replace(self.command, actor_id=actor.pk))
        assign_permission(self.creator, self.empresa, "Tareas", ingresar=True)
        with self.assertRaises(PermissionDenied):
            reprogram_task(replace(self.command, actor_id=self.creator.pk))
        self.assert_unchanged()

    def test_django_rollback_history_and_m2m(self):
        for target in (
            "django.db.models.query.QuerySet.create",
            "django.db.models.query.QuerySet.bulk_create",
        ):
            with self.subTest(target=target):
                with patch(target, side_effect=RuntimeError("simulated write failure")):
                    with self.assertRaises(TaskStorageError):
                        reprogram_task(self.command)
                self.assert_unchanged()

    @patch("tareas.services.reprogramming_storage.resolve_operational_backend")
    def test_no_fallback(self, resolve):
        resolve.side_effect = TareaConnectionRoleNotFoundError("missing")
        with self.assertRaisesMessage(TaskStorageError, "backend"):
            reprogram_task(self.command)
        self.assert_unchanged()

    @patch("tareas.services.detail_storage.resolve_operational_backend")
    def test_detail_configuration_error_has_no_fallback(self, resolve):
        resolve.side_effect = TareaConnectionRoleNotFoundError("missing")
        with self.assertRaises(TaskStorageError):
            resolve_detail_storage()

    @patch("tareas.services.notifications.send_task_email")
    @patch("tareas.services.notifications.notify_task_event")
    def test_notifications_after_commit_recipients_and_email(self, notify, email):
        for user in (self.actor, self.responsible, self.participant, self.inactive):
            TareaParticipante.objects.create(
                tarea=self.task, usuario=user, rol=TareaParticipante.Rol.PARTICIPANTE
            )
        self.responsible.email = "responsible@example.test"
        self.responsible.save(update_fields=["email"])
        Tarea.objects.filter(pk=self.task.pk).update(prioridad=Tarea.Prioridad.CRITICA)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            reprogram_task(self.command)
            notify.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(
            {call.kwargs["destinatario"].pk for call in notify.call_args_list},
            {self.responsible.pk, self.participant.pk},
        )
        self.assertTrue(all(":reprogramacion:" in call.kwargs["dedupe_key"]
                            for call in notify.call_args_list))
        email.assert_called_once()
        notify.side_effect = RuntimeError("simulated notification failure")
        email.side_effect = RuntimeError("simulated mail failure")
        with self.assertLogs("tareas.services.notifications", level="ERROR"):
            with self.captureOnCommitCallbacks(execute=True):
                reprogram_task(replace(
                    self.command, fecha_tope_nueva=self.command.fecha_tope_nueva + timedelta(days=1)
                ))
        self.assertEqual(Reprogramacion.objects.filter(tarea=self.task).count(), 2)

    @patch("tareas.services.notifications.send_task_email")
    def test_noncritical_has_no_email(self, email):
        with self.captureOnCommitCallbacks(execute=True):
            reprogram_task(self.command)
        email.assert_not_called()

    def _login(self, client=None):
        client = client or self.client
        client.force_login(self.actor)
        activate_company(client, self.empresa)
        return client

    def _post(self, **overrides):
        data = {
            "fecha_tope_nueva": self.command.fecha_tope_nueva.isoformat(),
            "justificacion": "TEST POST", "causa_ids": list(self.command.causa_ids),
        }
        data.update(overrides)
        return self.client.post(reverse("tareas:reprogramar_tarea", args=[self.task.pk]), data)

    def test_endpoint_prg_ignores_post_company_and_404(self):
        self._login()
        response = self._post(empresa_id=self.other_empresa.pk)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("#tarea-reprogramaciones"))
        self.task.refresh_from_db()
        self.assertEqual(self.task.fecha_tope, self.command.fecha_tope_nueva)
        response = self.client.post(
            reverse("tareas:reprogramar_tarea", args=[999999]),
            {"fecha_tope_nueva": self.command.fecha_tope_nueva.isoformat(),
             "justificacion": "TEST", "causa_ids": list(self.command.causa_ids)},
        )
        self.assertEqual(response.status_code, 404)

    def test_get_csrf_permission_and_form_errors(self):
        self._login()
        url = reverse("tareas:reprogramar_tarea", args=[self.task.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = self._login(Client(enforce_csrf_checks=True))
        self.assertEqual(csrf_client.post(url, {}).status_code, 403)
        self.assertEqual(self._post(fecha_tope_nueva="invalid").status_code, 302)
        self.assert_unchanged()
        assign_permission(self.actor, self.empresa, "Tareas", ingresar=True)
        self.assertEqual(self._post().status_code, 403)
        self.assert_unchanged()

    def test_post_cross_company_rejected_and_validation_errors_visible(self):
        self._login()
        Tarea.objects.filter(pk=self.task.pk).update(empresa=self.other_empresa)
        self.assertEqual(self._post().status_code, 404)
        self.assert_unchanged()
        Tarea.objects.filter(pk=self.task.pk).update(empresa=self.empresa)
        for data, key in (
            ({"justificacion": " "}, "justification_required"),
            ({"causa_ids": []}, "causes_required"),
            ({"causa_ids": ["bad"]}, "invalid_causes"),
            ({"causa_ids": [self.causes[0].pk] * 2}, "duplicate_causes"),
            ({"fecha_tope_nueva": (timezone.localdate() - timedelta(days=1)).isoformat()}, "past_date"),
        ):
            with self.subTest(key=key):
                response = self._post(**data)
                self.assertEqual(response.status_code, 302)
                response = self.client.get(response.url)
                self.assertContains(response, "tareas.reprogramming.errors." + key)
                self.assert_unchanged()

    def test_detail_modal_history_visibility_and_escaping(self):
        self._login()
        reprogram_task(replace(self.command, justificacion="<script>bad</script>"))
        response = self.client.get(reverse("tareas:detalle_tarea", args=[self.task.pk]))
        self.assertContains(response, 'id="reprogramar-tarea-modal"')
        self.assertContains(response, "&lt;script&gt;bad&lt;/script&gt;")
        self.assertContains(response, self.actor.username)
        self.assertContains(response, self.causes[0].nombre)
        for state in (Tarea.Estado.BORRADOR, Tarea.Estado.PENDIENTE_APROBACION_CIERRE, Tarea.Estado.CERRADA):
            Tarea.objects.filter(pk=self.task.pk).update(estado=state)
            response = self.client.get(reverse("tareas:detalle_tarea", args=[self.task.pk]))
            self.assertNotContains(response, 'id="reprogramar-tarea-modal"')
            self.assertContains(response, "&lt;script&gt;bad&lt;/script&gt;")
        Tarea.objects.filter(pk=self.task.pk).update(estado=Tarea.Estado.GESTION, anulada=True)
        response = self.client.get(reverse("tareas:detalle_tarea", args=[self.task.pk]))
        self.assertNotContains(response, 'id="reprogramar-tarea-modal"')
        Tarea.objects.filter(pk=self.task.pk).update(anulada=False)
        assign_permission(self.actor, self.empresa, "Tareas", ingresar=True)
        response = self.client.get(reverse("tareas:detalle_tarea", args=[self.task.pk]))
        self.assertNotContains(response, 'id="reprogramar-tarea-modal"')

    def test_form_preserves_duplicate_causes_for_storage_validation(self):
        form = ReprogramTaskForm({
            "fecha_tope_nueva": timezone.localdate().isoformat(),
            "justificacion": " test ", "causa_ids": ["1", "1"],
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["causa_ids"], (1, 1))


class FakeReprogrammingConnection:
    """Transactional fake: rollback restores the actual simulated write set."""
    def __init__(self, task_id, empresa_id, actor_id, cause_ids):
        self.task = (task_id, Tarea.Estado.GESTION, False,
                     timezone.localdate() + timedelta(days=5), "NORMAL", actor_id)
        self.empresa_id = empresa_id
        self.causes = set(cause_ids)
        self.parents = {}
        self.history = []
        self.m2m = []
        self.calls = []
        self.fail = None
        self.commits = 0
        self.rollbacks = 0
        self.lastrowid = None
        self.results = []
        self.closed = False

    def cursor(self):
        return self

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.task, self.history, self.m2m = deepcopy(self.snapshot)
        self.rollbacks += 1

    def close(self):
        self.closed = True

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        self.results = []
        if sql == "START TRANSACTION":
            self.snapshot = deepcopy((self.task, self.history, self.m2m))
        elif sql.startswith("SELECT id, estado"):
            self.results = [self.task] if params == (self.task[0], self.empresa_id) else []
        elif sql.startswith("SELECT p.id"):
            parent = self.parents.get(params[0])
            self.results = [parent] if parent else []
        elif sql.startswith("SELECT id FROM tareas_causaatraso"):
            self.results = [(item,) for item in params if item in self.causes]
        elif sql.startswith("SELECT p.usuario_id"):
            self.results = []
        elif sql.startswith("UPDATE"):
            self.task = (*self.task[:3], params[0], *self.task[4:])
        elif sql.startswith("INSERT INTO tareas_reprogramacion_causas"):
            if self.fail == "m2m" or (self.fail == "second_m2m" and self.m2m):
                raise RuntimeError("simulated M2M failure")
            self.m2m.append(params)
        elif sql.startswith("INSERT INTO tareas_reprogramacion "):
            if self.fail == "history":
                raise RuntimeError("simulated history failure")
            self.history.append(params)
            self.lastrowid = len(self.history)
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.results[0] if self.results else None

    def fetchall(self):
        return self.results


class MySQLReprogrammingTests(ReprogrammingFixture):
    def fake_operation(self, fake, command=None):
        with patch("tareas.services.reprogramming_storage.open_mysql_connection",
                   return_value=nullcontext(fake)):
            with patch("tareas.services.reprogramming_storage._notify") as notify:
                result = MySQLReprogrammingStorage(object(), "tareas").reprogram(
                    command or self.command
                )
                return result, notify

    def fake(self):
        return FakeReprogrammingConnection(
            self.task.pk, self.empresa.pk, self.actor.pk, self.command.causa_ids
        )

    def test_mysql_same_pk_and_cause_collision(self):
        fake = self.fake()
        self.assertFalse(hasattr(fake, "begin"))
        original = self.task.fecha_tope
        result, notify = self.fake_operation(fake)
        self.assertEqual(fake.task[3], self.command.fecha_tope_nueva)
        self.assertEqual(result.fecha_tope_anterior, timezone.localdate() + timedelta(days=5))
        self.assertEqual(len(fake.history), 1)
        self.assertEqual(len(fake.m2m), 2)
        self.task.refresh_from_db()
        self.assertEqual(self.task.fecha_tope, original)
        self.assertFalse(self.task.reprogramaciones.exists())
        self.assertEqual(fake.commits, 1)
        self.assertEqual(fake.calls[0], ("START TRANSACTION", ()))
        notify.assert_called_once()
        self.assertTrue(any("FOR UPDATE" in sql and "empresa_id=%s" in sql
                            for sql, params in fake.calls))
        missing = self.fake()
        missing.causes.clear()
        with self.assertRaisesMessage(ValidationError, "invalid_causes"):
            self.fake_operation(missing)
        self.assertFalse(missing.history)

    def test_mysql_endpoint_same_pk_uses_only_resolved_backend(self):
        fake = self.fake()
        self.client.force_login(self.actor)
        activate_company(self.client, self.empresa)
        with patch("tareas.services.reprogramming_storage.resolve_operational_backend",
                   return_value=BackendContext(
                       logical_role="BASE_TAREAS", backend_type="MYSQL_CONFIG",
                       mysql_connection=object(), database_name="tareas",
                   )), \
             patch("tareas.services.reprogramming_storage.open_mysql_connection",
                   return_value=nullcontext(fake)), \
             patch("tareas.services.reprogramming_storage._notify"), \
             patch("tareas.services.reprogramming_storage.Tarea.objects.get",
                   side_effect=AssertionError("Django task lookup")):
            response = self.client.post(
                reverse("tareas:reprogramar_tarea", args=[self.task.pk]),
                {"fecha_tope_nueva": self.command.fecha_tope_nueva.isoformat(),
                 "justificacion": "MYSQL POST", "causa_ids": list(self.command.causa_ids)},
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(fake.commits, 1)
        self.task.refresh_from_db()
        self.assertEqual(self.task.fecha_tope, timezone.localdate() + timedelta(days=8))
        self.assertFalse(self.task.reprogramaciones.exists())

    def test_mysql_company_and_states(self):
        for state in (*Tarea.Estado.values, "UNKNOWN"):
            with self.subTest(state=state):
                fake = self.fake()
                fake.task = (fake.task[0], state, *fake.task[2:])
                if state in {Tarea.Estado.ACTIVA, Tarea.Estado.GESTION}:
                    self.fake_operation(fake)
                    self.assertEqual(fake.commits, 1)
                else:
                    with self.assertRaises(ValidationError):
                        self.fake_operation(fake)
                    self.assertFalse(fake.history)
                    self.assertFalse(any(sql.startswith("UPDATE") for sql, _ in fake.calls))
        fake = self.fake()
        with self.assertRaises(EditTaskNotFound):
            self.fake_operation(fake, replace(self.command, empresa_id=self.other_empresa.pk))
        self.assertFalse(fake.history)

    def test_mysql_annulment_chain(self):
        for level in range(3):
            with self.subTest(level=level):
                fake = self.fake()
                fake.parents = {self.task.pk: (800, level == 1), 800: (900, level == 2)}
                fake.task = (*fake.task[:2], level == 0, *fake.task[3:])
                with self.assertRaisesMessage(ValidationError, "annulled"):
                    self.fake_operation(fake)
                self.assertFalse(fake.history)
                self.assertFalse(fake.m2m)

    def test_mysql_rollback_each_write_boundary(self):
        for failure in ("history", "m2m", "second_m2m"):
            with self.subTest(failure=failure):
                fake = self.fake()
                original = fake.task
                fake.fail = failure
                with self.assertRaises(TaskStorageError):
                    self.fake_operation(fake)
                self.assertEqual(fake.task, original)
                self.assertEqual(fake.history, [])
                self.assertEqual(fake.m2m, [])
                self.assertEqual(fake.rollbacks, 1)
                self.assertEqual(fake.commits, 0)

    def test_mysql_sequential_lock_capture(self):
        fake = self.fake()
        first, _ = self.fake_operation(fake)
        second, _ = self.fake_operation(fake, replace(
            self.command, fecha_tope_nueva=self.command.fecha_tope_nueva + timedelta(days=1)
        ))
        self.assertEqual(second.fecha_tope_anterior, first.fecha_tope_nueva)
        self.assertEqual(fake.history[1][1], fake.history[0][2])

    @patch("tareas.services.reprogramming_storage.User.objects")
    def test_mysql_communication_failure_does_not_rollback(self, users):
        fake = self.fake()
        users.using.side_effect = RuntimeError("simulated identity read failure")
        with patch("tareas.services.reprogramming_storage.open_mysql_connection",
                   return_value=nullcontext(fake)):
            with self.assertLogs("tareas.services.reprogramming_storage", level="ERROR"):
                MySQLReprogrammingStorage(object(), "tareas").reprogram(self.command)
        self.assertEqual(fake.commits, 1)
        self.assertEqual(fake.rollbacks, 0)
        self.assertEqual(len(fake.history), 1)

    def test_mysql_input_failures_no_write(self):
        invalid = [
            replace(self.command, fecha_tope_nueva=timezone.localdate() - timedelta(days=1)),
            replace(self.command, justificacion=" "),
            replace(self.command, causa_ids=()),
            replace(self.command, causa_ids=(None,)),
            replace(self.command, causa_ids=(self.causes[0].pk,) * 2),
        ]
        for command in invalid:
            with self.subTest(command=command):
                fake = self.fake()
                with self.assertRaises(ValidationError):
                    self.fake_operation(fake, command)
                self.assertFalse(fake.history)
                self.assertFalse(fake.m2m)
        for old_date in (None, self.command.fecha_tope_nueva):
            fake = self.fake()
            fake.task = (*fake.task[:3], old_date, *fake.task[4:])
            with self.assertRaises(ValidationError):
                self.fake_operation(fake)

    def test_mysql_today_advance_and_postpone(self):
        for value in (
            timezone.localdate(),
            timezone.localdate() + timedelta(days=3),
            timezone.localdate() + timedelta(days=12),
        ):
            with self.subTest(value=value):
                fake = self.fake()
                original = fake.task
                result, _ = self.fake_operation(
                    fake, replace(self.command, fecha_tope_nueva=value)
                )
                self.assertEqual(result.fecha_tope_anterior, original[3])
                self.assertEqual(fake.task[3], value)
                self.assertEqual(fake.task[:3], original[:3])
                self.assertEqual(fake.task[4:], original[4:])
                self.assertEqual(fake.history[0][1:3], (original[3], value))

    def test_mysql_detail_causes_and_history_are_operational(self):
        cursor = MagicMock()
        now = timezone.now()
        cursor.fetchall.side_effect = [
            [(7, "MYSQL", "MYSQL-only cause")],
            [(12, self.task.fecha_tope, self.command.fecha_tope_nueva,
              "MYSQL reason", self.actor.pk, now)],
            [(12, 7, "MYSQL", "MYSQL-only cause")],
        ]
        causes, history = mysql_reprogramming_detail(cursor, self.task.pk, self.empresa.pk)
        self.assertEqual(causes[0].nombre, "MYSQL-only cause")
        self.assertEqual(history[0].causas, causes)
        self.assertTrue(all("empresa_id=%s" in call.args[0]
                            for call in cursor.execute.call_args_list[1:]))

    @patch("tareas.services.detail_storage.open_mysql_connection")
    def test_mysql_full_detail_and_modal_resolve_actor_and_causes(self, open_connection):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        now = timezone.now()
        task = {
            "id": self.task.pk, "titulo": "MYSQL RP", "descripcion": "",
            "prioridad": "NORMAL", "correlativo": "A0000001", "anulada": 0,
            "fechas_pendientes_confirmacion": 0, "requiere_evidencia_cierre": 0,
            "estado": "GESTION", "responsable_id": self.responsible.pk,
            "empresa_id": self.empresa.pk, "creada_por_id": self.creator.pk,
            "fecha_creacion": now, "fecha_publicacion": now, "fecha_asignacion": now,
            "fecha_tope": self.command.fecha_tope_nueva, "fecha_cumplimiento": None,
        }

        def execute(sql, params=()):
            cursor._rows = []
            cursor.description = []
            if sql.startswith("SELECT id, titulo"):
                cursor.description = [(name,) for name in task]
                cursor._rows = [tuple(task.values())]
            elif sql.startswith("SELECT id, codigo"):
                cursor._rows = [(700, "MYSQL", "MYSQL-only cause")]
            elif sql.startswith("SELECT r.id, r.fecha_tope"):
                cursor._rows = [
                    (12, self.task.fecha_tope, self.command.fecha_tope_nueva,
                     "MYSQL TEST reason", self.actor.pk, now)
                ]
            elif sql.startswith("SELECT rc.reprogramacion_id"):
                cursor._rows = [(12, 700, "MYSQL", "MYSQL-only cause")]
        cursor.execute.side_effect = execute
        cursor.fetchall.side_effect = lambda: cursor._rows
        open_connection.side_effect = lambda *args, **kwargs: nullcontext(connection)
        storage = MySQLTaskDetailStorage(object(), "tareas")
        result = storage.get_task_detail(
            task_id=self.task.pk, empresa_id=self.empresa.pk, sections=TaskDetailSections()
        )
        self.assertEqual(result.reprogramming_history[0].usuario_username, self.actor.username)
        self.assertEqual(result.reprogramming_history[0].causas[0].nombre, "MYSQL-only cause")
        self.client.force_login(self.actor)
        activate_company(self.client, self.empresa)
        with patch("tareas.views.resolve_detail_storage", return_value=storage):
            response = self.client.get(reverse("tareas:detalle_tarea", args=[self.task.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MYSQL TEST reason")
        self.assertContains(response, "MYSQL-only cause")
        self.assertContains(response, self.actor.username)
        self.assertContains(response, 'value="700"')
        self.assertNotContains(response, self.causes[0].nombre)

    @patch("tareas.services.reprogramming_storage.resolve_operational_backend")
    def test_mysql_resolver_uses_existing_role(self, resolve):
        resolve.return_value = BackendContext(
            logical_role="BASE_TAREAS", backend_type="MYSQL_CONFIG",
            mysql_connection=object(), database_name="tareas",
        )
        storage = resolve_reprogramming_storage()
        self.assertIsInstance(storage, MySQLReprogrammingStorage)
        self.assertEqual(storage.database_name, "tareas")
        resolve.assert_called_once_with("BASE_TAREAS")


class DjangoReprogrammingAliasTests(ReprogrammingFixture):
    databases = {"default", "system_test"}

    def test_explicit_alias_with_colliding_task_and_causes(self):
        alias = "system_test"
        Empresa.objects.using(alias).create(pk=self.empresa.pk, codigo="RPG")
        from django.contrib.auth.models import User
        User.objects.using(alias).bulk_create([
            User(pk=user.pk, username=user.username)
            for user in (self.actor, self.creator, self.responsible)
        ])
        other = Tarea(
            pk=self.task.pk, titulo="Other alias", empresa_id=self.empresa.pk,
            creada_por_id=self.creator.pk, responsable_id=self.responsible.pk,
            estado=Tarea.Estado.ACTIVA, correlativo="A0000001",
            fecha_tope=timezone.localdate() + timedelta(days=2),
        )
        other.save(using=alias)
        self.role.django_alias = alias
        self.role.save(update_fields=["django_alias"])
        for cause in self.causes:
            CausaAtraso.objects.using(alias).create(
                pk=cause.pk, codigo=cause.codigo, nombre=cause.nombre,
            )
        result = reprogram_task(self.command)
        other.refresh_from_db(using=alias)
        self.assertEqual(other.fecha_tope, self.command.fecha_tope_nueva)
        history = Reprogramacion.objects.using(alias).get(pk=result.reprogramacion_id)
        self.assertEqual(
            history.causas.using(alias).count(), len(self.command.causa_ids)
        )
        self.assertEqual(Reprogramacion.objects.using("default").count(), 0)
        self.task.refresh_from_db()
        self.assertEqual(self.task.fecha_tope, timezone.localdate() + timedelta(days=8))
        _causes, records = django_reprogramming_detail(alias, self.task.pk, self.empresa.pk)
        self.assertEqual(records[0].id, result.reprogramacion_id)
