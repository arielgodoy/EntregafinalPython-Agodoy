import json
import re
from pathlib import Path
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.forms.utils import ErrorList
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from tareas.forms import CompletarHitoForm, DocumentoForm, EvidenciaRegistroForm
from tareas.models import DocumentoTarea


ROOT = Path(__file__).resolve().parents[2]
CATALOGS = {
    "sp": json.loads((ROOT / "static/lang/sp.json").read_text(encoding="utf-8")),
    "en": json.loads((ROOT / "static/lang/en.json").read_text(encoding="utf-8")),
}
MESSAGE_KEY_PATTERN = re.compile(
    r"tareas\.(?:messages|validation|links|meetings)(?:\.[a-z0-9_]+)+"
)
MEETING_SCOPE_ERROR_MESSAGES = {
    "tareas.meetings.errors.company_invalid": (
        "No hay una Empresa activa válida para esta operación.",
        "No valid active company is available for this operation.",
    ),
    "tareas.meetings.errors.local_company": (
        "El Local no está disponible para la Empresa activa.",
        "The Local is not available for the active company.",
    ),
    "tareas.meetings.errors.department_company": (
        "El Departamento no está disponible para la Empresa activa.",
        "The Department is not available for the active company.",
    ),
    "tareas.meetings.errors.local_inactive": (
        "El Local está inactivo y no puede asignarse a una reunión nueva.",
        "This Local is inactive and cannot be assigned to a new meeting.",
    ),
    "tareas.meetings.errors.department_inactive": (
        "El Departamento está inactivo y no puede asignarse a una reunión nueva.",
        "This Department is inactive and cannot be assigned to a new meeting.",
    ),
    "tareas.meetings.errors.historical_reference_invalid": (
        "No puede reemplazarse la referencia de esta reunión por un registro inactivo.",
        "This meeting's reference cannot be replaced with an inactive record.",
    ),
    "tareas.meetings.errors.scope_incompatible": (
        "La selección no es compatible con el tipo de ámbito de la reunión.",
        "The selection is not compatible with the meeting scope type.",
    ),
    "tareas.meetings.errors.scope_type_invalid": (
        "El tipo de ámbito de la reunión no es válido.",
        "The meeting scope type is invalid.",
    ),
    "tareas.meetings.errors.selection_invalid": (
        "La selección no está disponible para la Empresa activa.",
        "The selection is not available for the active company.",
    ),
}
HIERARCHY_DETAIL_KEYS = {
    "tareas.hierarchy.parent",
    "tareas.hierarchy.children",
    "tareas.hierarchy.kind.main",
    "tareas.hierarchy.kind.mother",
    "tareas.hierarchy.kind.child",
    "tareas.hierarchy.kind.grandchild",
    "tareas.hierarchy.kind.also_mother",
    "tareas.hierarchy.direct_mother",
}


