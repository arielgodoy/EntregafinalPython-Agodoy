from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from access_control.models import Empresa, PerfilAcceso, UsuarioPerfilEmpresa, Vista, Permiso


class SeedChatPermisosTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")

    def test_seed_crea_vistas_chat(self):
        call_command('seed_access_control')

        for vista_nombre in [
            'chat.inbox',
            'chat.thread',
            'chat.create',
            'chat.send_message',
            'chat.delete',
        ]:
            self.assertTrue(Vista.objects.filter(nombre=vista_nombre).exists())

    def test_seed_asigna_ingresar_por_perfil_y_empresa(self):
        perfiles = {
            'Usuario (Basico)': {
                'chat.inbox': True,
                'chat.thread': True,
                'chat.create': True,
                'chat.send_message': True,
                'chat.delete': False,
            },
            'Profesional': {
                'chat.inbox': True,
                'chat.thread': True,
                'chat.create': True,
                'chat.send_message': True,
                'chat.delete': False,
            },
            'Administrador': {
                'chat.inbox': True,
                'chat.thread': True,
                'chat.create': True,
                'chat.send_message': True,
                'chat.delete': True,
            },
        }

        users = {}
        for nombre in perfiles:
            user = User.objects.create_user(username=nombre.lower().replace(' ', '_'), password='pass')
            perfil = PerfilAcceso.objects.create(nombre=nombre, is_active=True)
            UsuarioPerfilEmpresa.objects.create(usuario=user, empresa=self.empresa, perfil=perfil)
            users[nombre] = user

        call_command('seed_access_control')

        for perfil_nombre, vistas in perfiles.items():
            user = users[perfil_nombre]
            for vista_nombre, ingresar in vistas.items():
                permiso = Permiso.objects.filter(
                    usuario=user,
                    empresa=self.empresa,
                    vista__nombre=vista_nombre,
                ).first()
                self.assertIsNotNone(permiso)
                self.assertEqual(permiso.ingresar, ingresar)

    def test_seed_no_pisa_permiso_existente(self):
        perfil = PerfilAcceso.objects.create(nombre='Usuario (Basico)', is_active=True)
        user = User.objects.create_user(username='user_base', password='pass')
        UsuarioPerfilEmpresa.objects.create(usuario=user, empresa=self.empresa, perfil=perfil)

        vista = Vista.objects.create(nombre='chat.inbox')
        Permiso.objects.create(
            usuario=user,
            empresa=self.empresa,
            vista=vista,
            ingresar=False,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

        call_command('seed_access_control')

        permiso = Permiso.objects.get(usuario=user, empresa=self.empresa, vista=vista)
        self.assertFalse(permiso.ingresar)
