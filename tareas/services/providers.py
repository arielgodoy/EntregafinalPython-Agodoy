"""SQL service for the Tareas Proveedores catalog."""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import connections
from django.utils import timezone

from tareas.utils.rut import RutValidationError, normalizar_rut

from .master_catalog_common import (
    CompanyContext,
    MasterCatalogNotFound,
    MasterCatalogBackendError,
    MasterCatalogConflict,
    MasterCatalogDatabaseError,
    MasterCatalogValidationError,
    MutationMetadata,
    MutationResult,
    execute_or_raise_conflict,
    execute_or_raise_database,
    normalize_optional_text,
    normalize_required_text,
    require_metadata,
    require_company_context,
    verify_base_tareas_database,
    verified_base_tareas_connection,
)
from .connection_roles import TareaConnectionError, resolve_operational_backend
from .master_operation_service import MasterMutationChange, execute_master_mutation


@dataclass(frozen=True)
class ProviderRecord:
    id: int
    rut: str | None
    nombre: str
    direccion: str
    comuna: str
    ciudad: str
    fono1: str
    fono2: str
    fax: str
    contacto: str
    email1: str
    email2: str
    activo: bool
    created_at: object
    updated_at: object


@dataclass(frozen=True)
class ProviderInput:
    rut: str | None
    nombre: str
    direccion: str = ""
    comuna: str = ""
    ciudad: str = ""
    fono1: str = ""
    fono2: str = ""
    fax: str = ""
    contacto: str = ""
    email1: str = ""
    email2: str = ""


_PROVIDER_COLUMNS = (
    "id, rut, nombre, direccion, comuna, ciudad, fono1, fono2, fax, "
    "contacto, email1, email2, activo, created_at, updated_at"
)
_PROVIDER_INPUT_FIELDS = (
    "rut",
    "nombre",
    "direccion",
    "comuna",
    "ciudad",
    "fono1",
    "fono2",
    "fax",
    "contacto",
    "email1",
    "email2",
)


def _record(row) -> ProviderRecord:
    return ProviderRecord(
        id=row[0],
        rut=row[1],
        nombre=row[2],
        direccion=row[3],
        comuna=row[4],
        ciudad=row[5],
        fono1=row[6],
        fono2=row[7],
        fax=row[8],
        contacto=row[9],
        email1=row[10],
        email2=row[11],
        activo=bool(row[12]),
        created_at=row[13],
        updated_at=row[14],
    )


def _normalize_input(data: ProviderInput) -> tuple[object, ...]:
    if not isinstance(data, ProviderInput):
        raise MasterCatalogValidationError("Los datos del Proveedor no son válidos.")
    try:
        rut = normalizar_rut(data.rut)
    except (RutValidationError, TypeError) as exc:
        raise MasterCatalogValidationError("El RUT no es válido.") from exc
    values = [
        normalize_required_text(data.nombre, "nombre", 255),
        normalize_optional_text(data.direccion, "direccion", 255),
        normalize_optional_text(data.comuna, "comuna", 100),
        normalize_optional_text(data.ciudad, "ciudad", 100),
        normalize_optional_text(data.fono1, "fono1", 30),
        normalize_optional_text(data.fono2, "fono2", 30),
        normalize_optional_text(data.fax, "fax", 30),
        normalize_optional_text(data.contacto, "contacto", 150),
        normalize_optional_text(data.email1, "email1", 254),
        normalize_optional_text(data.email2, "email2", 254),
    ]
    for field_name, value in (("email1", values[8]), ("email2", values[9])):
        if value:
            try:
                validate_email(value)
            except ValidationError as exc:
                raise MasterCatalogValidationError(
                    f"{field_name} no tiene un formato válido."
                ) from exc
    return (
        rut,
        values[0],
        values[1],
        values[2],
        values[3],
        values[4],
        values[5],
        values[6],
        values[7],
        values[8],
        values[9],
    )


