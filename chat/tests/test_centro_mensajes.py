from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from chat.models import Conversacion, Mensaje, MensajeLeido


class TestCentroMensajes(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.user1 = User.objects.create_user(username="user1", password="pass")
        self.user2 = User.objects.create_user(username="user2", password="pass")
        vista = Vista.objects.create(nombre="chat.inbox")
        Permiso.objects.create(
            usuario=self.user1,
            empresa=self.empresa,
            vista=vista,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

        self.conversacion = Conversacion.objects.create(empresa=self.empresa)
        self.conversacion.participantes.set([self.user1, self.user2])

        self.conversacion_no_match = Conversacion.objects.create(empresa=self.empresa)
        self.conversacion_no_match.participantes.set([self.user1, self.user2])

    def _login_with_empresa(self):
        self.client.force_login(self.user1)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def test_busqueda_filtra_conversaciones(self):
        Mensaje.objects.create(
            conversacion=self.conversacion,
            remitente=self.user2,
            contenido="hola mundo",
        )
        Mensaje.objects.create(
            conversacion=self.conversacion_no_match,
            remitente=self.user2,
            contenido="otro texto",
        )

        self._login_with_empresa()
        response = self.client.get(reverse("centro_mensajes") + "?q=hola")
        conversaciones = list(response.context["conversations"])
        self.assertIn(self.conversacion, conversaciones)
        self.assertNotIn(self.conversacion_no_match, conversaciones)

        response = self.client.get(reverse("centro_mensajes") + "?q=xyz")
        conversaciones = list(response.context["conversations"])
        self.assertNotIn(self.conversacion, conversaciones)

    def test_unread_filtra_conversaciones(self):
        Mensaje.objects.create(
            conversacion=self.conversacion,
            remitente=self.user2,
            contenido="hola unread",
        )
        msg_read = Mensaje.objects.create(
            conversacion=self.conversacion_no_match,
            remitente=self.user2,
            contenido="hola leido",
        )
        MensajeLeido.objects.create(
            empresa=self.empresa,
            mensaje=msg_read,
            user=self.user1,
        )

        self._login_with_empresa()
        response = self.client.get(reverse("centro_mensajes") + "?unread=1")
        conversaciones = list(response.context["conversations"])
        self.assertIn(self.conversacion, conversaciones)
        self.assertNotIn(self.conversacion_no_match, conversaciones)
