from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.db import router
from django.test import SimpleTestCase


FRAMEWORK_ADMIN_EXCLUSIONS = {
    'admin.LogEntry': 'Django admin operation log; not a business-data surface.',
    'auth.Permission': 'Django authorization metadata; managed by the permission framework.',
    'contenttypes.ContentType': 'Django model registry metadata; managed by the framework.',
    'sessions.Session': 'Serialized session storage; never expose through the admin.',
}


class GlobalAdminModelCoverageTests(SimpleTestCase):
    def test_default_sqlite_models_are_registered_or_documented_exclusions(self):
        self.assertEqual(settings.DATABASES['default']['ENGINE'], 'django.db.backends.sqlite3')

        framework_labels = {
            model._meta.label
            for model in apps.get_models(include_auto_created=False)
            if model._meta.label in FRAMEWORK_ADMIN_EXCLUSIONS
        }
        self.assertEqual(framework_labels, set(FRAMEWORK_ADMIN_EXCLUSIONS))
        self.assertTrue(all(reason.strip() for reason in FRAMEWORK_ADMIN_EXCLUSIONS.values()))

        missing = []
        for model in apps.get_models(include_auto_created=False):
            options = model._meta
            if options.abstract or options.proxy or not options.managed:
                continue
            if (router.db_for_write(model) or 'default') != 'default':
                continue
            if options.label in FRAMEWORK_ADMIN_EXCLUSIONS:
                continue
            if not admin.site.is_registered(model):
                missing.append(options.label)

        self.assertEqual(missing, [], f'Modelos default/SQLite sin admin: {missing}')
