import json
import re
from io import StringIO
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.template.loader import get_template
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from access_control.services.permissions import (
    SIDEBAR_GROUPS,
    get_sidebar_visible_items,
)
from tareas.models import TareaEliminacionOperacion
from tareas.vicmeas import DELETED_TASKS_HISTORY
from tareas.services.deleted_tasks_history import (
    DeletedTaskHistoryFilters,
    DeletedTaskHistoryNotFound,
    DeletedTaskHistoryPage,
)


class _ScopedI18nTextAudit(HTMLParser):
    _VOID_ELEMENTS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self, scope_ids):
        super().__init__(convert_charrefs=True)
        self.scope_ids = set(scope_ids)
        self.found_scopes = set()
        self.untranslated_text = []
        self._stack = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        parent_in_scope = self._stack[-1][1] if self._stack else False
        parent_keyed = self._stack[-1][2] if self._stack else False
        scope_id = attributes.get("id")
        in_scope = parent_in_scope or scope_id in self.scope_ids
        keyed = parent_keyed or "data-key" in attributes
        if scope_id in self.scope_ids:
            self.found_scopes.add(scope_id)
        if tag not in self._VOID_ELEMENTS:
            self._stack.append((tag, in_scope, keyed))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data):
        if not self._stack or not self._stack[-1][1] or self._stack[-1][2]:
            return
        visible = re.sub(r"\{\{.*?\}\}|\{%.*?%\}", "", data, flags=re.DOTALL).strip()
        if visible.strip("—:·"):
            self.untranslated_text.append(visible)


class DeletedTasksHistoryViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="deleted-history-user",
            password="not-used",
        )
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.otra_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa B")

    def _activate_company(self, empresa=None):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = (empresa or self.empresa).pk
        session.save()

    def _grant_history(self, *, ver=False, ingresar=False, supervisor=False):
        vista, _created = Vista.objects.get_or_create(
            nombre="Tareas - Tareas eliminadas",
            defaults={"route_name": "tareas:eliminadas_lista"},
        )
        return Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            ver=ver,
            ingresar=ingresar,
            supervisor=supervisor,
        )

    def test_missing_vista_fails_closed_without_materializing_catalog_or_permission(self):
        self._activate_company()

        response = self.client.get(reverse("tareas:eliminadas_lista"))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Vista.objects.filter(nombre="Tareas - Tareas eliminadas").exists()
        )
        self.assertEqual(Permiso.objects.count(), 0)

    def test_explicit_ingresar_is_required_even_when_sidebar_ver_is_granted(self):
        self._grant_history(ver=True, ingresar=False)
        self._activate_company()

        response = self.client.get(reverse("tareas:eliminadas_lista"))

        visible = get_sidebar_visible_items(
            self.user,
            self.empresa.pk,
            materialize_permissions=False,
        )
        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            reverse("tareas:eliminadas_lista"),
            status_code=403,
        )
        self.assertIn("tasks_deleted", visible)
        self.assertIn("tasks", visible)
        self.assertEqual(SIDEBAR_GROUPS["tasks"][-1], "tasks_deleted")

    def test_history_permission_allows_read_only_list_without_granting_sidebar_ver(self):
        self._grant_history(ver=False, ingresar=True)
        self._activate_company()
        page = DeletedTaskHistoryPage(
            items=(),
            total=0,
            page=1,
            page_size=25,
            total_pages=0,
        )

        with patch(
            "tareas.views.list_deleted_task_history",
            return_value=page,
        ) as history_reader:
            response = self.client.get(
                reverse("tareas:eliminadas_lista"),
                {"empresa_id": self.otra_empresa.pk},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tareas eliminadas")
        self.assertEqual(
            history_reader.call_args.kwargs,
            {
                "empresa_id": self.empresa.pk,
                "filters": DeletedTaskHistoryFilters(),
            },
        )
        visible = get_sidebar_visible_items(
            self.user,
            self.empresa.pk,
            materialize_permissions=False,
        )
        self.assertNotIn("tasks_deleted", visible)

    def test_post_is_not_supported_and_does_not_call_history_service(self):
        self._grant_history(ingresar=True)
        self._activate_company()

        with patch("tareas.views.list_deleted_task_history") as history_reader:
            response = self.client.post(reverse("tareas:eliminadas_lista"))

        self.assertEqual(response.status_code, 405)
        history_reader.assert_not_called()

    def test_history_get_is_read_only_and_never_calls_restoration_service(self):
        self._grant_history(ingresar=True)
        self._activate_company()
        page = DeletedTaskHistoryPage(
            items=(),
            total=0,
            page=1,
            page_size=25,
            total_pages=0,
        )
        operation_count = TareaEliminacionOperacion.objects.count()

        with (
            patch(
                "tareas.views.list_deleted_task_history",
                return_value=page,
            ),
            patch(
                "tareas.services.logical_restoration.restore_logical_task_tree",
            ) as restoration_writer,
        ):
            response = self.client.get(reverse("tareas:eliminadas_lista"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(TareaEliminacionOperacion.objects.count(), operation_count)
        restoration_writer.assert_not_called()

    def test_operation_and_task_details_use_only_the_active_company(self):
        self._grant_history(ingresar=True)
        self._activate_company()
        operation_id = UUID("25ffcbcf-5257-46ea-8b4b-9a5e29ebe7e0")

        with patch(
            "tareas.views.get_deleted_task_history_operation",
            side_effect=DeletedTaskHistoryNotFound("not found"),
        ) as operation_reader:
            operation_response = self.client.get(
                reverse(
                    "tareas:eliminacion_operacion_detalle",
                    kwargs={"operation_id": operation_id},
                ),
                {"empresa_id": self.otra_empresa.pk},
            )

        self.assertEqual(operation_response.status_code, 404)
        self.assertEqual(
            operation_reader.call_args.kwargs,
            {
                "empresa_id": self.empresa.pk,
                "operation_id": operation_id,
            },
        )

        with patch(
            "tareas.views.get_deleted_task_history_detail",
            side_effect=DeletedTaskHistoryNotFound("not found"),
        ) as detail_reader:
            detail_response = self.client.get(
                reverse(
                    "tareas:eliminada_detalle",
                    kwargs={"operation_id": operation_id, "task_id": 84},
                ),
                {"empresa_id": self.otra_empresa.pk},
            )

        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(
            detail_reader.call_args.kwargs,
            {
                "empresa_id": self.empresa.pk,
                "operation_id": operation_id,
                "task_id": 84,
                "can_read_related": False,
                "can_read_comments": False,
                "can_read_hidden_comments": False,
            },
        )

    def test_deletion_supervisor_permission_on_tasks_does_not_grant_history_access(self):
        task_view = Vista.objects.create(nombre="Tareas")
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=task_view,
            supervisor=True,
        )
        self._activate_company()

        response = self.client.get(reverse("tareas:eliminadas_lista"))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Vista.objects.filter(nombre="Tareas - Tareas eliminadas").exists()
        )

    def test_all_history_templates_compile(self):
        for template_name in (
            "tareas/deleted_tasks_history_list.html",
            "tareas/deleted_task_history_detail.html",
            "tareas/deleted_task_history_operation.html",
        ):
            with self.subTest(template=template_name):
                self.assertIsNotNone(get_template(template_name))

    def test_l4_visible_translation_keys_exist_in_both_catalogs(self):
        root = Path(settings.BASE_DIR)
        template_paths = (
            root / "tareas" / "templates" / "tareas" / "deleted_tasks_history_list.html",
            root / "tareas" / "templates" / "tareas" / "deleted_task_history_detail.html",
            root / "tareas" / "templates" / "tareas" / "deleted_task_history_operation.html",
            root / "templates" / "partials" / "sidebar.html",
        )
        used_keys = set()
        for path in template_paths:
            content = path.read_text(encoding="utf-8")
            for match in re.findall(r'data-key=["\']([^"\']+)["\']', content):
                if "{{" not in match and (
                    match.startswith("tareas.deleted_history.")
                    or match == "menu.tareas.deleted"
                ):
                    used_keys.add(match)

        for language in ("sp", "en"):
            with self.subTest(language=language):
                duplicate_l4_keys = set()

                def collect_pairs(pairs):
                    catalog = {}
                    for key, value in pairs:
                        if key in catalog and (
                            key.startswith("tareas.deleted_history.")
                            or key == "menu.tareas.deleted"
                        ):
                            duplicate_l4_keys.add(key)
                        catalog[key] = value
                    return catalog

                catalog = json.loads(
                    (root / "static" / "lang" / f"{language}.json").read_text(
                        encoding="utf-8"
                    ),
                    object_pairs_hook=collect_pairs,
                )
                self.assertEqual(used_keys - catalog.keys(), set())
                self.assertEqual(duplicate_l4_keys, set())

    def test_restoration_projection_text_is_keyed_and_catalogued(self):
        root = Path(settings.BASE_DIR)
        scoped_templates = (
            (
                root / "tareas" / "templates" / "tareas" / "deleted_tasks_history_list.html",
                ("l5-deletion-projection",),
            ),
            (
                root / "tareas" / "templates" / "tareas" / "deleted_task_history_operation.html",
                ("l5-restoration-trace",),
            ),
            (
                root / "tareas" / "templates" / "tareas" / "deleted_task_history_detail.html",
                ("l5-restored-snapshot-notice",),
            ),
        )
        for path, scope_ids in scoped_templates:
            parser = _ScopedI18nTextAudit(scope_ids)
            parser.feed(path.read_text(encoding="utf-8"))
            with self.subTest(template=path.name):
                self.assertEqual(parser.found_scopes, set(scope_ids))
                self.assertEqual(parser.untranslated_text, [])

        required_keys = {
            "tareas.deleted_history.column.restoration_status",
            "tareas.deleted_history.projection.currently_deleted",
            "tareas.deleted_history.projection.restored",
            "tareas.deleted_history.projection.inconsistent",
            "tareas.deleted_history.restoration.title",
            "tareas.deleted_history.restoration.id",
            "tareas.deleted_history.restoration.source_operation",
            "tareas.deleted_history.restoration.actor",
            "tareas.deleted_history.restoration.reason",
            "tareas.deleted_history.restoration.created_at",
            "tareas.deleted_history.restoration.committed_at",
            "tareas.deleted_history.restoration.status",
            "tareas.deleted_history.restoration.result",
            "tareas.deleted_history.restoration.audit",
            "tareas.deleted_history.restoration.audit_event",
            "tareas.deleted_history.restoration.validation",
            "tareas.deleted_history.restoration.validation_valid",
            "tareas.deleted_history.restoration.validation_invalid",
            "tareas.deleted_history.restoration.pending_notice",
            "tareas.deleted_history.restoration.audit_unconfirmed",
            "tareas.deleted_history.detail.restored_snapshot_unavailable",
            "tareas.deleted_history.related.restored_snapshot_unavailable",
        }
        for language in ("sp", "en"):
            catalog = json.loads(
                (root / "static" / "lang" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            with self.subTest(language=language):
                self.assertEqual(required_keys - catalog.keys(), set())
                logical_only_text = catalog[
                    "tareas.logical_deletion.preview.logical_only"
                ].casefold()
                self.assertNotIn("no permite restaurarlos", logical_only_text)
                self.assertNotIn("allow restoration", logical_only_text)

    def test_catalog_command_registers_only_view_without_creating_permissions(self):
        permissions_before = Permiso.objects.count()
        output = StringIO()

        call_command(
            "ensure_view_catalog",
            app="tareas",
            apply=True,
            stdout=output,
        )

        vista = Vista.objects.get(nombre="Tareas - Tareas eliminadas")
        self.assertEqual(vista.route_name, "tareas:eliminadas_lista")
        self.assertEqual(
            tuple(
                (route.route_name, route.permiso_requerido)
                for route in DELETED_TASKS_HISTORY.routes
            ),
            (
                ("tareas:eliminadas_lista", "ingresar"),
                ("tareas:eliminada_detalle", "ingresar"),
                ("tareas:eliminacion_operacion_detalle", "ingresar"),
            ),
        )
        self.assertEqual(Permiso.objects.count(), permissions_before)
        self.assertIn("Permisos creados: 0", output.getvalue())

    def test_catalog_command_renames_by_route_preserving_view_and_permission_ids(self):
        legacy = Vista.objects.create(
            nombre="Tareas eliminadas",
            route_name="tareas:eliminadas_lista",
        )
        permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=legacy,
            ver=True,
            ingresar=True,
            modificar=True,
        )
        permission_before = tuple(
            Permiso.objects.filter(pk=permission.pk).values_list(
                "id",
                "usuario_id",
                "empresa_id",
                "ver",
                "ingresar",
                "crear",
                "modificar",
                "eliminar",
                "autorizar",
                "supervisor",
            ).get()
        )
        view_id = legacy.pk
        permission_id = permission.pk

        call_command(
            "ensure_view_catalog",
            app="tareas",
            apply=True,
            stdout=StringIO(),
        )

        legacy.refresh_from_db()
        permission.refresh_from_db()
        permission_after = tuple(
            Permiso.objects.filter(pk=permission.pk).values_list(
                "id",
                "usuario_id",
                "empresa_id",
                "ver",
                "ingresar",
                "crear",
                "modificar",
                "eliminar",
                "autorizar",
                "supervisor",
            ).get()
        )
        self.assertEqual(legacy.pk, view_id)
        self.assertEqual(legacy.nombre, "Tareas - Tareas eliminadas")
        self.assertEqual(legacy.route_name, "tareas:eliminadas_lista")
        self.assertEqual(permission.pk, permission_id)
        self.assertEqual(permission.vista_id, view_id)
        self.assertEqual(permission_after, permission_before)
        self.assertFalse(Vista.objects.filter(nombre="Tareas eliminadas").exists())
        self.assertEqual(
            Vista.objects.filter(nombre="Tareas - Tareas eliminadas").count(),
            1,
        )
