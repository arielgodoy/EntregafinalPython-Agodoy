from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from gestiondte.forms import CertificadoUploadForm
from gestiondte.models import CertificadoSII
from gestiondte.tests.certificado_fixtures import configure_serverbasedte_django


class CertificadoSiiSnapshotTests(TestCase):
    def setUp(self):
        configure_serverbasedte_django()
        self.creator = User.objects.create_user(username='creator-user', password='pass')
        self.editor = User.objects.create_user(username='editor-user', password='pass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa prueba')
        self.vista, _ = Vista.objects.get_or_create(
            nombre='Gestión DTE - Certificados PFX-DTE',
            defaults={'route_name': 'gestion_dte:certificados'},
        )

    def _certificate_form(self, user):
        form = CertificadoUploadForm(
            data={'empresa_codigo': '01', 'activo': False},
            files={'archivo': SimpleUploadedFile('certificado.pfx', b'pfx')},
        )
        with patch('gestiondte.forms.get_maestroempresa_by_codigo', return_value={'codigo': '01'}):
            self.assertTrue(form.is_valid(), form.errors)
        return form.save(user=user)

    def test_creation_stores_id_and_username_snapshot(self):
        certificate = self._certificate_form(self.creator)

        self.assertEqual(certificate.created_by_id, self.creator.id)
        self.assertEqual(certificate.created_by_username, 'creator-user')
        self.assertEqual(certificate.updated_by_id, self.creator.id)
        self.assertEqual(certificate.updated_by_username, 'creator-user')

    def test_modification_updates_updated_snapshot_without_changing_created_snapshot(self):
        certificate = self._certificate_form(self.creator)
        certificate.titular = 'Titular actualizado'
        modified = CertificadoUploadForm(
            data={'empresa_codigo': '01', 'activo': False, 'titular': 'Titular actualizado'},
            instance=certificate,
        )
        with patch('gestiondte.forms.get_maestroempresa_by_codigo', return_value={'codigo': '01'}):
            self.assertTrue(modified.is_valid(), modified.errors)
        certificate = modified.save(user=self.editor)

        self.assertEqual(certificate.created_by_id, self.creator.id)
        self.assertEqual(certificate.created_by_username, 'creator-user')
        self.assertEqual(certificate.updated_by_id, self.editor.id)
        self.assertEqual(certificate.updated_by_username, 'editor-user')

    def test_username_rename_does_not_change_existing_snapshot(self):
        certificate = self._certificate_form(self.creator)
        self.creator.username = 'creator-renamed'
        self.creator.save(update_fields=['username'])

        certificate.refresh_from_db()

        self.assertEqual(certificate.created_by_username, 'creator-user')

    def test_toggle_modification_captures_username_snapshot(self):
        certificate = CertificadoSII.objects.create(
            empresa_codigo='01',
            archivo='gestiondte/certificados/01/certificado.pfx',
            created_by=self.creator,
            created_by_username='creator-user',
            updated_by=self.creator,
            updated_by_username='creator-user',
        )
        Permiso.objects.create(
            usuario=self.editor,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
            modificar=True,
        )
        self.client.force_login(self.editor)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

        response = self.client.post(
            reverse('gestion_dte:certificados_toggle_active', args=[certificate.pk])
        )

        self.assertEqual(response.status_code, 302)
        certificate.refresh_from_db()
        self.assertEqual(certificate.updated_by_id, self.editor.id)
        self.assertEqual(certificate.updated_by_username, 'editor-user')
        self.assertEqual(certificate.created_by_username, 'creator-user')

    def test_snapshots_allow_null_for_historical_records(self):
        certificate = CertificadoSII.objects.create(
            empresa_codigo='01',
            archivo='gestiondte/certificados/01/historico.pfx',
        )

        self.assertIsNone(certificate.created_by_username)
        self.assertIsNone(certificate.updated_by_username)