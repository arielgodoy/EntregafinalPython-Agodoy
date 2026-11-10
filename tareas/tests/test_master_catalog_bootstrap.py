from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from tareas.management.commands.bootstrap_master_catalog_views import (
    bootstrap_master_catalog_views,
    inspect_master_catalog_views,
)


class _FakeVistaManager:
    def __init__(self):
        self.rows = []

    def filter(self, *, nombre):
        return _FakeVistaQuerySet(
            [row for row in self.rows if row.nombre == nombre]
        )

    def create(self, **values):
        row = SimpleNamespace(pk=len(self.rows) + 1, **values)
        self.rows.append(row)
        return row


class _FakeVistaQuerySet:
    def __init__(self, rows):
        self.rows = rows

    def order_by(self, *_fields):
        return self.rows


class MasterCatalogBootstrapTests(SimpleTestCase):
    def setUp(self):
        self.manager = _FakeVistaManager()
        self.vista = SimpleNamespace(objects=self.manager)

    def test_inspection_is_read_only(self):
        with patch(
            "tareas.management.commands.bootstrap_master_catalog_views.Vista",
            self.vista,
        ):
            plan = inspect_master_catalog_views()

        self.assertEqual(len(plan), 3)
        self.assertTrue(all(item["status"] == "missing" for item in plan))
        self.assertEqual(self.manager.rows, [])

    def test_explicit_apply_is_idempotent(self):
        with patch(
            "tareas.management.commands.bootstrap_master_catalog_views.Vista",
            self.vista,
        ), patch(
            "tareas.management.commands.bootstrap_master_catalog_views.transaction.atomic",
            return_value=nullcontext(),
        ):
            first = bootstrap_master_catalog_views(apply=True)
            second = bootstrap_master_catalog_views(apply=True)

        self.assertTrue(all(item["status"] == "exists" for item in first))
        self.assertTrue(all(item["status"] == "exists" for item in second))
        self.assertEqual(len(self.manager.rows), 3)
        self.assertEqual(
            {row.nombre for row in self.manager.rows},
            {
                "Proveedores - Maestro",
                "Tareas - Maestro de locales",
                "Tareas - Maestro de departamentos",
            },
        )
