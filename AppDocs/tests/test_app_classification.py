from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from AppDocs.app_classification import (
    APPLICATION_APPS,
    CORE_SYSTEM_APPS,
    PROJECT_APPS,
    SYSTEM_APPS,
    SYSTEM_SUPPORT_APPS,
)


class AppClassificationTests(SimpleTestCase):
    def test_system_groups_are_disjoint_and_complete(self):
        system_apps = set(SYSTEM_APPS)

        self.assertTrue(set(CORE_SYSTEM_APPS).issubset(system_apps))
        self.assertTrue(set(SYSTEM_SUPPORT_APPS).issubset(system_apps))
        self.assertFalse(set(CORE_SYSTEM_APPS) & set(SYSTEM_SUPPORT_APPS))
        self.assertFalse(system_apps & set(APPLICATION_APPS))

    def test_all_project_apps_exist_and_are_installed(self):
        project_root = Path(settings.BASE_DIR)
        installed_project_apps = {
            app_name
            for app_name in settings.INSTALLED_APPS
            if (project_root / app_name).is_dir()
        }

        self.assertEqual(set(PROJECT_APPS), installed_project_apps)
        for app_name in PROJECT_APPS:
            self.assertTrue((project_root / app_name / "apps.py").is_file())
