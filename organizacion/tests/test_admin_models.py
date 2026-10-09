from types import SimpleNamespace

from django.contrib import admin
from django.test import RequestFactory, SimpleTestCase

from organizacion.models import Departamento, Local


class OrganizacionAdminTests(SimpleTestCase):
    def test_company_catalogs_are_registered_read_only(self):
        request = RequestFactory().get('/admin/')
        request.user = SimpleNamespace(is_active=True, is_staff=True, is_superuser=True)

        for model in (Local, Departamento):
            with self.subTest(model=model._meta.label):
                model_admin = admin.site._registry[model]
                self.assertFalse(model_admin.has_add_permission(request))
                self.assertFalse(model_admin.has_change_permission(request))
                self.assertFalse(model_admin.has_delete_permission(request))
                self.assertIn('codigo', model_admin.get_list_display(request))
                self.assertIn('nombre', model_admin.get_list_display(request))
