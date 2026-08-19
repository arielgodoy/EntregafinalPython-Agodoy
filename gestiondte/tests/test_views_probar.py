"""Tests de permisos ICMEAS para la vista certificados_probar_conexion."""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from access_control.models import Empresa, Permiso, Vista


def _setup_user_with_permiso(modificar=True):
    user = User.objects.create_user(username=f"u_probar_{modificar}", password="pass")
    empresa = Empresa.objects.create(codigo="09", descripcion="Test")
    vista, _ = Vista.objects.get_or_create(nombre="Gestión DTE - Certificados PFX-DTE")
    Permiso.objects.create(
        usuario=user,
        empresa=empresa,
        vista=vista,
        ingresar=True,
        crear=False,
        modificar=modificar,
        eliminar=False,
    )
    return user, empresa


class TestCertificadoProbarPermisos(TestCase):
    def _client_for(self, user, empresa):
        c = Client()
        c.login(username=user.username, password="pass")
        s = c.session
        s["empresa_id"] = empresa.id
        s.save()
        return c

    def test_sin_permiso_modificar_recibe_403(self):
        user, empresa = _setup_user_with_permiso(modificar=False)
        c = self._client_for(user, empresa)
        resp = c.get(reverse("gestion_dte:certificados_probar_conexion", args=[9999]))
        self.assertEqual(resp.status_code, 403)

    def test_sin_empresa_activa_redirige(self):
        user, _ = _setup_user_with_permiso(modificar=True)
        c = Client()
        c.login(username=user.username, password="pass")
        # sin empresa_id en sesión
        resp = c.get(reverse("gestion_dte:certificados_probar_conexion", args=[9999]))
        self.assertIn(resp.status_code, (302, 403))
