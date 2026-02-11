from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from chat.models import Conversacion
from notificaciones.models import Notification


class ChatNotificationsTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.user_a = User.objects.create_user(username="user_a", password="pass")
        self.user_b = User.objects.create_user(username="user_b", password="pass")
        self.conversacion = Conversacion.objects.create(empresa=self.empresa)
        self.conversacion.participantes.set([self.user_a, self.user_b])

        vista = Vista.objects.create(nombre="chat.send_message")
        Permiso.objects.create(
            usuario=self.user_a,
            empresa=self.empresa,
            vista=vista,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

    def test_crea_notificacion_al_enviar_mensaje(self):
        self.client.force_login(self.user_a)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

        response = self.client.post(
            reverse("enviar_mensaje", args=[self.conversacion.id]),
            {"contenido": "Hola desde A"},
        )
        self.assertIn(response.status_code, [302, 200])

        notification = Notification.objects.filter(
            destinatario=self.user_b,
            empresa=self.empresa,
            tipo=Notification.Tipo.MESSAGE,
        ).first()
        self.assertIsNotNone(notification)
        self.assertEqual(notification.actor, self.user_a)
        self.assertFalse(notification.is_read)
        self.assertTrue(notification.dedupe_key.startswith("chat:msg:"))

    def test_no_duplica_notificacion_por_mensaje(self):
        self.client.force_login(self.user_a)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

        response = self.client.post(
            reverse("enviar_mensaje", args=[self.conversacion.id]),
            {"contenido": "Hola sin duplicados"},
        )
        self.assertIn(response.status_code, [302, 200])

        notifications = Notification.objects.filter(
            destinatario=self.user_b,
            empresa=self.empresa,
            tipo=Notification.Tipo.MESSAGE,
        )
        self.assertEqual(notifications.count(), 1)
