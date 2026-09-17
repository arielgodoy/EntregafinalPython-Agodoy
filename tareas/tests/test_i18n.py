import json
import re
from pathlib import Path
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from tareas.forms import CompletarHitoForm, DocumentoForm, EvidenciaRegistroForm


ROOT = Path(__file__).resolve().parents[2]
CATALOGS = {
    "sp": json.loads((ROOT / "static/lang/sp.json").read_text(encoding="utf-8")),
    "en": json.loads((ROOT / "static/lang/en.json").read_text(encoding="utf-8")),
}


class TareasI18nTests(SimpleTestCase):
    def test_literal_data_keys_are_catalogued_and_not_dynamic(self):
        keys = set()
        dynamic = []
        for source in (ROOT / "tareas/templates/tareas").rglob("*.html"):
            content = source.read_text(encoding="utf-8")
            for key in re.findall(r'data-key\s*=\s*["\']([^"\']+)["\']', content):
                keys.add(key)
                if "{{" in key or "{%" in key:
                    dynamic.append((source, key))

        self.assertFalse(dynamic)
        self.assertEqual({key for key in keys if key not in CATALOGS["sp"]}, set())
        self.assertEqual({key for key in keys if key not in CATALOGS["en"]}, set())

    def test_file_or_url_validations_expose_catalog_keys(self):
        cases = (
            (CompletarHitoForm, {"resena_cierre": "ok", "formato_archivo": "PDF"},
             "tareas.validation.evidence_file_or_url_required"),
            (EvidenciaRegistroForm, {"formato_archivo": "PDF"},
             "tareas.validation.evidence_file_or_url_required"),
            (DocumentoForm, {"tipo": "OTRO", "formato_archivo": "PDF", "fecha_documento": "2026-09-17"},
             "tareas.validation.document_file_or_url_required"),
        )

        for form_class, data, expected_code in cases:
            form = form_class(data=data)
            self.assertFalse(form.is_valid())
            self.assertEqual(form.errors.as_data()["__all__"][0].code, expected_code)

    def test_python_and_task_link_message_keys_exist_in_both_catalogs(self):
        sources = (
            ROOT / "tareas/forms.py",
            ROOT / "tareas/views.py",
            ROOT / "tareas/static/tareas/js/task_links.js",
        )
        used = set()
        pattern = re.compile(r"tareas\.(?:messages|validation|links)\.[a-z0-9_]+")
        for source in sources:
            used.update(pattern.findall(source.read_text(encoding="utf-8")))

        for key in used:
            self.assertIn(key, CATALOGS["sp"], key)
            self.assertIn(key, CATALOGS["en"], key)

    def test_task_link_script_resolves_keys_without_displaying_them(self):
        script = (ROOT / "tareas/static/tareas/js/task_links.js").read_text(encoding="utf-8")
        self.assertIn("function resolveMessage(key)", script)
        self.assertNotIn("No fue posible crear el enlace.", script)
        self.assertNotIn("URL creada:", script)
        self.assertNotIn("result.data.message_key)", script)

    def test_unknown_i18n_codes_use_translated_fallbacks(self):
        message = SimpleNamespace(message="tareas.messages.unknown_future_code")
        rendered_message = render_to_string("tareas/_i18n_message.html", {"message": message})
        self.assertNotIn("tareas.messages.unknown_future_code", rendered_message)
        self.assertIn('data-key="tareas.messages.generic_error"', rendered_message)

        error = SimpleNamespace(code="tareas.validation.unknown_future_code", message="unused")
        rendered_error = render_to_string("tareas/_i18n_form_errors.html", {"errors": [error]})
        self.assertNotIn("tareas.validation.unknown_future_code", rendered_error)
        self.assertIn('data-key="tareas.messages.generic_error"', rendered_error)

    def test_message_keys_are_catalogued_and_never_rendered_directly(self):
        sources = [ROOT / "tareas/forms.py", ROOT / "tareas/views.py"]
        sources += list((ROOT / "tareas/templates/tareas").rglob("*.html"))
        sources += list((ROOT / "tareas/static/tareas").rglob("*.js"))
        used = set()
        for source in sources:
            content = source.read_text(encoding="utf-8")
            used.update(re.findall(r"tareas\.(?:messages|validation|links)\.[a-z0-9_]+", content))
            self.assertNotRegex(content, r"\{\{\s*message_key\b")
            self.assertNotRegex(content, r"textContent\s*=\s*message_key\b")

        self.assertTrue(used)
        self.assertTrue(used <= CATALOGS["sp"].keys())
        self.assertTrue(used <= CATALOGS["en"].keys())

    def test_catalogs_have_no_duplicate_tareas_keys(self):
        for language in ("sp", "en"):
            duplicates = []

            def collect_pairs(pairs):
                seen = set()
                for key, _ in pairs:
                    if key.startswith("tareas.") and key in seen:
                        duplicates.append(key)
                    seen.add(key)
                return dict(pairs)

            json.loads(
                (ROOT / f"static/lang/{language}.json").read_text(encoding="utf-8"),
                object_pairs_hook=collect_pairs,
            )
            self.assertEqual(duplicates, [], language)

    def test_visible_enum_literals_are_not_rendered_as_bare_labels(self):
        technical_values = (
            "GESTION",
            "CRITICA",
            "PENDIENTE_APROBACION_CIERRE",
        )
        for source in (ROOT / "tareas/templates/tareas").rglob("*.html"):
            content = source.read_text(encoding="utf-8")
            for value in technical_values:
                self.assertNotRegex(content, rf">\s*{value}\s*<", str(source))

    def test_stage_two_catalogs_are_symmetric(self):
        sp_keys = {key for key in CATALOGS["sp"] if key.startswith("tareas.")}
        en_keys = {key for key in CATALOGS["en"] if key.startswith("tareas.")}
        self.assertEqual(sp_keys, en_keys)
