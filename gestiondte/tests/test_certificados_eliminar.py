from django.contrib.auth.models import User
import json

from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from auditoria.models import AuditoriaGestionDTEEvent
from gestiondte.models import CertificadoSII


class CertificadoEliminarViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cert-delete', password='pass')
        self.empresa = Empresa.objects.create(codigo='09', descripcion='Empresa test')
        self.vista, _ = Vista.objects.get_or_create(nombre='Gestión DTE - Certificados PFX-DTE')
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
            eliminar=True,
        )
        self.certificado = CertificadoSII.objects.create(
            empresa_codigo='09',
            archivo='gestiondte/certificados/09/test.pfx',
            activo=False,
        )
        self.client = Client()
        self.client.login(username='cert-delete', password='pass')
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def test_ajax_post_elimina_certificado(self):
        response = self.client.post(
            reverse('gestion_dte:certificados_eliminar', args=[self.certificado.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertFalse(CertificadoSII.objects.filter(pk=self.certificado.pk).exists())

        eventos_delete = AuditoriaGestionDTEEvent.objects.filter(action='DELETE')
        self.assertEqual(eventos_delete.count(), 1)
        evento = eventos_delete.get()
        self.assertEqual(evento.object_type, 'certificado_sii')
        self.assertEqual(evento.object_id, str(self.certificado.pk))
        self.assertEqual(evento.empresa_id, self.empresa.id)
        self.assertEqual(evento.before['empresa_codigo'], '09')
        self.assertEqual(evento.meta['empresa_codigo'], '09')
        self.assertEqual(evento.meta['empresa_id'], self.empresa.id)
        serialized_audit = json.dumps(
            {'meta': evento.meta, 'before': evento.before, 'after': evento.after},
            sort_keys=True,
        ).lower()
        for sensitive_term in ('test.pfx', 'password', 'private key', 'private_key', 'token', 'secret'):
            self.assertNotIn(sensitive_term, serialized_audit)

    def test_get_no_elimina_y_rechaza_metodo(self):
        response = self.client.get(
            reverse('gestion_dte:certificados_eliminar', args=[self.certificado.pk])
        )
        self.assertEqual(response.status_code, 405)
        self.assertTrue(CertificadoSII.objects.filter(pk=self.certificado.pk).exists())

    def test_sin_permiso_eliminar_recibe_403(self):
        Permiso.objects.update(eliminar=False)
        response = self.client.post(
            reverse('gestion_dte:certificados_eliminar', args=[self.certificado.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(CertificadoSII.objects.filter(pk=self.certificado.pk).exists())

    def test_no_permite_eliminar_certificado_de_otra_empresa(self):
        otra = Empresa.objects.create(codigo='10', descripcion='Otra empresa')
        otro_certificado = CertificadoSII.objects.create(
            empresa_codigo='10', archivo='gestiondte/certificados/10/otro.pfx', activo=False,
        )
        response = self.client.post(
            reverse('gestion_dte:certificados_eliminar', args=[otro_certificado.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(CertificadoSII.objects.filter(pk=otro_certificado.pk).exists())
