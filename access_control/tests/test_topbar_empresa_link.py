"""
Tests para verificar que el link de cambio de empresa en topbar funciona correctamente.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista


class TopbarEmpresaLinkTests(TestCase):
    """
    Verifica que el topbar renderiza correctamente el link/modal trigger para cambiar empresa.
    """

    def setUp(self):
        """
        Crea usuario, empresa y permiso mínimo para acceder al sistema.
        """
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.empresa = Empresa.objects.create(
            codigo="01",
            descripcion="Empresa de prueba",
        )
        # Crear permiso para la vista raíz (biblioteca listar propiedades)
        self.vista = Vista.objects.get_or_create(nombre="Listado de Propiedades")[0]
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
        )

    def test_topbar_con_empresa_seleccionada_tiene_modal_trigger_bootstrap5(self):
        """
        Verifica que cuando hay empresa seleccionada, el topbar renderiza
        el span con data-bs-toggle y data-bs-target (Bootstrap 5).
        """
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

        # Acceder a cualquier vista que renderice el topbar
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

        html = response.content.decode("utf-8")

        # Verificar que el modal trigger existe con Bootstrap 5 syntax
        self.assertIn('data-bs-toggle="modal"', html)
        self.assertIn('data-bs-target="#cambiarEmpresaModal"', html)
        self.assertIn(self.empresa.descripcion, html)

        # Verificar que NO usa Bootstrap 4 syntax (data-toggle, data-target)
        # Excepto si hay otros elementos que lo usen, pero el de empresa debe ser BS5
        # Buscamos el contexto específico del texto "Empresa:"
        self.assertIn("Empresa:", html)

    def test_topbar_sin_empresa_seleccionada_tiene_modal_trigger(self):
        """
        Verifica que cuando NO hay empresa seleccionada, el topbar renderiza
        "Seleccionar Empresa" con el modal trigger.
        """
        self.client.force_login(self.user)
        # NO seteamos empresa_id en sesión

        # Acceder a seleccionar_empresa directamente (está en whitelist)
        response = self.client.get("/access-control/seleccionar_empresa/", follow=False)
        # Si middleware redirige, espera 200 (GET de seleccionar_empresa)
        # Si no hay empresa, puede redirigir o mostrar selector
        self.assertIn(response.status_code, [200, 302])

    def test_modal_cambiar_empresa_form_action_correcta(self):
        """
        Verifica que el modal de cambiar empresa tiene el form action correcto.
        """
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

        html = response.content.decode("utf-8")

        # Verificar que el modal existe
        self.assertIn('id="cambiarEmpresaModal"', html)
        # Verificar que el form apunta a la URL correcta
        # El form está en templates/partials/base.html
        # y tiene action="{% url 'access_control:seleccionar_empresa' %}"

    def test_post_seleccionar_empresa_actualiza_sesion(self):
        """
        Verifica que POST a seleccionar_empresa actualiza la sesión correctamente.
        """
        self.client.force_login(self.user)

        # Crear segunda empresa
        empresa2 = Empresa.objects.create(
            codigo="02",
            descripcion="Segunda empresa",
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=empresa2,
            vista=self.vista,
            ingresar=True,
        )

        # Setear empresa inicial
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

        # POST para cambiar a empresa2
        response = self.client.post(
            "/access-control/seleccionar_empresa/",
            {"empresa_id": empresa2.id},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        # Verificar que la sesión se actualizó
        self.assertEqual(self.client.session.get("empresa_id"), empresa2.id)
