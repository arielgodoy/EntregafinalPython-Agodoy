from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import AccessRequest, Empresa, Permiso, PerfilAcceso, PerfilAccesoDetalle, Vista
from access_control.services.empresa_activa import get_navigable_vistas
from access_control.services.view_catalog import get_legacy_views_for_app
from core_search.models import SearchPageIndex
from settings.models import UserPreferences


class LegacyViewReportingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="legacy-report-user")
        self.empresa = Empresa.objects.create(codigo="01")
        self.legacy = Vista.objects.create(
            nombre="Tareas - Publicar tarea",
            route_name="tareas:publicar_tarea",
            descripcion="Histórica",
        )
        self.canonical = Vista.objects.create(
            nombre="Tareas",
            route_name="tareas:listar_tareas",
        )

    def test_report_is_read_only_and_suggests_lifecycle_replacement(self):
        permiso = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.legacy,
            ingresar=True,
            modificar=True,
        )
        perfil = PerfilAcceso.objects.create(nombre="Perfil legacy")
        PerfilAccesoDetalle.objects.create(
            perfil=perfil,
            vista=self.legacy,
            modificar=True,
        )
        UserPreferences.objects.update_or_create(
            user=self.user,
            defaults={"vista_inicial": self.legacy},
        )
        SearchPageIndex.objects.create(
            key="legacy.tasks.publish",
            vista=self.legacy,
            url_name="tareas:publicar_tarea",
            label_key="legacy.tasks.publish",
            default_label="Publicar",
        )
        AccessRequest.objects.create(
            solicitante=self.user,
            empresa=self.empresa,
            vista_nombre=self.legacy.nombre,
            motivo="Histórico",
        )
        before = {
            "vistas": tuple(Vista.objects.values_list("id", "nombre", "route_name")),
            "permisos": tuple(Permiso.objects.values_list("id", "vista_id", "ingresar", "modificar")),
            "requests": tuple(AccessRequest.objects.values_list("id", "vista_nombre")),
        }

        reports = get_legacy_views_for_app("tareas")

        report = next(item for item in reports if item.vista.pk == self.legacy.pk)
        self.assertEqual(report.motivo_legacy, "No corresponde a una definición declarativa activa de la app.")
        self.assertEqual(report.reemplazo_canonico_sugerido, "Tareas - Ciclo de vida")
        self.assertFalse(report.safe_to_delete)
        self.assertIn("permisos históricos", report.blockers)
        self.assertIn("referencias persistentes", report.blockers)
        self.assertEqual(report.permisos.count, 1)
        self.assertEqual(dict(report.permisos.flags)["modificar"], 1)
        self.assertEqual(
            tuple(Vista.objects.values_list("id", "nombre", "route_name")),
            before["vistas"],
        )
        self.assertEqual(
            tuple(Permiso.objects.values_list("id", "vista_id", "ingresar", "modificar")),
            before["permisos"],
        )
        self.assertEqual(
            tuple(AccessRequest.objects.values_list("id", "vista_nombre")),
            before["requests"],
        )

    def test_unreferenced_legacy_is_safe_future_cleanup_candidate(self):
        report = next(item for item in get_legacy_views_for_app("tareas") if item.vista.pk == self.legacy.pk)

        self.assertTrue(report.safe_to_delete)
        self.assertEqual(report.blockers, ())

    def test_apps_without_registry_are_not_classified(self):
        Vista.objects.create(nombre="Inventada - Legacy", route_name="inventada:index")

        self.assertEqual(get_legacy_views_for_app("inventada"), ())

    def test_legacy_rows_are_not_navigable(self):
        names = {vista.nombre for vista in get_navigable_vistas()}

        self.assertNotIn(self.legacy.nombre, names)
        self.assertIn(self.canonical.nombre, names)
