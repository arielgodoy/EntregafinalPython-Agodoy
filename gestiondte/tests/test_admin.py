from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from access_control.models import AccessRequest, Empresa
from acounts.models import UserEmailToken
from api.models import Contratopublicidad, LmovimientosDetalle19
from chat.models import MensajeLeido
from gestiondte.models import (
    CertificadoSII,
    CesionRPETC,
    CesionRPETCHistorial,
    EstadoContableCesion,
    LecturaAutomaticaConfig,
    LecturaAutomaticaEjecucion,
    TareaCesionRPETC,
    TareaRPETC,
)
from settings.models import SettingsMySQLConnection, UserPreferences


class AdminRegistrationTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get('/admin/')
        self.request.user = User(is_staff=True, is_superuser=True)
        self.admin_user = User.objects.create_superuser('admin-check', 'admin-check@example.com', 'pass')
        self.client.force_login(self.admin_user)

    def admin_for(self, model):
        return admin.site._registry[model]

    def test_all_missing_sqlite_models_are_registered(self):
        missing_models = (
            AccessRequest,
            MensajeLeido,
            CertificadoSII,
            TareaRPETC,
            LecturaAutomaticaConfig,
            LecturaAutomaticaEjecucion,
            CesionRPETC,
            EstadoContableCesion,
            TareaCesionRPETC,
            CesionRPETCHistorial,
            SettingsMySQLConnection,
        )
        for model in missing_models:
            with self.subTest(model=model.__name__):
                self.assertIn(model, admin.site._registry)

    def test_read_only_models_disallow_add_change_and_delete(self):
        read_only_models = (
            AccessRequest,
            MensajeLeido,
            CertificadoSII,
            TareaRPETC,
            LecturaAutomaticaConfig,
            LecturaAutomaticaEjecucion,
            CesionRPETC,
            EstadoContableCesion,
            TareaCesionRPETC,
            CesionRPETCHistorial,
            SettingsMySQLConnection,
        )
        for model in read_only_models:
            model_admin = self.admin_for(model)
            with self.subTest(model=model.__name__):
                self.assertFalse(model_admin.has_add_permission(self.request))
                self.assertFalse(model_admin.has_change_permission(self.request))
                self.assertFalse(model_admin.has_delete_permission(self.request))

    def test_sensitive_certificate_fields_are_not_listed(self):
        model_admin = self.admin_for(CertificadoSII)
        self.assertNotIn('password_encrypted', model_admin.list_display)
        self.assertNotIn('password_encrypted', model_admin.search_fields)
        self.assertNotIn('archivo', model_admin.list_display)
        self.assertIn('password_encrypted', model_admin.exclude)
        self.assertIn('archivo', model_admin.exclude)

    def test_mysql_password_is_not_exposed(self):
        model_admin = self.admin_for(SettingsMySQLConnection)
        self.assertNotIn('password', model_admin.list_display)
        self.assertNotIn('password', model_admin.search_fields)
        self.assertIn('password', model_admin.exclude)

    def test_existing_user_preferences_admin_does_not_show_email_passwords(self):
        model_admin = self.admin_for(UserPreferences)
        fields = {
            field
            for fieldset in model_admin.fieldsets
            for field in fieldset[1].get('fields', ())
        }
        self.assertNotIn('email_password', fields)
        self.assertNotIn('smtp_password', fields)

    def test_api_unmanaged_models_remain_unmanaged_and_untouched(self):
        self.assertFalse(Contratopublicidad._meta.managed)
        self.assertFalse(LmovimientosDetalle19._meta.managed)
        self.assertIn(Contratopublicidad, admin.site._registry)
        self.assertIn(LmovimientosDetalle19, admin.site._registry)

    def test_access_request_admin_does_not_allow_manual_creation(self):
        model_admin = self.admin_for(AccessRequest)
        self.assertFalse(model_admin.has_add_permission(self.request))
        self.assertFalse(model_admin.has_change_permission(self.request))
        self.assertFalse(model_admin.has_delete_permission(self.request))

    def test_message_read_admin_is_read_only(self):
        model_admin = self.admin_for(MensajeLeido)
        self.assertFalse(model_admin.has_add_permission(self.request))
        self.assertFalse(model_admin.has_change_permission(self.request))
        self.assertFalse(model_admin.has_delete_permission(self.request))

    def test_all_new_admin_changelists_load_for_superuser(self):
        models = (
            AccessRequest,
            MensajeLeido,
            CertificadoSII,
            TareaRPETC,
            LecturaAutomaticaConfig,
            LecturaAutomaticaEjecucion,
            CesionRPETC,
            EstadoContableCesion,
            TareaCesionRPETC,
            CesionRPETCHistorial,
            SettingsMySQLConnection,
        )
        for model in models:
            with self.subTest(model=model.__name__):
                url = f'/admin/{model._meta.app_label}/{model._meta.model_name}/'
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_new_read_only_admins_do_not_offer_add_urls(self):
        models = (
            AccessRequest,
            MensajeLeido,
            CertificadoSII,
            TareaRPETC,
            LecturaAutomaticaConfig,
            LecturaAutomaticaEjecucion,
            CesionRPETC,
            EstadoContableCesion,
            TareaCesionRPETC,
            CesionRPETCHistorial,
            SettingsMySQLConnection,
        )
        for model in models:
            with self.subTest(model=model.__name__):
                url = f'/admin/{model._meta.app_label}/{model._meta.model_name}/add/'
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_admin_changelists_do_not_render_sensitive_values(self):
        user = self.admin_user
        empresa = Empresa.objects.create(codigo='99', descripcion='Admin test')
        CertificadoSII.objects.create(
            empresa_codigo='99',
            archivo='gestiondte/certificados/99/admin-test.pfx',
            password_encrypted=b'CERTIFICATE_SECRET_SENTINEL',
        )
        SettingsMySQLConnection.objects.create(
            empresa=empresa,
            nombre_logico='admin-test',
            host='mysql.example.invalid',
            user='admin-test-user',
            password='MYSQL_PASSWORD_SENTINEL',
            db_name='admin_test',
        )
        UserPreferences.objects.update_or_create(
            user=user,
            defaults={
                'email_password': 'EMAIL_PASSWORD_SENTINEL',
                'smtp_password': 'SMTP_PASSWORD_SENTINEL',
            },
        )
        UserEmailToken.objects.create(
            user=user,
            purpose='ACTIVATE',
            token_hash='TOKEN_HASH_SENTINEL',
            expires_at='2030-01-01T00:00:00Z',
        )

        urls_and_secrets = (
            ('/admin/gestiondte/certificadosii/', 'CERTIFICATE_SECRET_SENTINEL'),
            ('/admin/settings/settingsmysqlconnection/', 'MYSQL_PASSWORD_SENTINEL'),
            ('/admin/settings/userpreferences/', 'EMAIL_PASSWORD_SENTINEL'),
            ('/admin/settings/userpreferences/', 'SMTP_PASSWORD_SENTINEL'),
            ('/admin/acounts/useremailtoken/', 'TOKEN_HASH_SENTINEL'),
        )
        for url, secret in urls_and_secrets:
            with self.subTest(url=url, secret=secret):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, secret)
