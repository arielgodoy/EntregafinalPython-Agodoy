from django.test import SimpleTestCase, override_settings

from settings.services.legacy_database_names import (
    LegacyDatabaseNameError,
    get_legacy_database_name,
)


class LegacyDatabaseNameTests(SimpleTestCase):
    @override_settings(CLIENTE_SISTEMA="eltit_")
    def test_eltit_gestion(self):
        self.assertEqual(get_legacy_database_name("gestion"), "eltit_gestion")

    @override_settings(CLIENTE_SISTEMA="eltit_")
    def test_eltit_contabilidad_base_and_empresa_00(self):
        self.assertEqual(get_legacy_database_name("contabilidad"), "eltit_conta")
        self.assertEqual(
            get_legacy_database_name("contabilidad", "00"), "eltit_conta"
        )

    @override_settings(CLIENTE_SISTEMA="eltit_")
    def test_eltit_contabilidad_empresa_codes(self):
        self.assertEqual(
            get_legacy_database_name("contabilidad", "01"), "eltit_conta01"
        )
        self.assertEqual(
            get_legacy_database_name("contabilidad", "09"), "eltit_conta09"
        )
        self.assertEqual(
            get_legacy_database_name("contabilidad", "34"), "eltit_conta34"
        )

    @override_settings(CLIENTE_SISTEMA="carozzi_")
    def test_custom_prefix_contabilidad(self):
        self.assertEqual(
            get_legacy_database_name("contabilidad", "09"), "carozzi_conta09"
        )

    @override_settings(CLIENTE_SISTEMA="acuenta_")
    def test_custom_prefix_gestion(self):
        self.assertEqual(get_legacy_database_name("gestion"), "acuenta_gestion")

    @override_settings(CLIENTE_SISTEMA="bad-prefix")
    def test_invalid_prefix_raises(self):
        with self.assertRaises(LegacyDatabaseNameError):
            get_legacy_database_name("gestion")

    @override_settings(CLIENTE_SISTEMA="eltit_")
    def test_invalid_company_code_raises(self):
        with self.assertRaises(LegacyDatabaseNameError):
            get_legacy_database_name("contabilidad", "9")

    @override_settings(CLIENTE_SISTEMA="eltit_")
    def test_unknown_domain_raises(self):
        with self.assertRaises(LegacyDatabaseNameError):
            get_legacy_database_name("remuneraciones")
