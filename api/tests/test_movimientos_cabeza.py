import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


class _DummyCursor:
    def __init__(self, *, description=None, fetchall_results=None, fetchone_results=None):
        self.description = description or []
        self._fetchall_results = list(fetchall_results or [])
        self._fetchone_results = list(fetchone_results or [])
        self.executed = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        stmt = (sql or "").lstrip().upper()
        if stmt.startswith("UPDATE") or stmt.startswith("DELETE") or stmt.startswith("INSERT"):
            self.rowcount = 1
        else:
            self.rowcount = 0

    def fetchall(self):
        if self._fetchall_results:
            return self._fetchall_results.pop(0)
        return []

    def fetchone(self):
        if self._fetchone_results:
            return self._fetchone_results.pop(0)
        return None

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
    def __init__(self, mapping):
        self._mapping = dict(mapping)
        self.last_alias = None

    def __getitem__(self, alias):
        self.last_alias = alias
        if alias not in self._mapping:
            raise KeyError(alias)
        return self._mapping[alias]


class MovimientosCabezaApiTests(TestCase):
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
        from api.views_movimientos import VISTA_NOMBRE_MOVIMIENTOS_CABEZA

        vista = Vista.objects.create(nombre=VISTA_NOMBRE_MOVIMIENTOS_CABEZA)
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

    def test_list_invalid_rubro_returns_400(self):
        self._grant_all_perms()

        url = reverse("api_movimientos_cabeza_list")
        resp = self.client.get(url + "?rubro=2&local=19", HTTP_ACCEPT="application/json")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("detail"), "rubro inválido.")

    def test_list_returns_rows_with_pagination(self):
        self._grant_all_perms()

        cursor = _DummyCursor(
            description=[("tipo",), ("numero",), ("fecha",), ("glosa",)],
            fetchall_results=[[ ("FC", "12345", "2026-01-01", "X") ]],
        )
        conn = _DummyConnection(cursor)
        dummy_connections = _DummyConnections({"eltit_gestion02": conn})

        url = reverse("api_movimientos_cabeza_list")
        with patch("api.views_movimientos.connections", dummy_connections):
            resp = self.client.get(
                url + "?rubro=02&local=19&limit=100&offset=0",
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0]["tipo"], "FC")
        self.assertEqual(payload[0]["numero"], "12345")

        self.assertEqual(dummy_connections.last_alias, "eltit_gestion02")
        self.assertIn("FROM `l_movimientos_cabeza_19`", cursor.executed[0][0])
        self.assertIn("LIMIT 100", cursor.executed[0][0])
        self.assertIn("OFFSET 0", cursor.executed[0][0])

    def test_detail_missing_returns_404(self):
        self._grant_all_perms()

        cursor = _DummyCursor(
            description=[("tipo",), ("numero",), ("fecha",)],
            fetchall_results=[[]],
        )
        dummy_connections = _DummyConnections({"eltit_gestion02": _DummyConnection(cursor)})

        url = reverse("api_movimientos_cabeza_detail", kwargs={"tipo": "FC", "numero": "12345"})
        with patch("api.views_movimientos.connections", dummy_connections):
            resp = self.client.get(url + "?rubro=02&local=19", HTTP_ACCEPT="application/json")

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json().get("detail"), "No encontrado.")

    def test_detail_ambiguous_returns_409(self):
        self._grant_all_perms()

        cursor = _DummyCursor(
            description=[("tipo",), ("numero",), ("fecha",)],
            fetchall_results=[
                [
                    ("FC", "12345", "2026-01-01"),
                    ("FC", "12345", "2026-01-02"),
                ]
            ],
        )
        dummy_connections = _DummyConnections({"eltit_gestion02": _DummyConnection(cursor)})

        url = reverse("api_movimientos_cabeza_detail", kwargs={"tipo": "FC", "numero": "12345"})
        with patch("api.views_movimientos.connections", dummy_connections):
            resp = self.client.get(url + "?rubro=02&local=19", HTTP_ACCEPT="application/json")

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json().get("detail"), "Ambigüedad: múltiples fechas para tipo/numero.")

    def test_create_success_returns_201(self):
        self._grant_all_perms()

        cursor = _DummyCursor(fetchone_results=[None])
        conn = _DummyConnection(cursor)
        dummy_connections = _DummyConnections({"eltit_gestion02": conn})

        url = reverse("api_movimientos_cabeza_list")
        body = {
            "rubro": "02",
            "local": "19",
            "tipo": "FC",
            "numero": "12345",
            "fecha": "2026-01-01",
            "glosa": "X",
        }

        with patch("api.views_movimientos.connections", dummy_connections):
            resp = self.client.post(
                url,
                data=json.dumps(body),
                content_type="application/json",
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(resp.status_code, 201)
        payload = resp.json()
        self.assertEqual(payload.get("tipo"), "FC")
        self.assertEqual(payload.get("numero"), "12345")
        self.assertEqual(payload.get("fecha"), "2026-01-01")
        self.assertEqual(payload.get("glosa"), "X")

        self.assertEqual(len(cursor.executed), 2)
        self.assertIn("SELECT 1 FROM `l_movimientos_cabeza_19`", cursor.executed[0][0])
        self.assertIn("INSERT INTO `l_movimientos_cabeza_19`", cursor.executed[1][0])
        self.assertEqual(conn.commit_calls, 1)

    def test_create_existing_pk_returns_409(self):
        self._grant_all_perms()

        cursor = _DummyCursor(fetchone_results=[(1,)])
        conn = _DummyConnection(cursor)
        dummy_connections = _DummyConnections({"eltit_gestion02": conn})

        url = reverse("api_movimientos_cabeza_list")
        body = {
            "rubro": "02",
            "local": "19",
            "tipo": "FC",
            "numero": "12345",
            "fecha": "2026-01-01",
        }

        with patch("api.views_movimientos.connections", dummy_connections):
            resp = self.client.post(
                url,
                data=json.dumps(body),
                content_type="application/json",
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json().get("detail"), "Ya existe un registro con la misma PK.")
        self.assertEqual(len(cursor.executed), 1)
        self.assertEqual(conn.commit_calls, 0)

    def test_update_success_returns_200(self):
        self._grant_all_perms()

        cursor = _DummyCursor(
            description=[("tipo",), ("numero",), ("fecha",), ("glosa",)],
            fetchall_results=[[ ("FC", "12345", "2026-01-01", "OLD") ]],
        )
        conn = _DummyConnection(cursor)
        dummy_connections = _DummyConnections({"eltit_gestion02": conn})

        url = reverse("api_movimientos_cabeza_detail", kwargs={"tipo": "FC", "numero": "12345"})
        body = {"glosa": "NEW"}

        with patch("api.views_movimientos.connections", dummy_connections):
            resp = self.client.put(
                url + "?rubro=02&local=19",
                data=json.dumps(body),
                content_type="application/json",
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload.get("glosa"), "NEW")

        self.assertEqual(len(cursor.executed), 2)
        self.assertIn("SELECT * FROM `l_movimientos_cabeza_19`", cursor.executed[0][0])
        self.assertIn("UPDATE `l_movimientos_cabeza_19`", cursor.executed[1][0])
        self.assertEqual(conn.commit_calls, 1)

    def test_delete_success_returns_204(self):
        self._grant_all_perms()

        cursor = _DummyCursor(fetchall_results=[[ ("2026-01-01",) ]])
        conn = _DummyConnection(cursor)
        dummy_connections = _DummyConnections({"eltit_gestion02": conn})

        url = reverse("api_movimientos_cabeza_detail", kwargs={"tipo": "FC", "numero": "12345"})
        with patch("api.views_movimientos.connections", dummy_connections):
            resp = self.client.delete(url + "?rubro=02&local=19", HTTP_ACCEPT="application/json")

        self.assertEqual(resp.status_code, 204)
        self.assertEqual(len(cursor.executed), 2)
        self.assertIn("SELECT fecha FROM `l_movimientos_cabeza_19`", cursor.executed[0][0])
        self.assertIn("DELETE FROM `l_movimientos_cabeza_19`", cursor.executed[1][0])
        self.assertEqual(cursor.executed[1][1], ["FC", "12345", "2026-01-01"])
        self.assertEqual(conn.commit_calls, 1)
