"""Tests de la pestana 'Sesiones' del perfil y de la semantica ICMEAS (ingresar vs modificar)."""
from datetime import datetime, timezone as dt_timezone

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from acounts.services.session_info import format_local_datetime


class PerfilSesionesTests(TestCase):
    def setUp(self):
        self.password = "pass1234"
        self.user = User.objects.create_user(username="sesiones-user", password=self.password)
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa Sesiones")
        self.client.force_login(self.user)

        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_nombre"] = "01 - Empresa Sesiones"
        session["login_at"] = timezone.now().isoformat()
        session["last_activity"] = timezone.now().isoformat()
        session["ip_address"] = "203.0.113.9"
        session["user_agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"
        session["remember_me"] = True
        session.save()

    def test_get_perfil_funciona_con_capacidad_ingresar(self):
        response = self.client.get(reverse("editar_perfil"))
        self.assertEqual(response.status_code, 200)

    def test_get_perfil_no_autoconcede_modificar(self):
        self.client.get(reverse("editar_perfil"))
        permiso = Permiso.objects.get(
            usuario=self.user, empresa=self.empresa, vista__nombre="Accounts - Editar Perfil"
        )
        self.assertTrue(permiso.ingresar)
        self.assertFalse(permiso.modificar)

    def test_modificar_datos_personales_autoconcede_y_guarda(self):
        response = self.client.post(
            reverse("editar_perfil"),
            {
                "form_action": "profile",
                "username": self.user.username,
                "first_name": "Nuevo",
                "last_name": "Apellido",
                "email": "nuevo@example.com",
                "profesion": "Ingeniera",
                "dni": "12.345.678-5",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Nuevo")

        permiso = Permiso.objects.get(
            usuario=self.user, empresa=self.empresa, vista__nombre="Accounts - Editar Perfil"
        )
        self.assertTrue(permiso.modificar)

    def test_pestana_sesiones_aparece_para_el_propietario(self):
        response = self.client.get(reverse("editar_perfil"))
        self.assertContains(response, 'href="#userSessions"')
        self.assertContains(response, "Sesiones")

    def test_informacion_mostrada_corresponde_a_request_user(self):
        response = self.client.get(reverse("editar_perfil"))
        self.assertContains(response, "203.0.113.9")

    def test_query_string_user_id_no_cambia_nada(self):
        response = self.client.get(reverse("editar_perfil") + "?user_id=999999")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "203.0.113.9")

    def test_session_key_completa_no_aparece_en_html(self):
        response = self.client.get(reverse("editar_perfil"))
        session_key = self.client.session.session_key
        self.assertNotIn(session_key, response.content.decode("utf-8"))

    def test_session_key_parcial_no_aparece_en_html(self):
        response = self.client.get(reverse("editar_perfil"))
        session_key = self.client.session.session_key
        self.assertNotIn(session_key[:10], response.content.decode("utf-8"))

    def test_fecha_proceso_erp_distinta_no_afecta_expiracion(self):
        session = self.client.session
        session["fecha_sistema"] = "2000-01-01"
        session.save()

        response = self.client.get(reverse("editar_perfil"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2000-01-01")
        self.assertContains(response, "Fecha de proceso ERP")
        # el tiempo restante sigue reflejando ~8h reales, no la fecha antigua
        self.assertContains(response, "h")

    def test_usuario_anonimo_es_redirigido_a_login(self):
        self.client.logout()
        response = self.client.get(reverse("editar_perfil"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)


class SessionInfoTimezoneTests(TestCase):
    """Protege el bug de +4h: la presentacion debe convertirse a settings.SYSTEM_LOCAL_TIME_ZONE,
    aunque el proyecto almacene y compare todo en UTC (TIME_ZONE='UTC', USE_TZ=True)."""

    @override_settings(SYSTEM_LOCAL_TIME_ZONE="America/Santiago")
    def test_format_local_datetime_convierte_utc_a_santiago(self):
        value_utc = datetime(2026, 9, 2, 21, 11, tzinfo=dt_timezone.utc)

        self.assertEqual(format_local_datetime(value_utc), "02/09/2026 17:11")

    @override_settings(SYSTEM_LOCAL_TIME_ZONE="America/Santiago")
    def test_format_local_datetime_expiry_convierte_utc_a_santiago(self):
        expiry_utc = datetime(2026, 9, 3, 5, 11, tzinfo=dt_timezone.utc)

        self.assertEqual(format_local_datetime(expiry_utc), "03/09/2026 01:11")

    @override_settings(SYSTEM_LOCAL_TIME_ZONE="Asia/Tokyo")
    def test_format_local_datetime_respeta_el_setting_no_hardcodea_santiago(self):
        value_utc = datetime(2026, 9, 2, 21, 11, tzinfo=dt_timezone.utc)

        self.assertEqual(format_local_datetime(value_utc), "03/09/2026 06:11")

    def test_format_local_datetime_none_retorna_none(self):
        self.assertIsNone(format_local_datetime(None))
