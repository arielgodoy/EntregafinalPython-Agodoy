from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, PerfilAcceso, UsuarioPerfilEmpresa, Vista
from tareas.models import EnlaceTarea, EventoAccesoEnlace, Tarea, TareaParticipante
from tareas.services.links import (
    TaskLinkAccessError,
    create_task_link,
    resolve_task_link,
    revoke_task_link,
)


class TaskLinkServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="L01", descripcion="Empresa enlaces")
        cls.otra_empresa = Empresa.objects.create(codigo="L02", descripcion="Otra empresa")
        cls.creador = User.objects.create_user("link_creator", email="creator@example.test")
        cls.destinatario = User.objects.create_user("link_recipient", email="recipient@example.test")
        cls.otro_usuario = User.objects.create_user("link_other", email="other@example.test")
        cls.perfil = PerfilAcceso.objects.create(nombre="Perfil enlaces")
        UsuarioPerfilEmpresa.objects.create(
            usuario=cls.destinatario,
            empresa=cls.empresa,
            perfil=cls.perfil,
        )
        UsuarioPerfilEmpresa.objects.create(
            usuario=cls.otro_usuario,
            empresa=cls.otra_empresa,
            perfil=cls.perfil,
        )
        vista = Vista.objects.create(nombre="Tareas")
        Permiso.objects.create(
            usuario=cls.creador,
            empresa=cls.empresa,
            vista=vista,
            ingresar=True,
            modificar=True,
        )
        UsuarioPerfilEmpresa.objects.create(
            usuario=cls.creador,
            empresa=cls.empresa,
            perfil=cls.perfil,
        )

    def setUp(self):
        self.tarea = Tarea.objects.create(
            titulo="Tarea compartida",
            correlativo="L01-0001",
            empresa=self.empresa,
            creada_por=self.creador,
            responsable=self.creador,
        )
        self.expiracion = timezone.now() + timedelta(days=1)

    def create_link(self, **changes):
        values = {
            "tarea": self.tarea,
            "destinatario": self.destinatario,
            "creado_por": self.creador,
            "fecha_expiracion": self.expiracion,
        }
        values.update(changes)
        with patch("tareas.services.links.create_notification"), patch(
            "tareas.services.links.send_email_for_purpose"
        ):
            return create_task_link(**values)

    def test_create_link_returns_plain_token_but_persists_only_hash(self):
        with patch("tareas.services.links.create_notification"), patch(
            "tareas.services.links.send_email_for_purpose"
        ):
            enlace, token = create_task_link(
                tarea=self.tarea,
                destinatario=self.destinatario,
                creado_por=self.creador,
                fecha_expiracion=self.expiracion,
            )
        self.assertNotEqual(token, enlace.token_hash)
        self.assertEqual(len(enlace.token_hash), 64)
        self.assertNotIn(token, EnlaceTarea.objects.values_list("token_hash", flat=True))
        self.assertTrue(token.replace("-", "").replace("_", "").isalnum())

    def test_expiration_and_users_are_validated(self):
        with self.assertRaises(ValidationError):
            self.create_link(fecha_expiracion=timezone.now())
        with self.assertRaises(ValidationError):
            self.create_link(destinatario=self.otro_usuario)
        with self.assertRaises(ValidationError):
            self.create_link(creado_por=self.otro_usuario)

    def test_token_hash_is_unique_and_links_are_multiuse(self):
        first, first_token = self.create_link()
        second, second_token = self.create_link()
        self.assertNotEqual(first.token_hash, second.token_hash)
        with patch("tareas.services.links._hash_token", return_value=first.token_hash):
            with self.assertRaises(ValidationError):
                self.create_link()
        resolve_task_link(token=first_token, usuario=self.destinatario, empresa=self.empresa)
        resolve_task_link(token=first_token, usuario=self.destinatario, empresa=self.empresa)
        self.assertEqual(first.eventos_acceso.count(), 2)
        self.assertNotEqual(first_token, second_token)

    def test_invalid_token_does_not_create_orphan_event(self):
        with self.assertRaises(TaskLinkAccessError):
            resolve_task_link(token="missing-token", usuario=self.destinatario, empresa=self.empresa)
        self.assertEqual(EventoAccesoEnlace.objects.count(), 0)

    def test_rejected_accesses_are_audited(self):
        enlace, token = self.create_link()
        with self.assertRaises(TaskLinkAccessError):
            resolve_task_link(token=token, usuario=self.creador, empresa=self.empresa)
        with self.assertRaises(TaskLinkAccessError):
            resolve_task_link(token=token, usuario=self.destinatario, empresa=self.otra_empresa)
        enlace.fecha_expiracion = timezone.now() - timedelta(seconds=1)
        enlace.save(update_fields=["fecha_expiracion"])
        with self.assertRaises(TaskLinkAccessError):
            resolve_task_link(token=token, usuario=self.destinatario, empresa=self.empresa)
        enlace.fecha_expiracion = self.expiracion
        enlace.revocado_at = timezone.now()
        enlace.save(update_fields=["fecha_expiracion", "revocado_at"])
        with self.assertRaises(TaskLinkAccessError):
            resolve_task_link(token=token, usuario=self.destinatario, empresa=self.empresa)
        self.assertEqual(
            list(enlace.eventos_acceso.values_list("resultado", flat=True)),
            [
                EventoAccesoEnlace.Resultado.RECHAZADO_USUARIO,
                EventoAccesoEnlace.Resultado.RECHAZADO_EMPRESA,
                EventoAccesoEnlace.Resultado.RECHAZADO_EXPIRADO,
                EventoAccesoEnlace.Resultado.RECHAZADO_REVOCADO,
            ],
        )

    def test_revoke_records_actor_and_is_idempotent(self):
        enlace, _ = self.create_link()
        revoke_task_link(enlace=enlace, actor=self.creador)
        enlace.refresh_from_db()
        first_timestamp = enlace.revocado_at
        self.assertEqual(enlace.revocado_por_id, self.creador.pk)
        revoke_task_link(enlace=enlace, actor=self.creador)
        enlace.refresh_from_db()
        self.assertEqual(enlace.revocado_at, first_timestamp)
        self.assertEqual(enlace.revocado_por_id, self.creador.pk)

    def test_link_does_not_change_task_permissions_or_participants(self):
        before = self.tarea.updated_at if hasattr(self.tarea, "updated_at") else None
        permissions = Permiso.objects.count()
        participants = TareaParticipante.objects.count()
        self.create_link()
        self.tarea.refresh_from_db()
        self.assertEqual(Permiso.objects.count(), permissions)
        self.assertEqual(TareaParticipante.objects.count(), participants)
        if before is not None:
            self.assertEqual(self.tarea.updated_at, before)

    @patch("tareas.services.links.send_email_for_purpose", side_effect=RuntimeError("email"))
    @patch("tareas.services.links.create_notification", side_effect=RuntimeError("notification"))
    def test_notification_failures_do_not_rollback_link(self, notification, email):
        enlace, _ = create_task_link(
            tarea=self.tarea,
            destinatario=self.destinatario,
            creado_por=self.creador,
            fecha_expiracion=self.expiracion,
        )
        self.assertTrue(EnlaceTarea.objects.filter(pk=enlace.pk).exists())
        notification.assert_called_once()
        email.assert_called_once()


