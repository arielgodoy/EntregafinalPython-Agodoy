from django.test import SimpleTestCase

from tareas.utils.rut import (
    RutValidationError,
    calcular_digito_verificador,
    limpiar_rut,
    normalizar_rut,
    validar_rut,
)


class RutUtilityTests(SimpleTestCase):
    def test_valid_rut_with_dots_and_without_dots(self):
        self.assertTrue(validar_rut("12.345.678-5"))
        self.assertTrue(validar_rut("12345678-5"))
        self.assertEqual(normalizar_rut("12.345.678-5"), "12345678-5")

    def test_valid_rut_with_k_is_normalized_to_uppercase(self):
        self.assertTrue(validar_rut("6-k"))
        self.assertEqual(normalizar_rut("6-k"), "6-K")

    def test_valid_rut_with_zero_verification_digit(self):
        self.assertTrue(validar_rut("14-0"))
        self.assertEqual(calcular_digito_verificador("14"), "0")

    def test_invalid_verification_digit_is_rejected(self):
        self.assertFalse(validar_rut("12.345.678-6"))
        with self.assertRaises(RutValidationError):
            normalizar_rut("12345678-6")

    def test_empty_and_none_represent_absence(self):
        self.assertIsNone(limpiar_rut(""))
        self.assertIsNone(limpiar_rut(" \t"))
        self.assertIsNone(normalizar_rut(None))
        self.assertFalse(validar_rut(None))
        self.assertFalse(validar_rut(""))

    def test_permitted_spaces_and_separators_are_removed(self):
        self.assertEqual(normalizar_rut(" 12.345.678 - 5 "), "12345678-5")

    def test_lowercase_k_is_cleaned(self):
        self.assertEqual(limpiar_rut("6-k"), "6K")

    def test_invalid_characters_are_rejected(self):
        with self.assertRaises(RutValidationError):
            limpiar_rut("12.345.678/5")
        with self.assertRaises(RutValidationError):
            limpiar_rut("１２３４５６７８-５")
        self.assertFalse(validar_rut("12A345678-5"))

    def test_invalid_types_are_rejected_controlled(self):
        with self.assertRaises(TypeError):
            limpiar_rut(123456785)
        with self.assertRaises(TypeError):
            calcular_digito_verificador(12345678)
        self.assertFalse(validar_rut(123456785))

    def test_body_and_length_rules_are_enforced(self):
        self.assertFalse(validar_rut("123456789-0"))
        self.assertFalse(validar_rut("-5"))
        with self.assertRaises(RutValidationError):
            calcular_digito_verificador("12A4")

    def test_leading_zeroes_are_preserved(self):
        self.assertEqual(normalizar_rut("01-9"), "01-9")
