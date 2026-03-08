from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from evaluaciones.models import Persona


def _employee_payload(*, person_id: int) -> dict:
    return {
        "person_id": person_id,
        "id": 13229,
        "first_name": "Ana",
        "surname": "Pérez",
        "second_surname": "Gómez",
        "full_name": "Ana Pérez Gómez",
        "document_type": "RUT",
        "document_number": "12345678",
        "rut": "12345678-9",
        "code_sheet": "CS-01",
        "email": "ana@example.com",
        "personal_email": "ana.personal@example.com",
        "address": "Dirección 1",
        "street": "Calle 1",
        "street_number": "100",
        "office_number": "",
        "city": "Santiago",
        "district": "Centro",
        "location_id": 242,
        "region": "RM",
        "office_phone": None,
        "phone": "+56911111111",
        "gender": "F",
        "birthday": "1989-12-01",
        "active_since": "2024-03-14",
        "created_at": "2025-03-07T15:56:12.444-03:00",
        "status": "activo",
        "payment_method": "transferencia",
        "payment_period": "mensual",
        "advance_payment": "no",
        "bank": "Banco",
        "account_type": "corriente",
        "account_number": "123",
        "private_role": False,
        "progressive_vacations_start": "2037-03-14",
        "nationality": "CL",
        "country_code": "CL",
        "civil_status": "soltero",
        "health_company": "isapre",
        "pension_regime": "regimen",
        "pension_fund": "fondo",
        "afc": "afc",
        "retired": False,
    }


class ImportarPersonasViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u", password="p")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 1")
        self.vista = Vista.objects.create(nombre="Evaluaciones - Importar Personas")
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session.save()

    @patch("api.services.buk_api.fetch_active_employees")
    def test_post_import_creates_persona_and_renders_result(self, mock_fetch):
        employee = _employee_payload(person_id=16047)
        mock_fetch.return_value = {"pagination": {"next": None}, "data": [employee]}

        url = reverse("evaluaciones:importar_personas")
        resp = self.client.post(url, {"date": "2026-03-07", "exclude_pending": "on"})

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Persona.objects.filter(person_id=16047).exists())
        self.assertIn("import_result", resp.context)
        self.assertEqual(resp.context["import_result"].creados, 1)

    def test_post_invalid_date_returns_controlled_error(self):
        url = reverse("evaluaciones:importar_personas")
        resp = self.client.post(url, {"date": "2026-13-40"})

        self.assertEqual(resp.status_code, 200)
        self.assertIn("import_error_key", resp.context)
        self.assertEqual(resp.context["import_error_key"], "evaluaciones.personas.import.error.date_invalid")

    def test_view_requires_permission(self):
        # Usuario sin permiso para la vista
        user2 = User.objects.create_user(username="u2", password="p")
        self.client.force_login(user2)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session.save()

        url = reverse("evaluaciones:importar_personas")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)
