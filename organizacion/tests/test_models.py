from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from access_control.models import Empresa
from organizacion.models import Departamento, Local, OrganizationalSource


class OrganizacionModelTests(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa B")

    def test_creates_local_with_erp_source_and_defaults(self):
        local = Local.objects.create(
            empresa=self.empresa_a,
            codigo="001",
            nombre="Local principal",
            legacy_code="LEG-001",
            source=OrganizationalSource.ERP,
        )

        self.assertEqual(str(local), "001 - Local principal")
        self.assertTrue(local.activo)
        self.assertIsNotNone(local.created_at)
        self.assertIsNotNone(local.updated_at)

    def test_local_accepts_local_source_and_nullable_legacy_code(self):
        local = Local.objects.create(
            empresa=self.empresa_a,
            codigo="002",
            nombre="Local local",
            source=OrganizationalSource.LOCAL,
        )

        self.assertEqual(local.source, OrganizationalSource.LOCAL)
        self.assertIsNone(local.legacy_code)

    def test_creates_department_with_local_source(self):
        departamento = Departamento.objects.create(
            empresa=self.empresa_a,
            codigo="001",
            nombre="Operaciones",
            source=OrganizationalSource.LOCAL,
        )

        self.assertEqual(str(departamento), "001 - Operaciones")
        self.assertTrue(departamento.activo)
        self.assertIsNotNone(departamento.created_at)
        self.assertIsNotNone(departamento.updated_at)

    def test_empresa_is_required_for_both_models(self):
        with self.assertRaises(ValidationError):
            Local(codigo="001", nombre="Sin empresa", source=OrganizationalSource.LOCAL).full_clean()

        with self.assertRaises(ValidationError):
            Departamento(
                codigo="001",
                nombre="Sin empresa",
                source=OrganizationalSource.LOCAL,
            ).full_clean()

    def test_local_codigo_is_unique_per_empresa(self):
        Local.objects.create(
            empresa=self.empresa_a,
            codigo="001",
            nombre="Local A",
            source=OrganizationalSource.LOCAL,
        )

        with self.assertRaises(IntegrityError):
            Local.objects.create(
                empresa=self.empresa_a,
                codigo="001",
                nombre="Local duplicado",
                source=OrganizationalSource.LOCAL,
            )

    def test_department_codigo_is_unique_per_empresa(self):
        Departamento.objects.create(
            empresa=self.empresa_a,
            codigo="001",
            nombre="Departamento A",
            source=OrganizationalSource.LOCAL,
        )

        with self.assertRaises(IntegrityError):
            Departamento.objects.create(
                empresa=self.empresa_a,
                codigo="001",
                nombre="Departamento duplicado",
                source=OrganizationalSource.LOCAL,
            )

    def test_same_codigo_is_allowed_between_different_empresas(self):
        Local.objects.create(
            empresa=self.empresa_a,
            codigo="001",
            nombre="Local A",
            source=OrganizationalSource.LOCAL,
        )
        Departamento.objects.create(
            empresa=self.empresa_a,
            codigo="001",
            nombre="Departamento A",
            source=OrganizationalSource.LOCAL,
        )

        Local.objects.create(
            empresa=self.empresa_b,
            codigo="001",
            nombre="Local B",
            source=OrganizationalSource.LOCAL,
        )
        Departamento.objects.create(
            empresa=self.empresa_b,
            codigo="001",
            nombre="Departamento B",
            source=OrganizationalSource.LOCAL,
        )

    def test_logical_deactivation_is_supported(self):
        local = Local.objects.create(
            empresa=self.empresa_a,
            codigo="001",
            nombre="Local inactivo",
            activo=False,
            source=OrganizationalSource.LOCAL,
        )
        departamento = Departamento.objects.create(
            empresa=self.empresa_a,
            codigo="001",
            nombre="Departamento inactivo",
            activo=False,
            source=OrganizationalSource.LOCAL,
        )

        self.assertFalse(local.activo)
        self.assertFalse(departamento.activo)

    def test_department_has_no_local_relationship(self):
        field_names = {field.name for field in Departamento._meta.get_fields()}

        self.assertNotIn("local", field_names)
        self.assertNotIn("local_id", field_names)