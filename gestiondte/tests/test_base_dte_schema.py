import re
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.conf import settings
from django.core import signing
from django.db import connections
from django.db.backends.mysql.base import DatabaseWrapper
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from gestiondte.models import (
    CertificadoSII,
    GestionDTEConnectionRole,
    LecturaAutomaticaEjecucion,
    TareaRPETC,
)
from gestiondte.services.base_dte_schema import (
    BaseDTESchemaInstallError,
    MODEL_BY_TABLE,
    SCHEMA_PATH,
    TABLE_NAMES,
    _build_preview,
    _column_compatibility_differences,
    _column_difference_plan,
    _column_type_is_compatible,
    _json_validation_is_proven,
    _read_schema_statements,
    _schema_statement_for_connection,
    _validate_connection,
    install_base_dte_schema,
)
from settings.models import SettingsMySQLConnection


class BaseDTESchemaComparatorTests(SimpleTestCase):
    @staticmethod
    def _mysql_connection():
        return SimpleNamespace(
            data_types={
                'BinaryField': 'longblob',
                'JSONField': 'json',
                'UUIDField': 'uuid',
            },
            ops=SimpleNamespace(quote_name=lambda name: name),
            cursor=MagicMock(),
            vendor='mysql',
            features=SimpleNamespace(has_native_uuid_field=True),
        )

    @staticmethod
    def _certificate_schema(actual_type='blob', actual_nullable='YES'):
        table = CertificadoSII._meta.db_table
        return {
            'tables': {
                table: {
                    'TABLE_TYPE': 'BASE TABLE',
                    'ENGINE': 'InnoDB',
                    'TABLE_COLLATION': 'utf8mb4_unicode_ci',
                },
            },
            'columns': {
                table: [
                    {
                        'COLUMN_NAME': 'password_encrypted',
                        'COLUMN_TYPE': actual_type,
                        'IS_NULLABLE': actual_nullable,
                        'EXTRA': '',
                    },
                ],
            },
            'indexes': {table: []},
            'foreign_keys': {table: []},
        }

    def test_narrower_binary_storage_is_not_compatible(self):
        password_field = CertificadoSII._meta.get_field('password_encrypted')

        self.assertTrue(
            _column_type_is_compatible(password_field, 'longblob', 'longblob')
        )
        self.assertFalse(
            _column_type_is_compatible(password_field, 'longblob', 'blob')
        )
        self.assertFalse(
            _column_type_is_compatible(password_field, 'longblob', 'mediumblob')
        )

    def test_sqlite_binary_and_json_types_require_backend_semantics(self):
        password_field = CertificadoSII._meta.get_field('password_encrypted')
        json_field = TareaRPETC._meta.get_field('parametros')

        self.assertTrue(
            _column_type_is_compatible(
                password_field,
                'BLOB',
                'BLOB',
                vendor='sqlite',
            )
        )
        self.assertTrue(
            _column_type_is_compatible(
                json_field,
                'TEXT',
                'TEXT',
                vendor='sqlite',
                json_validation_proven=True,
            )
        )
        self.assertFalse(
            _column_type_is_compatible(
                json_field,
                'TEXT',
                'TEXT',
                vendor='sqlite',
            )
        )

    def test_json_native_and_validated_longtext_are_mysql_compatible(self):
        json_field = TareaRPETC._meta.get_field('parametros')

        self.assertTrue(
            _column_type_is_compatible(
                json_field,
                'json',
                'json',
                vendor='mysql',
            )
        )
        self.assertTrue(
            _column_type_is_compatible(
                json_field,
                'json',
                'longtext',
                vendor='mysql',
                json_validation_proven=True,
            )
        )
        self.assertFalse(
            _column_type_is_compatible(
                json_field,
                'json',
                'longtext',
                vendor='mysql',
            )
        )

    def test_mariadb_json_valid_check_proves_longtext_semantics(self):
        json_field = TareaRPETC._meta.get_field('parametros')
        connection = self._mysql_connection()
        schema = {
            'server_version': '10.11.13-MariaDB-ubu2004',
            'is_mariadb': True,
            'check_constraints_enforced': True,
            'checks': {
                TareaRPETC._meta.db_table: [
                    {
                        'name': 'parametros',
                        'clause': 'json_valid(`parametros`)',
                    },
                ],
            },
        }

        self.assertTrue(
            _json_validation_is_proven(
                json_field,
                TareaRPETC._meta.db_table,
                'longtext',
                schema,
                connection,
            )
        )
        schema['checks'][TareaRPETC._meta.db_table] = []
        self.assertFalse(
            _json_validation_is_proven(
                json_field,
                TareaRPETC._meta.db_table,
                'longtext',
                schema,
                connection,
            )
        )

    def test_sqlite_json_valid_check_with_nullable_guard_is_proven(self):
        json_field = TareaRPETC._meta.get_field('parametros')
        connection = SimpleNamespace(vendor='sqlite')
        table = TareaRPETC._meta.db_table
        schema = {
            'check_constraints_enforced': True,
            'checks': {
                table: [
                    {
                        'name': 'json_valid_parametros',
                        'clause': (
                            'JSON_VALID("parametros") OR "parametros" IS NULL'
                        ),
                    },
                ],
            },
        }

        self.assertTrue(
            _json_validation_is_proven(
                json_field,
                table,
                'TEXT',
                schema,
                connection,
            )
        )
        schema['checks'][table] = []
        self.assertFalse(
            _json_validation_is_proven(
                json_field,
                table,
                'TEXT',
                schema,
                connection,
            )
        )

    def test_signed_bigint_user_reference_is_a_safe_widening(self):
        creator_field = CertificadoSII._meta.get_field('created_by')

        self.assertTrue(
            _column_type_is_compatible(creator_field, 'integer', 'bigint(20)')
        )
        self.assertFalse(
            _column_type_is_compatible(
                creator_field,
                'integer',
                'bigint unsigned',
            )
        )

    def test_uuid_storage_follows_sqlite_and_mariadb_backend_contracts(self):
        field = LecturaAutomaticaEjecucion._meta.get_field('lote_id')
        value = uuid.UUID('12345678-1234-5678-1234-567812345678')
        sqlite_connection = connections['default']
        mariadb_connection = self._mysql_connection()

        self.assertEqual(field.db_type(sqlite_connection), 'char(32)')
        self.assertEqual(
            field.get_db_prep_value(value, sqlite_connection, prepared=False),
            value.hex,
        )
        self.assertEqual(field.to_python(value.hex), value)

        self.assertEqual(field.db_type(mariadb_connection), 'uuid')
        self.assertTrue(
            _column_type_is_compatible(
                field,
                field.db_type(mariadb_connection),
                'uuid',
                vendor='mysql',
            )
        )
        self.assertFalse(
            _column_type_is_compatible(
                field,
                field.db_type(mariadb_connection),
                'char(32)',
                vendor='mysql',
            )
        )
        self.assertFalse(
            _column_type_is_compatible(
                field,
                field.db_type(mariadb_connection),
                'char(36)',
                vendor='mysql',
            )
        )
        self.assertEqual(
            field.get_db_prep_value(value, mariadb_connection, prepared=False),
            value,
        )
        self.assertEqual(field.to_python(value.hex), value)

    def test_uuid_char32_is_compatible_only_when_backend_expects_char32(self):
        field = LecturaAutomaticaEjecucion._meta.get_field('lote_id')
        mysql_connection = self._mysql_connection()
        mysql_connection.data_types['UUIDField'] = 'char(32)'
        mysql_connection.features.has_native_uuid_field = False

        self.assertTrue(
            _column_type_is_compatible(
                field,
                field.db_type(mysql_connection),
                'char(32)',
                vendor='mysql',
            )
        )
        self.assertFalse(
            _column_type_is_compatible(
                field,
                field.db_type(mysql_connection),
                'uuid',
                vendor='mysql',
            )
        )

    def test_uuid_difference_rejects_native_char_and_nullability_mismatches(self):
        field = LecturaAutomaticaEjecucion._meta.get_field('lote_id')
        connection = self._mysql_connection()
        table = field.model._meta.db_table
        actual = {
            'tables': {table: {'TABLE_TYPE': 'BASE TABLE'}},
            'columns': {
                table: [
                    {
                        'COLUMN_NAME': 'lote_id',
                        'COLUMN_TYPE': 'char(32)',
                        'IS_NULLABLE': 'NO',
                    },
                ],
            },
            'checks': {},
        }

        difference = _column_compatibility_differences(
            field.model,
            actual,
            connection,
        )[0]

        self.assertEqual(difference['expected_type'], 'uuid')
        self.assertEqual(difference['actual_type'], 'char(32)')
        self.assertFalse(difference['type_compatible'])
        self.assertTrue(difference['nullability_compatible'])
        self.assertEqual(difference['classification'], 'INCOMPATIBLE')

        actual['columns'][table][0].update(
            {'COLUMN_TYPE': 'uuid', 'IS_NULLABLE': 'YES'}
        )
        difference = _column_compatibility_differences(
            field.model,
            actual,
            connection,
        )[0]
        self.assertTrue(difference['type_compatible'])
        self.assertFalse(difference['nullability_compatible'])
        self.assertEqual(difference['classification'], 'INCOMPATIBLE')

    def test_uuid_create_statement_uses_active_backend_type(self):
        table = LecturaAutomaticaEjecucion._meta.db_table
        statement = _read_schema_statements()[table]
        native_connection = self._mysql_connection()
        char_connection = self._mysql_connection()
        char_connection.data_types['UUIDField'] = 'char(32)'
        char_connection.features.has_native_uuid_field = False

        native_statement = _schema_statement_for_connection(
            table,
            statement,
            native_connection,
        )

        self.assertIn('`lote_id` UUID NOT NULL', native_statement)
        self.assertNotIn('`lote_id` CHAR(32) NOT NULL', native_statement)
        self.assertEqual(
            _schema_statement_for_connection(table, statement, char_connection),
            statement,
        )
        with self.assertRaises(BaseDTESchemaInstallError):
            _schema_statement_for_connection(
                table,
                statement.replace(
                    '`lote_id` CHAR(32) NOT NULL',
                    '`lote_id` CHAR(36) NOT NULL',
                ),
                native_connection,
            )

    def test_binary_capacity_mismatch_proposes_only_a_separate_plan(self):
        plan = _column_difference_plan(
            CertificadoSII._meta.get_field('password_encrypted'),
            'longblob',
            'blob',
            'YES',
            'YES',
            False,
            'mysql',
        )

        self.assertEqual(plan['classification'], 'REQUIERE_AMPLIACIÓN_SEGURA')
        self.assertIn('BLOB → LONGBLOB', plan['action_proposed'])
        self.assertTrue(plan['requires_confirmation'])

    def test_preview_exposes_column_type_and_nullability_differences(self):
        connection = self._mysql_connection()
        schema = self._certificate_schema(actual_nullable='NO')

        differences = _column_compatibility_differences(
            CertificadoSII,
            schema,
            connection,
        )

        self.assertEqual(
            differences[0]['column'],
            'password_encrypted',
        )
        self.assertEqual(differences[0]['expected_type'], 'longblob')
        self.assertEqual(differences[0]['actual_type'], 'blob')
        self.assertEqual(differences[0]['expected_nullability'], 'YES')
        self.assertEqual(differences[0]['actual_nullability'], 'NO')
        self.assertEqual(
            differences[0]['classification'],
            'INCOMPATIBLE',
        )

    def test_real_column_mismatch_blocks_all_ddl(self):
        connection = self._mysql_connection()
        schema = self._certificate_schema()
        preview = _build_preview(schema, 'gestiondte', connection)

        with (
            patch(
                'gestiondte.services.base_dte_schema._read_schema_statements',
                return_value={},
            ),
            patch(
                'gestiondte.services.base_dte_schema._schema_operation',
                side_effect=lambda config, database_name, operation: operation(
                    connection,
                    schema,
                ),
            ),
        ):
            result = install_base_dte_schema(
                MagicMock(spec=SettingsMySQLConnection),
                'gestiondte',
                preview['fingerprint'],
            )

        self.assertEqual(result['created'], [])
        self.assertEqual(result['conflicts'][0]['name'], 'gestiondte_certificadosii')
        self.assertEqual(result['conflicts'][0]['classification'], 'INCOMPATIBLE')
        self.assertEqual(
            result['conflicts'][0]['column_differences'][0]['column'],
            'password_encrypted',
        )
        self.assertTrue(
            result['conflicts'][0]['column_differences'][0][
                'requires_confirmation'
            ]
        )
        connection.cursor.assert_not_called()


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
        session['empresa_id'] = self.empresa.pk
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

        response = self.client.post(
            reverse('gestion_dte:base_dte_schema_install'),
            {'schema_action': 'preview'},
        )

        self.assertEqual(response.status_code, 403)

    def test_csrf_is_required_for_schema_preview(self):
        self._activate()
        self._grant(ver=True, ingresar=True, supervisor=True)
        self._configure_mysql_role()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        session = client.session
        session['empresa_id'] = self.empresa.pk
        session.save()

        client.get(reverse('gestion_dte:connection_roles'))
        response = client.post(
            reverse('gestion_dte:base_dte_schema_install'),
            {'schema_action': 'preview'},
        )

        self.assertEqual(response.status_code, 403)

    @patch('gestiondte.connection_views.install_base_dte_schema')
    @patch('gestiondte.connection_views.preview_base_dte_schema')
    def test_incomplete_configuration_does_not_inspect_or_execute_ddl(
        self, preview, install
    ):
        self._activate()
        self._grant(ver=True, ingresar=True, supervisor=True)
        GestionDTEConnectionRole.objects.create(
            role='serverbasedte',
            source_type='MYSQL_CONFIG',
            mysql_connection=self.connection,
        )

        response = self.client.post(
            reverse('gestion_dte:base_dte_schema_install'),
            {'schema_action': 'preview'},
        )

        self.assertEqual(response.status_code, 302)
        preview.assert_not_called()
        install.assert_not_called()

    def test_button_is_visible_only_for_supervisor_and_mysql_config(self):
        self._activate()
        self._configure_mysql_role()
        self._grant(ver=True, ingresar=True)

        response_without_supervisor = self.client.get(reverse('gestion_dte:connection_roles'))
        self.assertNotContains(response_without_supervisor, 'Crear estructura Base DTE')

        Permiso.objects.filter(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
        ).update(supervisor=True)
        response_with_supervisor = self.client.get(reverse('gestion_dte:connection_roles'))
        self.assertContains(response_with_supervisor, 'Crear estructura Base DTE')

        GestionDTEConnectionRole.objects.filter(role='serverbasedte').update(
            source_type='DJANGO',
            django_alias='default',
            mysql_connection=None,
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

    def test_button_render_contains_database_name_and_inspection_step(self):
        self._activate()
        self._grant(ver=True, ingresar=True, supervisor=True)
        self._configure_mysql_role()

        response = self.client.get(reverse('gestion_dte:connection_roles'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Crear estructura Base DTE')
        self.assertContains(response, "esquema 'gestiondte'")
        self.assertContains(response, 'Inspeccionar estructura')
        self.assertNotContains(response, 'Confirmar creación')

    @patch('gestiondte.connection_views.preview_base_dte_schema')
    @patch('gestiondte.connection_views.get_gestiondte_mysql_connection')
    @patch('gestiondte.connection_views.get_gestiondte_connection')
    def test_preview_resolves_serverbasedte_and_shows_second_confirmation(
        self, get_connection, get_mysql_connection, preview
    ):
        self._activate()
        self._grant(ver=True, ingresar=True, supervisor=True)
        self._configure_mysql_role()
        get_connection.return_value = {
            'type': 'MYSQL_CONFIG',
            'connection_id': self.connection.pk,
            'database_name': 'gestiondte',
        }
        get_mysql_connection.return_value = self.connection
        preview.return_value = {
            'database_name': 'gestiondte',
            'tables': [
                {
                    'name': 'gestiondte_tarearpetc',
                    'status': 'missing',
                    'issues': [],
                },
            ],
            'existing': [],
            'missing': ['gestiondte_tarearpetc'],
            'conflicts': [],
            'fingerprint': 'signed-fingerprint',
        }

        response = self.client.post(
            reverse('gestion_dte:base_dte_schema_install'),
            {'schema_action': 'preview'},
        )

        self.assertEqual(response.status_code, 200)
        get_connection.assert_called_once_with('serverbasedte')
        get_mysql_connection.assert_called_once_with('serverbasedte')
        preview.assert_called_once_with(self.connection, 'gestiondte')
        self.assertContains(response, 'gestiondte_tarearpetc')
        self.assertContains(response, 'Confirmar creación')
        self.assertEqual(
            get_connection.call_args_list[0].args[0],
            'serverbasedte',
        )

    @patch('gestiondte.connection_views.install_base_dte_schema')
    @patch('gestiondte.connection_views.get_gestiondte_mysql_connection')
    @patch('gestiondte.connection_views.get_gestiondte_connection')
    def test_confirmation_re_resolves_role_and_uses_signed_preview(
        self, get_connection, get_mysql_connection, install
    ):
        self._activate()
        self._grant(ver=True, ingresar=True, supervisor=True)
        self._configure_mysql_role()
        get_connection.return_value = {
            'type': 'MYSQL_CONFIG',
            'connection_id': self.connection.pk,
            'database_name': 'gestiondte',
        }
        get_mysql_connection.return_value = self.connection
        install.return_value = {
            'created': ['gestiondte_tarearpetc'],
            'existing': [],
            'omitted': [],
            'conflicts': [],
            'error_table': None,
            'error_type': None,
            'pending': [],
        }
        token = signing.dumps(
            {
                'connection_id': self.connection.pk,
                'connection_updated_at': self.connection.updated_at.isoformat(),
                'database_name': 'gestiondte',
                'fingerprint': 'signed-fingerprint',
            },
            salt='gestiondte.base-dte-schema-preview',
            compress=True,
        )

        response = self.client.post(
            reverse('gestion_dte:base_dte_schema_install'),
            {
                'schema_action': 'confirm',
                'schema_preview_token': token,
            },
        )

        self.assertEqual(response.status_code, 302)
        install.assert_called_once_with(
            self.connection,
            database_name='gestiondte',
            expected_fingerprint='signed-fingerprint',
        )
        self.assertEqual(get_connection.call_count, 1)

    @patch('gestiondte.connection_views.install_base_dte_schema')
    @patch('gestiondte.connection_views.get_gestiondte_mysql_connection')
    @patch('gestiondte.connection_views.get_gestiondte_connection')
    def test_confirmation_without_valid_preview_does_not_execute_ddl(
        self, get_connection, get_mysql_connection, install
    ):
        self._activate()
        self._grant(ver=True, ingresar=True, supervisor=True)
        self._configure_mysql_role()
        get_connection.return_value = {
            'type': 'MYSQL_CONFIG',
            'connection_id': self.connection.pk,
            'database_name': 'gestiondte',
        }
        get_mysql_connection.return_value = self.connection

        response = self.client.post(
            reverse('gestion_dte:base_dte_schema_install'),
            {
                'schema_action': 'confirm',
                'schema_preview_token': 'invalid-token',
            },
        )

        self.assertEqual(response.status_code, 302)
        install.assert_not_called()

    @patch('gestiondte.connection_views.get_gestiondte_connection')
    def test_django_role_does_not_execute_schema_operations(self, get_connection):
        self._activate()
        self._grant(ver=True, ingresar=True, supervisor=True)
        GestionDTEConnectionRole.objects.create(
            role='serverbasedte',
            source_type='DJANGO',
            django_alias='default',
        )
        get_connection.return_value = {'type': 'DJANGO', 'alias': 'default'}

        response = self.client.post(
            reverse('gestion_dte:base_dte_schema_install'),
            {'schema_action': 'preview'},
        )

        self.assertEqual(response.status_code, 302)

    def test_sql_file_only_creates_whitelisted_tables_and_internal_relations(self):
        statements = _read_schema_statements()
        sql = SCHEMA_PATH.read_text(encoding='utf-8')

        self.assertEqual(set(statements), set(TABLE_NAMES))
        self.assertTrue(
            all(statement.upper().startswith('CREATE TABLE') for statement in statements.values())
        )
        self.assertNotRegex(
            '\n'.join(statements.values()),
            r'\b(?:ALTER|DROP|TRUNCATE|DELETE|RENAME|INSERT|UPDATE)\b',
        )
        self.assertIn('gestiondte_certificadosii', sql)
        self.assertIn('created_by_id', sql)
        self.assertIn('updated_by_id', sql)
        self.assertIn('created_by_username', sql)
        self.assertIn('updated_by_username', sql)
        self.assertIn('FOREIGN KEY', sql.upper())
        self.assertNotIn('AUTH_USER', sql.upper())
        self.assertNotIn('ACCESS_CONTROL_EMPRESA', sql.upper())
        references = {
            target
            for statement in statements.values()
            for target in re.findall(
                r'\bREFERENCES\s+`([A-Za-z0-9_]+)`',
                statement,
                re.IGNORECASE,
            )
        }
        self.assertTrue(references.issubset(MODEL_BY_TABLE))

    def test_existing_certificate_binary_narrowing_is_not_compatible(self):
        password_field = CertificadoSII._meta.get_field('password_encrypted')
        creator_field = CertificadoSII._meta.get_field('created_by')

        self.assertFalse(
            _column_type_is_compatible(password_field, 'longblob', 'blob')
        )
        self.assertTrue(
            _column_type_is_compatible(creator_field, 'integer', 'bigint')
        )
        self.assertFalse(
            _column_type_is_compatible(password_field, 'longblob', 'tinyblob')
        )

    @staticmethod
    def _mysql_connection(alias):
        config = settings.DATABASES['default'].copy()
        config.update(
            {
                'ENGINE': 'django.db.backends.mysql',
                'NAME': 'offline_schema_only',
                'USER': '',
                'PASSWORD': '',
                'HOST': '',
                'PORT': '',
                'TIME_ZONE': settings.TIME_ZONE,
            }
        )
        return DatabaseWrapper(config, alias)

    def test_connection_validation_rejects_default_alias(self):
        connection = self._mysql_connection('default')

        with self.assertRaisesRegex(
            BaseDTESchemaInstallError,
            'alias MySQL operacional aislado',
        ):
            _validate_connection(connection, 'gestiondte')

    def test_connection_validation_requires_exact_database_name(self):
        connection = self._mysql_connection('mysql_runtime_test')
        cursor = MagicMock()
        connection.cursor = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchone.return_value = ('other_database',)

        with self.assertRaisesRegex(
            BaseDTESchemaInstallError,
            'no corresponde a la base',
        ):
            _validate_connection(connection, 'gestiondte')

    @staticmethod
    def _actual_schema(tables=()):
        return {
            'tables': {
                table: {
                    'TABLE_TYPE': 'BASE TABLE',
                    'ENGINE': 'InnoDB',
                    'TABLE_COLLATION': 'utf8mb4_unicode_ci',
                }
                for table in tables
            },
            'columns': {},
            'indexes': {},
            'foreign_keys': {},
        }

    def _run_install_with_schema(
        self,
        initial_tables=(),
        failing_table=None,
        issues=None,
        issue_resolver=None,
    ):
        existing_tables = set(initial_tables)
        executed = []
        cursor = MagicMock()
        connection = SimpleNamespace(
            vendor='mysql',
            data_types={'UUIDField': 'char(32)'},
            ops=SimpleNamespace(quote_name=lambda name: name),
            cursor=MagicMock(),
        )
        connection.cursor.return_value.__enter__.return_value = cursor

        def execute(statement):
            table = next(
                name for name in TABLE_NAMES if f'CREATE TABLE `{name}`' in statement
            )
            if table == failing_table:
                raise RuntimeError('sanitized test failure')
            executed.append(table)
            existing_tables.add(table)

        def inspect_schema(actual_connection, actual_database):
            self.assertIs(actual_connection, connection)
            self.assertEqual(actual_database, 'gestiondte')
            return self._actual_schema(existing_tables)

        def compatibility_issues(model, *_):
            if issue_resolver is not None:
                return issue_resolver(model, existing_tables)
            return issues or []

        cursor.execute.side_effect = execute
        initial_schema = self._actual_schema(initial_tables)
        with (
            patch(
                'gestiondte.services.base_dte_schema._table_compatibility_issues',
                side_effect=compatibility_issues,
            ),
        ):
            fingerprint = _build_preview(
                initial_schema,
                'gestiondte',
                connection,
            )['fingerprint']
            with (
                patch('gestiondte.services.base_dte_schema._schema_operation') as operation,
                patch(
                    'gestiondte.services.base_dte_schema._inspect_schema',
                    side_effect=inspect_schema,
                ),
            ):
                operation.side_effect = (
                    lambda *args: args[2](
                        connection,
                        initial_schema,
                    )
                )
                result = install_base_dte_schema(
                    self.connection,
                    'gestiondte',
                    fingerprint,
                )
        return result, executed

    def test_install_creates_only_missing_tables_and_is_idempotent(self):
        result, executed = self._run_install_with_schema()

        self.assertEqual(executed, list(TABLE_NAMES))
        self.assertEqual(result['created'], list(TABLE_NAMES))
        self.assertFalse(result['pending'])

        existing, second_execution = self._run_install_with_schema(TABLE_NAMES)
        self.assertEqual(existing['created'], [])
        self.assertEqual(existing['existing'], list(TABLE_NAMES))
        self.assertEqual(second_execution, [])

    def test_incompatible_existing_table_blocks_all_ddl(self):
        result, executed = self._run_install_with_schema(
            initial_tables=(TABLE_NAMES[0],),
            issues=['ENGINE_MISMATCH'],
        )

        self.assertEqual(executed, [])
        self.assertEqual(result['conflicts'][0]['issues'], ['ENGINE_MISMATCH'])

    def test_partial_ddl_failure_reports_created_and_pending_tables(self):
        failing = TABLE_NAMES[1]
        result, executed = self._run_install_with_schema(failing_table=failing)

        self.assertEqual(executed, [TABLE_NAMES[0]])
        self.assertEqual(result['created'], [TABLE_NAMES[0]])
        self.assertEqual(result['error_table'], failing)
        self.assertEqual(result['error_type'], 'RuntimeError')
        self.assertEqual(result['pending'], list(TABLE_NAMES[1:]))

    def test_install_resumes_after_partial_creation_without_recreating_tables(self):
        existing_tables = TABLE_NAMES[:7]

        result, executed = self._run_install_with_schema(
            initial_tables=existing_tables,
        )

        self.assertEqual(executed, list(TABLE_NAMES[7:]))
        self.assertEqual(result['existing'], list(existing_tables))
        self.assertEqual(result['created'], list(TABLE_NAMES[7:]))
        self.assertFalse(result['pending'])

    def test_post_create_uuid_mismatch_stops_and_blocks_retry_ddl(self):
        uuid_table = LecturaAutomaticaEjecucion._meta.db_table

        def mismatch_after_creation(model, existing_tables):
            if model._meta.db_table == uuid_table and uuid_table in existing_tables:
                return ['COLUMN_TYPE_MISMATCH']
            return []

        initial_tables = TABLE_NAMES[:6]
        result, executed = self._run_install_with_schema(
            initial_tables=initial_tables,
            issue_resolver=mismatch_after_creation,
        )

        self.assertEqual(executed, [uuid_table])
        self.assertEqual(result['created'], [uuid_table])
        self.assertEqual(result['existing'], list(initial_tables))
        self.assertEqual(result['error_table'], uuid_table)
        self.assertEqual(result['error_type'], 'POST_CREATE_SCHEMA_MISMATCH')
        self.assertEqual(result['pending'], list(TABLE_NAMES[7:]))
        self.assertEqual(result['conflicts'][0]['name'], uuid_table)

        partial_tables = (*initial_tables, uuid_table)
        retry, retry_executed = self._run_install_with_schema(
            initial_tables=partial_tables,
            issue_resolver=mismatch_after_creation,
        )

        self.assertEqual(retry_executed, [])
        self.assertEqual(retry['created'], [])
        self.assertEqual(retry['existing'], list(initial_tables))
        self.assertEqual(retry['omitted'], list(TABLE_NAMES[7:]))
        self.assertEqual(retry['conflicts'][0]['name'], uuid_table)
