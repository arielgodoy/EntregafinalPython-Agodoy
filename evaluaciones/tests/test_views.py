from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from evaluaciones.models import Persona
from evaluaciones.services.persona_storage import (
    DjangoPersonaStorage,
    PersonaStorageError,
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
    yield DjangoPersonaStorage("default")


def _list_test_period_data(requested_period=None):
    personas = list(
        Persona.objects.all().defer("buk_payload").order_by("-anio", "-mes", "full_name")
    )
    periods = sorted(
        {(persona.anio, persona.mes) for persona in personas},
        reverse=True,
    )
    selected_period = (
        requested_period
        if requested_period in periods
        else periods[0] if periods else None
    )
    period_people = [
        persona
        for persona in personas
        if selected_period == (persona.anio, persona.mes)
    ]
    return periods, selected_period, period_people


def _persona(
    *,
    pk,
    anio=2026,
    mes=2,
    rut_normalizado="100000001",
    company_id=None,
    ctrlit_recinto=None,
    role_id=None,
    role_name=None,
    role_family_name=None,
    area_id=None,
    cost_center=None,
    full_name="Persona Sintetica",
    email=None,
    status=None,
    buk_payload=None,
):
    return Persona(
        id=pk,
        person_id=pk + 10_000,
        anio=anio,
        mes=mes,
        rut="10.000.000-1",
        rut_normalizado=rut_normalizado,
        full_name=full_name,
        email=email,
        status=status,
        company_id=company_id,
        ctrlit_recinto=ctrlit_recinto,
        role_id=role_id,
        role_name=role_name,
        role_family_name=role_family_name,
        area_id=area_id,
        cost_center=cost_center,
        buk_payload=buk_payload or {},
    )


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
        storage_patch = patch(
            "evaluaciones.services.persona_importer.open_persona_storage",
            _open_test_storage,
        )
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        listing_patch = patch(
            "evaluaciones.views.list_persona_period_data",
            _list_test_period_data,
        )
        listing_patch.start()
        self.addCleanup(listing_patch.stop)

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
            supervisor=True,
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

        with patch(
            "evaluaciones.views.system_date_context",
            return_value={"fecha_sistema": "2026-10-13"},
        ):
            resp = self.client.post(
                reverse("evaluaciones:importar_personas"),
                {
                    "date": "2025-01-02",
                    "fecha": "2024-02-03",
                    "anio": "2020",
                    "mes": "4",
                    "exclude_pending": "on",
                },
            )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Persona.objects.filter(person_id=16047).exists())
        self.assertIn("import_result", resp.context)
        self.assertEqual(resp.context["import_result"].creados, 1)
        persona = Persona.objects.get(person_id=16047)
        self.assertEqual((persona.anio, persona.mes), (2026, 10))
        self.assertEqual(persona.fecha_corte.isoformat(), "2026-10-13")
        mock_fetch.assert_called_once_with(
            date_str="2026-10-13",
            exclude_pending=True,
        )

    def test_get_shows_official_system_date_read_only_and_keeps_period_filter(self):
        with patch(
            "evaluaciones.views.system_date_context",
            return_value={"fecha_sistema": "2026-10-13"},
        ):
            response = self.client.get(
                reverse("evaluaciones:importar_personas"),
                {"period": "2025-12"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fecha de Sistema")
        self.assertContains(response, "13-10-2026")
        self.assertContains(response, 'aria-readonly="true"')
        self.assertContains(response, 'name="period"')
        self.assertNotContains(response, 'id="importDate"')
        self.assertNotContains(response, 'name="date"')

    @patch("api.services.buk_api.fetch_active_employees")
    def test_missing_system_date_rejects_traditional_post(self, mock_fetch):
        with patch(
            "evaluaciones.views.system_date_context",
            return_value={"fecha_sistema": None},
        ):
            response = self.client.post(
                reverse("evaluaciones:importar_personas"),
                {"date": "2026-10-13"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["import_error_key"],
            "evaluaciones.personas.import.error.system_date_unavailable",
        )
        self.assertIsNone(response.context["import_result"])
        mock_fetch.assert_not_called()

    def test_system_date_resolution_error_is_controlled(self):
        with patch(
            "evaluaciones.views.system_date_context",
            side_effect=RuntimeError("synthetic resolver failure"),
        ):
            response = self.client.post(
                reverse("evaluaciones:importar_personas"),
                {"date": "2026-10-13"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["import_error_key"],
            "evaluaciones.personas.import.error.system_date_unavailable",
        )
        self.assertNotContains(response, "synthetic resolver failure")

    @patch("api.services.buk_api.fetch_active_employees")
    def test_authorized_system_date_change_applies_to_next_import(self, mock_fetch):
        employee = _employee_payload(person_id=16047)
        mock_fetch.return_value = {"pagination": {"next": None}, "data": [employee]}
        date_values = iter(("2026-10-13", "2026-11-02"))

        with patch(
            "evaluaciones.views.system_date_context",
            side_effect=lambda request: {
                "fecha_sistema": next(date_values),
            },
        ):
            first = self.client.post(
                reverse("evaluaciones:importar_personas"),
                {"date": "2001-01-01"},
            )
            second = self.client.post(
                reverse("evaluaciones:importar_personas"),
                {"date": "2001-01-01"},
            )

        self.assertEqual(first.context["import_result"].creados, 1)
        self.assertEqual(second.context["import_result"].creados, 1)
        self.assertCountEqual(
            list(Persona.objects.values_list("anio", "mes", "fecha_corte")),
            [
                (2026, 10, date(2026, 10, 13)),
                (2026, 11, date(2026, 11, 2)),
            ],
        )
        self.assertEqual(
            [call.kwargs["date_str"] for call in mock_fetch.call_args_list],
            ["2026-10-13", "2026-11-02"],
        )

    @patch("api.services.buk_api.fetch_buk_url")
    @patch("api.services.buk_api.fetch_active_employees")
    def test_system_date_is_pinned_across_all_import_pages(
        self,
        mock_fetch_active,
        mock_fetch_next,
    ):
        first_employee = _employee_payload(person_id=16047)
        second_employee = _employee_payload(person_id=16048)
        date_state = {"value": "2026-10-13"}
        mock_fetch_active.return_value = {
            "pagination": {"next": "https://synthetic.invalid/page/2"},
            "data": [first_employee],
        }

        def fetch_second_page(*, url):
            date_state["value"] = "2026-11-02"
            return {"pagination": {"next": None}, "data": [second_employee]}

        mock_fetch_next.side_effect = fetch_second_page
        with patch(
            "evaluaciones.views.system_date_context",
            side_effect=lambda request: {
                "fecha_sistema": date_state["value"],
            },
        ) as mock_system_date:
            response = self.client.post(
                reverse("evaluaciones:importar_personas"),
                {"date": "2001-01-01"},
            )

        self.assertEqual(response.context["import_result"].paginas_procesadas, 2)
        self.assertEqual(mock_system_date.call_count, 1)
        self.assertEqual(
            list(
                Persona.objects.order_by("person_id").values_list(
                    "anio",
                    "mes",
                    "fecha_corte",
                )
            ),
            [
                (2026, 10, date(2026, 10, 13)),
                (2026, 10, date(2026, 10, 13)),
            ],
        )
        mock_fetch_active.assert_called_once_with(
            date_str="2026-10-13",
            exclude_pending=False,
        )

    @patch("api.services.buk_api.fetch_active_employees")
    def test_legacy_import_post_requires_supervisor_permission(self, mock_fetch):
        permission = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
        )
        permission.supervisor = False
        permission.save(update_fields=["supervisor"])

        response = self.client.post(
            reverse("evaluaciones:importar_personas"),
            {"date": "2026-03-07"},
        )

        self.assertEqual(response.status_code, 403)
        mock_fetch.assert_not_called()

    @patch("api.services.buk_api.fetch_active_employees")
    def test_invalid_rut_error_does_not_expose_personal_payload(self, mock_fetch):
        employee = _employee_payload(person_id=16047)
        employee["rut"] = "99999999-0"
        employee["private_test_marker"] = "synthetic-payload-marker"
        mock_fetch.return_value = {"pagination": {"next": None}, "data": [employee]}

        with patch(
            "evaluaciones.views.system_date_context",
            return_value={"fecha_sistema": "2026-10-13"},
        ):
            response = self.client.post(
                reverse("evaluaciones:importar_personas"),
                {"date": "2026-03-07"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["import_result"].errores, 1)
        self.assertNotContains(response, "synthetic-payload-marker")
        self.assertNotContains(response, "99999999-0")

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

    def test_list_storage_failure_is_reported_as_controlled_error(self):
        with patch(
            "evaluaciones.views.list_persona_period_data",
            side_effect=PersonaStorageError("storage unavailable"),
        ):
            resp = self.client.get(reverse("evaluaciones:importar_personas"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.context["import_error_key"],
            "evaluaciones.personas.import.error.db",
        )
        self.assertIsNone(resp.context["personas_total"])

    def test_default_period_is_the_most_recent_period_in_storage(self):
        people = [
            _persona(pk=11, anio=2025, mes=12, rut_normalizado="rut-anterior"),
            _persona(pk=12, anio=2026, mes=2, rut_normalizado="rut-reciente"),
        ]

        def list_period_data(requested_period=None):
            periods = [(2026, 2), (2025, 12)]
            selected = requested_period if requested_period in periods else periods[0]
            return (
                periods,
                selected,
                [p for p in people if (p.anio, p.mes) == selected],
            )

        with patch("evaluaciones.views.list_persona_period_data", list_period_data):
            response = self.client.get(reverse("evaluaciones:importar_personas"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_period"], "2026-02")
        self.assertEqual([p.pk for p in response.context["personas"]], [12])

    def test_selected_period_filters_monthly_snapshots_for_same_rut(self):
        people = [
            _persona(pk=11, anio=2025, mes=12, rut_normalizado="same-rut"),
            _persona(pk=12, anio=2026, mes=2, rut_normalizado="same-rut"),
        ]

        def list_period_data(requested_period=None):
            periods = [(2026, 2), (2025, 12)]
            selected = requested_period if requested_period in periods else periods[0]
            return (
                periods,
                selected,
                [p for p in people if (p.anio, p.mes) == selected],
            )

        with patch("evaluaciones.views.list_persona_period_data", list_period_data):
            response = self.client.get(
                reverse("evaluaciones:importar_personas"),
                {"period": "2025-12"},
            )

        self.assertEqual(response.context["selected_period"], "2025-12")
        self.assertEqual([p.pk for p in response.context["personas"]], [11])

    def test_organizational_filters_combine_and_options_follow_period_data(self):
        people = [
            _persona(
                pk=11,
                rut_normalizado="rut-a",
                company_id=10,
                ctrlit_recinto="LOCAL-A",
                role_id=5,
                role_name="Cargo A",
                role_family_name="Familia A",
                area_id=21,
                cost_center="CC-A",
            ),
            _persona(
                pk=12,
                rut_normalizado="rut-b",
                company_id=10,
                ctrlit_recinto="LOCAL-B",
                role_id=6,
                role_name="Cargo B",
                role_family_name="Familia B",
                area_id=22,
                cost_center="CC-B",
            ),
            _persona(
                pk=13,
                rut_normalizado="rut-c",
                company_id=20,
                ctrlit_recinto="LOCAL-A",
                role_id=5,
                role_name="Cargo A",
                role_family_name="Familia A",
                area_id=23,
                cost_center="CC-C",
            ),
        ]

        with patch(
            "evaluaciones.views.list_persona_period_data",
            return_value=([(2026, 2)], (2026, 2), people),
        ):
            response = self.client.get(
                reverse("evaluaciones:importar_personas"),
                {
                    "period": "2026-02",
                    "company_id": "10",
                    "ctrlit_recinto": "LOCAL-A",
                    "role_id": "5",
                },
            )

        self.assertEqual([p.pk for p in response.context["personas"]], [11])
        self.assertEqual(
            [option["value"] for option in response.context["company_options"]],
            ["10", "20"],
        )
        self.assertEqual(
            [option["label"] for option in response.context["company_options"]],
            ["Empresa BUK #10", "Empresa BUK #20"],
        )
        self.assertEqual(
            [option["value"] for option in response.context["location_options"]],
            ["LOCAL-A", "LOCAL-B"],
        )
        self.assertEqual(
            [option["value"] for option in response.context["role_options"]],
            ["5"],
        )
        self.assertNotEqual(self.empresa.id, 10)
        for value in (
            "Empresa BUK #10",
            "LOCAL-A",
            "Cargo A",
            "Familia A",
            "CC-A",
        ):
            self.assertContains(response, value)
        rendered = response.content.decode()
        self.assertIn(
            'evaluaciones.personas.value.area_prefix">',
            rendered,
        )
        self.assertIn("</span>21", rendered)

    def test_invalid_company_filter_fails_closed(self):
        people = [
            _persona(pk=11, company_id=10, ctrlit_recinto="LOCAL-A", role_id=5),
            _persona(pk=12, company_id=20, ctrlit_recinto="LOCAL-B", role_id=6),
        ]

        with patch(
            "evaluaciones.views.list_persona_period_data",
            return_value=([(2026, 2)], (2026, 2), people),
        ):
            response = self.client.get(
                reverse("evaluaciones:importar_personas"),
                {"period": "2026-02", "company_id": "999"},
            )

        self.assertEqual(response.context["personas"], [])
        self.assertTrue(response.context["persona_filter_error"])
        self.assertNotContains(response, "Persona Sintetica")

    def test_null_organization_values_are_labeled_without_payload_exposure(self):
        person = _persona(
            pk=11,
            rut_normalizado="rut-null",
            buk_payload={"synthetic_private_marker": "must-not-render"},
        )

        with patch(
            "evaluaciones.views.list_persona_period_data",
            return_value=([(2026, 2)], (2026, 2), [person]),
        ):
            response = self.client.get(
                reverse("evaluaciones:importar_personas"),
                {"period": "2026-02"},
            )

        self.assertContains(response, "Sin recinto")
        self.assertContains(response, "Sin información")
        self.assertNotContains(response, "must-not-render")
        content = response.content.decode()
        table_header = content.split("<thead>", 1)[1].split("</thead>", 1)[0]
        table_body = content.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        self.assertNotIn("evaluaciones.personas.columns.id", table_header)
        self.assertLess(
            table_header.index("evaluaciones.personas.columns.rut"),
            table_header.index("evaluaciones.personas.columns.full_name"),
        )
        self.assertEqual(
            table_header.count("evaluaciones.personas.columns.rut"),
            1,
        )
        self.assertNotIn("<td>11</td>", table_body)
        self.assertIn("<td>10.000.000-1</td>", table_body)
        self.assertEqual(Persona._meta.pk.name, "id")
        self.assertEqual(person.pk, 11)
        self.assertContains(response, "pageLength: 50")
