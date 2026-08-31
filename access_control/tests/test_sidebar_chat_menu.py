from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


class SidebarChatMenuTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="pass")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.vista_dashboard = Vista.objects.create(nombre="Control Operacional - Dashboard")
        self.vista_chat = Vista.objects.create(nombre="chat.inbox")
        self.vista_auditoria_biblioteca = Vista.objects.create(nombre="Auditoría - Biblioteca")
        self.vista_auditoria_gestiondte = Vista.objects.create(nombre="Auditoría - Gestión DTE")

    def _login_with_empresa(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def _grant_dashboard_permiso(self):
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_dashboard,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

    def test_sidebar_muestra_chat_con_permiso(self):
        self._login_with_empresa()
        self._grant_dashboard_permiso()
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_chat,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-key="menu.chat"')
        self.assertContains(response, reverse("chat_inbox"))

    def test_sidebar_muestra_chat_sin_permiso(self):
        self._login_with_empresa()
        self._grant_dashboard_permiso()

        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("chat_inbox")}"')

    def test_sidebar_muestra_permisos_por_vista_sin_permiso(self):
        self._login_with_empresa()
        self._grant_dashboard_permiso()

        response = self.client.get(reverse("control_operacional:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("access_control:permisos_por_vista")}"',
        )

    def test_sidebar_muestra_permisos_por_vista_con_modificar(self):
        self._login_with_empresa()
        self._grant_dashboard_permiso()
        vista = Vista.objects.create(nombre="Control de Acceso - Permisos por Vista")
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            modificar=True,
        )

        response = self.client.get(reverse("control_operacional:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("access_control:permisos_por_vista")}"',
        )
        self.assertEqual(
            self.client.get(reverse("access_control:permisos_por_vista")).status_code,
            200,
        )

    def test_sidebar_auditoria_muestra_biblioteca_con_permiso(self):
        self._login_with_empresa()
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_dashboard,
            ingresar=True,
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_auditoria_biblioteca,
            ingresar=True,
        )

        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Auditoría Biblioteca")
        self.assertContains(response, "Auditoría Gestión DTE")

    def test_sidebar_auditoria_muestra_dte_con_permiso(self):
        self._login_with_empresa()
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_dashboard,
            ingresar=True,
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_auditoria_gestiondte,
            ingresar=True,
        )

        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Auditoría Gestión DTE")
        self.assertContains(response, "Auditoría Biblioteca")

    def test_sidebar_auditoria_muestra_ambos_permisos(self):
        self._login_with_empresa()
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_dashboard,
            ingresar=True,
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_auditoria_biblioteca,
            ingresar=True,
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_auditoria_gestiondte,
            ingresar=True,
        )

        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Auditoría Biblioteca")
        self.assertContains(response, "Auditoría Gestión DTE")

    def test_sidebar_auditoria_visible_sin_permisos(self):
        self._login_with_empresa()
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_dashboard,
            ingresar=True,
        )

        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Auditoría Biblioteca")
        self.assertContains(response, "Auditoría Gestión DTE")
        self.assertEqual(
            Permiso.objects.filter(
                usuario=self.user,
                vista__nombre__in=("Auditoría - Biblioteca", "Auditoría - Gestión DTE"),
            ).count(),
            0,
        )

    def test_sidebar_auditoria_sin_permiso_conduce_a_403(self):
        self._login_with_empresa()
        self._grant_dashboard_permiso()

        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertContains(response, reverse("auditoria:auditoria_biblioteca_list"))
        self.assertContains(response, reverse("auditoria:auditoria_gestiondte_list"))
        self.assertEqual(
            self.client.get(reverse("auditoria:auditoria_biblioteca_list")).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("auditoria:auditoria_gestiondte_list")).status_code,
            403,
        )

    def test_sidebar_auditoria_con_permiso_conduce_a_200(self):
        self._login_with_empresa()
        self._grant_dashboard_permiso()
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_auditoria_biblioteca,
            ingresar=True,
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_auditoria_gestiondte,
            ingresar=True,
        )

        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertContains(response, "Auditoría Biblioteca")
        self.assertContains(response, "Auditoría Gestión DTE")
        self.assertEqual(
            self.client.get(reverse("auditoria:auditoria_biblioteca_list")).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("auditoria:auditoria_gestiondte_list")).status_code,
            200,
        )

    def test_sidebar_auditoria_no_requiere_superuser(self):
        self._login_with_empresa()
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_dashboard,
            ingresar=True,
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_auditoria_biblioteca,
            ingresar=True,
        )

        self.user.is_superuser = False
        self.user.save(update_fields=['is_superuser'])

        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Auditoría Biblioteca")
