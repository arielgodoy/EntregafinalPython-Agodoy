from types import SimpleNamespace

from django.contrib import admin
from django.test import RequestFactory, SimpleTestCase

from proveedores.models import Proveedor


class ProveedorAdminTests(SimpleTestCase):
    def test_proveedor_admin_is_read_only_and_limits_contact_data(self):
        model_admin = admin.site._registry[Proveedor]
        request = RequestFactory().get('/admin/')
        request.user = SimpleNamespace(is_active=True, is_staff=True, is_superuser=True)

        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertEqual(
            set(model_admin.get_fields(request)),
            {'nombre', 'rut', 'activo', 'created_at', 'updated_at'},
        )
        self.assertTrue(
            {'email1', 'email2', 'fono1', 'fono2', 'fax', 'contacto'}.isdisjoint(
                model_admin.get_list_display(request)
            )
        )
