from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from proveedores.models import Proveedor


class ProveedorModelTests(TestCase):
    def test_creates_with_name_only_and_defaults(self):
        proveedor = Proveedor.objects.create(nombre="Proveedor de prueba")

        self.assertTrue(proveedor.activo)
        self.assertIsNotNone(proveedor.created_at)
        self.assertIsNotNone(proveedor.updated_at)
        self.assertIsNone(proveedor.rut)

    def test_multiple_providers_without_rut_are_allowed(self):
        Proveedor.objects.create(nombre="Proveedor uno")
        Proveedor.objects.create(nombre="Proveedor dos")

        self.assertEqual(Proveedor.objects.filter(rut__isnull=True).count(), 2)

    def test_rut_formats_are_normalized(self):
        proveedor = Proveedor.objects.create(
            nombre="Proveedor de prueba", rut="12.345.678-5"
        )
        self.assertEqual(proveedor.rut, "12345678-5")

        proveedor = Proveedor(nombre="Proveedor validado", rut="12.345.679-3")
        proveedor.full_clean()
        self.assertEqual(proveedor.rut, "12345679-3")

        otro = Proveedor.objects.create(
            nombre="Otro proveedor", rut="12 345 679-3"
        )
        self.assertEqual(otro.rut, "12345679-3")

    def test_lowercase_k_is_normalized(self):
        proveedor = Proveedor.objects.create(nombre="Proveedor K", rut="6-k")
        self.assertEqual(proveedor.rut, "6-K")

    def test_valid_rut_is_accepted_and_invalid_rut_is_rejected(self):
        Proveedor.objects.create(nombre="Proveedor valido", rut="12345678-5")

        with self.assertRaises(ValidationError):
            Proveedor.objects.create(nombre="Proveedor invalido", rut="12345678-9")

    def test_same_rut_in_different_formats_is_duplicate(self):
        Proveedor.objects.create(nombre="Proveedor original", rut="12.345.678-5")

        with self.assertRaises((ValidationError, IntegrityError)):
            Proveedor.objects.create(nombre="Proveedor duplicado", rut="12345678-5")

    def test_inactive_rut_remains_unique(self):
        Proveedor.objects.create(
            nombre="Proveedor inactivo", rut="12345678-5", activo=False
        )

        with self.assertRaises((ValidationError, IntegrityError)):
            Proveedor.objects.create(nombre="Proveedor nuevo", rut="12345678-5")

    def test_name_is_required_and_trimmed(self):
        proveedor = Proveedor.objects.create(nombre="  Nombre con espacios  ")
        self.assertEqual(proveedor.nombre, "Nombre con espacios")

        with self.assertRaises(ValidationError):
            Proveedor.objects.create(nombre="   ")

    def test_email_validation(self):
        Proveedor.objects.create(nombre="Proveedor email", email1="test@example.com")

        with self.assertRaises(ValidationError):
            Proveedor.objects.create(nombre="Proveedor email invalido", email1="no-es-email")

    def test_string_representation(self):
        with_rut = Proveedor.objects.create(nombre="Proveedor con RUT", rut="12345678-5")
        without_rut = Proveedor.objects.create(nombre="Proveedor sin RUT")

        self.assertEqual(str(with_rut), "Proveedor con RUT (12345678-5)")
        self.assertEqual(str(without_rut), "Proveedor sin RUT")

    def test_is_global_and_has_no_legacy_fields(self):
        field_names = {field.name for field in Proveedor._meta.get_fields()}

        self.assertNotIn("empresa", field_names)
        self.assertNotIn("empresa_id", field_names)
        self.assertNotIn("legacy_id", field_names)
        self.assertNotIn("id_legacy", field_names)