class TaskLinkViewTests(TaskLinkServiceTests):
    def setUp(self):
        super().setUp()
        with patch("tareas.services.links.create_notification"), patch(
            "tareas.services.links.send_email_for_purpose"
        ):
            self.enlace, self.token = create_task_link(
                tarea=self.tarea,
                destinatario=self.destinatario,
                creado_por=self.creador,
                fecha_expiracion=self.expiracion,
            )

    def activate_company(self, company):
        session = self.client.session
        session["empresa_id"] = company.pk
        session.save()

    def test_create_requires_vicmeas_modificar(self):
        self.client.force_login(self.destinatario)
        self.activate_company(self.empresa)
        response = self.client.post(
            reverse("tareas:crear_enlace_tarea", args=[self.tarea.pk]),
            {
                "destinatario_id": self.destinatario.pk,
                "fecha_expiracion": "2099-01-01T00:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_revoke_requires_vicmeas_modificar(self):
        self.client.force_login(self.destinatario)
        self.activate_company(self.empresa)
        response = self.client.post(
            reverse("tareas:revocar_enlace_tarea", args=[self.enlace.pk])
        )
        self.assertEqual(response.status_code, 403)

    @patch("tareas.services.links.send_email_for_purpose")
    @patch("tareas.services.links.create_notification")
    def test_create_view_uses_vicmeas_and_notifies(self, notification, email):
        self.client.force_login(self.creador)
        self.activate_company(self.empresa)
        response = self.client.post(
            reverse("tareas:crear_enlace_tarea", args=[self.tarea.pk]),
            {
                "destinatario_id": self.destinatario.pk,
                "fecha_expiracion": "2099-01-01T00:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["token"])
        notification.assert_called_once()
        self.assertEqual(email.call_count, 1)
        self.assertEqual(email.call_args.kwargs["purpose"], "notifications")

    def test_open_requires_login_and_preserves_next(self):
        response = self.client.get(reverse("tareas:enlace_tarea", args=[self.token]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response["Location"])

    def test_open_does_not_require_general_vicmeas(self):
        self.client.force_login(self.destinatario)
        self.activate_company(self.empresa)
        Permiso.objects.filter(usuario=self.destinatario, empresa=self.empresa).delete()
        response = self.client.get(reverse("tareas:enlace_tarea", args=[self.token]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.tarea.titulo)

    def test_open_rejects_wrong_company_and_revoke_is_protected(self):
        self.client.force_login(self.destinatario)
        self.activate_company(self.otra_empresa)
        response = self.client.get(reverse("tareas:enlace_tarea", args=[self.token]))
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.creador)
        self.activate_company(self.empresa)
        response = self.client.post(
            reverse("tareas:revocar_enlace_tarea", args=[self.enlace.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.enlace.refresh_from_db()
        self.assertEqual(self.enlace.revocado_por_id, self.creador.pk)
