from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from gestiondte.forms import GestionDTEConnectionRoleForm
from gestiondte.connection_views import GestionDTEConnectionRoleView
from gestiondte.models import GestionDTEConnectionRole
from gestiondte.services.connection_roles import (
    GestionDTEAliasUnavailableError,
    GestionDTEConnectionSourceError,
    get_gestiondte_connection,
    get_gestiondte_connection_status,
    get_system_database_catalog,
)
from settings.models import SettingsMySQLConnection


class GestionDTEConnectionRoleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='connection-role-user', password='pass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa prueba')
        self.vista = Vista.objects.create(
            nombre='Gestion DTE - Conexiones SQL',
            route_name='gestion_dte:connection_roles',
        )
        self.connection = SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico='contabilidad',
            host='mysql.example.test',
            user='user',
            password='secret-no-debe-salir',
            db_name='contabilidad',
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

    def _valid_post_data(self):
        data = {}
        for role, _label in GestionDTEConnectionRole.ROLE_CHOICES:
            prefix = f'role-{role}'
            data[f'{prefix}-source_type'] = 'DJANGO'
            data[f'{prefix}-django_alias'] = 'default'
            data[f'{prefix}-mysql_connection'] = ''
        return data

    def test_get_requires_ingresar_and_post_requires_modificar(self):
        self._activate()
        self._grant(ver=True, ingresar=True, modificar=False)

        get_response = self.client.get(reverse('gestion_dte:connection_roles'))
        post_response = self.client.post(
            reverse('gestion_dte:connection_roles'),
            data=self._valid_post_data(),
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(post_response.status_code, 403)

    def test_final_view_name_and_all_roles_are_rendered(self):
        self._activate()
        self._grant(ver=True, ingresar=True)

        response = self.client.get(reverse('gestion_dte:connection_roles'))

        self.assertEqual(GestionDTEConnectionRoleView.vista_nombre, 'Gestion DTE - Conexiones SQL')
        self.assertContains(response, 'Gestion DTE - Conexiones SQL')
        for role, _label in GestionDTEConnectionRole.ROLE_CHOICES:
            self.assertContains(response, f'gestiondte.connection_roles.role.{role}')

    def test_system_database_options_are_rendered_in_role_selectors(self):
        self._activate()
        self._grant(ver=True, ingresar=True)

        response = self.client.get(reverse('gestion_dte:connection_roles'))

        self.assertContains(response, 'value="default"')
        self.assertContains(response, 'value="DB_sistema"')

    def test_template_contains_exclusive_selector_hooks(self):
        self._activate()
        self._grant(ver=True, ingresar=True)

        response = self.client.get(reverse('gestion_dte:connection_roles'))

        self.assertContains(response, 'data-connection-role="serverbasedte"')
        self.assertContains(response, 'data-role-source-type="true"')
        self.assertContains(response, 'data-role-field-container="django_alias"')
        self.assertContains(response, 'data-role-field-container="mysql_connection"')
        self.assertContains(response, 'gestiondte/js/connection_roles.js')

    def test_get_without_permission_is_rejected(self):
        self._activate()

        response = self.client.get(reverse('gestion_dte:connection_roles'))

        self.assertEqual(response.status_code, 403)

    def test_post_is_allowed_with_modificar(self):
        self._activate()
        self._grant(ver=True, ingresar=True, modificar=True)

        response = self.client.post(
            reverse('gestion_dte:connection_roles'),
            data=self._valid_post_data(),
        )

        self.assertEqual(response.status_code, 302)

    def test_form_requires_exactly_one_source(self):
        form = GestionDTEConnectionRoleForm(
            data={
                'source_type': 'DJANGO',
                'django_alias': '',
                'mysql_connection': self.connection.pk,
            },
            instance=GestionDTEConnectionRole(role='serverbasedte'),
        )

        self.assertFalse(form.is_valid())
        self.assertIn('django_alias', form.errors)
        self.assertIn('mysql_connection', form.errors)

    def test_form_only_offers_active_mysql_connections(self):
        inactive = SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico='inactiva',
            host='inactive.example.test',
            user='user',
            password='secret',
            db_name='inactive',
            is_active=False,
        )
        form = GestionDTEConnectionRoleForm(
            instance=GestionDTEConnectionRole(role='serverbasedte')
        )

        values = {str(value) for value, _label in form.fields['mysql_connection'].choices}
        self.assertIn(str(self.connection.pk), values)
        self.assertNotIn(str(inactive.pk), values)

    def test_database_name_is_normalized_away_for_django(self):
        role = GestionDTEConnectionRole(
            role='serverbasedte',
            source_type='DJANGO',
            django_alias='default',
            database_name='stale_database',
        )

        role.full_clean()

        self.assertIsNone(role.database_name)

    def test_configurable_mysql_roles_require_database_name(self):
        for role_name in ('serverbasedte', 'serverauditoriagestiondte'):
            with self.subTest(role=role_name):
                role = GestionDTEConnectionRole(
                    role=role_name,
                    source_type='MYSQL_CONFIG',
                    mysql_connection=self.connection,
                )

                with self.assertRaises(ValidationError) as raised:
                    role.full_clean()

                self.assertIn('database_name', raised.exception.message_dict)

    def test_configurable_mysql_roles_accept_suggested_and_custom_names(self):
        for role_name, database_name in (
            ('serverbasedte', 'gestiondte'),
            ('serverauditoriagestiondte', 'cliente01_dte'),
        ):
            with self.subTest(role=role_name):
                role = GestionDTEConnectionRole(
                    role=role_name,
                    source_type='MYSQL_CONFIG',
                    mysql_connection=self.connection,
                    database_name=database_name,
                )

                role.full_clean()

                self.assertEqual(role.database_name, database_name)

    def test_accounting_roles_reject_database_name(self):
        for role_name in ('servercontabilidad', 'serverauditoriacontabilidad'):
            with self.subTest(role=role_name):
                role = GestionDTEConnectionRole(
                    role=role_name,
                    source_type='MYSQL_CONFIG',
                    mysql_connection=self.connection,
                    database_name='gestiondte',
                )

                with self.assertRaises(ValidationError) as raised:
                    role.full_clean()

                self.assertIn('database_name', raised.exception.message_dict)

    def test_database_name_rejects_invalid_identifiers(self):
        for database_name in ('gestion-dte', 'gestion dte', 'gestion.dte', '`gestiondte`', 'gestiondte;', '1gestiondte', 'x' * 65):
            with self.subTest(database_name=database_name):
                role = GestionDTEConnectionRole(
                    role='serverbasedte',
                    source_type='MYSQL_CONFIG',
                    mysql_connection=self.connection,
                    database_name=database_name,
                )

                with self.assertRaises(ValidationError):
                    role.full_clean()

    def test_form_suggests_names_without_overwriting_custom_values(self):
        base_form = GestionDTEConnectionRoleForm(
            instance=GestionDTEConnectionRole(role='serverbasedte'),
            role='serverbasedte',
        )
        audit_form = GestionDTEConnectionRoleForm(
            instance=GestionDTEConnectionRole(role='serverauditoriagestiondte'),
            role='serverauditoriagestiondte',
        )
        custom_form = GestionDTEConnectionRoleForm(
            instance=GestionDTEConnectionRole(
                role='serverbasedte', database_name='cliente01_dte'
            ),
            role='serverbasedte',
        )

        self.assertEqual(base_form.initial['database_name'], 'gestiondte')
        self.assertEqual(audit_form.initial['database_name'], 'gestiondte_auditoria')
        self.assertEqual(custom_form.initial['database_name'], 'cliente01_dte')
        self.assertNotIn(
            'database_name',
            GestionDTEConnectionRoleForm(
                instance=GestionDTEConnectionRole(role='servercontabilidad'),
                role='servercontabilidad',
            ).fields,
        )

    def test_form_switching_to_django_clears_database_name(self):
        role = GestionDTEConnectionRole(
            role='serverbasedte',
            source_type='MYSQL_CONFIG',
            mysql_connection=self.connection,
            database_name='cliente01_dte',
        )
        role.save()
        form = GestionDTEConnectionRoleForm(
            data={'source_type': 'DJANGO', 'django_alias': 'default'},
            instance=role,
            role='serverbasedte',
        )

        self.assertTrue(form.is_valid(), form.errors)
        updated = form.save()

        self.assertIsNone(updated.database_name)

    @override_settings(DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}})
    def test_system_catalog_is_dynamic_and_classified(self):
        catalog = get_system_database_catalog()

        self.assertEqual([item['alias'] for item in catalog], ['default'])
        self.assertEqual(catalog[0]['classification'], 'SYSTEM')

    def test_mysql_resolution_does_not_return_password(self):
        GestionDTEConnectionRole.objects.create(
            role='servercontabilidad',
            source_type='MYSQL_CONFIG',
            mysql_connection=self.connection,
        )

        result = get_gestiondte_connection('servercontabilidad')

        self.assertNotIn('password', result)
        self.assertEqual(result['nombre_logico'], 'contabilidad')

    def test_configurable_mysql_role_without_database_name_is_invalid(self):
        GestionDTEConnectionRole.objects.create(
            role='serverbasedte',
            source_type='MYSQL_CONFIG',
            mysql_connection=self.connection,
        )

        status = get_gestiondte_connection_status()

        self.assertIn('serverbasedte', status['invalid_roles'])
        with self.assertRaises(GestionDTEConnectionSourceError):
            get_gestiondte_connection('serverbasedte')

    def test_missing_saved_alias_is_rejected(self):
        GestionDTEConnectionRole.objects.create(
            role='serverbasedte',
            source_type='DJANGO',
            django_alias='missing_system_alias',
        )

        with self.assertRaises(GestionDTEAliasUnavailableError):
            get_gestiondte_connection('serverbasedte')

    def test_model_rejects_inactive_mysql_connection(self):
        self.connection.is_active = False
        role = GestionDTEConnectionRole(
            role='serverauditoriagestiondte',
            source_type='MYSQL_CONFIG',
            mysql_connection=self.connection,
        )

        with self.assertRaises(ValidationError):
            role.full_clean()

    def test_status_reports_zero_to_four_configured_roles(self):
        roles = [role for role, _label in GestionDTEConnectionRole.ROLE_CHOICES]

        for configured_count in range(5):
            with self.subTest(configured_count=configured_count):
                GestionDTEConnectionRole.objects.all().delete()
                for role in roles[:configured_count]:
                    GestionDTEConnectionRole.objects.create(
                        role=role,
                        source_type='DJANGO',
                        django_alias='default',
                    )

                status = get_gestiondte_connection_status()

                self.assertEqual(len(status['roles']), 4)
                self.assertEqual(len(status['missing_roles']), 4 - configured_count)
                self.assertFalse(status['invalid_roles'])
                self.assertEqual(status['configured'], configured_count == 4)

    def test_status_detects_invalid_alias_and_inactive_mysql(self):
        GestionDTEConnectionRole.objects.create(
            role='serverbasedte',
            source_type='DJANGO',
            django_alias='missing_system_alias',
        )
        self.connection.is_active = False
        self.connection.save(update_fields=['is_active'])
        GestionDTEConnectionRole.objects.create(
            role='servercontabilidad',
            source_type='MYSQL_CONFIG',
            mysql_connection=self.connection,
        )

        status = get_gestiondte_connection_status()

        self.assertEqual(
            set(status['invalid_roles']),
            {'serverbasedte', 'servercontabilidad'},
        )
        self.assertFalse(status['configured'])

    def test_status_allows_one_source_to_be_shared_by_roles(self):
        for role in ('servercontabilidad', 'serverauditoriacontabilidad'):
            GestionDTEConnectionRole.objects.create(
                role=role,
                source_type='MYSQL_CONFIG',
                mysql_connection=self.connection,
            )

        status = get_gestiondte_connection_status()

        configured = {
            item['role'] for item in status['roles'] if item['status'] == 'configured'
        }
        self.assertEqual(
            configured,
            {'servercontabilidad', 'serverauditoriacontabilidad'},
        )

    @patch(
        'gestiondte.services.connection_roles.get_system_database_catalog',
        return_value=({'alias': 'default', 'vendor': 'sqlite', 'classification': 'SYSTEM'},),
    )
    def test_status_rejects_legacy_and_unknown_django_aliases(self, _catalog):
        for role, alias in (
            ('serverbasedte', 'legacy'),
            ('serverauditoriagestiondte', 'unknown'),
        ):
            GestionDTEConnectionRole.objects.create(
                role=role,
                source_type='DJANGO',
                django_alias=alias,
            )

        status = get_gestiondte_connection_status()

        self.assertEqual(
            set(status['invalid_roles']),
            {'serverbasedte', 'serverauditoriagestiondte'},
        )

    def test_status_allows_multiple_roles_to_share_django_alias(self):
        for role in ('serverbasedte', 'serverauditoriagestiondte'):
            GestionDTEConnectionRole.objects.create(
                role=role,
                source_type='DJANGO',
                django_alias='default',
            )

        status = get_gestiondte_connection_status()

        configured = {
            item['role'] for item in status['roles'] if item['status'] == 'configured'
        }
        self.assertEqual(
            configured,
            {'serverbasedte', 'serverauditoriagestiondte'},
        )

    @patch('pymysql.connect')
    def test_status_does_not_open_physical_connections(self, connect):
        status = get_gestiondte_connection_status()

        self.assertEqual(len(status['roles']), 4)
        connect.assert_not_called()


class GestionDTEConnectionRoleStaticTests(SimpleTestCase):
    @patch('gestiondte.services.connection_roles.get_database_classification')
    @override_settings(
        DATABASES={
            'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'},
            'legacy': {'ENGINE': 'django.db.backends.mysql', 'NAME': 'legacy'},
        }
    )
    def test_system_catalog_excludes_non_system_aliases(self, classification):
        classification.side_effect = lambda alias: 'SYSTEM' if alias == 'default' else 'LEGACY'

        catalog = get_system_database_catalog()

        self.assertEqual([item['alias'] for item in catalog], ['default'])