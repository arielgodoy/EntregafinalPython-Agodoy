from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.contrib.sessions.middleware import SessionMiddleware
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from chat.context_processors import chat_unread_count
from chat.models import Conversacion, Mensaje, MensajeLeido
from chat.services.unread import get_unread_count, mark_conversation_read


class TestChatUnread(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        user_model = get_user_model()
        self.user1 = user_model.objects.create_user(
            username="user1",
            email="user1@example.com",
            password="pass12345",
        )
        self.user2 = user_model.objects.create_user(
            username="user2",
            email="user2@example.com",
            password="pass12345",
        )
        self.vista_notificaciones, _ = Vista.objects.get_or_create(
            nombre="notificaciones.mis_notificaciones",
            defaults={"descripcion": ""},
        )

    def _make_conversation(self, empresa):
        conv = Conversacion.objects.create(empresa=empresa)
        conv.participantes.add(self.user1, self.user2)
        return conv

    def _make_message(self, conv, sender, text):
        return Mensaje.objects.create(conversacion=conv, remitente=sender, contenido=text)

    def test_unread_count_excluye_propios_y_respeta_empresa(self):
        conv_a = self._make_conversation(self.empresa_a)
        conv_b = self._make_conversation(self.empresa_b)

        self._make_message(conv_a, self.user2, "Hola A 1")
        self._make_message(conv_a, self.user2, "Hola A 2")
        self._make_message(conv_a, self.user1, "Propio A")
        self._make_message(conv_b, self.user2, "Hola B 1")

        count_a = get_unread_count(self.user1, self.empresa_a.id)
        count_b = get_unread_count(self.user1, self.empresa_b.id)

        self.assertEqual(count_a, 2)
        self.assertEqual(count_b, 1)

    def test_mark_conversation_read(self):
        conv_a = self._make_conversation(self.empresa_a)
        m1 = self._make_message(conv_a, self.user2, "Hola A 1")
        m2 = self._make_message(conv_a, self.user2, "Hola A 2")
        self._make_message(conv_a, self.user1, "Propio A")

        self.assertEqual(get_unread_count(self.user1, self.empresa_a.id), 2)
        created = mark_conversation_read(conv_a, self.user1)
        self.assertEqual(created, 2)
        self.assertEqual(get_unread_count(self.user1, self.empresa_a.id), 0)
        self.assertTrue(MensajeLeido.objects.filter(mensaje=m1, user=self.user1).exists())
        self.assertTrue(MensajeLeido.objects.filter(mensaje=m2, user=self.user1).exists())

    def test_topbar_incluye_unread_chat_messages(self):
        conv_a = self._make_conversation(self.empresa_a)
        self._make_message(conv_a, self.user2, "Hola A 1")
        self._make_message(conv_a, self.user2, "Hola A 2")

        self.client.force_login(self.user1)
        session = self.client.session
        session["empresa_id"] = self.empresa_a.id
        session["empresa_codigo"] = self.empresa_a.codigo
        session["empresa_nombre"] = self.empresa_a.descripcion
        session.save()
        Permiso.objects.update_or_create(
            usuario=self.user1,
            empresa=self.empresa_a,
            vista=self.vista_notificaciones,
            defaults={"ingresar": True},
        )

        response = self.client.get(reverse("notificaciones:topbar"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("unread_messages"), 2)

    def test_sidebar_badge_context(self):
        conv_a = self._make_conversation(self.empresa_a)
        self._make_message(conv_a, self.user2, "Hola A 1")

        factory = RequestFactory()
        request = factory.get("/")
        request.user = self.user1

        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session["empresa_id"] = self.empresa_a.id
        request.session.save()

        context = chat_unread_count(request)
        self.assertEqual(context.get("chat_unread_count"), 1)
