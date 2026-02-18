from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urljoin

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from acounts.models import SystemConfig
from access_control.models import AccessRequest, Empresa, Permiso, Vista
from notificaciones.models import Notification
from settings.models import UserPreferences


class TestAccessRequest403(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="requester", password="pass123", email="user@example.com")
        self.staff = User.objects.create_user(username="staff", password="pass123", email="staff@example.com", is_staff=True)
        self.empresa = Empresa.objects.create(codigo="99", descripcion="Empresa Test")
        self.vista = Vista.objects.create(nombre="Control de Acceso - Maestro Usuarios")
        
        # Crear Vistas para solicitar_acceso y grant_access_request (para decoradores @verificar_permiso)
        self.vista_solicitar_acceso = Vista.objects.create(nombre="Control de Acceso - Solicitar Acceso")
        # El nombre usado para la vista de otorgar acceso en el código es la clave interna
        # 'access_control.grant_access_request' (se crea en la vista si no existe).
        self.vista_otorgar_acceso = Vista.objects.create(nombre="access_control.grant_access_request")
        
        # Dar permisos al usuario para las nuevas vistas
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_solicitar_acceso,
            ingresar=True,
            crear=True,
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_otorgar_acceso,
            ingresar=True,
            autorizar=True,
        )
        
        # Permiso existente para pruebas de acceso denegado
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=False,
        )

    def _login_with_empresa(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session["empresa_nombre"] = f"{self.empresa.codigo} - {self.empresa.descripcion}"
        session.save()

    def _set_user_preferences(self, user, **defaults):
        prefs, _ = UserPreferences.objects.update_or_create(user=user, defaults=defaults)
        return prefs

    def test_403_includes_modal_and_hidden_fields(self):
        self._login_with_empresa(self.user)
        response = self.client.get(reverse("access_control:usuarios_lista"))
        self.assertEqual(response.status_code, 403)
        content = response.content.decode("utf-8")
        self.assertIn("accessRequestModal", content)
        self.assertIn("name=\"vista_nombre\"", content)
        self.assertIn("name=\"empresa_id\"", content)
        self.assertIn("access.request.button", content)

    def test_post_creates_access_request_and_notifications_and_dedupe(self):
        self._login_with_empresa(self.user)
        url = reverse("access_control:solicitar_acceso")
        payload = {
            "vista_nombre": self.vista.nombre,
            "empresa_id": str(self.empresa.id),
            "motivo": "Necesito acceso para trabajar en esta vista",
        }
        response = self.client.post(url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("created"))
        self.assertFalse(data.get("duplicate"))
        self.assertEqual(AccessRequest.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(tipo=Notification.Tipo.SYSTEM).count(), 1)
        access_request = AccessRequest.objects.get()
        grant_path = reverse("access_control:grant_access_request", args=[access_request.id])
        base_url = response.wsgi_request.build_absolute_uri("/")
        grant_url = urljoin(base_url.rstrip("/") + "/", grant_path.lstrip("/"))
        notification = Notification.objects.first()
        self.assertEqual(notification.url, grant_url)
        self.assertNotIn("http", notification.cuerpo)
        self.assertNotIn("Otorgar acceso", notification.cuerpo)

        response_dup = self.client.post(url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response_dup.status_code, 200)
        data_dup = response_dup.json()
        self.assertTrue(data_dup.get("ok"))
        self.assertTrue(data_dup.get("duplicate"))
        self.assertEqual(AccessRequest.objects.count(), 1)

    def test_post_without_email_does_not_send_mail(self):
        self.user.email = ""
        self.user.save(update_fields=["email"])
        self._set_user_preferences(self.user, email_enabled=False)
        self._login_with_empresa(self.user)
        url = reverse("access_control:solicitar_acceso")
        payload = {
            "vista_nombre": self.vista.nombre,
            "empresa_id": str(self.empresa.id),
            "motivo": "Necesito acceso para revisar configuraciones",
            "enviar_email": "on",
        }
        with patch("access_control.services.access_requests.send_email_message") as send_mail_mock:
            response = self.client.post(url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("created"))
        self.assertFalse(data.get("email_attempted"))
        self.assertFalse(data.get("email_sent"))
        send_mail_mock.assert_not_called()
        self.assertEqual(AccessRequest.objects.count(), 1)
        access_request = AccessRequest.objects.get()
        self.assertEqual(access_request.email_status, AccessRequest.EmailStatus.SKIPPED)
        self.assertEqual(access_request.email_error, "user_email_disabled")

    def test_access_request_audit_fields_saved_when_email_sent(self):
        self._set_user_preferences(
            self.user,
            email_enabled=True,
            smtp_host="smtp.local",
            smtp_port=587,
            smtp_username="requester@example.com",
            smtp_password="secret",
            smtp_encryption="STARTTLS",
        )
        staff_two = User.objects.create_user(
            username="staff2",
            password="pass123",
            email="staff2@example.com",
            is_staff=True,
        )
        self._login_with_empresa(self.user)
        url = reverse("access_control:solicitar_acceso")
        payload = {
            "vista_nombre": self.vista.nombre,
            "empresa_id": str(self.empresa.id),
            "motivo": "Necesito acceso para operar",
            "enviar_email": "on",
        }
        with patch("access_control.services.access_requests.send_email_message") as send_mail_mock:
            response = self.client.post(url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        send_mail_mock.assert_called_once()
        access_request = AccessRequest.objects.get()
        self.assertTrue(access_request.email_attempted)
        self.assertTrue(access_request.email_sent)
        self.assertIsNotNone(access_request.emailed_at)
        self.assertIsNotNone(access_request.email_sent_at)
        self.assertEqual(access_request.email_status, AccessRequest.EmailStatus.SENT)
        self.assertEqual(access_request.email_from, "requester@example.com")
        self.assertIn(self.staff.email, access_request.email_recipients)
        self.assertIn(staff_two.email, access_request.email_recipients)
        self.assertEqual(access_request.notified_staff_count, 2)
        self.assertTrue(access_request.staff_recipient_ids)

    def test_access_request_email_body_includes_grant_url(self):
        SystemConfig.objects.create(
            is_active=True,
            public_base_url="http://testserver",
            default_from_email="noreply@example.com",
            default_from_name="Sistema",
        )
        self._set_user_preferences(
            self.user,
            email_enabled=True,
            smtp_host="smtp.local",
            smtp_port=587,
            smtp_username="requester@example.com",
            smtp_password="secret",
            smtp_encryption="STARTTLS",
        )
        self._login_with_empresa(self.user)
        url = reverse("access_control:solicitar_acceso")
        payload = {
            "vista_nombre": self.vista.nombre,
            "empresa_id": str(self.empresa.id),
            "motivo": "Necesito acceso para revisar permisos",
            "enviar_email": "on",
        }
        with patch("access_control.services.access_requests.EmailMultiAlternatives") as email_mock:
            with patch("access_control.services.access_requests.send_email_message") as send_mail_mock:
                email_instance = email_mock.return_value
                email_instance.message.return_value = object()
                response = self.client.post(url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        access_request = AccessRequest.objects.get()
        grant_url = f"http://testserver/access-control/solicitudes/{access_request.id}/otorgar/"
        self.assertTrue(email_mock.called)
        self.assertTrue(send_mail_mock.called)
        call_args = email_mock.call_args
        if call_args.kwargs:
            body = call_args.kwargs.get("body", "")
        else:
            args = call_args.args
            body = args[1] if len(args) > 1 else ""
        self.assertIn(grant_url, body)

    def test_access_request_audit_fields_saved_when_no_staff_emails(self):
        self.staff.email = ""
        self.staff.save(update_fields=["email"])
        self._set_user_preferences(
            self.user,
            email_enabled=True,
            smtp_host="smtp.local",
            smtp_port=587,
            smtp_username="requester@example.com",
            smtp_password="secret",
            smtp_encryption="STARTTLS",
        )
        self._login_with_empresa(self.user)
        url = reverse("access_control:solicitar_acceso")
        payload = {
            "vista_nombre": self.vista.nombre,
            "empresa_id": str(self.empresa.id),
            "motivo": "Necesito acceso para tareas de auditoria",
            "enviar_email": "on",
        }
        response = self.client.post(url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        access_request = AccessRequest.objects.get()
        self.assertFalse(access_request.email_attempted)
        self.assertFalse(access_request.email_sent)
        self.assertEqual(access_request.email_status, AccessRequest.EmailStatus.SKIPPED)
        self.assertEqual(access_request.email_error, "no_staff_recipients")
        self.assertEqual(access_request.notified_staff_count, 1)
        self.assertEqual(access_request.email_recipients, "")

    def test_access_request_email_failed_records_error(self):
        self._set_user_preferences(
            self.user,
            email_enabled=True,
            smtp_host="smtp.local",
            smtp_port=587,
            smtp_username="requester@example.com",
            smtp_password="secret",
            smtp_encryption="STARTTLS",
        )
        self._login_with_empresa(self.user)
        url = reverse("access_control:solicitar_acceso")
        payload = {
            "vista_nombre": self.vista.nombre,
            "empresa_id": str(self.empresa.id),
            "motivo": "Necesito acceso para revisar permisos",
            "enviar_email": "on",
        }
        with patch(
            "access_control.services.access_requests.send_email_message",
            side_effect=Exception("smtp down"),
        ):
            response = self.client.post(url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        access_request = AccessRequest.objects.get()
        self.assertTrue(access_request.email_attempted)
        self.assertFalse(access_request.email_sent)
        self.assertEqual(access_request.email_status, AccessRequest.EmailStatus.FAILED)
        self.assertIn("smtp down", access_request.email_error)

    def test_access_request_skipped_when_missing_smtp_config(self):
        self._set_user_preferences(self.user, email_enabled=True)
        self._login_with_empresa(self.user)
        url = reverse("access_control:solicitar_acceso")
        payload = {
            "vista_nombre": self.vista.nombre,
            "empresa_id": str(self.empresa.id),
            "motivo": "Necesito acceso para validar configuracion",
            "enviar_email": "on",
        }
        response = self.client.post(url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        access_request = AccessRequest.objects.get()
        self.assertEqual(access_request.email_status, AccessRequest.EmailStatus.SKIPPED)
        self.assertEqual(access_request.email_error, "missing_smtp_config")

    def test_403_lists_pending_requests(self):
        self._login_with_empresa(self.user)
        AccessRequest.objects.create(
            solicitante=self.user,
            empresa=self.empresa,
            vista_nombre=self.vista.nombre,
            motivo="Pendiente de aprobacion",
            status=AccessRequest.Status.PENDING,
            created_at=timezone.now() - timedelta(minutes=5),
        )
        response = self.client.get(reverse("access_control:usuarios_lista"))
        self.assertEqual(response.status_code, 403)
        content = response.content.decode("utf-8")
        self.assertIn("Pendiente de aprobacion", content)

    def test_grant_access_request_get_staff(self):
        access_request = AccessRequest.objects.create(
            solicitante=self.user,
            empresa=self.empresa,
            vista_nombre=self.vista.nombre,
            motivo="Necesito acceso para operar",
            status=AccessRequest.Status.PENDING,
        )
        self._login_with_empresa(self.staff)
        url = reverse("access_control:grant_access_request", args=[access_request.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_request.grant.title", response.content.decode("utf-8"))
        self.assertTrue(Vista.objects.filter(nombre="access_control.grant_access_request").exists())
        self.assertTrue(Vista.objects.filter(nombre=access_request.vista_nombre).exists())

    def test_grant_access_request_get_non_staff(self):
        access_request = AccessRequest.objects.create(
            solicitante=self.user,
            empresa=self.empresa,
            vista_nombre=self.vista.nombre,
            motivo="Necesito acceso para operar",
            status=AccessRequest.Status.PENDING,
        )
        self._login_with_empresa(self.user)
        url = reverse("access_control:grant_access_request", args=[access_request.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Vista.objects.filter(nombre="access_control.grant_access_request").exists())

    def test_grant_access_request_post_creates_permiso_and_resolves(self):
        access_request = AccessRequest.objects.create(
            solicitante=self.user,
            empresa=self.empresa,
            vista_nombre=self.vista.nombre,
            motivo="Necesito acceso para operar",
            status=AccessRequest.Status.PENDING,
        )
        self._login_with_empresa(self.staff)
        url = reverse("access_control:grant_access_request", args=[access_request.id])
        payload = {
            "ingresar": "on",
            "crear": "on",
        }
        response = self.client.post(url, payload, follow=True)
        self.assertEqual(response.status_code, 200)
        permiso = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
        )
        self.assertTrue(permiso.ingresar)
        self.assertTrue(permiso.crear)
        access_request.refresh_from_db()
        self.assertEqual(access_request.status, AccessRequest.Status.RESOLVED)
        self.assertEqual(access_request.resolved_by, self.staff)
        self.assertIsNotNone(access_request.resolved_at)
        content = response.content.decode("utf-8")
        self.assertIn("access_requests.resolved_by", content)
        self.assertIn(self.staff.username, content)
