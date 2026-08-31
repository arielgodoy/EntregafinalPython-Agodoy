from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from settings.models import UserPreferences


class SetFechaSistemaTests(TestCase):
    vista_nombre = "Settings - Establecer Fecha Sistema"

    def setUp(self):
        self.user = User.objects.create_user(username="user2", password="pass123")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa")

        self.vista, _ = Vista.objects.get_or_create(nombre=self.vista_nombre)
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            modificar=True,
        )

    def _set_empresa_activa(self):
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def _post_fecha(self, fecha="2026-02-13"):
        return self.client.post(
            reverse("set_fecha_sistema"),
            {"fecha_sistema": fecha},
            HTTP_ACCEPT="application/json",
            follow=False,
        )

    def test_post_sin_login_redirige(self):
        response = self._post_fecha()
        self.assertIn(response.status_code, [302, 403])

    def test_post_fecha_valida_actualiza_prefs_y_sesion(self):
        self.client.force_login(self.user)
        self._set_empresa_activa()
        response = self.client.post(
            reverse("set_fecha_sistema"),
            {"fecha_sistema": "2026-02-13"},
            follow=False,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("fecha_sistema"), "2026-02-13")

        prefs = UserPreferences.objects.get(user=self.user)
        self.assertEqual(prefs.fecha_sistema, date(2026, 2, 13))
        self.assertEqual(self.client.session.get("fecha_sistema"), "2026-02-13")

    def test_post_fecha_invalida_rechaza(self):
        self.client.force_login(self.user)
        self._set_empresa_activa()
        response = self._post_fecha("2026-13-40")
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data.get("ok"))

    def test_post_formato_invalido_rechaza(self):
        self.client.force_login(self.user)
        self._set_empresa_activa()
        response = self._post_fecha("13-02-2026")
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data.get("ok"))

    def test_post_sin_permiso_crea_permiso_vacio_y_deniega(self):
        user = User.objects.create_user(username="sin_permiso", password="pass123")
        self.client.force_login(user)
        self._set_empresa_activa()
        fecha_original = UserPreferences.objects.get(user=user).fecha_sistema

        response = self._post_fecha()

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["success"])
        permiso = Permiso.objects.get(usuario=user, empresa=self.empresa, vista=self.vista)
        self.assertFalse(permiso.ingresar)
        self.assertFalse(permiso.crear)
        self.assertFalse(permiso.modificar)
        self.assertFalse(permiso.eliminar)
        self.assertFalse(permiso.autorizar)
        self.assertFalse(permiso.supervisor)
        self.assertEqual(UserPreferences.objects.get(user=user).fecha_sistema, fecha_original)

    def test_post_sin_modificar_no_altera_permiso_existente(self):
        user = User.objects.create_user(username="sin_modificar", password="pass123")
        permiso = Permiso.objects.create(
            usuario=user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
            crear=True,
            modificar=False,
            eliminar=True,
            autorizar=True,
            supervisor=False,
        )
        self.client.force_login(user)
        self._set_empresa_activa()
        fecha_original = UserPreferences.objects.get(user=user).fecha_sistema

        response = self._post_fecha()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Permiso.objects.filter(usuario=user, empresa=self.empresa, vista=self.vista).count(), 1)
        permiso.refresh_from_db()
        self.assertTrue(permiso.ingresar)
        self.assertTrue(permiso.crear)
        self.assertFalse(permiso.modificar)
        self.assertTrue(permiso.eliminar)
        self.assertTrue(permiso.autorizar)
        self.assertFalse(permiso.supervisor)
        self.assertEqual(UserPreferences.objects.get(user=user).fecha_sistema, fecha_original)

    def test_post_con_ingresar_sin_modificar_deniega(self):
        user = User.objects.create_user(username="solo_ingresar", password="pass123")
        Permiso.objects.create(
            usuario=user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
        )
        self.client.force_login(user)
        self._set_empresa_activa()
        fecha_original = UserPreferences.objects.get(user=user).fecha_sistema

        response = self._post_fecha()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(UserPreferences.objects.get(user=user).fecha_sistema, fecha_original)

    def test_post_sin_permiso_crea_registro_solo_en_empresa_activa(self):
        otra_empresa = Empresa.objects.create(codigo="02", descripcion="Otra empresa")
        user = User.objects.create_user(username="empresa_activa", password="pass123")
        self.client.force_login(user)
        self._set_empresa_activa()

        response = self._post_fecha()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Permiso.objects.filter(usuario=user, empresa=self.empresa, vista=self.vista).exists())
        self.assertFalse(Permiso.objects.filter(usuario=user, empresa=otra_empresa, vista=self.vista).exists())
