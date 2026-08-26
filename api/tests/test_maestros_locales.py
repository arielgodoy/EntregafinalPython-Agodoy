import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from api.services.api_tokens import create_api_token


class _DummyCursor:
    def __init__(self, *, description=None, rows=None, row=None, rowcount=0):
        self.description = description or []
        self._rows = rows or []
        self._row = row
        self.rowcount = rowcount
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit_calls = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commit_calls += 1


class _DummyConnections:
    def __init__(self, connection):
        self._connection = connection

    def __getitem__(self, alias):
        if alias != "eltit_gestion":
            raise KeyError(alias)
        return self._connection


class MaestrosLocalesApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 1")
        self.vista_locales = Vista.objects.create(nombre="API - Maestros Locales")

        self.client = Client()
        self.client.force_login(self.user)

        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session.save()

    def _grant_all_perms(self):
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_locales,
            ingresar=True,
            crear=True,
            modificar=True,
            eliminar=True,
            autorizar=False,
            supervisor=False,
        )

    def _grant_ingresar(self, user, empresa, *, supervisor=False, ingresar=True):
        return Permiso.objects.create(
            usuario=user,
            empresa=empresa,
            vista=self.vista_locales,
            ingresar=ingresar,
            supervisor=supervisor,
        )

    def _create_bearer_token(self):
        _, token_value = create_api_token(user=self.user, name="Locales test")
        return token_value

    def test_get_list_returns_rows_and_colacion_numeric(self):
        self._grant_all_perms()

        from api.views_maestros import SQL_MAESTROS_LOCALES_LIST

        cursor = _DummyCursor(
            description=[
                ("codigo",),
                ("nombre",),
                ("direccion",),
                ("comuna",),
                ("ciudad",),
                ("giro",),
                ("rut",),
                ("ipremota",),
                ("ipmaster",),
                ("rubro",),
                ("nombrelocal",),
                ("colacion",),
            ],
            rows=[
                (
                    "01",
                    "Empresa",
                    "Dir 1",
                    "Comuna",
                    "Ciudad",
                    "Giro",
                    "1-9",
                    "10.0.0.1",
                    "10.0.0.2",
                    "01",
                    "Local 1",
                    1500.5,
                ),
                (
                    "02",
                    "Empresa 2",
                    "Dir 2",
                    "Comuna 2",
                    "Ciudad 2",
                    "Giro 2",
                    "2-7",
                    "10.0.0.3",
                    "10.0.0.4",
                    "02",
                    "Local 2",
                    0.0,
                ),
            ],
        )
        dummy_connections = _DummyConnections(_DummyConnection(cursor))

        url = reverse("api_maestros_locales_list")
        with patch("api.views_maestros.connections", dummy_connections):
            resp = self.client.get(url, HTTP_ACCEPT="application/json")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0]["codigo"], "01")
        self.assertEqual(payload[0]["colacion"], 1500.5)
        self.assertIsInstance(payload[0]["colacion"], float)
        self.assertIs(isinstance(payload[0]["colacion"], bool), False)

        self.assertEqual(cursor.executed[0][0], SQL_MAESTROS_LOCALES_LIST)

    def test_bearer_allowed_uses_validated_empresa_and_preserves_json(self):
        token_value = self._create_bearer_token()
        self._grant_ingresar(self.user, self.empresa)
        cursor = _DummyCursor(
            description=[("codigo",), ("nombrelocal",)],
            rows=[("01", "Local 1")],
        )
        dummy_connections = _DummyConnections(_DummyConnection(cursor))

        with patch("api.views_maestros.connections", dummy_connections), patch(
            "api.views_maestros.resolve_db_for_empresa",
            return_value=("django", None),
        ) as resolve_db:
            response = self.client.get(
                reverse("api_maestros_locales_list") + "?empresa=01&rubro=02",
                HTTP_AUTHORIZATION=f"Bearer {token_value}",
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"codigo": "01", "nombrelocal": "Local 1"}])
        self.assertEqual(resolve_db.call_args.args[0], self.empresa)

    def test_bearer_without_permission_does_not_open_connection(self):
        token_value = self._create_bearer_token()

        with patch("api.views_maestros.resolve_db_for_empresa") as resolve_db:
            response = self.client.get(
                reverse("api_maestros_locales_list") + "?empresa=01",
                HTTP_AUTHORIZATION=f"Bearer {token_value}",
            )

        self.assertEqual(response.status_code, 403)
        resolve_db.assert_not_called()

    def test_bearer_other_empresa_permission_does_not_open_connection(self):
        token_value = self._create_bearer_token()
        self._grant_ingresar(self.user, self.empresa)
        other_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa 2")

        with patch("api.views_maestros.resolve_db_for_empresa") as resolve_db:
            response = self.client.get(
                reverse("api_maestros_locales_list") + "?empresa=02",
                HTTP_AUTHORIZATION=f"Bearer {token_value}",
            )

        self.assertEqual(response.status_code, 403)
        resolve_db.assert_not_called()

    def test_bearer_missing_empresa_does_not_open_connection(self):
        token_value = self._create_bearer_token()

        with patch("api.views_maestros.resolve_db_for_empresa") as resolve_db:
            response = self.client.get(
                reverse("api_maestros_locales_list"),
                HTTP_AUTHORIZATION=f"Bearer {token_value}",
            )

        self.assertEqual(response.status_code, 400)
        resolve_db.assert_not_called()

    def test_bearer_unknown_empresa_does_not_open_connection(self):
        token_value = self._create_bearer_token()

        with patch("api.views_maestros.resolve_db_for_empresa") as resolve_db:
            response = self.client.get(
                reverse("api_maestros_locales_list") + "?empresa=99",
                HTTP_AUTHORIZATION=f"Bearer {token_value}",
            )

        self.assertEqual(response.status_code, 404)
        resolve_db.assert_not_called()

    def test_bearer_invalid_does_not_open_connection(self):
        with patch("api.views_maestros.resolve_db_for_empresa") as resolve_db:
            response = self.client.get(
                reverse("api_maestros_locales_list") + "?empresa=01",
                HTTP_AUTHORIZATION="Bearer invalid-token",
            )

        self.assertEqual(response.status_code, 401)
        resolve_db.assert_not_called()

    def test_session_explicit_empresa_uses_selected_empresa_without_changing_session(self):
        other_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa 2")
        self._grant_ingresar(self.user, other_empresa)
        original_empresa_id = self.client.session["empresa_id"]
        tokenless_connection_result = ("django", None)
        dummy_connections = _DummyConnections(_DummyConnection(_DummyCursor()))

        with patch("api.views_maestros.connections", dummy_connections), patch(
            "api.views_maestros.resolve_db_for_empresa",
            return_value=tokenless_connection_result,
        ) as resolve_db:
            response = self.client.get(
                reverse("api_maestros_locales_list") + "?empresa=02",
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(resolve_db.call_args.args[0], other_empresa)
        self.assertEqual(self.client.session["empresa_id"], original_empresa_id)

    def test_same_bearer_uses_two_authorized_companies(self):
        token_value = self._create_bearer_token()
        other_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa 2")
        self._grant_ingresar(self.user, self.empresa)
        self._grant_ingresar(self.user, other_empresa)
        dummy_connections = _DummyConnections(_DummyConnection(_DummyCursor()))

        with patch("api.views_maestros.connections", dummy_connections), patch(
            "api.views_maestros.resolve_db_for_empresa",
            return_value=("django", None),
        ) as resolve_db:
            first = self.client.get(
                reverse("api_maestros_locales_list") + "?empresa=01",
                HTTP_AUTHORIZATION=f"Bearer {token_value}",
            )
            second = self.client.get(
                reverse("api_maestros_locales_list") + "?empresa=02",
                HTTP_AUTHORIZATION=f"Bearer {token_value}",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(resolve_db.call_args_list[0].args[0], self.empresa)
        self.assertEqual(resolve_db.call_args_list[1].args[0], other_empresa)

    def test_ingresar_false_and_supervisor_preserve_icmeas_semantics(self):
        token_value = self._create_bearer_token()
        self._grant_ingresar(self.user, self.empresa, ingresar=False)
        denied = self.client.get(
            reverse("api_maestros_locales_list") + "?empresa=01",
            HTTP_AUTHORIZATION=f"Bearer {token_value}",
        )
        self.assertEqual(denied.status_code, 403)

        permiso = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_locales,
        )
        permiso.supervisor = True
        permiso.save(update_fields=["supervisor"])
        dummy_connections = _DummyConnections(_DummyConnection(_DummyCursor()))
        with patch("api.views_maestros.connections", dummy_connections):
            allowed = self.client.get(
                reverse("api_maestros_locales_list") + "?empresa=01",
                HTTP_AUTHORIZATION=f"Bearer {token_value}",
            )
        self.assertEqual(allowed.status_code, 200)

    def test_get_detail_missing_returns_404(self):
        self._grant_all_perms()

        from api.views_maestros import SQL_MAESTROS_LOCALES_GET

        cursor = _DummyCursor(row=None)
        dummy_connections = _DummyConnections(_DummyConnection(cursor))

        url = reverse("api_maestros_locales_detail", kwargs={"codigo": "99"})
        with patch("api.views_maestros.connections", dummy_connections):
            resp = self.client.get(url, HTTP_ACCEPT="application/json")

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json().get("detail"), "No encontrado.")
        self.assertEqual(cursor.executed[0][0], SQL_MAESTROS_LOCALES_GET)
        self.assertEqual(cursor.executed[0][1], ["99"])

    def test_post_create_inserts_and_returns_201(self):
        self._grant_all_perms()

        from api.views_maestros import SQL_MAESTROS_LOCALES_INSERT

        cursor = _DummyCursor()
        conn = _DummyConnection(cursor)
        dummy_connections = _DummyConnections(conn)

        url = reverse("api_maestros_locales_list")
        body = {
            "codigo": "03",
            "nombre": "Empresa 3",
            "direccion": "Dir 3",
            "comuna": "Comuna 3",
            "ciudad": "Ciudad 3",
            "giro": "Giro 3",
            "rut": "3-5",
            "ipremota": "10.0.0.5",
            "ipmaster": "10.0.0.6",
            "rubro": "03",
            "nombrelocal": "Local 3",
            "colacion": 1200.0,
        }

        with patch("api.views_maestros.connections", dummy_connections):
            resp = self.client.post(
                url,
                data=json.dumps(body),
                content_type="application/json",
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(resp.status_code, 201)
        payload = resp.json()
        self.assertEqual(payload.get("codigo"), "03")
        self.assertEqual(payload.get("nombrelocal"), "Local 3")
        self.assertEqual(payload.get("colacion"), 1200.0)

        self.assertEqual(cursor.executed[0][0], SQL_MAESTROS_LOCALES_INSERT)
        self.assertEqual(len(cursor.executed[0][1]), 29)
        self.assertEqual(conn.commit_calls, 1)

    def test_put_update_missing_returns_404(self):
        self._grant_all_perms()

        from api.views_maestros import SQL_MAESTROS_LOCALES_UPDATE

        cursor = _DummyCursor(rowcount=0)
        conn = _DummyConnection(cursor)
        dummy_connections = _DummyConnections(conn)

        url = reverse("api_maestros_locales_detail", kwargs={"codigo": "01"})
        body = {
            "nombre": "Empresa",
            "direccion": "Dir",
            "comuna": "Comuna",
            "ciudad": "Ciudad",
            "giro": "Giro",
            "rut": "1-9",
            "ipremota": "10.0.0.1",
            "ipmaster": "10.0.0.2",
            "rubro": "01",
            "nombrelocal": "Local",
            "colacion": 0.0,
        }

        with patch("api.views_maestros.connections", dummy_connections):
            resp = self.client.put(
                url,
                data=json.dumps(body),
                content_type="application/json",
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json().get("detail"), "No encontrado.")
        self.assertEqual(cursor.executed[0][0], SQL_MAESTROS_LOCALES_UPDATE)
        self.assertEqual(conn.commit_calls, 0)

    def test_delete_success_returns_204(self):
        self._grant_all_perms()

        from api.views_maestros import SQL_MAESTROS_LOCALES_DELETE

        cursor = _DummyCursor(rowcount=1)
        conn = _DummyConnection(cursor)
        dummy_connections = _DummyConnections(conn)

        url = reverse("api_maestros_locales_detail", kwargs={"codigo": "01"})
        with patch("api.views_maestros.connections", dummy_connections):
            resp = self.client.delete(url, HTTP_ACCEPT="application/json")

        self.assertEqual(resp.status_code, 204)
        self.assertEqual(cursor.executed[0][0], SQL_MAESTROS_LOCALES_DELETE)
        self.assertEqual(cursor.executed[0][1], ["01"])
        self.assertEqual(conn.commit_calls, 1)
