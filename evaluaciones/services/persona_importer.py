from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from api.services import buk_api

from ..models import Persona


@dataclass(frozen=True)
class PersonaImportResult:
    total_recibidos: int
    creados: int
    actualizados: int
    omitidos: int
    errores: int
    paginas_procesadas: int


class PersonaImportServiceError(Exception):
    def __init__(self, message_key: str):
        super().__init__(message_key)
        self.message_key = message_key


_MAX_PAGES = 500
_BULK_BATCH_SIZE = 200

_NULLABLE_STRING_FIELDS = {
    "second_surname",
    "email",
    "personal_email",
    "office_number",
    "office_phone",
}

_NULLABLE_INT_FIELDS = {"location_id"}

_UPDATE_FIELDS = [
    "full_name",
    "first_name",
    "surname",
    "second_surname",
    "document_type",
    "document_number",
    "rut",
    "code_sheet",
    "email",
    "personal_email",
    "address",
    "street",
    "street_number",
    "office_number",
    "city",
    "district",
    "location_id",
    "region",
    "office_phone",
    "phone",
    "gender",
    "birthday",
    "active_since",
    "created_at",
    "status",
    "payment_method",
    "payment_period",
    "advance_payment",
    "bank",
    "account_type",
    "account_number",
    "private_role",
    "progressive_vacations_start",
    "nationality",
    "country_code",
    "civil_status",
    "health_company",
    "pension_regime",
    "pension_fund",
    "afc",
    "retired",
    "mes",
    "anio",
]


def _get_max_lengths() -> Dict[str, Optional[int]]:
    max_lengths: Dict[str, Optional[int]] = {}
    for field_name in _UPDATE_FIELDS + ["rut", "document_type", "document_number", "code_sheet"]:
        try:
            field = Persona._meta.get_field(field_name)
        except Exception:
            continue
        max_lengths[field_name] = getattr(field, "max_length", None)
    return max_lengths


_MAX_LENGTHS = _get_max_lengths()


def _truncate(value: str, *, max_length: Optional[int]) -> str:
    if max_length is None:
        return value
    if len(value) <= max_length:
        return value
    return value[:max_length]


def _as_str(value: Any, *, field_name: str, allow_none: bool) -> Optional[str]:
    if value is None:
        return None if allow_none else ""

    text = str(value)
    if text == "":
        return None if allow_none else ""

    return _truncate(text, max_length=_MAX_LENGTHS.get(field_name))


def _as_int(value: Any, *, allow_none: bool) -> Optional[int]:
    if value is None or value == "":
        return None if allow_none else 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return None if allow_none else 0


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    normalized = str(value).strip().lower()
    return normalized in ("true", "1", "yes", "y", "on")


def _parse_required_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    return parse_date(str(value))


def _parse_required_datetime(value: Any):
    if value is None or value == "":
        return None

    dt = parse_datetime(str(value))
    if dt is None:
        return None

    if settings.USE_TZ:
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
    else:
        if timezone.is_aware(dt):
            dt = timezone.make_naive(dt, timezone.get_current_timezone())

    return dt


def _extract_total_pages(pagination: Any) -> Optional[int]:
    if not isinstance(pagination, dict):
        return None

    for key in (
        "total_pages",
        "totalPages",
        "last_page",
        "lastPage",
        "pages",
    ):
        try:
            value = pagination.get(key)
            if value is None or value == "":
                continue
            pages = int(value)
            if pages > 0:
                return pages
        except (TypeError, ValueError):
            continue

    try:
        total_raw = pagination.get("total")
        if total_raw in (None, ""):
            total_raw = pagination.get("count")
        per_page_raw = pagination.get("per_page")
        if per_page_raw in (None, ""):
            per_page_raw = pagination.get("perPage")
        if per_page_raw in (None, ""):
            per_page_raw = pagination.get("limit")

        total = int(total_raw) if total_raw not in (None, "") else 0
        per_page = int(per_page_raw) if per_page_raw not in (None, "") else 0
        if total > 0 and per_page > 0:
            return (total + per_page - 1) // per_page
    except (TypeError, ValueError):
        return None

    return None


