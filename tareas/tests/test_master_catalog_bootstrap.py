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

    def filter(self, **criteria):
        rows = self.rows
        for field, value in criteria.items():
            rows = [
                row
                for row in rows
                if getattr(row, field) == value
            ]
        return _FakeVistaQuerySet(rows)

    def create(self, **values):
        values.setdefault("route_name", None)
        row = SimpleNamespace(pk=len(self.rows) + 1, **values)
        self.rows.append(row)
        return row


class _FakeVistaQuerySet:
    def __init__(self, rows):
        self.rows = rows

    def order_by(self, *_fields):
        return self.rows

    def update(self, **values):
        for row in self.rows:
            for field, value in values.items():
                setattr(row, field, value)
        return len(self.rows)


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
                "Maestros - Proveedores",
                "Tareas - Maestro de locales",
                "Tareas - Maestro de departamentos",
            },
        )

    def test_explicit_apply_fills_only_missing_master_routes(self):
        self.manager.rows.append(
            SimpleNamespace(
                pk=17,
                nombre="Tareas - Maestro de locales",
                route_name=None,
                descripcion="",
            )
        )
        with patch(
            "tareas.management.commands.bootstrap_master_catalog_views.Vista",
            self.vista,
        ), patch(
            "tareas.management.commands.bootstrap_master_catalog_views.transaction.atomic",
            return_value=nullcontext(),
        ):
            result = bootstrap_master_catalog_views(apply=True)

        self.assertEqual(
            next(
                row.route_name
                for row in self.manager.rows
                if row.nombre == "Tareas - Maestro de locales"
            ),
            "tareas:locales_maestro",
        )
        self.assertTrue(all(item["status"] == "exists" for item in result))
