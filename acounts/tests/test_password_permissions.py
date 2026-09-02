from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from acounts.services.password_permissions import user_can_change_password_globally


class GlobalPasswordPermissionTests(TestCase):
    def setUp(self):
        self.old_password = "pass1234"
        self.user = User.objects.create_user(
            username="global-password-user",
            password=self.old_password,
        )
        self.empresa_a = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        self.profile_view = Vista.objects.create(nombre="Accounts - Editar Perfil")
        self.password_view = Vista.objects.create(nombre="Accounts - Cambiar Password")
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa_a,
            vista=self.profile_view,
            ingresar=True,
        )
        self.client.force_login(self.user)
        self._set_active_company(self.empresa_a)

    def _set_active_company(self, empresa):
        session = self.client.session
        session["empresa_id"] = empresa.id
        session.save()

    def _set_password_permission(self, empresa, modificar=False):
        return Permiso.objects.create(
            usuario=self.user,
            empresa=empresa,
            vista=self.password_view,
            modificar=modificar,
        )

    def _password_payload(self, new_password="CorrectHorse9"):
        return {
            "form_action": "password",
            "old_password": self.old_password,
            "new_password1": new_password,
            "new_password2": new_password,
        }

    def test_permiso_en_empresa_a_habilita_pestana_y_cambio_en_a(self):
        self._set_password_permission(self.empresa_a, modificar=True)

        response = self.client.get(reverse("editar_perfil"))
        self.assertContains(response, "Cambiar contraseña")

        response = self.client.post(reverse("editar_perfil"), self._password_payload())
        self.assertEqual(response.status_code, 302)

    def test_permiso_en_a_habilita_pestana_y_post_con_empresa_b(self):
        self._set_password_permission(self.empresa_a, modificar=True)
        self._set_active_company(self.empresa_b)

        response = self.client.get(reverse("editar_perfil"))
        self.assertContains(response, "Cambiar contraseña")

        response = self.client.post(reverse("editar_perfil"), self._password_payload())
        self.assertEqual(response.status_code, 302)

    def test_permiso_falso_en_b_y_verdadero_en_a_es_global(self):
        self._set_password_permission(self.empresa_a, modificar=True)
        self._set_password_permission(self.empresa_b, modificar=False)
        self._set_active_company(self.empresa_b)

        self.assertTrue(user_can_change_password_globally(self.user))
        self.assertContains(self.client.get(reverse("editar_perfil")), "Cambiar contraseña")

    def test_sin_modificar_en_ninguna_empresa_no_muestra_pestana_y_devuelve_403(self):
        self._set_password_permission(self.empresa_a, modificar=False)
        self._set_password_permission(self.empresa_b, modificar=False)
        self._set_active_company(self.empresa_b)

        self.assertFalse(user_can_change_password_globally(self.user))
        self.assertNotContains(self.client.get(reverse("editar_perfil")), "Cambiar contraseña")
        self.assertEqual(
            self.client.post(reverse("editar_perfil"), self._password_payload()).status_code,
            403,
        )
        self.assertEqual(self.client.get(reverse("cambiar_password")).status_code, 403)

    def test_sin_fila_de_permiso_no_muestra_pestana_y_devuelve_403(self):
        self._set_active_company(self.empresa_b)

        self.assertFalse(user_can_change_password_globally(self.user))
        self.assertNotContains(self.client.get(reverse("editar_perfil")), "Cambiar contraseña")
        self.assertEqual(self.client.get(reverse("cambiar_password")).status_code, 403)

    def test_url_legacy_usa_la_misma_regla_global(self):
        self._set_password_permission(self.empresa_a, modificar=True)
        self._set_active_company(self.empresa_b)

        response = self.client.get(reverse("cambiar_password"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="old_password"')

        response = self.client.post(
            reverse("cambiar_password"),
            self._password_payload(),
        )
        self.assertEqual(response.status_code, 302)

    def test_cambiar_empresa_no_altera_permiso_global(self):
        self._set_password_permission(self.empresa_a, modificar=True)
        self._set_active_company(self.empresa_a)
        permitido_en_a = user_can_change_password_globally(self.user)
        self._set_active_company(self.empresa_b)
        permitido_en_b = user_can_change_password_globally(self.user)

        self.assertTrue(permitido_en_a)
        self.assertEqual(permitido_en_a, permitido_en_b)

    def test_editar_perfil_sigue_dependiendo_de_empresa_activa(self):
        self._set_active_company(self.empresa_b)

        response = self.client.get(reverse("editar_perfil"))
        self.assertEqual(response.status_code, 200)
        profile_permission = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa_b,
            vista=self.profile_view,
        )
        self.assertTrue(profile_permission.ingresar)
        self.assertFalse(profile_permission.modificar)
