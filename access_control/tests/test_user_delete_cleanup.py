import hashlib
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from acounts.models import UserEmailToken, UserEmailTokenPurpose
from access_control.models import Empresa, Permiso, PerfilAcceso, UsuarioPerfilEmpresa, Vista


def _hash_token(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class UserDeleteCleanupTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='pass')
        self.target = User.objects.create_user(username='target', password='pass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        self.vista = Vista.objects.create(nombre='Maestro Usuarios')

        Permiso.objects.create(
            usuario=self.admin,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=True,
            autorizar=False,
            supervisor=False,
        )

    def test_eliminar_usuario_limpia_relaciones(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

        Permiso.objects.create(
            usuario=self.target,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

        perfil = PerfilAcceso.objects.create(nombre='TEMP', is_active=True)
        UsuarioPerfilEmpresa.objects.create(
            usuario=self.target,
            empresa=self.empresa,
            perfil=perfil,
            asignado_por=self.admin,
        )

        UserEmailToken.objects.create(
            user=self.target,
            purpose=UserEmailTokenPurpose.ACTIVATE,
            token_hash=_hash_token('cleanup-token')[:64],
            expires_at=timezone.now() + timedelta(days=1),
            meta={'empresa_id': self.empresa.id},
        )

        response = self.client.post(
            reverse('access_control:usuario_eliminar', args=[self.target.id])
        )
        self.assertEqual(response.status_code, 302)

        self.assertFalse(User.objects.filter(pk=self.target.id).exists())
        self.assertFalse(Permiso.objects.filter(usuario=self.target).exists())
        self.assertFalse(UsuarioPerfilEmpresa.objects.filter(usuario=self.target).exists())
        self.assertFalse(UserEmailToken.objects.filter(user=self.target).exists())
