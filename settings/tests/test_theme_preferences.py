import json
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from settings.context_processors import user_preferences_to_localstorage
from settings.models import ThemePreferences


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

    def test_data_preloader_se_guarda_por_usuario_y_empresa_activa(self):
        response = self.client.post(
            reverse('guardar_preferencias'),
            data=json.dumps({'data-preloader': 'enable'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ThemePreferences.objects.get(user=self.user, empresa=self.empresa_a).data_preloader,
            'enable',
        )

    def test_dos_empresas_mantienen_preloader_independiente(self):
        ThemePreferences.objects.create(user=self.user, empresa=self.empresa_a, data_preloader='enable')
        ThemePreferences.objects.create(user=self.user, empresa=self.empresa_b, data_preloader='disable')

        self._set_active_empresa(self.empresa_b)
        request = type('Request', (), {'user': self.user, 'session': self.client.session})()
        context = user_preferences_to_localstorage(request)

        self.assertEqual(context['theme_preferences']['data-preloader'], 'disable')

        self._set_active_empresa(self.empresa_a)
        request.session = self.client.session
        context = user_preferences_to_localstorage(request)
        self.assertEqual(context['theme_preferences']['data-preloader'], 'enable')

    def test_dashboard_renderiza_preloader_de_empresa_activa(self):
        ThemePreferences.objects.create(user=self.user, empresa=self.empresa_a, data_preloader='enable')

        response = self.client.get(reverse('dashboard:dashboard_general'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"data-preloader": "enable"')

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

        self.assertIn('if (attr === "data-preloader")', theme_config)
        self.assertIn('const serverValue = serverPrefs[attr] || "disable"', theme_config)
        self.assertIn('localStorage.removeItem(attr)', theme_config)
        self.assertEqual(customizer.count('id="status"'), 1)
        self.assertIn('id="preloader-preview-status"', customizer)