class TareasI18nTests(SimpleTestCase):
    def test_hierarchy_detail_labels_have_catalog_parity_without_duplicate_keys(self):
        for language in ("sp", "en"):
            self.assertTrue(
                HIERARCHY_DETAIL_KEYS.issubset(CATALOGS[language]),
                f"Missing hierarchy detail translations in {language}",
            )
            duplicates = []

            def object_pairs_hook(pairs):
                seen = set()
                for key, _value in pairs:
                    if key in HIERARCHY_DETAIL_KEYS and key in seen:
                        duplicates.append(key)
                    seen.add(key)
                return dict(pairs)

            catalog_path = ROOT / f"static/lang/{language}.json"
            json.loads(
                catalog_path.read_text(encoding="utf-8"),
                object_pairs_hook=object_pairs_hook,
            )
            self.assertEqual(duplicates, [])

    def test_comment_document_types_use_cataloged_dynamic_i18n_keys(self):
        template = (ROOT / "tareas/templates/tareas/_tarea_comentarios.html").read_text(encoding="utf-8")
        script = (ROOT / "tareas/static/tareas/js/task_comments.js").read_text(encoding="utf-8")

        for value, _label in DocumentoTarea.Tipo.choices:
            key = f"tareas.documents.type.{value.lower()}"
            self.assertIn(key, CATALOGS["sp"], key)
            self.assertIn(key, CATALOGS["en"], key)
            self.assertIn(f'data-key="{key}"', template)

        self.assertIn("function documentTypeLabel(root, attachment)", script)
        self.assertIn("function appendDocumentTypeLabel(root, container, attachment)", script)
        self.assertIn('label.setAttribute("data-key", key)', script)
        self.assertNotIn("attachment.tipo || textFor", script)

    def test_literal_data_keys_are_catalogued_and_not_dynamic(self):
        keys = set()
        dynamic = []
        for source in (ROOT / "tareas/templates/tareas").rglob("*.html"):
            content = source.read_text(encoding="utf-8")
            for key in re.findall(r'data-key\s*=\s*["\']([^"\']+)["\']', content):
                if "{{" in key or "{%" in key:
                    dynamic.append((source, key))
                else:
                    keys.add(key)

        self.assertIn(
            (ROOT / "tareas/templates/tareas/enlace_tarea_error.html", "{{ error_title_key }}"),
            dynamic,
        )
        self.assertIn(
            (ROOT / "tareas/templates/tareas/enlace_tarea_error.html", "{{ error_description_key }}"),
            dynamic,
        )
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
            ROOT / "tareas/services/meetings.py",
            ROOT / "tareas/views.py",
            ROOT / "tareas/static/tareas/js/task_links.js",
        )
        used = set()
        for source in sources:
            used.update(MESSAGE_KEY_PATTERN.findall(source.read_text(encoding="utf-8")))

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

        error_list = ErrorList(
            [
                ValidationError(
                    "tareas.validation.unknown_future_code",
                    code="tareas.validation.unknown_future_code",
                )
            ]
        )
        rendered_error_list = render_to_string(
            "tareas/_i18n_form_errors.html",
            {"errors": error_list},
        )
        self.assertIn('data-key="tareas.messages.generic_error"', rendered_error_list)

    def test_participant_messages_have_explicit_rendered_branches(self):
        added = render_to_string(
            "tareas/_i18n_message.html",
            {"message": SimpleNamespace(message="tareas.messages.participant_added")},
        )
        invalid = render_to_string(
            "tareas/_i18n_message.html",
            {"message": SimpleNamespace(message="tareas.messages.participant_invalid")},
        )

        self.assertIn("Participante o responsable asignado correctamente.", added)
        self.assertNotIn('data-key="tareas.messages.generic_error"', added)
        self.assertIn(
            "No fue posible asignar o actualizar el participante o responsable.",
            invalid,
        )
        self.assertNotIn('data-key="tareas.messages.generic_error"', invalid)

    def test_message_keys_are_catalogued_and_never_rendered_directly(self):
        sources = [ROOT / "tareas/forms.py", ROOT / "tareas/views.py"]
        sources += list((ROOT / "tareas/templates/tareas").rglob("*.html"))
        sources += list((ROOT / "tareas/static/tareas").rglob("*.js"))
        used = set()
        for source in sources:
            content = source.read_text(encoding="utf-8")
            used.update(MESSAGE_KEY_PATTERN.findall(content))
            self.assertNotRegex(content, r"\{\{\s*message_key\b")
            self.assertNotRegex(content, r"textContent\s*=\s*message_key\b")

        self.assertTrue(used)
        self.assertTrue(used <= CATALOGS["sp"].keys())
        self.assertTrue(used <= CATALOGS["en"].keys())

    def test_meeting_scope_errors_have_explicit_es_en_rendering(self):
        for key, (spanish, english) in MEETING_SCOPE_ERROR_MESSAGES.items():
            with self.subTest(key=key):
                self.assertEqual(CATALOGS["sp"].get(key), spanish)
                self.assertEqual(CATALOGS["en"].get(key), english)

                for code in (key, "invalid_choice"):
                    error_list = ErrorList([ValidationError(key, code=code)])
                    for errors in (error_list, error_list.as_data()):
                        rendered = render_to_string(
                            "tareas/_i18n_form_errors.html",
                            {"errors": errors},
                        )
                        self.assertIn(f'data-key="{key}"', rendered)
                        self.assertIn(spanish, rendered)
                        self.assertNotIn(f">{key}</span>", rendered)

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
