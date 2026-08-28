from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from api.Router_Databases import MultiDatabaseRouter
from common.database_classification import (
    DatabaseClassification,
    get_database_classification,
)


class DatabaseClassificationTests(SimpleTestCase):
    def test_classifies_system_legacy_and_unknown_aliases(self):
        self.assertEqual(get_database_classification("default"), DatabaseClassification.SYSTEM)
        self.assertEqual(get_database_classification("DB_sistema"), DatabaseClassification.UNKNOWN)
        self.assertEqual(get_database_classification("dinamica"), DatabaseClassification.LEGACY)
        self.assertEqual(get_database_classification("maestro_check_7"), DatabaseClassification.LEGACY)
        self.assertEqual(get_database_classification("other"), DatabaseClassification.UNKNOWN)


class MultiDatabaseRouterTests(SimpleTestCase):
    def setUp(self):
        self.router = MultiDatabaseRouter()
        self.managed_model = SimpleNamespace(_meta=SimpleNamespace(managed=True))
        self.unmanaged_model = SimpleNamespace(_meta=SimpleNamespace(managed=False))

    def test_system_migration_is_allowed(self):
        self.assertTrue(self.router.allow_migrate("default", "auth"))
        self.assertFalse(self.router.allow_migrate("DB_sistema", "auth"))

    @override_settings(SYSTEM_DATABASE_ALIASES={"default", "DB_sistema"})
    def test_registered_future_system_database_is_allowed(self):
        self.assertEqual(get_database_classification("DB_sistema"), DatabaseClassification.SYSTEM)
        self.assertTrue(self.router.allow_migrate("DB_sistema", "auth"))

    def test_legacy_and_unknown_migrations_are_blocked(self):
        self.assertFalse(self.router.allow_migrate("dinamica", "auth"))
        self.assertFalse(self.router.allow_migrate("unknown", "auth"))

    def test_unmanaged_models_are_blocked(self):
        self.assertFalse(
            self.router.allow_migrate(
                "default", "api", "contratopublicidad", model=self.unmanaged_model
            )
        )
        self.assertTrue(
            self.router.allow_migrate(
                "default", "auth", "user", model=self.managed_model
            )
        )

    def test_relations_require_the_same_database(self):
        system_one = SimpleNamespace(_state=SimpleNamespace(db="default"))
        system_two = SimpleNamespace(_state=SimpleNamespace(db="default"))
        other_system = SimpleNamespace(_state=SimpleNamespace(db="DB_sistema"))
        legacy = SimpleNamespace(_state=SimpleNamespace(db="dinamica"))

        self.assertTrue(self.router.allow_relation(system_one, system_two))
        self.assertFalse(self.router.allow_relation(system_one, other_system))
        self.assertFalse(self.router.allow_relation(system_one, legacy))
