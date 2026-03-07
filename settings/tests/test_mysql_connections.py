from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from access_control.models import Empresa, Permiso, Vista
from ..models import SettingsMySQLConnection


class MySQLConnectionsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='p')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 1')

        vista, _ = Vista.objects.get_or_create(nombre='Settings - Conexiones MySQL')
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            ingresar=True,
            crear=True,
            modificar=True,
            eliminar=True,
        )

        self.client = Client()
        self.client.login(username='u', password='p')
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def test_create_and_list_connection(self):
        # create
        url = reverse('mysql_connections_create')
        resp = self.client.post(url, {
            'nombre_logico': 'ventas', 'host': '127.0.0.1', 'port': 3306,
            'user': 'u', 'password': 'p', 'db_name': 'db1'
        })
        self.assertIn(resp.status_code, (302, 200))
        qs = SettingsMySQLConnection.objects.filter(empresa=self.empresa, nombre_logico='ventas')
        self.assertEqual(qs.count(), 1)

    def test_create_duplicate_nombre_logico_shows_form_error(self):
        SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico='ventas',
            engine=SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
            host='127.0.0.1',
            port=3306,
            user='u',
            password='p',
            db_name='db1',
            charset='utf8',
            is_active=True,
        )

        url = reverse('mysql_connections_create')
        resp = self.client.post(url, {
            'nombre_logico': 'ventas',
            'engine': SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
            'host': '127.0.0.1',
            'port': 3306,
            'user': 'u',
            'password': 'p',
            'db_name': 'db2',
            'charset': 'utf8',
            'is_active': 'on',
        })

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ya existe una conexión con ese nombre lógico para la empresa activa.')
        self.assertEqual(
            SettingsMySQLConnection.objects.filter(empresa=self.empresa, nombre_logico='ventas').count(),
            1,
        )

    def test_update_duplicate_nombre_logico_shows_form_error(self):
        first = SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico='first',
            engine=SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
            host='127.0.0.1',
            port=3306,
            user='u',
            password='p',
            db_name='db1',
            charset='utf8',
            is_active=True,
        )
        second = SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico='second',
            engine=SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
            host='127.0.0.1',
            port=3306,
            user='u',
            password='p',
            db_name='db2',
            charset='utf8',
            is_active=True,
        )

        url = reverse('mysql_connections_edit', args=[second.pk])
        resp = self.client.post(url, {
            'nombre_logico': 'first',
            'engine': SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
            'host': '127.0.0.1',
            'port': 3306,
            'user': 'u',
            'password': 'p',
            'db_name': 'db2',
            'charset': 'utf8',
            'is_active': 'on',
        })

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ya existe una conexión con ese nombre lógico para la empresa activa.')

        second.refresh_from_db()
        self.assertEqual(second.nombre_logico, 'second')
        self.assertEqual(SettingsMySQLConnection.objects.filter(empresa=self.empresa).count(), 2)
