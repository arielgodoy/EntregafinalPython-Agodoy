from types import SimpleNamespace

from django.contrib import admin
from django.test import RequestFactory, SimpleTestCase

from auditoria.models import (
    AuditArchiveBatch,
    AuditArchivePurgeChunk,
    AuditoriaGestionDTEEvent,
    UserPresence,
)


AUDIT_MODELS = (
    AuditoriaGestionDTEEvent,
    UserPresence,
    AuditArchiveBatch,
    AuditArchivePurgeChunk,
)
SENSITIVE_ADMIN_FIELDS = {
    'after',
    'archive_path',
    'before',
    'company_ids',
    'error_message',
    'ip_address',
    'manifest',
    'meta',
    'path',
    'purge_error_message',
    'querystring',
    'source_checksum',
    'archive_checksum',
    'user_agent',
}


class AuditoriaAdminTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get('/admin/')
        self.request.user = SimpleNamespace(is_active=True, is_staff=True, is_superuser=True)

    def test_audit_models_are_registered_read_only(self):
        for model in AUDIT_MODELS:
            with self.subTest(model=model._meta.label):
                model_admin = admin.site._registry[model]
                self.assertFalse(model_admin.has_add_permission(self.request))
                self.assertFalse(model_admin.has_change_permission(self.request))
                self.assertFalse(model_admin.has_delete_permission(self.request))

    def test_sensitive_audit_data_is_not_in_admin_lists_or_detail_fields(self):
        for model in AUDIT_MODELS:
            with self.subTest(model=model._meta.label):
                model_admin = admin.site._registry[model]
                list_display = set(model_admin.get_list_display(self.request))
                detail_fields = set(model_admin.get_fields(self.request))
                self.assertTrue(list_display.isdisjoint(SENSITIVE_ADMIN_FIELDS))
                self.assertTrue(detail_fields.isdisjoint(SENSITIVE_ADMIN_FIELDS))
