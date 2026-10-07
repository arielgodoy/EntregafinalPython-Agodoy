import re

from django.apps import apps
from django.contrib import admin
from django.contrib.auth.models import User
from django.db import connections
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from access_control.models import Empresa
from settings.models import SettingsMySQLConnection
from tareas.models import TareaConnectionRole


class TareaConnectionRoleAdminTests(TestCase):
    password_sentinel = "admin-list-must-not-render-this-password"

    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(
            codigo="00",
            descripcion="Catálogo de conexiones",
        )
        cls.mysql_connection = SettingsMySQLConnection.objects.create(
            empresa=cls.empresa,
            nombre_logico="base_tareas_test",
            engine=SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
            host="mysql.example.test",
            port=3306,
            user="test-user",
            password=cls.password_sentinel,
            db_name="tareas",
            is_active=True,
        )
        cls.role = TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="MYSQL_CONFIG",
            mysql_connection=cls.mysql_connection,
            database_name="tareas",
        )
        cls.admin_user = User.objects.create_superuser(
            username="connection-role-admin",
            email="connection-role-admin@example.test",
            password="test-password",
        )

    def setUp(self):
        self.client.force_login(self.admin_user)

    def test_role_is_registered_with_admin_site(self):
        self.assertTrue(admin.site.is_registered(TareaConnectionRole))

    def test_authorized_user_can_open_changelist_without_operational_queries(self):
        operational_tables = {
            model._meta.db_table
            for model in apps.get_app_config("tareas").get_models(include_auto_created=True)
            if model is not TareaConnectionRole
        }
        table_pattern = re.compile(
            r'\b(?:FROM|JOIN|UPDATE|INTO)\s+["`\[]?([\w]+)',
            re.IGNORECASE,
        )
        with CaptureQueriesContext(connections["default"]) as captured_queries:
            response = self.client.get(
                reverse("admin:tareas_tareaconnectionrole_changelist")
            )

        queried_tables = {
            match.group(1).lower()
            for query in captured_queries.captured_queries
            for match in table_pattern.finditer(query["sql"])
            if match.group(1).lower() in operational_tables
        }
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "BASE_TAREAS")
        self.assertEqual(queried_tables, set())

    def test_admin_views_are_read_only_and_disable_actions(self):
        model_admin = admin.site._registry[TareaConnectionRole]
        request = RequestFactory().get("/")
        request.user = self.admin_user

        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request, self.role))
        self.assertFalse(model_admin.has_delete_permission(request, self.role))
        self.assertIsNone(model_admin.actions)
        self.assertEqual(
            set(model_admin.get_readonly_fields(request)),
            {field.name for field in TareaConnectionRole._meta.fields},
        )

        add_response = self.client.post(
            reverse("admin:tareas_tareaconnectionrole_add"),
            {"role": "LEGACY_MYSQL"},
        )
        change_response = self.client.post(
            reverse(
                "admin:tareas_tareaconnectionrole_change",
                args=(self.role.pk,),
            ),
            {"role": "LEGACY_MYSQL"},
        )
        delete_response = self.client.post(
            reverse(
                "admin:tareas_tareaconnectionrole_delete",
                args=(self.role.pk,),
            ),
            {"post": "yes"},
        )

        self.assertEqual(add_response.status_code, 403)
        self.assertEqual(change_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        self.role.refresh_from_db()
        self.assertEqual(self.role.role, "BASE_TAREAS")

    def test_changelist_does_not_expose_connection_credentials(self):
        response = self.client.get(
            reverse("admin:tareas_tareaconnectionrole_changelist")
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.password_sentinel)
        self.assertContains(response, "base_tareas_test")
