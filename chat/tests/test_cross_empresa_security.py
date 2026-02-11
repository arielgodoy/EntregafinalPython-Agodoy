from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from access_control.models import Empresa, PerfilAcceso, Permiso, UsuarioPerfilEmpresa, Vista
from chat.models import Conversacion, Mensaje


def _build_test_templates():
    base_template = "{% block contenido %}{% endblock contenido %}"
    base_config = dict(settings.TEMPLATES[0])
    base_config["APP_DIRS"] = False
    base_config["OPTIONS"] = dict(base_config.get("OPTIONS", {}))
    base_config["OPTIONS"]["loaders"] = [
        ("django.template.loaders.locmem.Loader", {"base.html": base_template}),
        "django.template.loaders.filesystem.Loader",
        "django.template.loaders.app_directories.Loader",
    ]
    return [base_config]


@override_settings(TEMPLATES=_build_test_templates())
class TestCrossEmpresaSecurity(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        self.user1 = User.objects.create_user(username="user1", password="pass")
        self.user2 = User.objects.create_user(username="user2", password="pass")
        self.user3 = User.objects.create_user(username="user3", password="pass")
        self.perfil = PerfilAcceso.objects.create(nombre="Demo", is_active=True)

        self.vista_chat_create = Vista.objects.create(nombre="chat.create")
        self.vista_chat_send = Vista.objects.create(nombre="chat.send_message")
        self.vista_chat_thread = Vista.objects.create(nombre="chat.thread")

    def _grant_permiso(self, user, empresa, vista):
        return Permiso.objects.create(
            usuario=user,
            empresa=empresa,
            vista=vista,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

    def _set_empresa_activa(self, empresa_id):
        session = self.client.session
        session["empresa_id"] = empresa_id
        session.save()

    def test_create_conversation_rechaza_participante_fuera_de_empresa_activa(self):
        UsuarioPerfilEmpresa.objects.create(usuario=self.user1, empresa=self.empresa_a, perfil=self.perfil)
        UsuarioPerfilEmpresa.objects.create(usuario=self.user1, empresa=self.empresa_b, perfil=self.perfil)
        UsuarioPerfilEmpresa.objects.create(usuario=self.user2, empresa=self.empresa_b, perfil=self.perfil)

        self._grant_permiso(self.user1, self.empresa_a, self.vista_chat_create)
        self.client.force_login(self.user1)
        self._set_empresa_activa(self.empresa_a.id)

        response = self.client.post(
            reverse("crear_conversacion"),
            {"participantes": [self.user1.id, self.user2.id]},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Conversacion.objects.count(), 0)

    def test_send_message_rechaza_conversacion_de_otra_empresa(self):
        UsuarioPerfilEmpresa.objects.create(usuario=self.user1, empresa=self.empresa_a, perfil=self.perfil)
        UsuarioPerfilEmpresa.objects.create(usuario=self.user1, empresa=self.empresa_b, perfil=self.perfil)
        UsuarioPerfilEmpresa.objects.create(usuario=self.user3, empresa=self.empresa_b, perfil=self.perfil)

        self._grant_permiso(self.user1, self.empresa_a, self.vista_chat_send)

        conv_b = Conversacion.objects.create(empresa=self.empresa_b)
        conv_b.participantes.set([self.user1, self.user3])

        self.client.force_login(self.user1)
        self._set_empresa_activa(self.empresa_a.id)

        response = self.client.post(
            reverse("enviar_mensaje", args=[conv_b.id]),
            {"contenido": "Hola"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Mensaje.objects.count(), 0)

    def test_multiempresa_permite_en_empresa_correcta(self):
        UsuarioPerfilEmpresa.objects.create(usuario=self.user1, empresa=self.empresa_a, perfil=self.perfil)
        UsuarioPerfilEmpresa.objects.create(usuario=self.user2, empresa=self.empresa_a, perfil=self.perfil)
        UsuarioPerfilEmpresa.objects.create(usuario=self.user1, empresa=self.empresa_b, perfil=self.perfil)

        self._grant_permiso(self.user1, self.empresa_a, self.vista_chat_create)
        self._grant_permiso(self.user1, self.empresa_a, self.vista_chat_send)
        self._grant_permiso(self.user1, self.empresa_b, self.vista_chat_send)
        self._grant_permiso(self.user1, self.empresa_b, self.vista_chat_thread)

        self.client.force_login(self.user1)
        self._set_empresa_activa(self.empresa_a.id)

        response = self.client.post(
            reverse("crear_conversacion"),
            {"participantes": [self.user1.id, self.user2.id]},
        )
        self.assertEqual(response.status_code, 302)
        conversacion = Conversacion.objects.first()
        self.assertIsNotNone(conversacion)

        response_send = self.client.post(
            reverse("enviar_mensaje", args=[conversacion.id]),
            {"contenido": "Hola A"},
        )
        self.assertIn(response_send.status_code, [200, 302])
        self.assertEqual(Mensaje.objects.count(), 1)

        self._set_empresa_activa(self.empresa_b.id)
        response_cross = self.client.post(
            reverse("enviar_mensaje", args=[conversacion.id]),
            {"contenido": "Hola B"},
        )
        self.assertEqual(response_cross.status_code, 404)
        self.assertEqual(Mensaje.objects.count(), 1)