def _map_employee_to_persona_fields(employee: Dict[str, Any], *, import_date: date) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        person_id_raw = employee.get("person_id")
        if person_id_raw is None or person_id_raw == "":
            return None, "evaluaciones.personas.import.error.missing_person_id"
        person_id = int(person_id_raw)
    except (TypeError, ValueError):
        return None, "evaluaciones.personas.import.error.missing_person_id"

    birthday = _parse_required_date(employee.get("birthday"))
    if not birthday:
        return None, "evaluaciones.personas.import.error.invalid_date_fields"

    active_since = _parse_required_date(employee.get("active_since"))
    if not active_since:
        return None, "evaluaciones.personas.import.error.invalid_date_fields"

    progressive_vacations_start = _parse_required_date(employee.get("progressive_vacations_start"))
    if not progressive_vacations_start:
        return None, "evaluaciones.personas.import.error.invalid_date_fields"

    created_at = _parse_required_datetime(employee.get("created_at"))
    if not created_at:
        return None, "evaluaciones.personas.import.error.invalid_datetime_fields"

    gender_value = _as_str(employee.get("gender"), field_name="gender", allow_none=False) or ""
    gender_value = (gender_value[:1] if gender_value else "")

    fields: Dict[str, Any] = {
        "person_id": person_id,
        "full_name": _as_str(employee.get("full_name"), field_name="full_name", allow_none=False) or "",
        "first_name": _as_str(employee.get("first_name"), field_name="first_name", allow_none=False) or "",
        "surname": _as_str(employee.get("surname"), field_name="surname", allow_none=False) or "",
        "second_surname": _as_str(
            employee.get("second_surname"),
            field_name="second_surname",
            allow_none=True,
        ),
        "document_type": _as_str(employee.get("document_type"), field_name="document_type", allow_none=False) or "",
        "document_number": _as_str(employee.get("document_number"), field_name="document_number", allow_none=False) or "",
        "rut": _as_str(employee.get("rut"), field_name="rut", allow_none=False) or "",
        "code_sheet": _as_str(employee.get("code_sheet"), field_name="code_sheet", allow_none=False) or "",
        "email": _as_str(employee.get("email"), field_name="email", allow_none=True),
        "personal_email": _as_str(employee.get("personal_email"), field_name="personal_email", allow_none=True),
        "address": _as_str(employee.get("address"), field_name="address", allow_none=False) or "",
        "street": _as_str(employee.get("street"), field_name="street", allow_none=False) or "",
        "street_number": _as_str(employee.get("street_number"), field_name="street_number", allow_none=False) or "",
        "office_number": _as_str(employee.get("office_number"), field_name="office_number", allow_none=True),
        "city": _as_str(employee.get("city"), field_name="city", allow_none=False) or "",
        "district": _as_str(employee.get("district"), field_name="district", allow_none=False) or "",
        "location_id": _as_int(employee.get("location_id"), allow_none=True),
        "region": _as_str(employee.get("region"), field_name="region", allow_none=False) or "",
        "office_phone": _as_str(employee.get("office_phone"), field_name="office_phone", allow_none=True),
        "phone": _as_str(employee.get("phone"), field_name="phone", allow_none=False) or "",
        "gender": gender_value,
        "birthday": birthday,
        "active_since": active_since,
        "created_at": created_at,
        "status": _as_str(employee.get("status"), field_name="status", allow_none=False) or "",
        "payment_method": _as_str(employee.get("payment_method"), field_name="payment_method", allow_none=False) or "",
        "payment_period": _as_str(employee.get("payment_period"), field_name="payment_period", allow_none=False) or "",
        "advance_payment": _as_str(employee.get("advance_payment"), field_name="advance_payment", allow_none=False) or "",
        "bank": _as_str(employee.get("bank"), field_name="bank", allow_none=False) or "",
        "account_type": _as_str(employee.get("account_type"), field_name="account_type", allow_none=False) or "",
        "account_number": _as_str(employee.get("account_number"), field_name="account_number", allow_none=False) or "",
        "private_role": _as_bool(employee.get("private_role")),
        "progressive_vacations_start": progressive_vacations_start,
        "nationality": _as_str(employee.get("nationality"), field_name="nationality", allow_none=False) or "",
        "country_code": _as_str(employee.get("country_code"), field_name="country_code", allow_none=False) or "",
        "civil_status": _as_str(employee.get("civil_status"), field_name="civil_status", allow_none=False) or "",
        "health_company": _as_str(employee.get("health_company"), field_name="health_company", allow_none=False) or "",
        "pension_regime": _as_str(employee.get("pension_regime"), field_name="pension_regime", allow_none=False) or "",
        "pension_fund": _as_str(employee.get("pension_fund"), field_name="pension_fund", allow_none=False) or "",
        "afc": _as_str(employee.get("afc"), field_name="afc", allow_none=False) or "",
        "retired": _as_bool(employee.get("retired")),
        "mes": import_date.month,
        "anio": import_date.year,
    }

    for field_name in _NULLABLE_STRING_FIELDS:
        if fields.get(field_name) == "":
            fields[field_name] = None

    for field_name in _NULLABLE_INT_FIELDS:
        if fields.get(field_name) == 0:
            fields[field_name] = None

    return fields, None


