from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from AppDocs.architecture_report import build_report, render_report


class ArchitectureReportTests(SimpleTestCase):
    def test_report_combines_static_and_dynamic_findings(self):
        report = build_report(Path(settings.BASE_DIR))
        api_biblioteca = report["groups"][("api", "biblioteca")]

        self.assertEqual(len(api_biblioteca["static"]), 2)
        self.assertEqual(len(api_biblioteca["dynamic"]), 0)
        self.assertIn(frozenset(("control_de_proyectos", "control_operacional")), report["cycles"])
        self.assertIn("ALLOWED_BY_STATIC_ALLOWLIST", render_report(report))
        self.assertIn("REPORT_ONLY_DYNAMIC", render_report(report))
        self.assertIn("api -> biblioteca: static=2; dynamic=0", render_report(report, summary=True))

    def test_allowlist_is_marked_stale_when_it_has_no_references(self):
        report = build_report(
            Path(settings.BASE_DIR),
            {("missing_system", "missing_application"): "Artificial stale allowlist."},
        )

        self.assertTrue(report["allowlists"][0]["stale"])