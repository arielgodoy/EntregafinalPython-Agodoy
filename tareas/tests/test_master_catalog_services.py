from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.utils import timezone

from tareas.services.department_catalog import (
    DepartmentInput,
    create_department,
    set_department_active,
)
from tareas.services.locals import LocalInput, create_local, set_local_active
from tareas.services.master_catalog_common import (
    CompanyContext,
    MasterCatalogBackendError,
    MasterCatalogCapabilityBlocked,
    MasterCatalogConflict,
    MasterCatalogValidationError,
    MutationMetadata,
    execute_or_raise_conflict,
    require_metadata,
    verify_base_tareas_database,
)
from tareas.services.providers import (
    ProviderInput,
    _normalize_input as normalize_provider_input,
)


def _metadata():
    return MutationMetadata(
        operation_id=str(uuid4()),
        actor_id=7,
        motivo="prueba unitaria",
    )


class MasterCatalogContractTests(SimpleTestCase):
    def test_base_tareas_identity_uses_the_configured_database_name(self):
        class Cursor:
            def execute(self, _sql):
                return None

            def fetchone(self):
                return ("django_lab",)

            def close(self):
                return None

        class Connection:
            def cursor(self):
                return Cursor()

        verify_base_tareas_database(
            Connection(),
            expected_database="django_lab",
        )
        with self.assertRaises(MasterCatalogBackendError):
            verify_base_tareas_database(
                Connection(),
                expected_database="tareas",
            )

    def test_company_context_rejects_non_integer_company(self):
        with self.assertRaises(MasterCatalogValidationError):
            CompanyContext("1").validate()

    def test_metadata_requires_uuid(self):
        metadata = MutationMetadata("not-a-uuid", 7, "motivo")
        with self.assertRaises(MasterCatalogValidationError):
            require_metadata(metadata)

    def test_metadata_rejects_blank_reason(self):
        with self.assertRaises(MasterCatalogValidationError):
            require_metadata(MutationMetadata(str(uuid4()), 7, "   "))

    def test_provider_rut_is_normalized_by_the_tareas_utility(self):
        values = normalize_provider_input(
            ProviderInput(rut="76.123.456-0", nombre="Proveedor")
        )
        self.assertEqual(values[0], "76123456-0")

    def test_provider_empty_rut_is_normalized_to_null(self):
        values = normalize_provider_input(
            ProviderInput(rut=" . - ", nombre="Proveedor")
        )
        self.assertIsNone(values[0])

    def test_provider_invalid_rut_is_rejected(self):
        with self.assertRaises(MasterCatalogValidationError):
            normalize_provider_input(
                ProviderInput(rut="76.123.456-1", nombre="Proveedor")
            )

    def test_department_rejects_unknown_source(self):
        from tareas.services.department_catalog import _normalize_input

        with self.assertRaises(MasterCatalogCapabilityBlocked):
            _normalize_input(DepartmentInput("D-1", "Departamento", source="BAD"))

    def test_department_update_requires_local_source(self):
        from tareas.services.department_catalog import _update_department_name

        with patch(
            "tareas.services.department_catalog._read_department",
            return_value=SimpleNamespace(source="IMPORT"),
        ), patch(
            "tareas.services.department_catalog.execute_master_mutation",
            side_effect=lambda **kwargs: kwargs["mutate"](SimpleNamespace(
                execute=lambda *_args: None,
                fetchone=lambda: None,
            )),
        ):
            with self.assertRaises(MasterCatalogCapabilityBlocked):
                _update_department_name(
                    CompanyContext(1),
                    4,
                    "Nuevo nombre",
                    metadata=_metadata(),
                )

    def test_local_erp_write_is_blocked(self):
        with self.assertRaises(MasterCatalogCapabilityBlocked):
            create_local(
                CompanyContext(1),
                LocalInput("ERP-1", "Local ERP", source="ERP"),
                metadata=_metadata(),
            )

    def test_local_lifecycle_is_blocked_until_t227(self):
        with self.assertRaises(MasterCatalogCapabilityBlocked):
            set_local_active(
                CompanyContext(1),
                4,
                False,
                metadata=_metadata(),
            )

    def test_department_lifecycle_is_blocked_until_contracts(self):
        with self.assertRaises(MasterCatalogCapabilityBlocked):
            set_department_active(
                CompanyContext(1),
                4,
                False,
                metadata=_metadata(),
            )

    def test_catalog_mutations_use_parameterized_sql_and_metadata(self):
        now = timezone.now()
        cursor = SimpleNamespace(
            lastrowid=42,
            close=lambda: None,
            fetchone=lambda: (42, 1, "D-1", "Departamento", True, "LOCAL", now, now),
        )
        executed = []

        def execute(sql, params=()):
            executed.append((sql, params))

        cursor.execute = execute

        def execute_mutation(**kwargs):
            change = kwargs["mutate"](cursor)
            return SimpleNamespace(
                id=change.result_id,
                operation_id=kwargs["metadata"].operation_id,
                audit_status="CONFIRMED",
            )

        with patch(
            "tareas.services.department_catalog.execute_master_mutation",
            side_effect=execute_mutation,
        ):
            result = create_department(
                CompanyContext(1),
                DepartmentInput("D-1", "Departamento"),
                metadata=_metadata(),
            )

        self.assertEqual(result.id, 42)
        self.assertIn("%s", executed[0][0])
        self.assertEqual(executed[0][1][0], 1)

    def test_duplicate_errors_are_domain_conflicts(self):
        class DuplicateError(Exception):
            errno = 1062

        class Cursor:
            def execute(self, sql, params):
                raise DuplicateError()

        with self.assertRaises(MasterCatalogConflict):
            execute_or_raise_conflict(Cursor(), "INSERT INTO x VALUES (%s)", (1,))
