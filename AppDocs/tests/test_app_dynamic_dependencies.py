from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from AppDocs.architecture_dependencies import collect_dynamic_dependencies, dependency_classification, production_dynamic_dependencies


class AppDynamicDependencyTests(SimpleTestCase):
    def test_detector_finds_literal_django_reference_types(self):
        source = "\n".join(
            (
                'models.ForeignKey("gestiondte.Cesion", on_delete=models.CASCADE)',
                'apps.get_model("biblioteca", "Propietario")',
                'reverse("gestion_dte:detalle")',
                'import_module("biblioteca.services")',
                'ContentType.objects.get(app_label="biblioteca", model="propiedad")',
            )
        )
        references = collect_dynamic_dependencies(source, "access_control", Path("access_control/example.py"))

        self.assertEqual(
            {(reference.reference_type, reference.destination) for reference in references},
            {
                ("model_relation", "gestiondte"),
                ("apps_get_model", "biblioteca"),
                ("reverse", "gestiondte"),
                ("import_module", "biblioteca"),
                ("app_label", "biblioteca"),
            },
        )

    def test_application_to_system_relation_is_classified_as_permitted_direction(self):
        references = collect_dynamic_dependencies(
            'models.ForeignKey("access_control.Empresa", on_delete=models.CASCADE)',
            "gestiondte",
            Path("gestiondte/example.py"),
        )

        self.assertEqual(references[0].destination, "access_control")
        self.assertEqual(dependency_classification(references[0]), "APPLICATION -> SYSTEM")

    def test_current_dynamic_inventory_contains_known_references(self):
        references = production_dynamic_dependencies(Path(settings.BASE_DIR))
        identities = {(reference.origin, reference.destination, reference.reference_type) for reference in references}

        self.assertIn(("auditoria", "biblioteca", "app_label_comparison"), identities)
        self.assertIn(("auditoria", "biblioteca", "app_label_mapping"), identities)
        self.assertIn(("auditoria", "gestiondte", "app_label_mapping"), identities)
        self.assertIn(("control_de_proyectos", "biblioteca", "model_relation"), identities)
        self.assertIn(("control_operacional", "control_de_proyectos", "reverse"), identities)