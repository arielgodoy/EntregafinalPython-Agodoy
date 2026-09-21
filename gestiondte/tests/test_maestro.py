from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from gestiondte.consultassql import build_maestroempresa_by_codigo_query
from gestiondte.utils.maestro import get_maestroempresa_by_codigo


class MaestroEmpresaQueryTests(SimpleTestCase):
    def test_query_uses_global_schema_and_parameterized_company(self):
        query, params = build_maestroempresa_by_codigo_query("cliente_conta", "09")

        self.assertIn("FROM `cliente_conta`.maestroempresas", query)
        self.assertIn("codigoempresa, nombre, rut, rutenviasii", query)
        self.assertIn("LIMIT 1", query)
        self.assertEqual(params, ("09",))

    @patch("gestiondte.utils.maestro.open_mysql_connection")
    @patch("gestiondte.utils.maestro.SettingsMySQLConnection.objects.get")
    @patch("gestiondte.utils.maestro.get_gestiondte_connection")
    @patch("gestiondte.utils.maestro.get_legacy_database_name")
    def test_mysql_role_uses_global_database_without_fallback(
        self, database_name, get_role, get_config, open_connection
    ):
        database_name.return_value = "cliente_conta"
        get_role.return_value = {"type": "MYSQL_CONFIG", "connection_id": 7}
        config = MagicMock()
        get_config.return_value = config
        cursor = MagicMock()
        cursor.fetchone.return_value = ("09", "Empresa", "123", "456")
        connection = MagicMock()
        connection.cursor.return_value = cursor
        open_connection.return_value.__enter__.return_value = connection

        result = get_maestroempresa_by_codigo("09")

        self.assertEqual(result["codigo"], "09")
        database_name.assert_called_once_with("contabilidad", None)
        get_role.assert_called_once_with("servercontabilidad")
        open_connection.assert_called_once_with(config, database_name="cliente_conta")
        cursor.execute.assert_called_once()
        self.assertEqual(cursor.execute.call_args.args[1], ("09",))

    @patch("gestiondte.utils.maestro.open_mysql_connection")
    @patch("gestiondte.utils.maestro.get_gestiondte_connection")
    @patch("gestiondte.utils.maestro.get_legacy_database_name", return_value="cliente_conta")
    def test_role_error_does_not_scan_other_connections(self, get_database_name, get_role, open_connection):
        get_role.side_effect = RuntimeError("role unavailable")

        with self.assertRaises(RuntimeError):
            get_maestroempresa_by_codigo("09")

        open_connection.assert_not_called()
