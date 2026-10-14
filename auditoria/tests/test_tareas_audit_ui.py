from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from access_control.services.permissions import get_sidebar_visible_items
from auditoria.models import AuditoriaTareasEvent


User = get_user_model()


class TareasAuditUITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tareas-auditor", password="test")
        self.empresa_autorizada = Empresa.objects.create(codigo="01")
        self.empresa_sin_permiso = Empresa.objects.create(codigo="02")
        self.vista = Vista.objects.create(
            nombre="Auditoría - Tareas",
            route_name="auditoria:auditoria_tareas_list",
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa_autorizada,
            vista=self.vista,
            ver=True,
            ingresar=True,
        )
        self.evento_autorizado = AuditoriaTareasEvent.objects.create(
            empresa_id=self.empresa_autorizada.pk,
            action="CREATE",
            object_type="Tarea",
            object_id="11",
            path="/tareas/",
        )
        self.evento_ajeno = AuditoriaTareasEvent.objects.create(
            empresa_id=self.empresa_sin_permiso.pk,
            action="CREATE",
            object_type="Tarea",
            object_id="22",
            path="/tareas/",
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa_autorizada.pk
        session.save()

    def test_list_and_detail_are_scoped_to_auditable_companies(self):
        response = self.client.get(reverse("auditoria:auditoria_tareas_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {event.pk for event in response.context["eventos"]},
            {self.evento_autorizado.pk},
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    "auditoria:auditoria_tareas_detail",
                    args=[self.evento_ajeno.pk],
                )
            ).status_code,
            404,
        )

    def test_list_requires_ingresar_permission(self):
        user_without_access = User.objects.create_user(
            username="tareas-auditor-without-access",
            password="test",
        )
        self.client.force_login(user_without_access)
        session = self.client.session
        session["empresa_id"] = self.empresa_autorizada.pk
        session.save()

        response = self.client.get(reverse("auditoria:auditoria_tareas_list"))

        self.assertEqual(response.status_code, 403)

    def test_sidebar_visibility_requires_ver_but_not_ingresar(self):
        permiso = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa_autorizada,
            vista=self.vista,
        )
        permiso.ingresar = False
        permiso.save(update_fields=["ingresar"])

        visible_items = get_sidebar_visible_items(
            self.user,
            self.empresa_autorizada.pk,
        )

        self.assertIn("audit_tasks", visible_items)
        self.assertIn("audit", visible_items)
