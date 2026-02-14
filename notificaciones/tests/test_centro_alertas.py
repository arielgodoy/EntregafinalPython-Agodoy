from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from notificaciones.models import Notification


class TestCentroAlertas(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        self.user = User.objects.create_user(username="user1", password="pass")

        Notification.objects.create(
            destinatario=self.user,
            empresa=self.empresa_a,
            tipo=Notification.Tipo.ALERT,
            titulo="ALERTA A",
        )
        Notification.objects.create(
            destinatario=self.user,
            empresa=None,
            tipo=Notification.Tipo.ALERT,
            titulo="ALERTA GLOBAL",
        )
        Notification.objects.create(
            destinatario=self.user,
            empresa=self.empresa_b,
            tipo=Notification.Tipo.ALERT,
            titulo="ALERTA B",
        )

    def _login_with_empresa(self):
        self.client.force_login(self.user)
        vista, _ = Vista.objects.get_or_create(
            nombre="notificaciones.mis_notificaciones",
            defaults={"descripcion": "Vista de notificaciones"},
        )
        Permiso.objects.update_or_create(
            usuario=self.user,
            empresa=self.empresa_a,
            vista=vista,
            defaults={"ingresar": True},
        )
        session = self.client.session
        session["empresa_id"] = self.empresa_a.id
        session.save()

    def test_scope_only_active(self):
        self._login_with_empresa()
        response = self.client.get(reverse("notificaciones:centro_alertas") + "?scope=only_active")
        titles = [item.titulo for item in response.context["page_obj"].object_list]
        self.assertIn("ALERTA A", titles)
        self.assertNotIn("ALERTA GLOBAL", titles)
        self.assertNotIn("ALERTA B", titles)

    def test_scope_only_global(self):
        self._login_with_empresa()
        response = self.client.get(reverse("notificaciones:centro_alertas") + "?scope=only_global")
        titles = [item.titulo for item in response.context["page_obj"].object_list]
        self.assertIn("ALERTA GLOBAL", titles)
        self.assertNotIn("ALERTA A", titles)
        self.assertNotIn("ALERTA B", titles)

    def test_scope_active_default(self):
        self._login_with_empresa()
        response = self.client.get(reverse("notificaciones:centro_alertas"))
        titles = [item.titulo for item in response.context["page_obj"].object_list]
        self.assertIn("ALERTA A", titles)
        self.assertIn("ALERTA GLOBAL", titles)
        self.assertNotIn("ALERTA B", titles)
