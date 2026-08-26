import hashlib
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from api.models import ApiToken
from api.services.api_tokens import (
    InvalidApiToken,
    create_api_token,
    revoke_api_token,
    validate_api_token,
)


class ApiTokenDomainTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="api-user", password="password")
        self.creator = User.objects.create_user(username="admin-user", password="password")

    def test_create_generates_high_entropy_token_and_stores_only_hash(self):
        api_token, token_value = create_api_token(
            user=self.user,
            name="Power BI",
            created_by=self.creator,
        )

        self.assertTrue(token_value.startswith(f"eltit_api_{api_token.prefix}_"))
        secret = token_value[len(f"eltit_api_{api_token.prefix}_"):]
        self.assertEqual(len(secret), 43)
        self.assertEqual(api_token.token_hash, hashlib.sha256(token_value.encode()).hexdigest())
        self.assertNotIn(token_value, api_token.token_hash)
        self.assertFalse(hasattr(api_token, "token_value"))
        self.assertEqual(api_token.created_by, self.creator)

    def test_prefix_is_unique_and_is_part_of_token(self):
        first, first_value = create_api_token(user=self.user, name="First")
        second, second_value = create_api_token(user=self.user, name="Second")

        self.assertNotEqual(first.prefix, second.prefix)
        self.assertIn(first.prefix, first_value)
        self.assertIn(second.prefix, second_value)
        self.assertEqual(ApiToken.objects.filter(prefix=first.prefix).count(), 1)

    def test_prefix_collision_retries(self):
        with patch(
            "api.services.api_tokens.secrets.token_urlsafe",
            side_effect=["same-prefix", "secret-one", "same-prefix", "secret-two", "new-prefix", "secret-three"],
        ):
            first, _ = create_api_token(user=self.user, name="First")
            second, second_value = create_api_token(user=self.user, name="Second")

        self.assertEqual(first.prefix, "same-prefix")
        self.assertEqual(second.prefix, "new-prefix")
        self.assertIn("new-prefix", second_value)

    def test_validate_accepts_active_unexpired_token_without_expiration(self):
        api_token, token_value = create_api_token(
            user=self.user,
            name="ERP externo",
            expires_at=timezone.now() + timedelta(days=1),
        )

        self.assertEqual(validate_api_token(token_value).pk, api_token.pk)
        api_token.expires_at = None
        api_token.save(update_fields=["expires_at"])
        self.assertEqual(validate_api_token(token_value).pk, api_token.pk)

    def test_validate_rejects_missing_expired_revoked_inactive_and_inactive_user(self):
        with self.assertRaises(InvalidApiToken):
            validate_api_token("does-not-exist")

        expired, expired_value = create_api_token(
            user=self.user,
            name="Expired",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        with self.assertRaises(InvalidApiToken):
            validate_api_token(expired_value)

        revoked, revoked_value = create_api_token(user=self.user, name="Revoked")
        revoke_api_token(revoked)
        with self.assertRaises(InvalidApiToken):
            validate_api_token(revoked_value)

        inactive, inactive_value = create_api_token(user=self.user, name="Inactive")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        with self.assertRaises(InvalidApiToken):
            validate_api_token(inactive_value)

        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(InvalidApiToken):
            validate_api_token(expired_value)

    def test_revoke_sets_state_and_is_idempotent(self):
        api_token, _ = create_api_token(user=self.user, name="Script contable")

        revoke_api_token(api_token)
        api_token.refresh_from_db()
        first_revoked_at = api_token.revoked_at
        self.assertFalse(api_token.is_active)
        self.assertIsNotNone(first_revoked_at)

        revoke_api_token(api_token)
        api_token.refresh_from_db()
        self.assertFalse(api_token.is_active)
        self.assertEqual(api_token.revoked_at, first_revoked_at)

    def test_user_can_have_multiple_independent_tokens(self):
        first, first_value = create_api_token(user=self.user, name="First")
        second, second_value = create_api_token(user=self.user, name="Second")

        revoke_api_token(first)

        with self.assertRaises(InvalidApiToken):
            validate_api_token(first_value)
        self.assertEqual(validate_api_token(second_value).pk, second.pk)
        self.assertNotEqual(first.token_hash, second.token_hash)