def importar_personas_desde_api_interna(
    date_value: Any,
    exclude_pending: Any,
    request_user=None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> PersonaImportResult:
    date_str = (str(date_value) if date_value is not None else "").strip()
    if not date_str:
        raise PersonaImportServiceError("evaluaciones.personas.import.error.date_required")

    try:
        import_date = date.fromisoformat(date_str)
    except ValueError:
        raise PersonaImportServiceError("evaluaciones.personas.import.error.date_invalid") from None

    exclude_pending_bool = _as_bool(exclude_pending)

    pages_processed = 0
    all_employees: List[Dict[str, Any]] = []

    try:
        payload = buk_api.fetch_active_employees(date_str=date_str, exclude_pending=exclude_pending_bool)

        while True:
            pages_processed += 1
            if not isinstance(payload, dict):
                raise PersonaImportServiceError("evaluaciones.personas.import.error.invalid_response")

            page_items = payload.get("data")
            if not isinstance(page_items, list):
                raise PersonaImportServiceError("evaluaciones.personas.import.error.invalid_response")

            all_employees.extend(page_items)

            pagination = payload.get("pagination")
            next_url = None
            if isinstance(pagination, dict):
                next_url = pagination.get("next")

            if progress_callback:
                try:
                    progress_callback(
                        {
                            "message_key": "evaluaciones.personas.import.in_progress",
                            "current_page": pages_processed,
                            "total_pages": _extract_total_pages(pagination),
                            "total_received": len(all_employees),
                        }
                    )
                except Exception:
                    # Progreso best-effort: nunca debe romper la importación
                    pass

            if not next_url:
                break

            if pages_processed >= _MAX_PAGES:
                raise PersonaImportServiceError("evaluaciones.personas.import.error.too_many_pages")

            payload = buk_api.fetch_buk_url(url=next_url)

    except PersonaImportServiceError:
        raise
    except buk_api.BukAPIError:
        raise PersonaImportServiceError("evaluaciones.personas.import.error.api") from None
    except Exception:
        raise PersonaImportServiceError("evaluaciones.personas.import.error.api") from None

    total_recibidos = len(all_employees)

    employees_by_person_id: Dict[int, Dict[str, Any]] = {}
    duplicates = 0
    errors = 0

    for item in all_employees:
        if not isinstance(item, dict):
            errors += 1
            continue

        person_id_raw = item.get("person_id")
        try:
            person_id_int = int(person_id_raw)
        except (TypeError, ValueError):
            errors += 1
            continue

        if person_id_int in employees_by_person_id:
            duplicates += 1
        employees_by_person_id[person_id_int] = item

    person_ids = list(employees_by_person_id.keys())
    existing_by_person_id = {
        p.person_id: p for p in Persona.objects.filter(person_id__in=person_ids)
    }

    to_create: List[Persona] = []
    to_update: List[Persona] = []

    created_count = 0
    updated_count = 0
    omitted_count = duplicates

    try:
        with transaction.atomic():
            for person_id_int, employee in employees_by_person_id.items():
                mapped, map_error_key = _map_employee_to_persona_fields(employee, import_date=import_date)
                if not mapped:
                    errors += 1
                    continue

                existing = existing_by_person_id.get(person_id_int)
                if not existing:
                    to_create.append(Persona(**mapped))
                    created_count += 1
                    continue

                changed = False
                for field_name in _UPDATE_FIELDS:
                    if getattr(existing, field_name) != mapped.get(field_name):
                        changed = True
                        break

                if not changed:
                    omitted_count += 1
                    continue

                for field_name in _UPDATE_FIELDS:
                    setattr(existing, field_name, mapped.get(field_name))

                to_update.append(existing)
                updated_count += 1

            if to_create:
                Persona.objects.bulk_create(to_create, batch_size=_BULK_BATCH_SIZE)

            if to_update:
                Persona.objects.bulk_update(to_update, _UPDATE_FIELDS, batch_size=_BULK_BATCH_SIZE)

    except Exception:
        raise PersonaImportServiceError("evaluaciones.personas.import.error.db") from None

    return PersonaImportResult(
        total_recibidos=total_recibidos,
        creados=created_count,
        actualizados=updated_count,
        omitidos=omitted_count,
        errores=errors,
        paginas_procesadas=pages_processed,
    )
