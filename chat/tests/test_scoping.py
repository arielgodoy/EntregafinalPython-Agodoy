from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.conf import settings
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista, PerfilAcceso, UsuarioPerfilEmpresa
from chat.models import Conversacion, Mensaje


def _build_test_templates():
    base_template = "{% block contenido %}{% endblock contenido %}"
    base_config = dict(settings.TEMPLATES[0])
    base_config['APP_DIRS'] = False
    base_config['OPTIONS'] = dict(base_config.get('OPTIONS', {}))
    base_config['OPTIONS']['loaders'] = [
        ('django.template.loaders.locmem.Loader', {'base.html': base_template}),
        'django.template.loaders.filesystem.Loader',
        'django.template.loaders.app_directories.Loader',
    ]
    return [base_config]


@override_settings(TEMPLATES=_build_test_templates())
class TestChatScoping(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa B")

        self.user1 = User.objects.create_user(username="user1", password="pass")
        self.user2 = User.objects.create_user(username="user2", password="pass")
        self.user3 = User.objects.create_user(username="user3", password="pass")

    def _grant_permiso(self, user, empresa, vista_nombre, ingresar=True):
        vista, _ = Vista.objects.get_or_create(nombre=vista_nombre)
        return Permiso.objects.create(
            usuario=user,
            empresa=empresa,
            vista=vista,
            ingresar=ingresar,
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

    def test_inbox_requires_empresa_activa(self):
        self.client.force_login(self.user1)
        response = self.client.get(reverse("lista_conversaciones"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("access_control:seleccionar_empresa"))

    def test_inbox_scoped_por_empresa_y_participante(self):
        self._grant_permiso(self.user1, self.empresa_a, "Chat - Lista de conversaciones")
        self._grant_permiso(self.user2, self.empresa_a, "Chat - Lista de conversaciones")
        self._grant_permiso(self.user3, self.empresa_b, "Chat - Lista de conversaciones")

        conversacion_a = Conversacion.objects.create(empresa=self.empresa_a)
        conversacion_a.participantes.set([self.user1, self.user2])

        conversacion_b = Conversacion.objects.create(empresa=self.empresa_b)
        conversacion_b.participantes.set([self.user1, self.user3])

        self.client.force_login(self.user1)
        self._set_empresa_activa(self.empresa_a.id)

        response = self.client.get(reverse("lista_conversaciones"))
        self.assertEqual(response.status_code, 200)
        conversaciones = list(response.context["conversaciones"])
        self.assertIn(conversacion_a, conversaciones)
        self.assertNotIn(conversacion_b, conversaciones)

    def test_thread_denies_cross_empresa(self):
        self._grant_permiso(self.user1, self.empresa_a, "Chat - Ver conversación")

        conversacion_b = Conversacion.objects.create(empresa=self.empresa_b)
        conversacion_b.participantes.set([self.user1])

        self.client.force_login(self.user1)
        self._set_empresa_activa(self.empresa_a.id)

        response = self.client.get(
            reverse("detalle_conversacion", args=[conversacion_b.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_create_conversation_rejects_participant_outside_empresa(self):
        self._grant_permiso(self.user1, self.empresa_a, "Chat - Crear conversación")
        self._grant_permiso(self.user2, self.empresa_a, "Chat - Crear conversación")
        self._grant_permiso(self.user3, self.empresa_b, "Chat - Crear conversación")

        perfil = PerfilAcceso.objects.create(nombre="Demo", is_active=True)
        UsuarioPerfilEmpresa.objects.create(usuario=self.user1, empresa=self.empresa_a, perfil=perfil)
        UsuarioPerfilEmpresa.objects.create(usuario=self.user2, empresa=self.empresa_a, perfil=perfil)
        UsuarioPerfilEmpresa.objects.create(usuario=self.user3, empresa=self.empresa_b, perfil=perfil)

        self.client.force_login(self.user1)
        self._set_empresa_activa(self.empresa_a.id)

        response = self.client.post(
            reverse("crear_conversacion"),
            {"participantes": [self.user1.id, self.user3.id]},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Conversacion.objects.count(), 0)

    def test_send_message_requires_participant(self):
        self._grant_permiso(self.user3, self.empresa_a, "Chat - Enviar mensaje")

        conversacion_a = Conversacion.objects.create(empresa=self.empresa_a)
        conversacion_a.participantes.set([self.user1, self.user2])

        self.client.force_login(self.user3)
        self._set_empresa_activa(self.empresa_a.id)

        response = self.client.post(
            reverse("enviar_mensaje", args=[conversacion_a.id]),
            {"contenido": "hola"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Mensaje.objects.count(), 0)
