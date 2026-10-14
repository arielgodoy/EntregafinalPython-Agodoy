from types import SimpleNamespace
from urllib.parse import parse_qs
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, TestCase

from auditoria.models import AuditoriaTareasEvent
from tareas.services.audit import log_task_operation, task_audit_snapshot


class TaskAuditAdapterTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().post("/tareas/compartida/secreto/")
        self.request.session = {"empresa_id": 42}
        self.request.user = AnonymousUser()
        self.request.resolver_match = SimpleNamespace(
            kwargs={"token": "secreto"},
        )
        self.request.META["QUERY_STRING"] = "token=secreto&vista=detalle"

    @patch("tareas.services.audit.AuditoriaService.log_event")
    def test_logs_scoped_operation_without_shared_token(self, log_event):
        log_event.return_value = object()

        operation_id = log_task_operation(
            self.request,
            task_id=17,
            empresa_id=42,
            action="UPDATE",
            operation="publish_task",
            before={"estado": "BORRADOR"},
            after={"estado": "ACTIVA"},
        )

        self.assertEqual(len(operation_id), 32)
        self.assertTrue(self.request._audit_logged)
        kwargs = log_event.call_args.kwargs
        self.assertEqual(kwargs["app_label"], "tareas")
        self.assertEqual(kwargs["empresa_id"], 42)
        self.assertNotIn("secreto", kwargs["path"])
        self.assertNotIn("secreto", kwargs["querystring"])
        self.assertEqual(
            parse_qs(kwargs["querystring"]),
            {"token": ["[REDACTED]"], "vista": ["detalle"]},
        )
        self.assertEqual(kwargs["meta"]["operation"], "publish_task")
        self.assertEqual(kwargs["after"], {"estado": "ACTIVA"})

    @patch("tareas.services.audit.AuditoriaService.log_event")
    def test_does_not_write_outside_active_company(self, log_event):
        result = log_task_operation(
            self.request,
            task_id=17,
            empresa_id=99,
            action="UPDATE",
            operation="publish_task",
        )

        self.assertIsNone(result)
        log_event.assert_not_called()
        self.assertFalse(getattr(self.request, "_audit_logged", False))

    def test_snapshot_normalizes_lifecycle_state(self):
        snapshot = task_audit_snapshot(
            SimpleNamespace(state="ACTIVA", transition_id=4)
        )

        self.assertEqual(snapshot, {"estado": "ACTIVA"})


class TaskAuditPersistenceTests(TestCase):
    def test_persists_event_in_the_tasks_audit_table(self):
        request = RequestFactory().post("/tareas/17/publicar/")
        request.session = {"empresa_id": 42}
        request.user = AnonymousUser()

        operation_id = log_task_operation(
            request,
            task_id=17,
            empresa_id=42,
            action="UPDATE",
            operation="publish_task",
            before={"estado": "BORRADOR"},
            after={"estado": "ACTIVA"},
            meta={"api_token": "sensitive", "transition_id": 9},
        )

        event = AuditoriaTareasEvent.objects.get(object_id="17")
        self.assertEqual(event.empresa_id, 42)
        self.assertEqual(event.action, "UPDATE")
        self.assertEqual(event.meta["operation_id"], operation_id)
        self.assertNotIn("api_token", event.meta)
        self.assertEqual(event.meta["transition_id"], 9)
        self.assertEqual(event.before, {"estado": "BORRADOR"})
        self.assertEqual(event.after, {"estado": "ACTIVA"})
