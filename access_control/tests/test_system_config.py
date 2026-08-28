from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import gettext as _

from acounts.models import SystemConfig
from access_control.forms import SystemConfigForm
from access_control.models import Empresa, Permiso, Vista


class SystemConfigFormTests(TestCase):
    def test_public_base_url_required(self):
        form = SystemConfigForm(data={
            'public_base_url': '',
            'default_from_email': '',
            'default_from_name': '',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('public_base_url', form.errors)


class SystemConfigModelTests(TestCase):
    databases = {'default', 'system_test'}

    def _config(self, is_active=False):
        return SystemConfig.objects.create(
            is_active=is_active,
            public_base_url='https://example.test',
            default_from_email='system@example.test',
            default_from_name='System',
        )

    def test_multiple_inactive_configs_are_allowed(self):
        self._config()
        self._config()

        self.assertEqual(SystemConfig.objects.filter(is_active=False).count(), 2)

    def test_saving_active_config_deactivates_previous_config(self):
        previous = self._config(is_active=True)
        current = self._config(is_active=True)

        previous.refresh_from_db()
        self.assertFalse(previous.is_active)
        self.assertIsNone(previous.active_slot)
        self.assertTrue(current.is_active)
        self.assertEqual(current.active_slot, 'SYSTEM_CONFIG_ACTIVE')
        self.assertEqual(SystemConfig.objects.filter(is_active=True).count(), 1)

    def test_active_slot_replaces_conditional_constraint(self):
        self.assertEqual(SystemConfig._meta.constraints, [])
        self.assertTrue(SystemConfig._meta.get_field('active_slot').unique)

    def test_update_fields_keeps_active_slot_consistent(self):
        config = self._config()

        config.is_active = True
        config.save(update_fields=['is_active'])
        config.refresh_from_db()
        self.assertTrue(config.is_active)
        self.assertEqual(config.active_slot, 'SYSTEM_CONFIG_ACTIVE')

        config.is_active = False
        config.save(update_fields=['is_active'])
        config.refresh_from_db()
        self.assertFalse(config.is_active)
        self.assertIsNone(config.active_slot)

    def test_save_uses_loaded_database_when_using_is_omitted(self):
        config = SystemConfig.objects.using('system_test').create(
            is_active=False,
            public_base_url='https://example.test',
            default_from_email='system@example.test',
            default_from_name='System',
        )
        config.is_active = True
        config.save()
        config.refresh_from_db()

        self.assertTrue(config.is_active)
        self.assertEqual(config.active_slot, 'SYSTEM_CONFIG_ACTIVE')
        self.assertFalse(SystemConfig.objects.filter(pk=config.pk).exists())


class SystemConfigViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='testpass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Test Empresa')
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def test_missing_vista_returns_400(self):
        response = self.client.get(reverse('access_control:system_config'))
        # La vista ahora se crea automáticamente; la comprobación de permisos devuelve 403 si no hay permiso.
        self.assertEqual(response.status_code, 403)

    def test_view_ok_with_permission(self):
        vista = Vista.objects.create(nombre='Settings - Configuración del Sistema')
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            ingresar=False,
            crear=False,
            modificar=True,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )
        response = self.client.get(reverse('access_control:system_config'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(SystemConfig.objects.filter(is_active=True).exists())
