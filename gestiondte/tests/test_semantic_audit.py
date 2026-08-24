from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from auditoria.models import AuditoriaGestionDTEEvent, UserPresence
from gestiondte.models import CertificadoSII


class GestionDTESemanticAuditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='semantic-auditor', password='pass')
        self.empresa = Empresa.objects.create(codigo='09', descripcion='Empresa test')
        self.vista, _ = Vista.objects.get_or_create(nombre='Gestión DTE - Certificados PFX-DTE')
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
            crear=True,
            modificar=True,
            eliminar=True,
        )
        self.certificado = CertificadoSII.objects.create(
            empresa_codigo='09',
            archivo='gestiondte/certificados/09/test.pfx',
            activo=False,
            titular='Titular',
            emisor_certificado='Emisor',
            numero_serie='123',
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def test_toggle_logs_update_with_before_and_after(self):
        response = self.client.post(
            reverse('gestion_dte:certificados_toggle_active', args=[self.certificado.pk])
        )

        self.assertEqual(response.status_code, 302)
        event = AuditoriaGestionDTEEvent.objects.get(action='UPDATE')
        self.assertEqual(event.object_type, 'certificado_sii')
        self.assertEqual(event.object_id, str(self.certificado.pk))
        self.assertEqual(event.empresa_id, self.empresa.id)
        self.assertEqual(event.before, {'activo': False})
        self.assertEqual(event.after, {'activo': True})

    def test_semantic_post_does_not_change_existing_presence(self):
        presence = UserPresence.objects.create(
            user=self.user,
            empresa_id=self.empresa.id,
            app_label='gestiondte',
            vista_nombre='Gestión DTE - Certificados PFX-DTE',
            path='/gestiondte/certificados/',
        )
        updated_at = presence.last_seen

        response = self.client.post(
            reverse('gestion_dte:certificados_toggle_active', args=[self.certificado.pk])
        )

        presence.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(presence.last_seen, updated_at)
        self.assertEqual(UserPresence.objects.filter(user=self.user).count(), 1)

    @patch('gestiondte.views.get_maestroempresa_by_codigo')
    @patch('cryptography.x509.Certificate')
    @patch('cryptography.hazmat.primitives.serialization.pkcs12.load_key_and_certificates')
    @patch('gestiondte.forms.get_maestroempresa_by_codigo')
    def test_create_logs_safe_metadata_only(self, forms_maestro_mock, load_key_and_certificates, certificate_class, maestro_mock):
        certificate = SimpleNamespace(
            subject=SimpleNamespace(
                rfc4514_string=lambda: 'CN=Titular',
                get_attributes_for_oid=lambda _oid: [SimpleNamespace(value='Titular')],
            ),
            issuer=SimpleNamespace(rfc4514_string=lambda: 'CN=Emisor'),
            serial_number=456,
            not_valid_before=None,
            not_valid_after=None,
        )
        load_key_and_certificates.return_value = (object(), certificate, [])
        forms_maestro_mock.return_value = self.empresa
        maestro_mock.return_value = self.empresa
        upload = SimpleUploadedFile('certificado.pfx', b'PRIVATE PFX CONTENT', content_type='application/x-pkcs12')

        response = self.client.post(
            reverse('gestion_dte:certificados_cargar'),
            {
                'empresa_codigo': '09',
                'archivo': upload,
                'password': 'secreto-super-sensible',
                'password_confirm': 'secreto-super-sensible',
                'activo': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        event = AuditoriaGestionDTEEvent.objects.get(action='CREATE')
        serialized = str({'meta': event.meta, 'before': event.before, 'after': event.after})
        self.assertNotIn('secreto-super-sensible', serialized)
        self.assertNotIn('PRIVATE PFX CONTENT', serialized)
        self.assertEqual(event.object_type, 'certificado_sii')
        self.assertEqual(event.empresa_id, self.empresa.id)