from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


class LoginEmpresaActivaTests(TestCase):
    def setUp(self):
        self.password = "pass1234"
        self.user = User.objects.create_user(username="tester", password=self.password)
        self.vista = Vista.objects.create(nombre="Listado de Propiedades")

    def _assign_empresa(self, empresa):
        Permiso.objects.create(
            usuario=self.user,
            empresa=empresa,
            vista=self.vista,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

    def test_login_con_una_empresa_setea_sesion_y_redirige(self):
        empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self._assign_empresa(empresa)

        response = self.client.post(
            reverse("login"),
            data={"username": self.user.username, "password": self.password},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("biblioteca:listar_propiedades"))

        session = self.client.session
        self.assertEqual(session.get("empresa_id"), empresa.id)
        self.assertEqual(session.get("empresa_codigo"), empresa.codigo)
        self.assertIn("empresa_nombre", session)

    def test_login_con_dos_empresas_redirige_a_selector(self):
        empresa_a = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa 02")
        self._assign_empresa(empresa_a)
        self._assign_empresa(empresa_b)

        response = self.client.post(
            reverse("login"),
            data={"username": self.user.username, "password": self.password},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("access_control:seleccionar_empresa"))
        self.assertIsNone(self.client.session.get("empresa_id"))