def _read_provider(cursor, provider_id: int, *, lock: bool = False) -> ProviderRecord:
    execute_or_raise_database(
        cursor,
        f"SELECT {_PROVIDER_COLUMNS} FROM proveedores_proveedor WHERE id=%s"
        + (" FOR UPDATE" if lock else ""),
        (provider_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise MasterCatalogNotFound("El Proveedor no existe.")
    return _record(row)


def get_provider_from_cursor(
    cursor,
    provider_id: int,
    *,
    include_inactive: bool = True,
    lock: bool = False,
) -> ProviderRecord:
    """Read a Tareas provider using the caller's already-resolved connection."""
    if (
        not isinstance(provider_id, int)
        or isinstance(provider_id, bool)
        or provider_id <= 0
    ):
        raise MasterCatalogValidationError("El ID del Proveedor no es válido.")
    predicate = "" if include_inactive else " AND activo = 1"
    execute_or_raise_database(
        cursor,
        f"SELECT {_PROVIDER_COLUMNS} FROM proveedores_proveedor "
        f"WHERE id = %s{predicate}" + (" FOR UPDATE" if lock else ""),
        (provider_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise MasterCatalogNotFound("El Proveedor no existe.")
    return _record(row)


def get_provider_for_quotation(provider_id: int) -> ProviderRecord:
    """Resolve an active provider exclusively from the BASE_TAREAS role."""
    try:
        backend = resolve_operational_backend("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise MasterCatalogBackendError(
            "No se pudo resolver el rol BASE_TAREAS."
        ) from exc

    if backend.backend_type == "MYSQL_CONFIG":
        with verified_base_tareas_connection() as connection:
            cursor = connection.cursor()
            try:
                record = get_provider_from_cursor(
                    cursor,
                    provider_id,
                    include_inactive=True,
                )
                if not record.activo:
                    raise MasterCatalogValidationError(
                        "El Proveedor está inactivo para nuevas cotizaciones."
                    )
                return record
            finally:
                cursor.close()

    if backend.backend_type != "DJANGO" or not backend.django_alias:
        raise MasterCatalogBackendError(
            "El backend de BASE_TAREAS no es compatible con Proveedores."
        )

    connection = connections[backend.django_alias]
    if connection.vendor == "mysql":
        verify_base_tareas_database(
            connection,
            expected_database=backend.database_name or connection.settings_dict["NAME"],
        )
    cursor = connection.cursor()
    try:
        record = get_provider_from_cursor(
            cursor,
            provider_id,
            include_inactive=True,
        )
        if not record.activo:
            raise MasterCatalogValidationError(
                "El Proveedor está inactivo para nuevas cotizaciones."
            )
        return record
    finally:
        cursor.close()


def _audit_snapshot(record: ProviderRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "nombre": record.nombre,
        "activo": record.activo,
        "rut_informado": record.rut is not None,
    }


def list_providers(*, active_only: bool = False, search: str = "") -> tuple[ProviderRecord, ...]:
    search = normalize_optional_text(search, "search", 255)
    clauses = []
    params: list[object] = []
    if active_only:
        clauses.append("activo = 1")
    if search:
        clauses.append("(nombre LIKE %s OR rut LIKE %s)")
        params.append(f"%{search}%")
        params.append(f"%{search}%")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with verified_base_tareas_connection() as connection:
        cursor = connection.cursor()
        try:
            execute_or_raise_database(
                cursor,
                f"SELECT {_PROVIDER_COLUMNS} FROM proveedores_proveedor"
                f"{where} ORDER BY nombre, id",
                tuple(params),
            )
            return tuple(_record(row) for row in cursor.fetchall())
        finally:
            cursor.close()


def get_provider(provider_id: int, *, include_inactive: bool = True) -> ProviderRecord:
    if (
        not isinstance(provider_id, int)
        or isinstance(provider_id, bool)
        or provider_id <= 0
    ):
        raise MasterCatalogValidationError("El ID del Proveedor no es válido.")
    with verified_base_tareas_connection() as connection:
        cursor = connection.cursor()
        try:
            return get_provider_from_cursor(
                cursor,
                provider_id,
                include_inactive=include_inactive,
            )
        finally:
            cursor.close()


def create_provider(
    context: CompanyContext,
    data: ProviderInput,
    *,
    metadata: MutationMetadata,
) -> MutationResult:
    require_company_context(context)
    require_metadata(metadata)
    values = _normalize_input(data)
    payload = dict(zip(_PROVIDER_INPUT_FIELDS, values))
    payload["motivo"] = metadata.motivo.strip()
    now = timezone.now()

    def mutate(cursor):
        execute_or_raise_conflict(
            cursor,
            "INSERT INTO proveedores_proveedor "
            "(rut, nombre, direccion, comuna, ciudad, fono1, fono2, fax, "
            "contacto, email1, email2, activo, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)",
            (*values, now, now),
        )
        record = _read_provider(cursor, cursor.lastrowid, lock=True)
        return MasterMutationChange(
            record.id,
            None,
            _audit_snapshot(record),
            _PROVIDER_INPUT_FIELDS,
        )

    return execute_master_mutation(
        context=context,
        metadata=metadata,
        entity_type="PROVEEDOR",
        action="CREATE",
        payload=payload,
        mutate=mutate,
    )


def update_provider(
    context: CompanyContext,
    provider_id: int,
    data: ProviderInput,
    *,
    metadata: MutationMetadata,
) -> MutationResult:
    require_company_context(context)
    require_metadata(metadata)
    if (
        not isinstance(provider_id, int)
        or isinstance(provider_id, bool)
        or provider_id <= 0
    ):
        raise MasterCatalogValidationError("El ID del Proveedor no es válido.")
    values = _normalize_input(data)
    payload = dict(zip(_PROVIDER_INPUT_FIELDS, values))
    payload.update({"provider_id": provider_id, "motivo": metadata.motivo.strip()})
    now = timezone.now()

    def mutate(cursor):
        before = _read_provider(cursor, provider_id, lock=True)
        execute_or_raise_conflict(
            cursor,
            "UPDATE proveedores_proveedor SET rut=%s, nombre=%s, direccion=%s, "
            "comuna=%s, ciudad=%s, fono1=%s, fono2=%s, fax=%s, contacto=%s, "
            "email1=%s, email2=%s, updated_at=%s WHERE id=%s",
            (*values, now, provider_id),
        )
        after = _read_provider(cursor, provider_id, lock=True)
        changed_fields = tuple(
            field
            for field, new_value in zip(_PROVIDER_INPUT_FIELDS, values)
            if getattr(before, field) != new_value
        )
        return MasterMutationChange(
            provider_id,
            _audit_snapshot(before),
            _audit_snapshot(after),
            changed_fields,
        )

    return execute_master_mutation(
        context=context,
        metadata=metadata,
        entity_type="PROVEEDOR",
        action="UPDATE",
        payload=payload,
        mutate=mutate,
    )


def set_provider_active(
    context: CompanyContext,
    provider_id: int,
    active: bool,
    *,
    metadata: MutationMetadata,
) -> MutationResult:
    require_company_context(context)
    require_metadata(metadata)
    if (
        not isinstance(provider_id, int)
        or isinstance(provider_id, bool)
        or provider_id <= 0
    ):
        raise MasterCatalogValidationError("El ID del Proveedor no es válido.")
    if not isinstance(active, bool):
        raise MasterCatalogValidationError("El estado activo no es válido.")
    action = "RESTORE" if active else "DELETE"

    def mutate(cursor):
        before = _read_provider(cursor, provider_id, lock=True)
        execute_or_raise_database(
            cursor,
            "UPDATE proveedores_proveedor SET activo=%s, updated_at=%s WHERE id=%s",
            (int(active), timezone.now(), provider_id),
        )
        after = _read_provider(cursor, provider_id, lock=True)
        return MasterMutationChange(
            provider_id,
            _audit_snapshot(before),
            _audit_snapshot(after),
            ("activo",) if before.activo != after.activo else (),
        )

    return execute_master_mutation(
        context=context,
        metadata=metadata,
        entity_type="PROVEEDOR",
        action=action,
        payload={
            "provider_id": provider_id,
            "active": active,
            "motivo": metadata.motivo.strip(),
        },
        mutate=mutate,
    )


def delete_provider(
    context: CompanyContext,
    provider_id: int,
    *,
    metadata: MutationMetadata,
) -> MutationResult:
    require_company_context(context)
    require_metadata(metadata)
    if not isinstance(provider_id, int) or isinstance(provider_id, bool) or provider_id <= 0:
        raise MasterCatalogValidationError("El ID del Proveedor no es válido.")

    def mutate(cursor):
        before = _read_provider(cursor, provider_id, lock=True)
        execute_or_raise_database(
            cursor,
            "SELECT COUNT(*) FROM tareas_cotizacion WHERE proveedor_id=%s",
            (provider_id,),
        )
        references = int(cursor.fetchone()[0])
        if references:
            raise MasterCatalogConflict(
                "No es posible eliminar este registro porque está siendo utilizado "
                "por cotizaciones."
            )
        execute_or_raise_database(
            cursor,
            "DELETE FROM proveedores_proveedor WHERE id=%s",
            (provider_id,),
        )
        if cursor.rowcount != 1:
            raise MasterCatalogDatabaseError(
                "No se eliminó exactamente el Proveedor solicitado."
            )
        return MasterMutationChange(
            provider_id,
            _audit_snapshot(before),
            None,
            ("deleted",),
        )

    return execute_master_mutation(
        context=context,
        metadata=metadata,
        entity_type="PROVEEDOR",
        action="DELETE",
        payload={
            "provider_id": provider_id,
            "motivo": metadata.motivo.strip(),
        },
        mutate=mutate,
    )
