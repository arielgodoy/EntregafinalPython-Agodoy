import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


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

        self.client = Client()
        self.client.force_login(self.user)

        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session.save()

    def _grant_all_perms(self):
        from api.views_maestros import VISTA_NOMBRE_LOCALES

        vista = Vista.objects.create(nombre=VISTA_NOMBRE_LOCALES)
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            ingresar=True,
            crear=True,
            modificar=True,
            eliminar=True,
            autorizar=False,
            supervisor=False,
        )

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
