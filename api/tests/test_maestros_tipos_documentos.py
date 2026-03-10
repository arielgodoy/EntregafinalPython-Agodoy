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


class MaestrosTiposDocumentosApiTests(TestCase):
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
        from api.views_maestros import VISTA_NOMBRE_TIPOS_DOCUMENTOS

        vista = Vista.objects.create(nombre=VISTA_NOMBRE_TIPOS_DOCUMENTOS)
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

    def test_get_list_returns_rows(self):
        self._grant_all_perms()

        from api.views_maestros import SQL_MAESTROS_TIPOS_DOCUMENTOS_LIST

        cursor = _DummyCursor(
            description=[
                ("tipos",),
                ("nombredocumento",),
                ("operacion",),
                ("tipodos",),
                ("cuentadebe",),
                ("cuentahaber",),
                ("costo",),
            ],
            rows=[
                ("01", "FACTURA", "V", "A", "11000001", "41000001", "N"),
                ("02", "BOLETA", "V", "B", "11000002", "41000002", "S"),
            ],
        )
        dummy_connections = _DummyConnections(_DummyConnection(cursor))

        url = reverse("api_maestros_tipos_documentos_list")
        with patch("api.views_maestros.connections", dummy_connections):
            resp = self.client.get(url, HTTP_ACCEPT="application/json")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0]["tipos"], "01")
        self.assertEqual(payload[0]["nombredocumento"], "FACTURA")
        self.assertEqual(cursor.executed[0][0], SQL_MAESTROS_TIPOS_DOCUMENTOS_LIST)

    def test_get_detail_missing_returns_404(self):
        self._grant_all_perms()

        from api.views_maestros import SQL_MAESTROS_TIPOS_DOCUMENTOS_GET

        cursor = _DummyCursor(row=None)
        dummy_connections = _DummyConnections(_DummyConnection(cursor))

        url = reverse("api_maestros_tipos_documentos_detail", kwargs={"tipos": "99"})
        with patch("api.views_maestros.connections", dummy_connections):
            resp = self.client.get(url, HTTP_ACCEPT="application/json")

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json().get("detail"), "No encontrado.")
        self.assertEqual(cursor.executed[0][0], SQL_MAESTROS_TIPOS_DOCUMENTOS_GET)
        self.assertEqual(cursor.executed[0][1], ["99"])

    def test_post_create_inserts_and_returns_201(self):
        self._grant_all_perms()

        from api.views_maestros import SQL_MAESTROS_TIPOS_DOCUMENTOS_INSERT

        cursor = _DummyCursor()
        conn = _DummyConnection(cursor)
        dummy_connections = _DummyConnections(conn)

        url = reverse("api_maestros_tipos_documentos_list")
        body = {
            "tipos": "01",
            "nombredocumento": "FACTURA",
            "operacion": "V",
            "tipodos": "A",
            "cuentadebe": "11000001",
            "cuentahaber": "41000001",
            "costo": "N",
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
        self.assertEqual(payload.get("tipos"), "01")
        self.assertEqual(payload.get("nombredocumento"), "FACTURA")

        self.assertEqual(cursor.executed[0][0], SQL_MAESTROS_TIPOS_DOCUMENTOS_INSERT)
        self.assertEqual(len(cursor.executed[0][1]), 7)
        self.assertEqual(conn.commit_calls, 1)

    def test_put_update_missing_returns_404(self):
        self._grant_all_perms()

        from api.views_maestros import SQL_MAESTROS_TIPOS_DOCUMENTOS_UPDATE

        cursor = _DummyCursor(rowcount=0)
        conn = _DummyConnection(cursor)
        dummy_connections = _DummyConnections(conn)

        url = reverse("api_maestros_tipos_documentos_detail", kwargs={"tipos": "01"})
        body = {
            "nombredocumento": "FACTURA",
            "operacion": "V",
            "tipodos": "A",
            "cuentadebe": "11000001",
            "cuentahaber": "41000001",
            "costo": "N",
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
        self.assertEqual(cursor.executed[0][0], SQL_MAESTROS_TIPOS_DOCUMENTOS_UPDATE)
        self.assertEqual(conn.commit_calls, 0)

    def test_delete_success_returns_204(self):
        self._grant_all_perms()

        from api.views_maestros import SQL_MAESTROS_TIPOS_DOCUMENTOS_DELETE

        cursor = _DummyCursor(rowcount=1)
        conn = _DummyConnection(cursor)
        dummy_connections = _DummyConnections(conn)

        url = reverse("api_maestros_tipos_documentos_detail", kwargs={"tipos": "01"})
        with patch("api.views_maestros.connections", dummy_connections):
            resp = self.client.delete(url, HTTP_ACCEPT="application/json")

        self.assertEqual(resp.status_code, 204)
        self.assertEqual(cursor.executed[0][0], SQL_MAESTROS_TIPOS_DOCUMENTOS_DELETE)
        self.assertEqual(cursor.executed[0][1], ["01"])
        self.assertEqual(conn.commit_calls, 1)
