from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from access_control.models import Empresa, Vista, Permiso
from auditoria.models import AuditoriaBibliotecaEvent

User = get_user_model()


class AuditoriaUITest(TestCase):
    def setUp(self):
        self.client = Client()
        # Empresas
        self.empresa1 = Empresa.objects.create(codigo='01', descripcion='Empresa 1')
        self.empresa2 = Empresa.objects.create(codigo='02', descripcion='Empresa 2')
        # Usuario y permisos
        self.user = User.objects.create_user(username='tester', password='secret')
        vista_listar, _ = Vista.objects.get_or_create(nombre='Auditoría - Listar')
        vista_detalle, _ = Vista.objects.get_or_create(nombre='Auditoría - Detalle')
        # Permiso para empresa1
        Permiso.objects.create(usuario=self.user, empresa=self.empresa1, vista=vista_listar, ingresar=True)
        # Eventos: uno para empresa1, otro para empresa2
        self.event1 = AuditoriaBibliotecaEvent.objects.create(
            user=self.user, empresa_id=self.empresa1.id, action='VIEW', object_type='Documento', object_id='1', path='/doc/1', vista_nombre='VistaX'
        )
        self.event2 = AuditoriaBibliotecaEvent.objects.create(
            user=self.user, empresa_id=self.empresa2.id, action='VIEW', object_type='Documento', object_id='2', path='/doc/2', vista_nombre='VistaY'
        )

    def test_listview_requires_login(self):
        url = reverse('auditoria:auditoria_biblioteca_list')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp['Location'])

    def test_listview_filters_by_empresa(self):
        self.client.login(username='tester', password='secret')
        session = self.client.session
        session['empresa_id'] = self.empresa1.id
        session.save()
        url = reverse('auditoria:auditoria_biblioteca_list')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn(self.event1.path, content)
        self.assertNotIn(self.event2.path, content)

    def test_detailview_empresa_protection(self):
        self.client.login(username='tester', password='secret')
        session = self.client.session
        session['empresa_id'] = self.empresa1.id
        session.save()
        url = reverse('auditoria:auditoria_biblioteca_detail', args=[self.event2.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_permission_denied_without_perm(self):
        # user_without_perm
        user2 = User.objects.create_user(username='noperm', password='x')
        self.client.login(username='noperm', password='x')
        session = self.client.session
        session['empresa_id'] = self.empresa1.id
        session.save()
        url = reverse('auditoria:auditoria_biblioteca_list')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_vista_nombre_shown_in_detail(self):
        self.client.login(username='tester', password='secret')
        session = self.client.session
        session['empresa_id'] = self.empresa1.id
        session.save()
        url = reverse('auditoria:auditoria_biblioteca_detail', args=[self.event1.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.event1.vista_nombre, resp.content.decode('utf-8'))
