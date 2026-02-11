from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa
from chat.models import Conversacion


class TestChatModels(TestCase):
    def test_conversacion_str_incluye_participantes(self):
        empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        user1 = User.objects.create_user(username="user1", password="pass")
        user2 = User.objects.create_user(username="user2", password="pass")

        conversacion = Conversacion.objects.create(empresa=empresa)
        conversacion.participantes.set([user1, user2])

        resultado = str(conversacion)
        self.assertIn("user1", resultado)
        self.assertIn("user2", resultado)
