import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from tareas.services.locals import LocalRecord
from tareas.services.providers import ProviderRecord
from tareas.views import (
    LocalCatalogMutationView,
    LocalMasterView,
    ProviderCatalogMutationView,
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

    def test_mutation_endpoint_stays_blocked_until_gate_closes(self):
        with patch("tareas.views._master_catalog_company_id", return_value=3):
            provider_response = ProviderCatalogMutationView().post(
                self.request("post"), operation_id=uuid4()
            )
            local_response = LocalCatalogMutationView().post(
                self.request("post"), operation_id=uuid4()
            )

        self.assertEqual(provider_response.status_code, 409)
        self.assertEqual(local_response.status_code, 409)
        self.assertEqual(json.loads(provider_response.content)["success"], False)
        self.assertEqual(json.loads(local_response.content)["success"], False)
