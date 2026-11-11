import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from tareas.services.locals import LocalRecord
from tareas.services.providers import ProviderRecord
from tareas.views import (
    LocalCatalogMutationView,
    LocalMasterView,
    ProviderCatalogMutationView,
    ProviderCatalogLifecycleView,
    ProviderCatalogUpdateView,
    ProviderDetailView,
    ProviderMasterView,
)


class MasterCatalogViewTests(SimpleTestCase):
    databases = {"default"}

    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(pk=7, is_active=True, is_authenticated=True)

    def request(self, method="get", path="/"):
        request = getattr(self.factory, method)(path)
        request.user = self.user
        request.session = {}
        return request

    def test_provider_list_uses_sql_service_and_renders_catalog(self):
        record = ProviderRecord(
            id=1,
            rut="76123456-0",
            nombre="Proveedor",
            direccion="",
            comuna="",
            ciudad="",
            fono1="",
            fono2="",
            fax="",
            contacto="",
            email1="",
            email2="",
            activo=True,
            created_at=None,
            updated_at=None,
        )
        with patch("tareas.views._master_catalog_company_id", return_value=3), patch(
            "tareas.views.list_providers",
            return_value=(record,),
        ), patch(
            "tareas.views.render",
            return_value=HttpResponse("Proveedor"),
        ) as render:
            response = ProviderMasterView().get(self.request())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Proveedor")
        self.assertEqual(render.call_args.args[2]["records"], (record,))

    def test_local_list_is_company_scoped_by_context(self):
        record = LocalRecord(
            id=2,
            empresa_id=3,
            codigo="L-1",
            nombre="Local",
            legacy_code=None,
            activo=True,
            source="LOCAL",
            created_at=None,
            updated_at=None,
        )
        with patch("tareas.views._master_catalog_company_id", return_value=3), patch(
            "tareas.views.list_locals",
            return_value=(record,),
        ) as list_locals, patch(
            "tareas.views.render",
            return_value=HttpResponse("L-1"),
        ) as render:
            response = LocalMasterView().get(self.request())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "L-1")
        self.assertEqual(list_locals.call_args.args[0].empresa_id, 3)
        self.assertEqual(render.call_args.args[2]["records"], (record,))

    def test_detail_endpoints_return_controlled_data(self):
        provider = ProviderRecord(
            1, None, "Proveedor", "", "", "", "", "", "", "", "", "", True, None, None
        )
        with patch("tareas.views._master_catalog_company_id", return_value=3), patch(
            "tareas.views.get_provider", return_value=provider
        ):
            response = ProviderDetailView().get(self.request(), 1)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["success"], True)
        self.assertEqual(payload["data"]["nombre"], "Proveedor")

    def test_provider_mutation_endpoint_creates_through_service(self):
        provider_request = self.factory.post(
            "/tareas/proveedores/maestro/crear/",
            data={
                "rut": "",
                "nombre": "Proveedor nuevo",
                "direccion": "",
                "comuna": "",
                "ciudad": "",
                "fono1": "",
                "fono2": "",
                "fax": "",
                "contacto": "",
                "email1": "",
                "email2": "",
                "motivo": "Alta de prueba",
                "operation_id": str(uuid4()),
            },
        )
        provider_request.user = self.user
        provider_request.session = {}
        with patch("tareas.views._master_catalog_company_id", return_value=3):
            with patch("tareas.views.create_provider") as create_provider:
                provider_response = ProviderCatalogMutationView().post(
                    provider_request,
                )
            local_request = self.factory.post(
                "/tareas/locales/maestro/crear/",
                data={
                    "codigo": "L-1",
                    "nombre": "Local nuevo",
                    "legacy_code": "",
                    "motivo": "Alta de prueba",
                    "operation_id": str(uuid4()),
                },
            )
            local_request.user = self.user
            local_request.session = {}
            with patch("tareas.views.create_local") as create_local:
                local_response = LocalCatalogMutationView().post(local_request)

        self.assertEqual(provider_response.status_code, 302)
        create_provider.assert_called_once()
        self.assertEqual(local_response.status_code, 302)
        create_local.assert_called_once()

    def test_provider_update_endpoint_uses_target_service(self):
        request = self.factory.post(
            "/tareas/proveedores/maestro/1/editar/",
            data={
                "rut": "",
                "nombre": "Proveedor editado",
                "direccion": "",
                "comuna": "",
                "ciudad": "",
                "fono1": "",
                "fono2": "",
                "fax": "",
                "contacto": "",
                "email1": "",
                "email2": "",
                "motivo": "Edición de prueba",
                "operation_id": str(uuid4()),
            },
        )
        request.user = self.user
        request.session = {}
        with patch("tareas.views._master_catalog_company_id", return_value=3):
            with patch("tareas.views.update_provider") as update_provider:
                response = ProviderCatalogUpdateView().post(
                    request,
                    provider_id=1,
                )

        self.assertEqual(response.status_code, 302)
        update_provider.assert_called_once()

    def test_provider_lifecycle_endpoint_uses_target_service(self):
        request = self.factory.post(
            "/tareas/proveedores/maestro/1/estado/",
            data={
                "activo": "0",
                "motivo": "Desactivación de prueba",
                "operation_id": str(uuid4()),
            },
        )
        request.user = self.user
        request.session = {}
        with patch("tareas.views._master_catalog_company_id", return_value=3):
            with patch("tareas.views.set_provider_active") as set_provider_active:
                response = ProviderCatalogLifecycleView().post(request, 1)

        self.assertEqual(response.status_code, 302)
        set_provider_active.assert_called_once()


class ProviderHttpFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="provider-http-user")
        self.empresa = Empresa.objects.create(
            codigo="31",
            descripcion="Empresa HTTP",
        )
        self.provider_view = Vista.objects.create(
            nombre="Maestros - Proveedores",
            route_name="tareas:maestros_proveedores_listado",
        )
        self.permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.provider_view,
            ver=True,
            ingresar=True,
            crear=True,
            modificar=True,
            eliminar=True,
        )
        for nombre, route_name in (
            ("Tareas - Maestro de locales", "tareas:maestros_locales_listado"),
            (
                "Tareas - Maestro de departamentos",
                "tareas:maestros_departamentos_listado",
            ),
        ):
            vista = Vista.objects.create(nombre=nombre, route_name=route_name)
            Permiso.objects.create(
                usuario=self.user,
                empresa=self.empresa,
                vista=vista,
                ver=True,
            )
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    @staticmethod
    def _provider_record(provider_id=17, *, active=True):
        return ProviderRecord(
            id=provider_id,
            rut="76123456-0",
            nombre="Proveedor HTTP",
            direccion="Av. de prueba 123",
            comuna="Santiago",
            ciudad="Santiago",
            fono1="123456",
            fono2="",
            fax="",
            contacto="Contacto",
            email1="contacto@example.test",
            email2="",
            activo=active,
            created_at=None,
            updated_at=None,
        )

    @staticmethod
    def _post_data():
        return {
            "rut": "",
            "nombre": "Proveedor HTTP",
            "direccion": "Av. de prueba 123",
            "comuna": "Santiago",
            "ciudad": "Santiago",
            "fono1": "123456",
            "fono2": "",
            "fax": "",
            "contacto": "Contacto",
            "email1": "contacto@example.test",
            "email2": "",
            "motivo": "Prueba HTTP autenticada",
            "operation_id": str(uuid4()),
        }

    def test_listing_routes_render_provider_action_and_full_master_navigation(self):
        with patch("tareas.views.list_providers", return_value=()):
            for route_name in (
                "tareas:maestros_proveedores_listado",
                "tareas:proveedores_maestro",
            ):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response,
                    f'href="{reverse("tareas:proveedores_maestro_crear")}"',
                )
                self.assertContains(response, 'id="sidebarTareas"')
                self.assertContains(response, 'id="sidebarTareasMaestros"')
                self.assertContains(
                    response,
                    f'href="{reverse("tareas:maestros_locales_listado")}"',
                )
                self.assertContains(
                    response,
                    f'href="{reverse("tareas:maestros_departamentos_listado")}"',
                )

    def test_creation_form_and_invalid_values_are_rendered_with_translated_errors(self):
        create_url = reverse("tareas:proveedores_maestro_crear")
        response = self.client.get(create_url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.context["form"].fields["operation_id"].widget.is_hidden
        )
        self.assertContains(response, 'data-key="tareas.master_catalog.provider.save"')

        with patch("tareas.views.create_provider") as create_provider:
            invalid_email = self._post_data()
            invalid_email["email1"] = "no-es-email"
            response = self.client.post(create_url, invalid_email)

            self.assertEqual(response.status_code, 400)
            self.assertContains(
                response,
                'data-key="tareas.master_catalog.provider.invalid_email"',
                status_code=400,
            )
            create_provider.assert_not_called()

            invalid_rut = self._post_data()
            invalid_rut["rut"] = "76.123.456-1"
            response = self.client.post(create_url, invalid_rut)

            self.assertEqual(response.status_code, 400)
            self.assertContains(
                response,
                'data-key="tareas.master_catalog.provider.invalid_rut"',
                status_code=400,
            )
            create_provider.assert_not_called()

    def test_create_detail_edit_and_lifecycle_http_flows(self):
        create_url = reverse("tareas:proveedores_maestro_crear")
        with patch("tareas.views.create_provider") as create_provider, patch(
            "tareas.views.list_providers",
            return_value=(),
        ):
            response = self.client.post(
                create_url,
                self._post_data(),
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain,
            [(reverse("tareas:proveedores_maestro"), 302)],
        )
        create_provider.assert_called_once()
        self.assertContains(
            response,
            'data-key="tareas.master_catalog.provider.created"',
        )

        provider_id = 17
        record = self._provider_record(provider_id)
        with patch("tareas.views.get_provider", return_value=record):
            detail = self.client.get(
                reverse("tareas:proveedores_maestro_detalle", args=[provider_id]),
                HTTP_ACCEPT="text/html",
            )
            edit_form = self.client.get(
                reverse("tareas:proveedores_maestro_editar", args=[provider_id])
            )

        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Proveedor HTTP")
        self.assertEqual(edit_form.status_code, 200)

        edit_url = reverse("tareas:proveedores_maestro_editar", args=[provider_id])
        with patch("tareas.views.update_provider") as update_provider, patch(
            "tareas.views.list_providers",
            return_value=(record,),
        ):
            response = self.client.post(
                edit_url,
                self._post_data(),
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        update_provider.assert_called_once()
        self.assertContains(
            response,
            'data-key="tareas.master_catalog.provider.updated"',
        )

        lifecycle_url = reverse(
            "tareas:proveedores_maestro_estado",
            args=[provider_id],
        )
        for active, message_key in (
            ("0", "tareas.master_catalog.provider.deactivated"),
            ("1", "tareas.master_catalog.provider.activated"),
        ):
            operation = {
                "activo": active,
                "motivo": "Cambio de estado de prueba",
                "operation_id": str(uuid4()),
            }
            with patch("tareas.views.set_provider_active") as set_active, patch(
                "tareas.views.list_providers",
                return_value=(record,),
            ):
                response = self.client.post(
                    lifecycle_url,
                    operation,
                    follow=True,
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(set_active.call_args.args[2], active == "1")
            self.assertContains(response, f'data-key="{message_key}"')

    def test_navigation_uses_ver_while_ingresar_still_returns_403(self):
        self.permission.ingresar = False
        self.permission.crear = False
        self.permission.save(update_fields=["ingresar", "crear"])

        dashboard = self.client.get(reverse("dashboard:dashboard_general"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, 'data-key="menu.tareas.masters"')
        self.assertContains(
            dashboard,
            f'href="{reverse("tareas:maestros_proveedores_listado")}"',
        )
        self.assertContains(
            dashboard,
            f'href="{reverse("tareas:maestros_locales_listado")}"',
        )
        self.assertContains(
            dashboard,
            f'href="{reverse("tareas:maestros_departamentos_listado")}"',
        )

        response = self.client.get(reverse("tareas:maestros_proveedores_listado"))
        self.assertEqual(response.status_code, 403)

    def test_create_button_is_hidden_without_create_permission(self):
        self.permission.crear = False
        self.permission.save(update_fields=["crear"])

        with patch("tareas.views.list_providers", return_value=()):
            response = self.client.get(reverse("tareas:maestros_proveedores_listado"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            'data-key="tareas.master_catalog.provider.create"',
        )

    def test_lifecycle_uses_modificar_and_delete_uses_eliminar(self):
        self.permission.modificar = False
        self.permission.save(update_fields=["modificar"])
        provider_id = 17
        lifecycle_url = reverse(
            "tareas:proveedores_maestro_estado",
            args=[provider_id],
        )

        with patch("tareas.views.list_providers", return_value=(self._provider_record(),)):
            active_list = self.client.get(
                reverse("tareas:maestros_proveedores_listado")
            )
        self.assertNotContains(
            active_list,
            'data-key="tareas.master_catalog.provider.deactivate"',
        )

        self.permission.modificar = True
        self.permission.save(update_fields=["modificar"])
        operation = {
            "activo": "1",
            "motivo": "Reactivación autorizada por modificar",
            "operation_id": str(uuid4()),
        }
        with patch("tareas.views.set_provider_active") as set_active:
            response = self.client.post(lifecycle_url, operation)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(set_active.call_args.args[2])

        operation["activo"] = "0"
        operation["operation_id"] = str(uuid4())
        with patch("tareas.views.set_provider_active") as set_active:
            response = self.client.post(lifecycle_url, operation)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(set_active.call_args.args[2])

    def test_provider_access_uses_the_active_company_not_a_request_parameter(self):
        other_company = Empresa.objects.create(
            codigo="32",
            descripcion="Otra Empresa",
        )
        session = self.client.session
        session["empresa_id"] = other_company.pk
        session.save()

        response = self.client.get(
            reverse("tareas:maestros_proveedores_listado"),
            {"empresa_id": self.empresa.pk},
        )

        self.assertEqual(response.status_code, 403)
