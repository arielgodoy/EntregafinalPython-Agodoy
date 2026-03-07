import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista

from ..forms import SettingsMySQLConnectionForm
from ..models import SettingsMySQLConnection


class MySQLEngineTests(TestCase):
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

    def test_form_engine_choices(self):
        form = SettingsMySQLConnectionForm()
        field = form.fields['engine']

        self.assertFalse(field.required)
        self.assertEqual(field.initial, SettingsMySQLConnection.ENGINE_DEFAULT)

        values = [v for v, _ in field.choices]
        self.assertEqual(set(values), set(SettingsMySQLConnection.ENGINE_ALLOWED))

    def test_import_defaults_engine_when_missing(self):
        url = reverse('mysql_connections_import')
        payload = {
            'version': 1,
            'empresa_id': self.empresa.id,
            'connections': [
                {
                    'nombre_logico': 'ventas',
                    'host': '127.0.0.1',
                    'port': 3306,
                    'user': 'u',
                    'password': 'p',
                    'db_name': 'db1',
                    'is_active': True,
                }
            ]
        }

        uploaded = SimpleUploadedFile(
            'conexionesMysql.cfg',
            json.dumps(payload).encode('utf-8'),
            content_type='application/json',
        )

        resp = self.client.post(
            url,
            {'conexionesMysql.cfg': uploaded},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            HTTP_ACCEPT='application/json',
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('success'))

        obj = SettingsMySQLConnection.objects.get(empresa=self.empresa, nombre_logico='ventas')
        self.assertEqual(obj.engine, SettingsMySQLConnection.ENGINE_DEFAULT)

    def test_existing_mysql_engine_still_works(self):
        cfg = SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico='ventas',
            engine=SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
            host='127.0.0.1',
            port=1,
            user='u',
            password='p',
            db_name='db1',
            is_active=True,
        )

        url = reverse('mysql_connections_test', args=[cfg.pk])
        resp = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertIn(
            data.get('message_key'),
            (
                'settings.mysql_connections.test_success',
                'settings.mysql_connections.test_error',
            ),
        )

    def test_legacy_pymysql_returns_controlled_error_when_driver_missing(self):
        legacy = SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico='legacy',
            engine=SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL,
            host='127.0.0.1',
            port=1,
            user='u',
            password='p',
            db_name='db1',
            is_active=True,
        )

        with patch('settings.views.pymysql', None):
            url = reverse('mysql_connections_test', args=[legacy.pk])
            resp = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get('success'))
        self.assertEqual(data.get('message_key'), 'settings.mysql_connections.test_missing_pymysql')

    def test_legacy_pymysql_success_when_connection_mocked(self):
        legacy = SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico='legacy_ok',
            engine=SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL,
            host='127.0.0.1',
            port=3306,
            user='u',
            password='p',
            db_name='db1',
            charset='utf8',
            is_active=True,
        )

        cursor = MagicMock()
        cursor.fetchall.return_value = [(f't{i}',) for i in range(25)]
        conn = MagicMock()
        conn.cursor.return_value = cursor

        pymysql_module = MagicMock()
        pymysql_module.connect.return_value = conn

        with patch('settings.views.pymysql', pymysql_module):
            url = reverse('mysql_connections_test', args=[legacy.pk])
            resp = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('message_key'), 'settings.mysql_connections.test_success')
        self.assertEqual(data.get('count'), 25)
        self.assertEqual(len(data.get('tables') or []), 20)

        self.assertTrue(cursor.close.called)
        self.assertTrue(conn.close.called)

    def test_api_remota_still_not_implemented(self):
        remote = SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico='remota',
            engine=SettingsMySQLConnection.ENGINE_API_REMOTA,
            host='127.0.0.1',
            port=1,
            user='u',
            password='p',
            db_name='db1',
            is_active=True,
        )
        url = reverse('mysql_connections_test', args=[remote.pk])
        resp = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get('success'))
        self.assertEqual(data.get('message_key'), 'settings.mysql_connections.test_not_implemented_api_remota')
