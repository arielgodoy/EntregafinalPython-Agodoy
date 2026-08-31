import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from access_control.models import Empresa, Permiso, Vista
from api.views import INVITAR_USUARIO_VISTA_NOMBRE


class InviteUserApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="api-user", password="pass")
        self.empresa_a = Empresa.objects.create(codigo="00", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="01", descripcion="Empresa B")
        self.vista = Vista.objects.create(nombre=INVITAR_USUARIO_VISTA_NOMBRE)
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa_a.id
        session.save()
        self.url = "/api/v1/auth/invite/"

    def _request(self, empresa):
        return self.client.post(
            self.url,
            data=json.dumps({"email": "new@example.com", "empresa_id": empresa.id}),
            content_type="application/json",
        )

    def _grant(self, empresa, **flags):
        return Permiso.objects.create(
            usuario=self.user,
            empresa=empresa,
            vista=self.vista,
            **flags,
        )

    def test_missing_create_permission_in_target_company_returns_403(self):
        response = self._request(self.empresa_a)

        self.assertEqual(response.status_code, 403)

    def test_permission_in_other_company_does_not_authorize_target(self):
        self._grant(self.empresa_b, crear=True)

        response = self._request(self.empresa_a)

        self.assertEqual(response.status_code, 403)

    @patch("api.views.invite_user_flow", return_value={"ok": True})
    def test_target_company_create_permission_authorizes_without_auth_invite(self, invite_flow):
        self._grant(self.empresa_a, crear=True)

        response = self._request(self.empresa_a)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertFalse(Vista.objects.filter(nombre="auth_invite").exists())
        invite_flow.assert_called_once()