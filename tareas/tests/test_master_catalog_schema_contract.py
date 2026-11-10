from django.test import SimpleTestCase

from tareas.services.base_tareas_schema import (
    MASTER_CATALOG_SCHEMA_PATH,
    MASTER_OPERATION_SCHEMA_PATH,
    _parse_expected_schema,
    _read_frozen_schema_statements,
)


class MasterCatalogSchemaContractTests(SimpleTestCase):
    def test_approved_manifests_are_part_of_read_only_preflight_contract(self):
        statements = _read_frozen_schema_statements()
        joined = "\n".join(statements)

        self.assertTrue(MASTER_CATALOG_SCHEMA_PATH.exists())
        self.assertTrue(MASTER_OPERATION_SCHEMA_PATH.exists())
        self.assertIn("organizacion_departamento", joined)
        self.assertIn("organizacion_local", joined)
        self.assertIn("proveedores_proveedor", joined)
        self.assertIn("tareas_master_operation", joined)
        self.assertFalse(
            any(
                statement.lstrip().upper().startswith(
                    ("DROP ", "TRUNCATE ", "DELETE ")
                )
                for statement in statements
            )
        )

    def test_inline_indexes_are_not_parsed_as_columns(self):
        schema = _parse_expected_schema(_read_frozen_schema_statements())

        proveedor = schema["tables"]["proveedores_proveedor"]
        local = schema["tables"]["organizacion_local"]
        operation = schema["tables"]["tareas_master_operation"]

        self.assertNotIn("UNIQUE", proveedor["columns"])
        self.assertNotIn("UNIQUE", local["columns"])
        self.assertEqual(
            proveedor["unique"],
            {("rut",)},
        )
        self.assertEqual(
            local["unique"],
            {("empresa_id", "codigo")},
        )
        self.assertEqual(
            proveedor["ordinary"],
            {("activo", "nombre"), ("nombre",)},
        )
        self.assertIn("updated_at", operation["columns"])
