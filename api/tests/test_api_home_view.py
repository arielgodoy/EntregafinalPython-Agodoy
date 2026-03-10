from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from api.views import API_HOME_VISTA_NOMBRE


class ApiHomeViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 1")

        self.client = Client()
        self.client.force_login(self.user)

        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session.save()

    def _grant_ingresar(self):
        vista = Vista.objects.create(nombre=API_HOME_VISTA_NOMBRE)
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

    def test_get_without_permiso_returns_403(self):
        url = reverse("api_home")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_get_with_permiso_renders_console(self):
        self._grant_ingresar()

        url = reverse("api_home")
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-key="menu.apis"')
        self.assertContains(resp, 'id="apisAccordion"')
        self.assertContains(resp, 'data-key="apis.accordion.rubros.title"')
        self.assertContains(resp, 'data-key="apis.accordion.locales.title"')
        self.assertContains(resp, 'data-key="apis.accordion.tipos_documentos.title"')
        self.assertContains(resp, 'data-key="apis.rubros.tech.title"')
        self.assertContains(resp, 'data-key="apis.locales.tech.title"')
        self.assertContains(resp, 'data-key="apis.tipos_documentos.tech.title"')
        self.assertContains(resp, 'id="rubrosConsoleForm"')
        self.assertContains(resp, 'id="localesConsoleForm"')
        self.assertContains(resp, 'id="tiposDocumentosConsoleForm"')
        self.assertContains(resp, 'data-key="apis.console.send"')

        content = resp.content.decode("utf-8")
        self.assertLess(
            content.find('data-key="apis.rubros.tech.title"'),
            content.find('id="rubrosConsoleForm"'),
        )

        self.assertLess(
            content.find('data-key="apis.locales.tech.title"'),
            content.find('id="localesConsoleForm"'),
        )

        self.assertLess(
            content.find('data-key="apis.tipos_documentos.tech.title"'),
            content.find('id="tiposDocumentosConsoleForm"'),
        )
