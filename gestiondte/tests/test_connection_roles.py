from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from gestiondte.forms import GestionDTEConnectionRoleForm
from gestiondte.models import GestionDTEConnectionRole
from gestiondte.services.connection_roles import (
    GestionDTEAliasUnavailableError,
    get_gestiondte_connection,
    get_system_database_catalog,
)
from settings.models import SettingsMySQLConnection


class GestionDTEConnectionRoleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='connection-role-user', password='pass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa prueba')
        self.vista = Vista.objects.create(
            nombre='Configuración - Conexiones Gestión DTE',
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