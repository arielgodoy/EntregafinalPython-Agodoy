from types import SimpleNamespace

from django.contrib import admin
from django.test import RequestFactory, SimpleTestCase

from acounts.models import UserActiveSession


class UserActiveSessionAdminTests(SimpleTestCase):
    def test_active_session_is_read_only_and_never_displays_session_key(self):
        model_admin = admin.site._registry[UserActiveSession]
        request = RequestFactory().get('/admin/')
        request.user = SimpleNamespace(is_active=True, is_staff=True, is_superuser=True)

        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertNotIn('session_key', model_admin.get_list_display(request))
        self.assertNotIn('session_key', model_admin.get_fields(request))
