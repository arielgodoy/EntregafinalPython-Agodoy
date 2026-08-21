import json
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from settings.context_processors import user_preferences_to_localstorage
from settings.models import ThemePreferences, UserPreferences


class ThemePreferencesPreloaderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='theme-user', password='pass1234')
        self.empresa_a = Empresa.objects.create(codigo='01', descripcion='Empresa A')
        self.empresa_b = Empresa.objects.create(codigo='02', descripcion='Empresa B')
        self.vista = Vista.objects.create(nombre='Settings - Theme preference')
        self._set_active_empresa(self.empresa_a)
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa_a,
            vista=self.vista,
            modificar=True,
        )
        self.client.force_login(self.user)

    def _set_active_empresa(self, empresa):
        session = self.client.session
        session['empresa_id'] = empresa.id
        session['empresa_codigo'] = empresa.codigo
        session['empresa_nombre'] = empresa.descripcion
        session.save()

    def test_preferencias_visuales_se_guardan_por_usuario(self):
        response = self.client.post(
            reverse('guardar_preferencias'),
            data=json.dumps({'data-bs-theme': 'dark', 'data-preloader': 'enable'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            UserPreferences.objects.get(user=self.user).data_bs_theme,
            'dark',
        )
        self.assertEqual(
            UserPreferences.objects.get(user=self.user).data_preloader,
            'enable',
        )
        self.assertFalse(ThemePreferences.objects.filter(user=self.user).exists())

    def test_cambio_de_empresa_mantiene_preferencias_visuales(self):
        UserPreferences.objects.create(user=self.user, data_bs_theme='dark', data_preloader='enable')
        request = type('Request', (), {'user': self.user, 'session': self.client.session})()
        context = user_preferences_to_localstorage(request)

        self.assertEqual(context['theme_preferences']['data-bs-theme'], 'dark')
        self.assertEqual(context['theme_preferences']['data-preloader'], 'enable')

        self._set_active_empresa(self.empresa_b)
        request.session = self.client.session
        context = user_preferences_to_localstorage(request)
        self.assertEqual(context['theme_preferences']['data-bs-theme'], 'dark')
        self.assertEqual(context['theme_preferences']['data-preloader'], 'enable')

    def test_dashboard_renderiza_preferencias_del_usuario(self):
        UserPreferences.objects.create(user=self.user, data_bs_theme='dark', data_preloader='enable')

        response = self.client.get(reverse('dashboard:dashboard_general'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"data-bs-theme": "dark"')
        self.assertContains(response, '"data-preloader": "enable"')

    def test_defaults_funcionan_sin_user_preferences(self):
        context = user_preferences_to_localstorage(
            type('Request', (), {'user': self.user, 'session': self.client.session})()
        )

        self.assertEqual(context['theme_preferences']['data-bs-theme'], 'light')
        self.assertEqual(context['theme_preferences']['data-preloader'], 'disable')

    def test_otro_usuario_no_hereda_preferencia_visual(self):
        UserPreferences.objects.create(user=self.user, data_bs_theme='dark')
        other_user = User.objects.create_user(username='other-theme-user', password='pass1234')
        request = type('Request', (), {'user': other_user, 'session': self.client.session})()

        context = user_preferences_to_localstorage(request)

        self.assertEqual(context['theme_preferences']['data-bs-theme'], 'light')

    def test_endpoint_rechaza_usuario_anonimo(self):
        self.client.logout()

        response = self.client.post(
            reverse('guardar_preferencias'),
            data=json.dumps({'data-preloader': 'enable'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 302)

    def test_frontend_prioriza_servidor_y_no_reutiliza_status_del_preview(self):
        theme_config = (
            Path(__file__).resolve().parents[2] / 'static/js/theme_config.js'
        ).read_text(encoding='utf-8')
        customizer = (
            Path(__file__).resolve().parents[2] / 'templates/partials/customizer.html'
        ).read_text(encoding='utf-8')

        self.assertIn('const serverValue = serverPrefs[attr] || defaultLayout[attr]', theme_config)
        self.assertIn('localStorage.removeItem(attr)', theme_config)
        self.assertIn('sessionStorage.removeItem(attr)', theme_config)
        self.assertNotIn('localStorage.getItem(attr)', theme_config)
        self.assertNotIn('localStorage.getItem(attr) || sessionStorage.getItem(attr)', theme_config)
        self.assertNotIn('localStorage.setItem(attr, serverValue)', theme_config)
        self.assertNotIn('localStorage.setItem(attr, value)', theme_config)
        self.assertIn('savePreferences();', theme_config)
        self.assertNotIn('localStorage.getItem(attr)', Path(__file__).resolve().parents[2].joinpath('static/js/layout.js').read_text(encoding='utf-8'))
        self.assertEqual(customizer.count('id="status"'), 1)
        self.assertIn('id="preloader-preview-status"', customizer)

