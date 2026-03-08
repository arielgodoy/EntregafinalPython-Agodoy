from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from evaluaciones.models import Persona
from evaluaciones.services.persona_importer import importar_personas_desde_api_interna


def _employee_payload(*, person_id: int, full_name: str) -> dict:
    return {
        "person_id": person_id,
        "id": 13229,
        "first_name": "Ana",
        "surname": "Pérez",
        "second_surname": "Gómez",
        "full_name": full_name,
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
        "current_job": {
            "company_id": 15,
            "cost_center": "104",
            "role": {"id": 78, "code": "roticero", "name": "ROTISERO"},
        },
    }


class PersonaImporterTests(TestCase):
    @patch("api.services.buk_api.fetch_active_employees")
    def test_importer_creates_persona_single_page(self, mock_fetch):
        employee = _employee_payload(person_id=16047, full_name="Ana Pérez Gómez")
        mock_fetch.return_value = {"pagination": {"next": None}, "data": [employee]}

        result = importar_personas_desde_api_interna("2026-03-07", True)

        self.assertEqual(result.paginas_procesadas, 1)
        self.assertEqual(result.total_recibidos, 1)
        self.assertEqual(result.creados, 1)
        self.assertEqual(result.actualizados, 0)
        self.assertEqual(result.omitidos, 0)
        self.assertEqual(result.errores, 0)

        p = Persona.objects.get(person_id=16047)
        self.assertEqual(p.full_name, "Ana Pérez Gómez")
        self.assertEqual(p.mes, 3)
        self.assertEqual(p.anio, 2026)

    @patch("api.services.buk_api.fetch_active_employees")
    def test_importer_updates_existing_persona_by_person_id(self, mock_fetch):
        Persona.objects.create(
            person_id=16047,
            full_name="Nombre Antiguo",
            first_name="Ana",
            surname="Pérez",
            second_surname=None,
            document_type="RUT",
            document_number="12345678",
            rut="12345678-9",
            code_sheet="CS-01",
            email=None,
            personal_email=None,
            address="Dirección 1",
            street="Calle 1",
            street_number="100",
            office_number=None,
            city="Santiago",
            district="Centro",
            location_id=None,
            region="RM",
            office_phone=None,
            phone="",
            gender="F",
            birthday=date(1989, 12, 1),
            active_since=date(2024, 3, 14),
            created_at=timezone.now(),
            status="activo",
            payment_method="transferencia",
            payment_period="mensual",
            advance_payment="no",
            bank="Banco",
            account_type="corriente",
            account_number="123",
            private_role=False,
            progressive_vacations_start=date(2037, 3, 14),
            nationality="CL",
            country_code="CL",
            civil_status="soltero",
            health_company="isapre",
            pension_regime="regimen",
            pension_fund="fondo",
            afc="afc",
            retired=False,
            mes=1,
            anio=2026,
        )

        employee = _employee_payload(person_id=16047, full_name="Nombre Nuevo")
        mock_fetch.return_value = {"pagination": {"next": None}, "data": [employee]}

        result = importar_personas_desde_api_interna("2026-03-07", False)

        self.assertEqual(result.creados, 0)
        self.assertEqual(result.actualizados, 1)

        p = Persona.objects.get(person_id=16047)
        self.assertEqual(p.full_name, "Nombre Nuevo")
        self.assertEqual(p.mes, 3)
        self.assertEqual(p.anio, 2026)

    @patch("api.services.buk_api.fetch_buk_url")
    @patch("api.services.buk_api.fetch_active_employees")
    def test_importer_multiple_pages_follows_pagination_next(self, mock_fetch, mock_fetch_next):
        employee1 = _employee_payload(person_id=16047, full_name="Persona 1")
        employee2 = _employee_payload(person_id=16048, full_name="Persona 2")

        mock_fetch.return_value = {
            "pagination": {"next": "https://buk.example/api/v1/employees/active?page=2"},
            "data": [employee1],
        }
        mock_fetch_next.return_value = {"pagination": {"next": None}, "data": [employee2]}

        result = importar_personas_desde_api_interna("2026-03-07", True)

        self.assertEqual(result.paginas_procesadas, 2)
        self.assertEqual(result.total_recibidos, 2)
        self.assertEqual(result.creados, 2)
        self.assertEqual(Persona.objects.count(), 2)

    @patch("api.services.buk_api.fetch_active_employees")
    def test_importer_counts_error_and_continues_on_invalid_employee(self, mock_fetch):
        invalid_employee = _employee_payload(person_id=16047, full_name="X")
        invalid_employee["birthday"] = None

        mock_fetch.return_value = {"pagination": {"next": None}, "data": [invalid_employee]}

        result = importar_personas_desde_api_interna("2026-03-07", False)

        self.assertEqual(result.total_recibidos, 1)
        self.assertEqual(result.creados, 0)
        self.assertEqual(result.actualizados, 0)
        self.assertEqual(result.errores, 1)
        self.assertEqual(Persona.objects.count(), 0)
