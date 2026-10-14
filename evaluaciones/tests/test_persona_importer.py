from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from django.test import TestCase

from evaluaciones.models import Persona
from evaluaciones.services.persona_storage import DjangoPersonaStorage
from evaluaciones.services.persona_importer import (
    _normalize_rut,
    importar_personas_desde_api_interna,
)


def _synthetic_rut(number: int) -> str:
    body = str(10_000_000 + number)
    total = 0
    factor = 2
    for digit in reversed(body):
        total += int(digit) * factor
        factor = 2 if factor == 7 else factor + 1
    remainder = 11 - total % 11
    check_digit = "0" if remainder == 11 else "K" if remainder == 10 else str(remainder)
    return f"{body[:2]}.{body[2:5]}.{body[5:]}-{check_digit}"


@contextmanager
def _open_test_storage():
    # Production resolution rejects default; this uses the isolated test database.
    yield DjangoPersonaStorage("default")


def _employee_payload(*, person_id: int, full_name: str) -> dict:
    return {
        "person_id": person_id,
        "id": 70000 + person_id,
        "first_name": "Ana",
        "surname": "Pérez",
        "second_surname": "Gómez",
        "full_name": full_name,
        "document_type": "RUT",
        "document_number": "12345678",
        "rut": _synthetic_rut(person_id),
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
        "active_until": None,
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
            "id": 30000 + person_id,
            "company_id": 15,
            "cost_center": "104",
            "area_id": 41,
            "start_date": "2023-01-02",
            "end_date": None,
            "contract_type": "indefinido",
            "role": {
                "id": 78,
                "code": "roticero",
                "name": "ROTISERO",
                "role_family": {"id": 81, "name": "Operaciones"},
            },
            "recinto_asistencia": {"id": 51, "code": "AS-01"},
            "recinto_primario": {"id": 52, "code": "PR-01"},
            "custom_attributes": {"ctrlit_recinto": "CTL-01"},
        },
    }


