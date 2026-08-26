from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from api.services.api_tokens import create_api_token, revoke_api_token


class ApiAuthenticationTests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(username="user-a", password="password")
        self.user_b = User.objects.create_user(username="user-b", password="password")
        self.empresa_a = Empresa.objects.create(codigo="00", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="01", descripcion="Empresa B")
        self.vista = Vista.objects.create(nombre="API - Acceso")
        self.url = "/api/v1/auth/whoami/"

    def _create_token(self, user=None, **kwargs):
        return create_api_token(
            user=user or self.user_a,
            name=kwargs.pop("name", "Test client"),
            **kwargs,
        )

    def _login_with_active_company(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["empresa_id"] = self.empresa_a.id
        session.save()

    def _grant(self, user, empresa, **flags):
        return Permiso.objects.create(
            usuario=user,
            empresa=empresa,
            vista=self.vista,
            **flags,
        )

    def test_valid_bearer_returns_bearer_identity(self):
        _, token_value = self._create_token()
        self._grant(self.user_a, self.empresa_a, ingresar=True)

        response = self.client.get(
            f"{self.url}?empresa=00",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "authenticated": True,
            "username": "user-a",
            "auth_mode": "bearer",
            "empresa": "00",
        })

    def test_invalid_bearer_returns_401(self):
        response = self.client.get(self.url, HTTP_AUTHORIZATION="Bearer eltit_api_valid-looking_invalid")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Autenticación API requerida."})
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

    def test_revoked_expired_inactive_and_inactive_user_bearers_return_401(self):
        revoked, revoked_value = self._create_token(name="Revoked")
        revoke_api_token(revoked)
        expired, expired_value = self._create_token(
            name="Expired",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        inactive, inactive_value = self._create_token(name="Inactive")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        _, inactive_user_value = self._create_token(user=self.user_b)
        self.user_b.is_active = False
        self.user_b.save(update_fields=["is_active"])

        for token_value in (revoked_value, expired_value, inactive_value, inactive_user_value):
            with self.subTest(token_value=token_value):
                self.assertEqual(
                    self.client.get(self.url, HTTP_AUTHORIZATION=f"Bearer {token_value}").status_code,
                    401,
                )

    def test_malformed_and_unknown_authorization_headers_return_401(self):
        headers = (
            "Bearer",
            "Basic xxx",
            "Bearer ",
            "Bearer token extra",
            "Bearer token\tpart",
        )

        for authorization in headers:
            with self.subTest(authorization=authorization):
                response = self.client.get(self.url, HTTP_AUTHORIZATION=authorization)
                self.assertEqual(response.status_code, 401)

    def test_missing_header_with_authenticated_session_returns_session_identity(self):
        self._login_with_active_company(self.user_a)
        self._grant(self.user_a, self.empresa_a, ingresar=True)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "user-a")
        self.assertEqual(response.json()["auth_mode"], "session")
        self.assertEqual(response.json()["empresa"], "00")

    def test_missing_header_without_session_returns_401(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)

    def test_invalid_bearer_does_not_fallback_to_valid_session(self):
        self._login_with_active_company(self.user_a)

        response = self.client.get(self.url, HTTP_AUTHORIZATION="Bearer invalid-token")

        self.assertEqual(response.status_code, 401)

    def test_bearer_user_takes_precedence_over_different_session_user(self):
        _, token_value = self._create_token(user=self.user_b)
        self._login_with_active_company(self.user_a)
        self._grant(self.user_b, self.empresa_a, ingresar=True)

        response = self.client.get(
            f"{self.url}?empresa=00",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "user-b")
        self.assertEqual(response.json()["auth_mode"], "bearer")

    def test_bearer_requires_explicit_empresa_even_when_session_has_one(self):
        _, token_value = self._create_token()
        self._login_with_active_company(self.user_a)

        response = self.client.get(self.url, HTTP_AUTHORIZATION=f"Bearer {token_value}")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "El parámetro empresa es obligatorio."})

    def test_bearer_rejects_unknown_and_invalid_empresa_codes(self):
        _, token_value = self._create_token()

        unknown = self.client.get(
            f"{self.url}?empresa=99",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )
        invalid = self.client.get(
            f"{self.url}?empresa=0",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )

        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(unknown.json(), {"detail": "Empresa no encontrada."})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json(), {"detail": "El parámetro empresa no es válido."})

    def test_bearer_does_not_modify_session_and_can_use_two_companies(self):
        _, token_value = self._create_token()
        self._login_with_active_company(self.user_a)
        self._grant(self.user_a, self.empresa_a, ingresar=True)
        self._grant(self.user_a, self.empresa_b, ingresar=True)
        original_empresa_id = self.client.session["empresa_id"]

        first = self.client.get(
            f"{self.url}?empresa=00",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )
        second = self.client.get(
            f"{self.url}?empresa=01",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["empresa"], "00")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["empresa"], "01")
        self.assertEqual(self.client.session["empresa_id"], original_empresa_id)

    def test_session_can_resolve_explicit_different_empresa_without_changing_session(self):
        self._login_with_active_company(self.user_a)
        self._grant(self.user_a, self.empresa_b, ingresar=True)
        original_empresa_id = self.client.session["empresa_id"]

        response = self.client.get(f"{self.url}?empresa=01")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["empresa"], "01")
        self.assertEqual(self.client.session["empresa_id"], original_empresa_id)

    def test_valid_permission_returns_200(self):
        _, token_value = self._create_token()
        self._grant(self.user_a, self.empresa_a, ingresar=True)

        response = self.client.get(
            f"{self.url}?empresa=00",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )

        self.assertEqual(response.status_code, 200)

    def test_missing_or_false_ingresar_returns_403(self):
        _, token_value = self._create_token()

        missing = self.client.get(
            f"{self.url}?empresa=00",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )
        self._grant(self.user_a, self.empresa_a, ingresar=False)
        false_flag = self.client.get(
            f"{self.url}?empresa=00",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )

        self.assertEqual(missing.status_code, 403)
        self.assertEqual(false_flag.status_code, 403)
        self.assertEqual(
            false_flag.json(),
            {"detail": "No tiene permisos para acceder a este recurso."},
        )

    def test_permission_in_other_empresa_returns_403(self):
        _, token_value = self._create_token()
        self._grant(self.user_a, self.empresa_a, ingresar=True)

        response = self.client.get(
            f"{self.url}?empresa=01",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )

        self.assertEqual(response.status_code, 403)

    def test_permission_belonging_to_other_user_returns_403(self):
        _, token_value = self._create_token(user=self.user_b)
        self._grant(self.user_a, self.empresa_a, ingresar=True)

        response = self.client.get(
            f"{self.url}?empresa=00",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )

        self.assertEqual(response.status_code, 403)

    def test_same_user_can_use_permission_in_two_companies(self):
        _, token_value = self._create_token()
        self._grant(self.user_a, self.empresa_a, ingresar=True)
        self._grant(self.user_a, self.empresa_b, ingresar=True)

        first = self.client.get(
            f"{self.url}?empresa=00",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )
        second = self.client.get(
            f"{self.url}?empresa=01",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

    def test_supervisor_bypasses_requested_permission(self):
        _, token_value = self._create_token()
        self._grant(self.user_a, self.empresa_a, supervisor=True)

        response = self.client.get(
            f"{self.url}?empresa=00",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )

        self.assertEqual(response.status_code, 200)

    def test_pipeline_reaches_403_only_after_valid_authentication_and_empresa(self):
        _, token_value = self._create_token()

        invalid_auth = self.client.get(
            f"{self.url}?empresa=00",
            HTTP_AUTHORIZATION="Bearer invalid-token",
        )
        valid_auth_invalid_empresa = self.client.get(
            f"{self.url}?empresa=99",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )
        valid_auth_empresa_no_permission = self.client.get(
            f"{self.url}?empresa=00",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )

        self.assertEqual(invalid_auth.status_code, 401)
        self.assertEqual(valid_auth_invalid_empresa.status_code, 404)
        self.assertEqual(valid_auth_empresa_no_permission.status_code, 403)
