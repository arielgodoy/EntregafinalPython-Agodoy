import json
from unittest.mock import patch
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from access_control.services.permissions import (
    SIDEBAR_VIEW_NAMES,
    get_sidebar_visible_items,
)
from access_control.services.view_catalog import ensure_declared_views_catalog
from access_control.services.view_registry import definitions_for_app
from tareas.services.authorization import MEETINGS_VISTA_NAME
from tareas.vicmeas import MEETINGS


class MeetingSidebarTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="meeting-sidebar-user")
        self.empresa = Empresa.objects.create(codigo="00", descripcion="Empresa activa")
        self.otra_empresa = Empresa.objects.create(codigo="01", descripcion="Otra empresa")
        self.tareas_vista = Vista.objects.create(
            nombre="Tareas",
            route_name="tareas:listar_tareas",
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def _meeting_view(self):
        vista, _created = Vista.objects.get_or_create(
            nombre=MEETINGS_VISTA_NAME,
            defaults={"route_name": "tareas:reunion_revision_lista"},
        )
        return vista

    def _grant(self, vista, *, empresa=None, **flags):
        values = {
            "ver": False,
            "ingresar": False,
            "crear": False,
            "modificar": False,
            "eliminar": False,
            "autorizar": False,
            "supervisor": False,
        }
        values.update(flags)
        return Permiso.objects.create(
            usuario=self.user,
            empresa=empresa or self.empresa,
            vista=vista,
            **values,
        )

    def test_registry_and_sidebar_mapping_use_one_canonical_definition(self):
        definitions = [
            definition
            for definition in definitions_for_app("tareas")
            if definition.nombre == MEETINGS_VISTA_NAME
        ]

        self.assertEqual(definitions, [MEETINGS])
        self.assertEqual(
            SIDEBAR_VIEW_NAMES["tasks_meetings"],
            MEETINGS_VISTA_NAME,
        )
        self.assertTrue(MEETINGS.navigable)
        self.assertEqual(MEETINGS.group, "tasks")

    def test_catalog_registration_is_idempotent_without_permission_grants(self):
        permissions_before = Permiso.objects.count()

        first = ensure_declared_views_catalog(
            app="tareas",
            definitions=(MEETINGS,),
        )
        second = ensure_declared_views_catalog(
            app="tareas",
            definitions=(MEETINGS,),
        )

        self.assertEqual(first.created, 1)
        self.assertEqual(second.created, 0)
        self.assertEqual(Vista.objects.filter(nombre=MEETINGS_VISTA_NAME).count(), 1)
        self.assertEqual(Permiso.objects.count(), permissions_before)

    def test_sidebar_translation_key_exists_in_both_languages(self):
        language_dir = Path(__file__).resolve().parents[2] / "static" / "lang"

        english = json.loads((language_dir / "en.json").read_text(encoding="utf-8"))
        spanish = json.loads((language_dir / "sp.json").read_text(encoding="utf-8"))

        self.assertEqual(english["menu.tareas.meetings"], "Meetings")
        self.assertEqual(spanish["menu.tareas.meetings"], "Reuniones")

    def test_meetings_sidebar_visibility_uses_active_company(self):
        meeting_view = self._meeting_view()
        self._grant(meeting_view, ver=True)
        self._grant(meeting_view, empresa=self.otra_empresa, ver=False)

        active_company_items = get_sidebar_visible_items(
            self.user,
            self.empresa.pk,
            materialize_permissions=False,
        )
        other_company_items = get_sidebar_visible_items(
            self.user,
            self.otra_empresa.pk,
            materialize_permissions=False,
        )

        self.assertIn("tasks_meetings", active_company_items)
        self.assertNotIn("tasks_meetings", other_company_items)

    def test_meetings_only_permission_does_not_require_a_tasks_permission(self):
        self._grant(self._meeting_view(), ver=True, ingresar=True)

        visible_items = get_sidebar_visible_items(
            self.user,
            self.empresa.pk,
            materialize_permissions=False,
        )

        self.assertIn("tasks_meetings", visible_items)
        self.assertNotIn("tasks_list", visible_items)
        self.assertNotIn("tasks_create", visible_items)

        with patch("tareas.views.resolve_meeting_storage") as resolve_storage:
            resolve_storage.return_value.list_meetings.return_value = []
            response = self.client.get(
                reverse("tareas:reunion_revision_lista")
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="sidebarTareas"')
        self.assertContains(response, 'data-key="menu.tareas.meetings"')
        self.assertNotContains(
            response,
            f'href="{reverse("tareas:listar_tareas")}"',
        )

    def test_any_navigation_visibility_does_not_replace_ingresar(self):
        meeting_view = self._meeting_view()
        for capability in ("crear", "modificar"):
            with self.subTest(capability=capability):
                permission = self._grant(
                    meeting_view,
                    ver=True,
                    **{capability: True},
                )
                visible_items = get_sidebar_visible_items(
                    self.user,
                    self.empresa.pk,
                    materialize_permissions=False,
                )

                self.assertIn("tasks_meetings", visible_items)
                response = self.client.get(
                    reverse("tareas:reunion_revision_lista")
                )
                self.assertEqual(response.status_code, 403)
                permission.delete()

    def test_existing_task_links_remain_and_meetings_link_is_not_duplicated(self):
        self._grant(self.tareas_vista, ver=True)
        self._grant(self._meeting_view(), ver=True, ingresar=True)

        with patch("tareas.views.resolve_meeting_storage") as resolve_storage:
            resolve_storage.return_value.list_meetings.return_value = []
            response = self.client.get(
                reverse("tareas:reunion_revision_lista")
            )

        meetings_url = reverse("tareas:reunion_revision_lista")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-key="menu.tareas.meetings"', count=1)
        self.assertEqual(
            response.content.decode("utf-8").count(f'href="{meetings_url}"'),
            1,
        )
        self.assertContains(
            response,
            f'href="{reverse("tareas:listar_tareas")}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("tareas:crear_tarea")}"',
        )

    def test_tasks_permission_without_meetings_visibility_does_not_show_meetings(self):
        self._grant(self.tareas_vista, ver=True)
        self._grant(self._meeting_view(), ingresar=True)

        visible_items = get_sidebar_visible_items(
            self.user,
            self.empresa.pk,
            materialize_permissions=False,
        )
        with patch("tareas.views.resolve_meeting_storage") as resolve_storage:
            resolve_storage.return_value.list_meetings.return_value = []
            response = self.client.get(
                reverse("tareas:reunion_revision_lista")
            )

        self.assertNotIn("tasks_meetings", visible_items)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'data-key="menu.tareas.meetings"')

    def test_permission_for_another_company_does_not_authorize_active_company(self):
        self._grant(
            self._meeting_view(),
            empresa=self.otra_empresa,
            ver=True,
            ingresar=True,
        )

        response = self.client.get(reverse("tareas:reunion_revision_lista"))

        self.assertEqual(response.status_code, 403)

    def test_revoking_ingresar_denies_the_meeting_list(self):
        permission = self._grant(
            self._meeting_view(),
            ver=True,
            ingresar=True,
        )
        with patch("tareas.views.resolve_meeting_storage") as resolve_storage:
            resolve_storage.return_value.list_meetings.return_value = []
            response = self.client.get(
                reverse("tareas:reunion_revision_lista")
            )
        self.assertEqual(response.status_code, 200)

        permission.ingresar = False
        permission.save(update_fields=["ingresar"])
        response = self.client.get(reverse("tareas:reunion_revision_lista"))

        self.assertEqual(response.status_code, 403)

    def test_inactive_user_cannot_access_the_meeting_list(self):
        self._grant(
            self._meeting_view(),
            ver=True,
            ingresar=True,
        )
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.get(reverse("tareas:reunion_revision_lista"))

        self.assertIn(response.status_code, (302, 403))
