from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from gestiondte.models import GestionDTEConnectionRole
from gestiondte.services.base_dte_schema import (
    BaseDTESchemaInstallError,
    SCHEMA_PATH,
    _read_schema_statements,
    install_base_dte_schema,
)
from settings.models import SettingsMySQLConnection


class BaseDTESchemaInstallTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='base-dte-user', password='pass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa prueba')
        self.vista = Vista.objects.create(
            nombre='Gestion DTE - Conexiones SQL',
            route_name='gestion_dte:connection_roles',
        )
        self.connection = SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico='base-dte',
            host='mysql.example.test',
            user='user',
            password='secret-no-debe-salir',
            db_name='base_dte',
        )

    def _activate(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def _grant(self, **flags):
        return Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            **flags,
        )

    def _configure_mysql_role(self):
        return GestionDTEConnectionRole.objects.create(
            role='serverbasedte',
            source_type='MYSQL_CONFIG',
            mysql_connection=self.connection,
            database_name='gestiondte',
        )

    def test_user_without_supervisor_cannot_execute(self):
        self._activate()
        self._grant(ver=True, ingresar=True, modificar=True)
        self._configure_mysql_role()

        response = self.client.post(reverse('gestion_dte:base_dte_schema_install'))

        self.assertEqual(response.status_code, 403)

    @patch('gestiondte.connection_views.install_base_dte_schema')
    def test_incomplete_configuration_does_not_execute_ddl(self, install):
        self._activate()
        self._grant(ver=True, ingresar=True, supervisor=True)
        GestionDTEConnectionRole.objects.create(
            role='serverbasedte',
            source_type='MYSQL_CONFIG',
            mysql_connection=self.connection,
        )

        response = self.client.post(reverse('gestion_dte:base_dte_schema_install'))

        self.assertEqual(response.status_code, 302)
        install.assert_not_called()

    def test_button_is_visible_only_for_supervisor_and_mysql_config(self):
        self._activate()
        self._configure_mysql_role()
        self._grant(ver=True, ingresar=True)

        response_without_supervisor = self.client.get(reverse('gestion_dte:connection_roles'))
        self.assertNotContains(response_without_supervisor, 'Crear estructura Base DTE')

        Permiso.objects.filter(usuario=self.user, empresa=self.empresa, vista=self.vista).update(supervisor=True)
        response_with_supervisor = self.client.get(reverse('gestion_dte:connection_roles'))
        self.assertContains(response_with_supervisor, 'Crear estructura Base DTE')

        GestionDTEConnectionRole.objects.filter(role='serverbasedte').update(
            source_type='DJANGO', django_alias='default', mysql_connection=None
        )
        response_with_django = self.client.get(reverse('gestion_dte:connection_roles'))
        self.assertNotContains(response_with_django, 'Crear estructura Base DTE')

    def test_button_is_hidden_without_database_name(self):
        self._activate()
        self._grant(ver=True, ingresar=True, supervisor=True)
        GestionDTEConnectionRole.objects.create(
            role='serverbasedte',
            source_type='MYSQL_CONFIG',
            mysql_connection=self.connection,
        )

        response = self.client.get(reverse('gestion_dte:connection_roles'))

        self.assertNotContains(response, 'Crear estructura Base DTE')

    def test_button_is_hidden_for_gestion_dte_audit_role(self):
        self._activate()
        self._grant(ver=True, ingresar=True, supervisor=True)
        GestionDTEConnectionRole.objects.create(
            role='serverauditoriagestiondte',
            source_type='MYSQL_CONFIG',
            mysql_connection=self.connection,
            database_name='gestiondte_auditoria',
        )

        response = self.client.get(reverse('gestion_dte:connection_roles'))

        self.assertNotContains(response, 'Crear estructura Base DTE')

    def test_button_render_contains_base_dte_database_name(self):
        self._activate()
        self._grant(ver=True, ingresar=True, supervisor=True)
        self._configure_mysql_role()

        response = self.client.get(reverse('gestion_dte:connection_roles'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Crear estructura Base DTE')
        self.assertContains(response, "base 'gestiondte'")

    @patch('gestiondte.connection_views.install_base_dte_schema')
    @patch('gestiondte.connection_views.get_gestiondte_mysql_connection')
    @patch('gestiondte.connection_views.get_gestiondte_connection')
    def test_supervisor_resolves_serverbasedte_and_uses_exact_config(
        self, get_connection, get_mysql_connection, install
    ):
        self._activate()
        self._grant(ver=True, ingresar=True, supervisor=True)
        self._configure_mysql_role()
        get_connection.return_value = {
            'type': 'MYSQL_CONFIG',
            'database_name': 'gestiondte',
        }
        get_mysql_connection.return_value = self.connection

        response = self.client.post(reverse('gestion_dte:base_dte_schema_install'))

        self.assertEqual(response.status_code, 302)
        get_connection.assert_called_once_with('serverbasedte')
        get_mysql_connection.assert_called_once_with('serverbasedte')
        install.assert_called_once_with(self.connection, database_name='gestiondte')
        self.assertFalse(get_connection.call_args_list[0].args[0] == 'servercontabilidad')

    @patch('gestiondte.connection_views.install_base_dte_schema')
    @patch('gestiondte.connection_views.get_gestiondte_connection')
    def test_django_role_does_not_execute_sql_file(self, get_connection, install):
        self._activate()
        self._grant(ver=True, ingresar=True, supervisor=True)
        GestionDTEConnectionRole.objects.create(
            role='serverbasedte', source_type='DJANGO', django_alias='default'
        )
        get_connection.return_value = {'type': 'DJANGO', 'alias': 'default'}

        response = self.client.post(reverse('gestion_dte:base_dte_schema_install'))

        self.assertEqual(response.status_code, 302)
        install.assert_not_called()

    def test_sql_file_is_create_only_and_idempotent(self):
        statements = _read_schema_statements()
        sql = SCHEMA_PATH.read_text(encoding='utf-8')

        self.assertTrue(statements)
        self.assertTrue(all(statement.upper().startswith('CREATE TABLE IF NOT EXISTS') for statement in statements))
        self.assertNotRegex('\n'.join(statements), r'\b(?:ALTER|DROP|TRUNCATE|DELETE|RENAME)\b')
        self.assertIn('gestiondte_certificadosii', sql)
        self.assertIn('created_by_id', sql)
        self.assertIn('updated_by_id', sql)
        self.assertIn('created_by_username', sql)
        self.assertIn('updated_by_username', sql)
        self.assertNotIn('FOREIGN KEY', sql.upper())
        self.assertNotIn('AUTH_USER', sql.upper())

    @patch('gestiondte.services.base_dte_schema.open_mysql_connection')
    def test_install_reads_only_schema_and_executes_each_statement(self, open_connection):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        open_connection.return_value.__enter__.return_value = connection

        processed = install_base_dte_schema(self.connection)

        self.assertEqual(processed, 1)
        open_connection.assert_called_once_with(self.connection)
        cursor.execute.assert_called_once_with(_read_schema_statements()[0])

    @patch('gestiondte.services.base_dte_schema.open_mysql_connection')
    def test_install_passes_role_database_name_without_changing_config(self, open_connection):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        open_connection.return_value.__enter__.return_value = connection

        install_base_dte_schema(self.connection, database_name='gestiondte')

        open_connection.assert_called_once_with(
            self.connection,
            database_name='gestiondte',
        )
        self.assertEqual(self.connection.db_name, 'base_dte')

    @patch('gestiondte.services.base_dte_schema.open_mysql_connection', side_effect=RuntimeError('password=hidden'))
    def test_install_sanitizes_connection_errors(self, _open_connection):
        with self.assertRaises(BaseDTESchemaInstallError) as raised:
            install_base_dte_schema(self.connection)

        self.assertNotIn('password', str(raised.exception).lower())