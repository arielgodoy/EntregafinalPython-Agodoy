from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


class DatabaseManagerViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='db-view-user', password='test-pass')
        empresa = Empresa.objects.create(codigo='02', descripcion='Empresa view')
        session = self.client.session
        session['empresa_id'] = empresa.id
        session.save()
        self.client.force_login(self.user)
        self.dashboard_vista = Vista.objects.create(nombre='Gestión de Bases - Dashboard')
        Permiso.objects.create(usuario=self.user, empresa=empresa, vista=self.dashboard_vista, ingresar=True)
        vista = Vista.objects.create(nombre='Gestión de Bases - Comparar')
        Permiso.objects.create(usuario=self.user, empresa=empresa, vista=vista, ingresar=True)

    def comparison_result(self, **overrides):
        result = {
            'source_alias': 'default',
            'target_alias': 'system_test',
            'source_classification': 'SYSTEM',
            'target_classification': 'SYSTEM',
            'source_vendor': 'sqlite',
            'target_vendor': 'mysql',
            'migration_sets_equal': True,
            'source_migration_count': 1,
            'target_migration_count': 1,
            'migrations_only_source': [],
            'migrations_only_target': [],
            'managed_tables_expected': ['auth_user'],
            'missing_in_source': [],
            'missing_in_target': [],
            'table_counts': {'auth_user': {'source': 2, 'target': 3, 'difference': 1}},
            'pk_max_values': {'auth_user': {'source': 2, 'target': 3}},
            'managed_false_tables_present': [],
            'warnings': ['table row counts differ'],
            'blocking_errors': [],
            'status': 'COMPATIBLE',
        }
        result.update(overrides)
        return result

    def test_reverse_names_are_registered(self):
        self.assertEqual(reverse('database_manager:dashboard'), '/database-manager/')
        self.assertEqual(reverse('database_manager:compare'), '/database-manager/compare/')

    def test_dashboard_renders_authorized_system_ui(self):
        response = self.client.get(reverse('database_manager:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'database_manager/dashboard.html')
        self.assertContains(response, 'GLOBAL DEL SISTEMA')
        self.assertContains(response, 'Próximamente')

    @patch('database_manager.views.compare_databases')
    def test_compare_delegates_to_service_and_exposes_metadata_only(self, compare):
        compare.return_value.to_dict.return_value = self.comparison_result()

        response = self.client.get(
            reverse('database_manager:compare'),
            {'source_alias': 'default', 'target_alias': 'system_test'},
        )

        self.assertEqual(response.status_code, 200)
        compare.assert_called_once_with('default', 'system_test')
        self.assertNotContains(response, 'PASSWORD')
        self.assertNotContains(response, 'token_hash')
        self.assertContains(response, 'COMPATIBLE')
        self.assertContains(response, 'table row counts differ')
        self.assertContains(response, 'Informativo')
        self.assertContains(response, 'Conteos distintos</p><h5 class="mb-1">1</h5>', html=False)

    @patch('database_manager.views.compare_databases')
    def test_compare_renders_blocking_errors_as_critical_status(self, compare):
        compare.return_value.to_dict.return_value = self.comparison_result(
            blocking_errors=['migration sets are different'],
            status='BLOCKED',
        )

        response = self.client.get(
            reverse('database_manager:compare'),
            {'source_alias': 'default', 'target_alias': 'system_test'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'BLOCKED')
        self.assertContains(response, 'migration sets are different')

    def test_compare_form_excludes_legacy_and_unknown_aliases(self):
        response = self.client.get(reverse('database_manager:compare'))
        form = response.context['form']
        values = [value for value, _label in form.fields['source_alias'].choices]

        self.assertNotIn('dinamica', values)
        self.assertNotIn('unknown', values)

    @patch('database_manager.views.compare_databases')
    def test_compare_rejects_legacy_and_unknown_post_targets(self, compare):
        for target_alias in ('dinamica', 'alias_unknown'):
            response = self.client.post(
                reverse('database_manager:compare'),
                {'source_alias': 'default', 'target_alias': target_alias},
            )

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)

        compare.assert_not_called()
