"""Tests de permisos ICMEAS para la vista certificados_probar_conexion."""
from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from access_control.models import Empresa, Permiso, Vista
from auditoria.models import AuditoriaBibliotecaEvent, AuditoriaGestionDTEEvent, UserPresence
from gestiondte.models import CertificadoSII


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


class TestCertificadoProbarAuditoria(TestCase):
    def setUp(self):
        self.user, self.empresa = _setup_user_with_permiso(modificar=True)
        self.cert = CertificadoSII.objects.create(
            empresa_codigo=self.empresa.codigo,
            archivo='certificado.pfx',
            activo=True,
        )
        self.client = Client()
        self.client.login(username=self.user.username, password='pass')
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    @patch('gestiondte.services.sii_auth.probar_autenticacion_sii')
    def test_success_registra_execute_sin_view_ni_presence(self, probar):
        probar.return_value = {
            'success': True,
            'token_obtenido': True,
            'token_expira': None,
            'rut_envio_sii': '7762388-4',
        }
        UserPresence.objects.create(
            user=self.user,
            empresa_id=self.empresa.id,
            app_label='gestiondte',
            vista_nombre='Gestión DTE - Certificados PFX-DTE',
            path='/gestiondte/certificados/',
        )

        response = self.client.get(reverse('gestion_dte:certificados_probar_conexion', args=[self.cert.pk]))

        self.assertEqual(response.status_code, 200)
        event = AuditoriaGestionDTEEvent.objects.get()
        self.assertEqual(event.action, 'EXECUTE')
        self.assertEqual(event.object_type, 'certificado_sii')
        self.assertEqual(event.object_id, str(self.cert.pk))
        self.assertEqual(event.meta['result'], 'success')
        self.assertEqual(AuditoriaBibliotecaEvent.objects.count(), 0)
        self.assertEqual(UserPresence.objects.get(user=self.user).path, '/gestiondte/certificados/')

    @patch('gestiondte.services.sii_auth.probar_autenticacion_sii')
    def test_failure_registra_execute_failure_sin_secretos(self, probar):
        from gestiondte.services.sii_auth import SiiAuthError
        probar.side_effect = SiiAuthError('password=SUPER_SECRET_TEST_VALUE', http_status=401)

        response = self.client.get(reverse('gestion_dte:certificados_probar_conexion', args=[self.cert.pk]))

        self.assertEqual(response.status_code, 200)
        event = AuditoriaGestionDTEEvent.objects.get()
        self.assertEqual(event.action, 'EXECUTE')
        self.assertEqual(event.meta['result'], 'failure')
        self.assertNotIn('SUPER_SECRET_TEST_VALUE', str(event))
        self.assertNotEqual(event.action, 'ERROR_500')
