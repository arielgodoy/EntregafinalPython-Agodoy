from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from gestiondte.consultassql import build_maestroempresa_by_codigo_query
from gestiondte.services.connection_roles import GestionDTECompanyMismatchError
from gestiondte.utils.maestro import get_maestroempresa_by_codigo


class MaestroEmpresaQueryTests(SimpleTestCase):
    def test_query_uses_global_schema_and_parameterized_company(self):
        query, params = build_maestroempresa_by_codigo_query("cliente_conta", "09")

        self.assertIn("FROM `cliente_conta`.maestroempresas", query)
        self.assertIn("codigoempresa, nombre, rut, rutenviasii", query)
        self.assertIn("LIMIT 1", query)
        self.assertEqual(params, ("09",))

    @patch("gestiondte.utils.maestro.get_gestiondte_connection")
    def test_company_code_cannot_override_active_company(self, get_role):
        with self.assertRaises(GestionDTECompanyMismatchError):
            get_maestroempresa_by_codigo(
                "02",
                empresa=SimpleNamespace(codigo="01", pk=1),
            )

        get_role.assert_not_called()

    def test_dynamic_sql_identifiers_are_rejected(self):
        for unsafe in ("", "cliente conta", "cliente`conta", "cliente.conta", "cliente;DROP"):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ValueError):
                    build_maestroempresa_by_codigo_query(unsafe, "09")

        with self.assertRaises(ValueError):
            from gestiondte.consultassql import build_certificado_insert_query

            build_certificado_insert_query({"archivo` = %s --": "value"})

    @patch("gestiondte.utils.maestro.open_mysql_connection")
    @patch("gestiondte.utils.maestro.get_gestiondte_mysql_connection")
    @patch("gestiondte.utils.maestro.get_gestiondte_connection")
    def test_mysql_role_uses_global_database_without_fallback(
        self, get_role, get_mysql_config, open_connection
    ):
        get_role.return_value = {"type": "MYSQL_CONFIG", "database_name": "cliente_conta"}
        config = MagicMock()
        get_mysql_config.return_value = config
        cursor = MagicMock()
        cursor.fetchone.return_value = ("09", "Empresa", "123", "456")
        connection = MagicMock()
        connection.cursor.return_value = cursor
        open_connection.return_value.__enter__.return_value = connection

        result = get_maestroempresa_by_codigo("09")

        self.assertEqual(result["codigo"], "09")
        get_role.assert_called_once_with("servercontabilidad")
        get_mysql_config.assert_called_once_with("servercontabilidad")
        open_connection.assert_called_once_with(config, database_name="cliente_conta")
        cursor.execute.assert_called_once()
        self.assertEqual(cursor.execute.call_args.args[1], ("09",))

    @patch("gestiondte.utils.maestro.open_mysql_connection")
    @patch(
        "gestiondte.utils.maestro.get_gestiondte_mysql_connection",
        side_effect=RuntimeError("role unavailable"),
    )
    @patch(
        "gestiondte.utils.maestro.get_gestiondte_connection",
        return_value={"type": "MYSQL_CONFIG", "database_name": "cliente_conta"},
    )
    def test_mysql_resolver_error_does_not_open_connection(
        self, get_role, get_mysql_config, open_connection
    ):
        with self.assertRaises(RuntimeError):
            get_maestroempresa_by_codigo("09")

        get_role.assert_called_once_with("servercontabilidad")
        get_mysql_config.assert_called_once_with("servercontabilidad")
        open_connection.assert_not_called()

    @patch("gestiondte.utils.maestro.open_mysql_connection")
    @patch("gestiondte.utils.maestro.get_gestiondte_connection")
    def test_role_error_does_not_scan_other_connections(self, get_role, open_connection):
        get_role.side_effect = RuntimeError("role unavailable")

        with self.assertRaises(RuntimeError):
            get_maestroempresa_by_codigo("09")

        open_connection.assert_not_called()
