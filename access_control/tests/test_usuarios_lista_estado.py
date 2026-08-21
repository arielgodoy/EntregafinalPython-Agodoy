import hashlib
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from acounts.models import UserEmailToken, UserEmailTokenPurpose


class UsuariosListaEstadoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='pass1234')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        vista = Vista.objects.create(nombre='Control de Acceso - Maestro Usuarios')
        Permiso.objects.create(
            usuario=self.admin,
            empresa=self.empresa,
            vista=vista,
            ingresar=True,
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def _get_response(self):
        return self.client.get(reverse('access_control:usuarios_lista'))

    def _add_pending_token(self, user):
        token_value = 'pending-token'
        UserEmailToken.objects.create(
            user=user,
            purpose=UserEmailTokenPurpose.ACTIVATE,
            token_hash=hashlib.sha256(token_value.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(hours=1),
        )

    def test_usuario_invitado_sin_activar_es_pendiente(self):
        user = User.objects.create(username='pending@example.com', is_active=False)
        user.set_unusable_password()
        user.save(update_fields=['password'])
        self._add_pending_token(user)

        response = self._get_response()

        item = next(item for item in response.context['usuarios'] if item.pk == user.pk)
        self.assertEqual(item.estado_key, 'users.status.pending_activation')
        self.assertEqual(item.estado_badge, 'warning')

    def test_usuario_activado_es_activo(self):
        user = User.objects.create_user(username='active@example.com', password='StrongPass123!')

        response = self._get_response()

        item = next(item for item in response.context['usuarios'] if item.pk == user.pk)
        self.assertEqual(item.estado_key, 'users.status.active')
        self.assertEqual(item.estado_badge, 'success')

    def test_usuario_antiguo_activo_sin_token_es_activo(self):
        user = User.objects.create_user(username='legacy@example.com', password='StrongPass123!')

        response = self._get_response()

        item = next(item for item in response.context['usuarios'] if item.pk == user.pk)
        self.assertEqual(item.estado_key, 'users.status.active')

    def test_usuario_deshabilitado_es_inactivo(self):
        user = User.objects.create_user(
            username='disabled@example.com',
            password='StrongPass123!',
            is_active=False,
        )

        response = self._get_response()

        item = next(item for item in response.context['usuarios'] if item.pk == user.pk)
        self.assertEqual(item.estado_key, 'users.status.inactive')
        self.assertEqual(item.estado_badge, 'secondary')

    def test_lista_renderiza_columna_estado_y_badges(self):
        user = User.objects.create_user(username='visible@example.com', password='StrongPass123!')

        response = self._get_response()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-key="users.status.column"')
        self.assertContains(response, 'data-key="users.status.active"')
        self.assertContains(response, 'bg-success')