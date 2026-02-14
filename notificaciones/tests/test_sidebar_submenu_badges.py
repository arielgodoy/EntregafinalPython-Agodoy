from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, PerfilAcceso, Permiso, UsuarioPerfilEmpresa, Vista
from notificaciones.models import Notification


class TestSidebarSubmenuBadges(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="user_a",
            email="user_a@example.com",
            password="pass12345",
            is_staff=True,
        )
        perfil = PerfilAcceso.objects.create(nombre="Basico", is_active=True)
        UsuarioPerfilEmpresa.objects.create(usuario=self.user, empresa=self.empresa, perfil=perfil)

    def _login_with_empresa(self):
        self.client.force_login(self.user)
        vista, _ = Vista.objects.get_or_create(
            nombre="Notificaciones - Mis Notificaciones",
            defaults={"descripcion": "Vista de notificaciones"},
        )
        Permiso.objects.update_or_create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            defaults={"ingresar": True},
        )
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session["empresa_nombre"] = self.empresa.descripcion
        session.save()

    def test_sidebar_submenu_badges(self):
        for _ in range(2):
            Notification.objects.create(
                destinatario=self.user,
                empresa=self.empresa,
                tipo=Notification.Tipo.ALERT,
                titulo="Alerta",
                cuerpo="",
                is_read=False,
            )
        Notification.objects.create(
            destinatario=self.user,
            empresa=self.empresa,
            tipo=Notification.Tipo.SYSTEM,
            titulo="Sistema",
            cuerpo="",
            is_read=False,
        )
        for _ in range(3):
            Notification.objects.create(
                destinatario=self.user,
                empresa=self.empresa,
                tipo=Notification.Tipo.MESSAGE,
                titulo="Mensaje",
                cuerpo="",
                is_read=False,
            )

        self._login_with_empresa()
        response = self.client.get(reverse("notificaciones:mis_notificaciones"))
        self.assertEqual(response.status_code, 200)

        html = response.content.decode("utf-8")

        self.assertContains(response, '<span class="badge rounded-pill bg-danger ms-2">6</span>', html=True)
        self.assertContains(response, '<span class="badge rounded-pill bg-danger ms-2">2</span>', html=True)

        force_index = html.find('href="/notificaciones/forzar/"')
        self.assertNotEqual(force_index, -1)
        force_segment = html[force_index:force_index + 200]
        self.assertNotIn("badge", force_segment)
