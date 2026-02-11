from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from acounts.models import UserEmailToken, UserEmailTokenPurpose
from access_control.models import Empresa, PerfilAcceso, Permiso, UsuarioPerfilEmpresa, Vista


class UsuarioDeleteTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="pass", is_staff=True)
        self.target = User.objects.create_user(username="target", password="pass")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.vista = Vista.objects.create(nombre="Maestro Usuarios")
        self.perfil = PerfilAcceso.objects.create(nombre="BASICO", is_active=True)

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
        UsuarioPerfilEmpresa.objects.create(
            usuario=self.target,
            empresa=self.empresa,
            perfil=self.perfil,
            asignado_por=self.admin,
        )
        UserEmailToken.objects.create(
            user=self.target,
            purpose=UserEmailTokenPurpose.ACTIVATE,
            token_hash="deadbeef" * 8,
            expires_at=self._future_time(),
            meta={"empresa_id": self.empresa.id},
        )

        self.client.force_login(self.admin)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def _future_time(self):
        from django.utils import timezone
        from datetime import timedelta

        return timezone.now() + timedelta(days=1)

    def test_eliminar_usuario_por_post_redirige_a_lista(self):
        response = self.client.post(
            reverse("access_control:usuario_eliminar", args=[self.target.id])
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("access_control:usuarios_lista"))
        self.assertFalse(User.objects.filter(pk=self.target.id).exists())
        self.assertFalse(Permiso.objects.filter(usuario=self.target).exists())
        self.assertFalse(UsuarioPerfilEmpresa.objects.filter(usuario=self.target).exists())
        self.assertFalse(UserEmailToken.objects.filter(user=self.target).exists())

    def test_post_a_lista_retorna_405(self):
        Permiso.objects.get(usuario=self.admin, empresa=self.empresa, vista=self.vista)
        response = self.client.post(reverse("access_control:usuarios_lista"))
        self.assertEqual(response.status_code, 405)
