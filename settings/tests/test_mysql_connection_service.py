from unittest.mock import MagicMock, patch

from django.test import TestCase, RequestFactory
from access_control.models import Empresa
from ..models import SettingsMySQLConnection
from settings.services.mysql_connections import (
    get_mysql_connection_config,
    get_mysql_connection_config_for_request,
    EmpresaActivaRequeridaError,
    MySQLConnectionConfigNotFoundError,
    MySQLConnectionConfigInactiveError,
    MySQLConnectionOpenError,
    open_mysql_connection,
)


class MySQLConnectionServiceTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 1')
        self.otra = Empresa.objects.create(codigo='02', descripcion='Empresa 2')
        SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico='ventas',
            host='127.0.0.1',
            port=3306,
            user='u',
            password='p',
            db_name='db1',
            is_active=True,
        )
        SettingsMySQLConnection.objects.create(
            empresa=self.otra,
            nombre_logico='ventas',
            host='10.0.0.1',
            port=3306,
            user='u2',
            password='p2',
            db_name='db2',
            is_active=True,
        )

    def _build_request_with_session(self, empresa_id=None):
        rf = RequestFactory()
        req = rf.get('/')
        # attach a simple session dict
        req.session = {}
        if empresa_id is not None:
            req.session['empresa_id'] = empresa_id
        return req

    def test_resolver_requires_empresa_activa(self):
        req = self._build_request_with_session()
        with self.assertRaises(EmpresaActivaRequeridaError):
            get_mysql_connection_config_for_request(req, 'ventas')

    def test_resolver_returns_config_for_empresa_and_nombre_logico(self):
        req = self._build_request_with_session(self.empresa.id)
        cfg = get_mysql_connection_config_for_request(req, 'ventas')
        self.assertEqual(cfg['empresa_id'], self.empresa.id)
        self.assertEqual(cfg['nombre_logico'], 'ventas')
        self.assertEqual(cfg['host'], '127.0.0.1')

    def test_resolver_blocks_other_empresa(self):
        # Ensure a company cannot retrieve another's configuration by empresa_id
        # Remove the config for the primary company and assert lookup fails
        SettingsMySQLConnection.objects.filter(empresa=self.empresa, nombre_logico='ventas').delete()
        with self.assertRaises(MySQLConnectionConfigNotFoundError):
            get_mysql_connection_config(self.empresa.id, 'ventas')

    def test_resolver_inactive_raises(self):
        inactive = SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico='inactiva',
            host='127.0.0.1',
            port=3306,
            user='u',
            password='p',
            db_name='dbx',
            is_active=False,
        )
        with self.assertRaises(MySQLConnectionConfigInactiveError):
            get_mysql_connection_config(self.empresa.id, 'inactiva')

    def test_nombre_logico_normalization(self):
        req = self._build_request_with_session(self.empresa.id)
        for variant in ('ventas', ' Ventas ', 'VENTAS'):
            cfg = get_mysql_connection_config_for_request(req, variant)
            self.assertEqual(cfg['nombre_logico'], 'ventas')

    @patch('pymysql.connect')
    def test_open_mysql_connection_uses_only_concrete_config_and_closes(self, connect):
        config = SettingsMySQLConnection.objects.get(empresa=self.empresa, nombre_logico='ventas')
        config.engine = SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL
        connection = MagicMock()
        connect.return_value = connection

        with open_mysql_connection(config) as opened:
            self.assertIs(opened, connection)

        connect.assert_called_once_with(
            host='127.0.0.1',
            port=3306,
            user='u',
            password='p',
            database='db1',
            charset='utf8',
            connect_timeout=5,
            read_timeout=10,
            write_timeout=10,
        )
        connection.close.assert_called_once_with()
        connection.cursor.assert_not_called()

    @patch('pymysql.connect')
    def test_open_mysql_connection_closes_when_caller_raises(self, connect):
        config = SettingsMySQLConnection.objects.get(empresa=self.empresa, nombre_logico='ventas')
        config.engine = SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL
        connection = MagicMock()
        connect.return_value = connection

        with self.assertRaises(RuntimeError):
            with open_mysql_connection(config):
                raise RuntimeError('caller failure')

        connection.close.assert_called_once_with()

    def test_open_mysql_connection_does_not_use_request_or_empresa_selection(self):
        config = SettingsMySQLConnection.objects.get(empresa=self.empresa, nombre_logico='ventas')
        config.engine = SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL

        with patch('pymysql.connect', return_value=MagicMock()) as connect:
            with open_mysql_connection(config):
                pass

        self.assertEqual(connect.call_args.kwargs['database'], 'db1')

    @patch('settings.services.mysql_connections.connections')
    def test_open_mysql_connection_supports_django_mysql_and_cleans_alias(self, connections):
        config = SettingsMySQLConnection.objects.get(empresa=self.empresa, nombre_logico='ventas')
        django_connection = MagicMock()
        connections.__getitem__.return_value = django_connection
        connections.databases = {}

        with open_mysql_connection(config) as opened:
            self.assertIs(opened, django_connection)
            django_connection.ensure_connection.assert_called_once_with()
            self.assertEqual(len(connections.databases), 1)

        django_connection.close.assert_called_once_with()
        self.assertEqual(connections.databases, {})

    def test_open_mysql_connection_rejects_remote_engine_without_sql(self):
        config = SettingsMySQLConnection.objects.get(empresa=self.empresa, nombre_logico='ventas')
        config.engine = SettingsMySQLConnection.ENGINE_API_REMOTA

        with self.assertRaises(MySQLConnectionOpenError):
            with open_mysql_connection(config):
                pass

    @patch('pymysql.connect', side_effect=RuntimeError('password=hidden'))
    def test_open_mysql_connection_sanitizes_open_error(self, connect):
        config = SettingsMySQLConnection.objects.get(empresa=self.empresa, nombre_logico='ventas')
        config.engine = SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL

        with self.assertRaises(MySQLConnectionOpenError) as raised:
            with open_mysql_connection(config):
                pass

        self.assertNotIn('password', str(raised.exception).lower())
