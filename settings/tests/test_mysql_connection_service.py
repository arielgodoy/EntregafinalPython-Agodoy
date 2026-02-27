from django.test import TestCase, RequestFactory
from access_control.models import Empresa
from ..models import SettingsMySQLConnection
from settings.services.mysql_connections import (
    get_mysql_connection_config,
    get_mysql_connection_config_for_request,
    EmpresaActivaRequeridaError,
    MySQLConnectionConfigNotFoundError,
    MySQLConnectionConfigInactiveError,
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