class PersonaImporterTests(TestCase):
    def setUp(self):
        storage_patch = patch(
            "evaluaciones.services.persona_importer.open_persona_storage",
            _open_test_storage,
        )
        storage_patch.start()
        self.addCleanup(storage_patch.stop)

    def test_normalizes_and_validates_rut_check_digit(self):
        self.assertEqual(_normalize_rut("10.000.123-3"), "100001233")
        self.assertIsNone(_normalize_rut("10.000.123-4"))

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
    def test_importer_updates_same_month_by_rut_and_preserves_primary_key(self, mock_fetch):
        employee = _employee_payload(person_id=16047, full_name="Nombre Inicial")
        mock_fetch.return_value = {"pagination": {"next": None}, "data": [employee]}
        first_result = importar_personas_desde_api_interna("2026-03-07", False)
        existing = Persona.objects.get(rut_normalizado=employee["rut"].replace(".", "").replace("-", ""))
        existing_id = existing.pk

        employee["full_name"] = "Nombre Actualizado"
        mock_fetch.return_value = {"pagination": {"next": None}, "data": [employee]}
        result = importar_personas_desde_api_interna("2026-03-07", False)

        self.assertEqual(first_result.creados, 1)
        self.assertEqual((result.creados, result.actualizados), (0, 1))
        self.assertEqual(Persona.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.pk, existing_id)
        self.assertEqual(existing.full_name, "Nombre Actualizado")
        self.assertEqual(existing.mes, 3)
        self.assertEqual(existing.anio, 2026)

    @patch("api.services.buk_api.fetch_active_employees")
    def test_selected_date_sets_month_year_and_cutoff_date(self, mock_fetch):
        employee = _employee_payload(person_id=16047, full_name="Persona Sintetica")
        mock_fetch.return_value = {"pagination": {"next": None}, "data": [employee]}

        importar_personas_desde_api_interna("2026-10-13", False)

        persona = Persona.objects.get()
        self.assertEqual((persona.anio, persona.mes), (2026, 10))
        self.assertEqual(persona.fecha_corte, date(2026, 10, 13))
        self.assertEqual(persona.rut_normalizado, employee["rut"].replace(".", "").replace("-", ""))
        mock_fetch.assert_called_once_with(
            date_str="2026-10-13",
            exclude_pending=False,
        )
        self.assertEqual(persona.buk_employee_id, employee["id"])
        self.assertNotEqual(persona.person_id, persona.buk_employee_id)

    @patch("api.services.buk_api.fetch_active_employees")
    def test_new_month_stores_new_snapshot_and_changed_organization(self, mock_fetch):
        employee = _employee_payload(person_id=16047, full_name="Persona Sintetica")
        mock_fetch.return_value = {"pagination": {"next": None}, "data": [employee]}
        importar_personas_desde_api_interna("2026-03-07", False)

        updated_employee = dict(employee)
        updated_employee["current_job"] = {
            **employee["current_job"],
            "company_id": 16,
            "role": {
                **employee["current_job"]["role"],
                "id": 79,
                "name": "Cargo Nuevo",
            },
            "recinto_asistencia": {"id": 61, "code": "AS-02"},
        }
        mock_fetch.return_value = {
            "pagination": {"next": None},
            "data": [updated_employee],
        }
        result = importar_personas_desde_api_interna("2026-04-13", False)

        self.assertEqual(result.creados, 1)
        self.assertEqual(Persona.objects.count(), 2)
        march = Persona.objects.get(anio=2026, mes=3)
        april = Persona.objects.get(anio=2026, mes=4)
        self.assertEqual(march.company_id, 15)
        self.assertEqual(march.role_id, 78)
        self.assertEqual(march.recinto_asistencia_code, "AS-01")
        self.assertEqual(april.company_id, 16)
        self.assertEqual(april.role_id, 79)
        self.assertEqual(april.role_name, "Cargo Nuevo")
        self.assertEqual(april.recinto_asistencia_code, "AS-02")

    @patch("api.services.buk_api.fetch_active_employees")
    def test_maps_organization_and_preserves_full_payload(self, mock_fetch):
        employee = _employee_payload(person_id=16047, full_name="Persona Sintetica")
        employee["current_job"]["custom_attributes"]["future_attribute"] = None
        employee["future_list"] = [None, {"nested_future": "value"}]
        mock_fetch.return_value = {"pagination": {"next": None}, "data": [employee]}

        importar_personas_desde_api_interna("2026-10-13", False)

        persona = Persona.objects.get()
        self.assertEqual(persona.company_id, 15)
        self.assertEqual(persona.role_id, 78)
        self.assertEqual(persona.role_code, "roticero")
        self.assertEqual(persona.role_name, "ROTISERO")
        self.assertEqual(persona.role_family_id, 81)
        self.assertEqual(persona.role_family_name, "Operaciones")
        self.assertEqual(persona.area_id, 41)
        self.assertEqual(persona.cost_center, "104")
        self.assertEqual(persona.recinto_asistencia_id, 51)
        self.assertEqual(persona.recinto_asistencia_code, "AS-01")
        self.assertEqual(persona.recinto_primario_id, 52)
        self.assertEqual(persona.recinto_primario_code, "PR-01")
        self.assertEqual(persona.ctrlit_recinto, "CTL-01")
        self.assertEqual(persona.job_id, employee["current_job"]["id"])
        self.assertEqual(persona.job_start_date, date(2023, 1, 2))
        self.assertIsNone(persona.job_end_date)
        self.assertEqual(persona.contract_type, "indefinido")
        self.assertEqual(persona.buk_payload, employee)

    @patch("api.services.buk_api.fetch_active_employees")
    def test_absent_nested_organization_fields_remain_null(self, mock_fetch):
        employee = _employee_payload(person_id=16047, full_name="Persona Sintetica")
        employee["current_job"] = None
        employee["custom_attributes"] = None
        mock_fetch.return_value = {"pagination": {"next": None}, "data": [employee]}

        importar_personas_desde_api_interna("2026-10-13", False)

        persona = Persona.objects.get()
        self.assertIsNone(persona.company_id)
        self.assertIsNone(persona.role_id)
        self.assertIsNone(persona.recinto_asistencia_id)
        self.assertIsNone(persona.recinto_primario_code)
        self.assertIsNone(persona.ctrlit_recinto)

    @patch("api.services.buk_api.fetch_active_employees")
    def test_invalid_or_missing_rut_is_counted_without_storing_a_row(self, mock_fetch):
        invalid = _employee_payload(person_id=16047, full_name="Dato Sintetico")
        invalid["rut"] = "12345678-9"
        missing = _employee_payload(person_id=16048, full_name="Otro Dato Sintetico")
        del missing["rut"]
        mock_fetch.return_value = {
            "pagination": {"next": None},
            "data": [invalid, missing],
        }

        result = importar_personas_desde_api_interna("2026-10-13", False)

        self.assertEqual(result.errores, 2)
        self.assertEqual(result.creados, 0)
        self.assertEqual(Persona.objects.count(), 0)

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
