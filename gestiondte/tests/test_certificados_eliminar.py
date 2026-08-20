from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from gestiondte.models import CertificadoSII


class CertificadoEliminarViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cert-delete', password='pass')
        self.empresa = Empresa.objects.create(codigo='09', descripcion='Empresa test')
        self.vista = Vista.objects.create(nombre='Gestión DTE - Certificados PFX-DTE')
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
