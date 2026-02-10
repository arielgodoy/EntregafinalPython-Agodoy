import hashlib

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User

from access_control.models import Empresa
from acounts.models import SystemConfig, UserEmailToken, UserEmailTokenPurpose
from acounts.services.tokens import generate_token


class TestActivationFlow(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        self.system_config = SystemConfig.objects.create(
            is_active=True,
            public_base_url='http://testserver',
            default_from_email='noreply@test.local',
            default_from_name='Test System',
            activation_ttl_hours=48,
        )
        self.user = User.objects.create(username='invited@test.local', email='invited@test.local', is_active=False)
        self.user.set_unusable_password()
        self.user.save(update_fields=['password'])

    def _get_token_hash(self, token_plain):
        return hashlib.sha256(token_plain.encode('utf-8')).hexdigest()

    def test_get_invalid_token_returns_400(self):
        url = reverse('acounts_activation:activate', args=['invalid-token'])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

    def test_get_valid_token_shows_form(self):
        token_plain = generate_token(
            self.user,
            meta={'empresa_id': self.empresa.id},
            created_by=self.user,
        )
        url = reverse('acounts_activation:activate', args=[token_plain])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Activar cuenta')

    def test_post_valid_activates_user_and_consumes_token(self):
        token_plain = generate_token(
            self.user,
            meta={'empresa_id': self.empresa.id},
            created_by=self.user,
        )
        url = reverse('acounts_activation:activate', args=[token_plain])

        response = self.client.post(
            url,
            data={
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login'))

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

        token_hash = self._get_token_hash(token_plain)
        token_obj = UserEmailToken.objects.get(token_hash=token_hash)
        self.assertIsNotNone(token_obj.used_at)

    def test_post_does_not_consume_on_invalid_form(self):
        token_plain = generate_token(
            self.user,
            meta={'empresa_id': self.empresa.id},
            created_by=self.user,
        )
        url = reverse('acounts_activation:activate', args=[token_plain])

        response = self.client.post(
            url,
            data={
                'password1': 'StrongPass123!',
                'password2': 'Mismatch123!',
            },
        )
        self.assertEqual(response.status_code, 200)

        token_hash = self._get_token_hash(token_plain)
        token_obj = UserEmailToken.objects.get(token_hash=token_hash)
        self.assertIsNone(token_obj.used_at)

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_active_user_valid_token_redirects_login_without_consuming(self):
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])

        token_plain = generate_token(
            self.user,
            meta={'empresa_id': self.empresa.id},
            created_by=self.user,
        )
        url = reverse('acounts_activation:activate', args=[token_plain])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login'))

        token_hash = self._get_token_hash(token_plain)
        token_obj = UserEmailToken.objects.get(token_hash=token_hash)
        self.assertIsNone(token_obj.used_at)
