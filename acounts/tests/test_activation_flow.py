import hashlib
import gzip
import itertools
import os

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
import django.contrib.auth.password_validation as password_validation

from access_control.models import Empresa
from acounts.models import SystemConfig, UserEmailToken, UserEmailTokenPurpose
from acounts.services.tokens import generate_token


def _find_common_password(min_length=12):
    """Busca en la lista real de Django una contraseña común alfabética (>= min_length)."""
    path = os.path.join(os.path.dirname(password_validation.__file__), 'common-passwords.txt.gz')
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        for word in itertools.islice(handle, 0, 20000):
            word = word.strip()
            if len(word) >= min_length and word.isalpha():
                return word
    raise AssertionError('No se encontró una contraseña común alfabética de longitud suficiente.')


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
        self.assertContains(response, 'invited@test.local')

    def test_post_no_permite_cambiar_username(self):
        token_plain = generate_token(
            self.user,
            meta={'empresa_id': self.empresa.id},
            created_by=self.user,
        )
        url = reverse('acounts_activation:activate', args=[token_plain])

        response = self.client.post(
            url,
            data={
                'username': 'otro-usuario',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'invited@test.local')
        self.assertTrue(self.user.is_active)

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


class TestActivationPasswordPolicy(TestCase):
    """Cobertura de la politica de contrasena especifica del flujo de activacion."""

    def setUp(self):
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        self.system_config = SystemConfig.objects.create(
            is_active=True,
            public_base_url='http://testserver',
            default_from_email='noreply@test.local',
            default_from_name='Test System',
            activation_ttl_hours=48,
        )
        self.user = User.objects.create(
            username='invited@test.local',
            email='invited@test.local',
            is_active=False,
        )
        self.user.set_unusable_password()
        self.user.save(update_fields=['password'])

    def _get_token_hash(self, token_plain):
        return hashlib.sha256(token_plain.encode('utf-8')).hexdigest()

    def _generate_token(self, user=None):
        return generate_token(
            user or self.user,
            meta={'empresa_id': self.empresa.id},
            created_by=self.user,
        )

    def _post_activation(self, token_plain, password1, password2=None):
        url = reverse('acounts_activation:activate', args=[token_plain])
        return self.client.post(
            url,
            data={
                'password1': password1,
                'password2': password2 if password2 is not None else password1,
            },
        )

    def test_password_menor_a_minimo_es_rechazada(self):
        token_plain = self._generate_token()
        response = self._post_activation(token_plain, 'ShortPass1')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors.get('password1'))

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

        token_obj = UserEmailToken.objects.get(token_hash=self._get_token_hash(token_plain))
        self.assertIsNone(token_obj.used_at)

    def test_password_valida_de_12_o_mas_caracteres_activa_la_cuenta(self):
        token_plain = self._generate_token()
        response = self._post_activation(token_plain, 'CorrectHorse9')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login'))

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.user.check_password('CorrectHorse9'))

        token_obj = UserEmailToken.objects.get(token_hash=self._get_token_hash(token_plain))
        self.assertIsNotNone(token_obj.used_at)

    def test_password_comun_es_rechazada(self):
        common_password = _find_common_password(min_length=12)
        token_plain = self._generate_token()
        response = self._post_activation(token_plain, common_password)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

        token_obj = UserEmailToken.objects.get(token_hash=self._get_token_hash(token_plain))
        self.assertIsNone(token_obj.used_at)

    def test_password_completamente_numerica_es_rechazada(self):
        token_plain = self._generate_token()
        response = self._post_activation(token_plain, '123456789012')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

        token_obj = UserEmailToken.objects.get(token_hash=self._get_token_hash(token_plain))
        self.assertIsNone(token_obj.used_at)

    def test_password_similar_al_username_o_email_es_rechazada(self):
        token_plain = self._generate_token()
        # username == email en este fixture; usar el valor completo garantiza alta similitud.
        response = self._post_activation(token_plain, self.user.username)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_password_similar_al_nombre_es_rechazada(self):
        user_con_nombre = User.objects.create(
            username='otro-invitado@test.local',
            email='otro-invitado@test.local',
            first_name='Alejandroperez',
            is_active=False,
        )
        user_con_nombre.set_unusable_password()
        user_con_nombre.save(update_fields=['password'])

        token_plain = self._generate_token(user=user_con_nombre)
        response = self._post_activation(token_plain, 'Alejandroperez')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())

        user_con_nombre.refresh_from_db()
        self.assertFalse(user_con_nombre.is_active)

    def test_passwords_no_coinciden_no_consume_token(self):
        token_plain = self._generate_token()
        response = self._post_activation(token_plain, 'CorrectHorse9', 'DifferentHorse9')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())

        token_obj = UserEmailToken.objects.get(token_hash=self._get_token_hash(token_plain))
        self.assertIsNone(token_obj.used_at)

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_password_invalida_por_cualquier_validador_no_consume_token(self):
        token_plain = self._generate_token()
        response = self._post_activation(token_plain, '111111111111')

        self.assertEqual(response.status_code, 200)

        token_obj = UserEmailToken.objects.get(token_hash=self._get_token_hash(token_plain))
        self.assertIsNone(token_obj.used_at)

    def test_replay_de_token_ya_consumido_es_rechazado(self):
        token_plain = self._generate_token()
        first_response = self._post_activation(token_plain, 'CorrectHorse9')
        self.assertEqual(first_response.status_code, 302)

        second_response = self._post_activation(token_plain, 'AnotherHorse9')
        self.assertEqual(second_response.status_code, 400)

    def test_token_expirado_es_rechazado(self):
        token_plain = generate_token(
            self.user,
            meta={'empresa_id': self.empresa.id},
            created_by=self.user,
            ttl_seconds=-1,
        )

        response = self._post_activation(token_plain, 'CorrectHorse9')
        self.assertEqual(response.status_code, 400)

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
