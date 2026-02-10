from datetime import timedelta
import hashlib
import secrets

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from acounts.models import UserEmailToken, UserEmailTokenPurpose
from access_control.models import Empresa, Permiso, Vista


def _hash_token(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class InvitacionesListTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pass')
        self.staff = User.objects.create_user(username='staff', password='pass', is_staff=True)
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        self.empresa_sec = Empresa.objects.create(codigo='02', descripcion='Empresa 02')
        self.vista = Vista.objects.create(nombre='invitaciones')

        Permiso.objects.create(
            usuario=self.staff,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=True,
            autorizar=False,
            supervisor=False,
        )

    def _create_token(self, user, expires_at, used_at=None, meta=None):
        seed = secrets.token_hex(8)
        return UserEmailToken.objects.create(
            user=user,
            purpose=UserEmailTokenPurpose.ACTIVATE,
            token_hash=_hash_token(f"{user.username}-{expires_at.isoformat()}-{seed}")[:64],
            expires_at=expires_at,
            used_at=used_at,
            meta=meta,
        )

    def test_lista_requiere_permiso(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()
        response = self.client.get(reverse('access_control:invitaciones_lista'))
        self.assertEqual(response.status_code, 403)

    def test_lista_estado_tokens(self):
        self.client.force_login(self.staff)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

        now = timezone.now()
        self._create_token(
            self.staff,
            expires_at=now + timedelta(days=1),
            meta={'empresa_id': self.empresa.id},
        )
        self._create_token(
            self.staff,
            expires_at=now - timedelta(days=1),
            meta={'empresa_id': self.empresa.id},
        )
        self._create_token(
            self.staff,
            expires_at=now + timedelta(days=1),
            used_at=now,
            meta={'empresa_id': self.empresa.id},
        )

        response = self.client.get(reverse('access_control:invitaciones_lista'), {'estado': 'all'})
        self.assertEqual(response.status_code, 200)
        items = response.context['invitaciones']
        status_keys = {item['status_key'] for item in items}
        self.assertIn('invitations.status.active', status_keys)
        self.assertIn('invitations.status.expired', status_keys)
        self.assertIn('invitations.status.used', status_keys)

    def test_filtro_empresa_activa(self):
        self.client.force_login(self.staff)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

        now = timezone.now()
        self._create_token(
            self.staff,
            expires_at=now + timedelta(days=1),
            meta={'empresa_id': self.empresa.id},
        )
        self._create_token(
            self.staff,
            expires_at=now + timedelta(days=1),
            meta={'empresa_id': self.empresa_sec.id},
        )

        response = self.client.get(reverse('access_control:invitaciones_lista'))
        items = response.context['invitaciones']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['token'].meta.get('empresa_id'), self.empresa.id)


class InvitacionesDeleteTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass', is_staff=True)
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        self.vista = Vista.objects.create(nombre='invitaciones')
        Permiso.objects.create(
            usuario=self.staff,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=True,
            autorizar=False,
            supervisor=False,
        )

    def test_eliminar_token(self):
        self.client.force_login(self.staff)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

        token = UserEmailToken.objects.create(
            user=self.staff,
            purpose=UserEmailTokenPurpose.ACTIVATE,
            token_hash=_hash_token('delete-token')[:64],
            expires_at=timezone.now() + timedelta(days=1),
            meta={'empresa_id': self.empresa.id},
        )

        response = self.client.post(
            reverse('access_control:invitaciones_eliminar', args=[token.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(UserEmailToken.objects.filter(pk=token.id).exists())
