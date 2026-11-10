import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AppDocs.settings")
django.setup()

from tareas.services.department_catalog import (
    DepartmentInput,
    create_department,
    get_department,
    update_department_name,
)
from tareas.services.locals import (
    LocalInput,
    create_local,
    get_local,
    update_local,
)
from tareas.services.master_catalog_common import (
    CompanyContext,
    MasterCatalogConflict,
    MasterCatalogNotFound,
    MutationMetadata,
    verified_base_tareas_connection,
)
from tareas.services.providers import (
    ProviderInput,
    create_provider,
    get_provider,
    set_provider_active,
    update_provider,
)
from tareas.utils.rut import calcular_digito_verificador


@unittest.skipUnless(
    os.environ.get("RUN_TAREAS_MYSQL_TESTS") == "1",
    "requiere RUN_TAREAS_MYSQL_TESTS=1 y BASE_TAREAS verificado",
)
class MasterCatalogMySQLTests(unittest.TestCase):
    def setUp(self):
        self.operation_ids = []
        self.provider_ids = []
        self.audit_patch = patch(
            "tareas.services.master_operation_service.log_master_catalog_operation",
            return_value=SimpleNamespace(pk=900001),
        )
        self.audit_patch.start()
        self.addCleanup(self.audit_patch.stop)

    def _metadata(self):
        operation_id = str(uuid4())
        self.operation_ids.append(operation_id)
        return MutationMetadata(operation_id, 1, "certificacion real de catalogos")

    def _available_rut(self):
        for _attempt in range(10):
            body = str(uuid4().int % 100_000_000).zfill(8)
            rut = f"{body}-{calcular_digito_verificador(body)}"
            with verified_base_tareas_connection() as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        "SELECT id FROM proveedores_proveedor WHERE rut=%s",
                        (rut,),
                    )
                    if cursor.fetchone() is None:
                        return rut
                finally:
                    cursor.close()
        self.fail("No se pudo reservar un RUT sintético libre para la prueba.")

    def _cleanup(
        self,
        *,
        local_code=None,
        department_code=None,
        company_id=None,
    ):
        with verified_base_tareas_connection() as connection:
            cursor = connection.cursor()
            try:
                for provider_id in self.provider_ids:
                    cursor.execute(
                        "DELETE FROM proveedores_proveedor WHERE id=%s",
                        (provider_id,),
                    )
                if local_code:
                    cursor.execute(
                        "DELETE FROM organizacion_local "
                        "WHERE empresa_id=%s AND codigo=%s",
                        (company_id, local_code),
                    )
                if department_code:
                    cursor.execute(
                        "DELETE FROM organizacion_departamento "
                        "WHERE empresa_id=%s AND codigo=%s",
                        (company_id, department_code),
                    )
                for operation_id in self.operation_ids:
                    cursor.execute(
                        "DELETE FROM tareas_master_operation WHERE operation_id=%s",
                        (operation_id,),
                    )
                connection.commit()
                if self.provider_ids:
                    placeholders = ", ".join(["%s"] * len(self.provider_ids))
                    cursor.execute(
                        "SELECT COUNT(*) FROM proveedores_proveedor "
                        f"WHERE id IN ({placeholders})",
                        tuple(self.provider_ids),
                    )
                    self.assertEqual(cursor.fetchone()[0], 0)
                if local_code:
                    cursor.execute(
                        "SELECT COUNT(*) FROM organizacion_local "
                        "WHERE empresa_id=%s AND codigo=%s",
                        (company_id, local_code),
                    )
                    self.assertEqual(cursor.fetchone()[0], 0)
                if department_code:
                    cursor.execute(
                        "SELECT COUNT(*) FROM organizacion_departamento "
                        "WHERE empresa_id=%s AND codigo=%s",
                        (company_id, department_code),
                    )
                    self.assertEqual(cursor.fetchone()[0], 0)
                if self.operation_ids:
                    placeholders = ", ".join(["%s"] * len(self.operation_ids))
                    cursor.execute(
                        "SELECT COUNT(*) FROM tareas_master_operation "
                        f"WHERE operation_id IN ({placeholders})",
                        tuple(self.operation_ids),
                    )
                    self.assertEqual(cursor.fetchone()[0], 0)
            finally:
                cursor.close()

    def test_company_isolation_and_department_commit(self):
        suffix = uuid4().hex
        local_code = f"__CERT_LOCAL_{suffix}"
        department_code = f"__CERT_DEPT_{suffix}"
        try:
            local_context = CompanyContext(910001, actor_id=1)
            local = create_local(
                local_context,
                LocalInput(local_code, "Local de certificacion"),
                metadata=self._metadata(),
            )
            updated_local = update_local(
                local_context,
                local.id,
                LocalInput(local_code, "Local de certificacion editado"),
                metadata=self._metadata(),
            )
            self.assertEqual(updated_local.id, local.id)
            department = create_department(
                CompanyContext(910001),
                DepartmentInput(department_code, "Departamento de certificacion"),
                metadata=self._metadata(),
            )
            department = get_department(CompanyContext(910001), department.id)
            updated_department = update_department_name(
                CompanyContext(910001, actor_id=1),
                department.id,
                "Departamento editado",
                metadata=self._metadata(),
            )
            self.assertEqual(updated_department.id, department.id)
            self.assertEqual(get_local(local_context, local.id).empresa_id, 910001)
            with self.assertRaises(MasterCatalogNotFound):
                get_local(CompanyContext(910002), local.id)
            with self.assertRaises(MasterCatalogNotFound):
                get_department(CompanyContext(910002), department.id)
        finally:
            self._cleanup(
                local_code=local_code,
                department_code=department_code,
                company_id=910001,
            )

    def test_provider_is_global_and_lifecycle_is_logical(self):
        suffix = uuid4().hex
        provider_name = f"__CERT_PROVIDER_{suffix}"
        rut = self._available_rut()
        context = CompanyContext(910004, actor_id=1)
        try:
            provider = create_provider(
                context,
                ProviderInput(rut=rut, nombre=provider_name),
                metadata=self._metadata(),
            )
            self.provider_ids.append(provider.id)
            self.assertEqual(get_provider(provider.id).rut, rut)
            with self.assertRaises(MasterCatalogConflict):
                create_provider(
                    CompanyContext(910005, actor_id=1),
                    ProviderInput(rut=rut, nombre=f"{provider_name}_DUPLICATE"),
                    metadata=self._metadata(),
                )

            updated = update_provider(
                context,
                provider.id,
                ProviderInput(rut=rut, nombre=f"{provider_name}_UPDATED"),
                metadata=self._metadata(),
            )
            self.assertEqual(updated.id, provider.id)
            set_provider_active(
                context,
                provider.id,
                False,
                metadata=self._metadata(),
            )
            self.assertFalse(get_provider(provider.id).activo)
            set_provider_active(
                context,
                provider.id,
                True,
                metadata=self._metadata(),
            )
            self.assertTrue(get_provider(provider.id).activo)
        finally:
            self._cleanup()

    def test_concurrent_duplicate_provider_rut_is_rejected(self):
        suffix = uuid4().hex
        rut = self._available_rut()

        def create_one(index):
            try:
                result = create_provider(
                    CompanyContext(910006, actor_id=1),
                    ProviderInput(
                        rut=rut,
                        nombre=f"__CERT_PROVIDER_RACE_{suffix}_{index}",
                    ),
                    metadata=self._metadata(),
                )
            except MasterCatalogConflict:
                return None
            self.provider_ids.append(result.id)
            return result

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(create_one, range(2)))
            self.assertEqual(sum(result is not None for result in results), 1)
        finally:
            self._cleanup()

    def test_concurrent_duplicate_local_is_rejected_by_unique_index(self):
        suffix = uuid4().hex
        local_code = f"__CERT_RACE_{suffix}"

        def create_one():
            try:
                return create_local(
                    CompanyContext(910003, actor_id=1),
                    LocalInput(local_code, "Local concurrente"),
                    metadata=self._metadata(),
                )
            except MasterCatalogConflict:
                return None

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: create_one(), range(2)))
            self.assertEqual(sum(result is not None for result in results), 1)
        finally:
            self._cleanup(local_code=local_code, company_id=910003)
