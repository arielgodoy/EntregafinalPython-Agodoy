"""SQL service for the company-scoped Locales catalog."""

from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from .master_catalog_common import (
    CompanyContext,
    MasterCatalogCapabilityBlocked,
    MasterCatalogConflict,
    MasterCatalogDatabaseError,
    MasterCatalogNotFound,
    MasterCatalogValidationError,
    MutationMetadata,
    MutationResult,
    execute_or_raise_conflict,
    execute_or_raise_database,
    normalize_optional_text,
    normalize_required_text,
    require_company_context,
    require_metadata,
    verified_base_tareas_connection,
)
from .master_operation_service import MasterMutationChange, execute_master_mutation


@dataclass(frozen=True)
class LocalRecord:
    id: int
    empresa_id: int
    codigo: str
    nombre: str
    legacy_code: str | None
    activo: bool
    source: str
    created_at: object
    updated_at: object


@dataclass(frozen=True)
class LocalInput:
    codigo: str
    nombre: str
    legacy_code: str | None = None
    source: str = "LOCAL"


def _record(row) -> LocalRecord:
    return LocalRecord(
        id=row[0],
        empresa_id=row[1],
        codigo=row[2],
        nombre=row[3],
        legacy_code=row[4],
        activo=bool(row[5]),
        source=row[6],
        created_at=row[7],
        updated_at=row[8],
    )


def _read_local(
    cursor,
    context: CompanyContext,
    local_id: int,
    *,
    lock: bool = False,
) -> LocalRecord:
    execute_or_raise_database(
        cursor,
        "SELECT id, empresa_id, codigo, nombre, legacy_code, activo, source, "
        "created_at, updated_at FROM organizacion_local "
        "WHERE id=%s AND empresa_id=%s" + (" FOR UPDATE" if lock else ""),
        (local_id, context.empresa_id),
    )
    row = cursor.fetchone()
    if row is None:
        raise MasterCatalogNotFound("El Local no existe en la Empresa activa.")
    return _record(row)


def _audit_snapshot(record: LocalRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "empresa_id": record.empresa_id,
        "codigo": record.codigo,
        "nombre": record.nombre,
        "legacy_code": record.legacy_code,
        "activo": record.activo,
        "source": record.source,
    }


def _normalize_input(data: LocalInput) -> tuple[str, str, str | None]:
    if not isinstance(data, LocalInput):
        raise MasterCatalogValidationError("Los datos del Local no son válidos.")
    source = normalize_required_text(data.source, "source", 5).upper()
    if source != "LOCAL":
        raise MasterCatalogCapabilityBlocked(
            "La escritura de Locales ERP requiere el contrato de sincronización."
        )
    return (
        normalize_required_text(data.codigo, "codigo", 100),
        normalize_required_text(data.nombre, "nombre", 255),
        normalize_optional_text(data.legacy_code, "legacy_code", 100) or None,
    )


def list_locals(
    context: CompanyContext,
    *,
    active_only: bool = False,
    search: str = "",
) -> tuple[LocalRecord, ...]:
    require_company_context(context)
    search = normalize_optional_text(search, "search", 255)
    where = "empresa_id=%s"
    params: list[object] = [context.empresa_id]
    if active_only:
        where += " AND activo=1"
    if search:
        where += " AND (codigo LIKE %s OR nombre LIKE %s OR legacy_code LIKE %s)"
        params.extend((f"%{search}%", f"%{search}%", f"%{search}%"))
    with verified_base_tareas_connection() as connection:
        cursor = connection.cursor()
        try:
            execute_or_raise_database(
                cursor,
                "SELECT id, empresa_id, codigo, nombre, legacy_code, activo, source, "
                "created_at, updated_at FROM organizacion_local "
                f"WHERE {where} ORDER BY codigo, id",
                tuple(params),
            )
            return tuple(_record(row) for row in cursor.fetchall())
        finally:
            cursor.close()


def get_local(context: CompanyContext, local_id: int) -> LocalRecord:
    require_company_context(context)
    if (
        not isinstance(local_id, int)
        or isinstance(local_id, bool)
        or local_id <= 0
    ):
        raise MasterCatalogValidationError("El ID del Local no es válido.")
    with verified_base_tareas_connection() as connection:
        cursor = connection.cursor()
        try:
            execute_or_raise_database(
                cursor,
                "SELECT id, empresa_id, codigo, nombre, legacy_code, activo, source, "
                "created_at, updated_at FROM organizacion_local "
                "WHERE id=%s AND empresa_id=%s",
                (local_id, context.empresa_id),
            )
            row = cursor.fetchone()
        finally:
            cursor.close()
    if row is None:
        raise MasterCatalogNotFound("El Local no existe en la Empresa activa.")
    return _record(row)


def create_local(
    context: CompanyContext,
    data: LocalInput,
    *,
    metadata: MutationMetadata,
) -> MutationResult:
    require_company_context(context)
    require_metadata(metadata)
    codigo, nombre, legacy_code = _normalize_input(data)
    payload = {
        "codigo": codigo,
        "nombre": nombre,
        "legacy_code": legacy_code,
        "source": "LOCAL",
        "motivo": metadata.motivo.strip(),
    }
    now = timezone.now()

    def mutate(cursor):
        execute_or_raise_conflict(
            cursor,
            "INSERT INTO organizacion_local "
            "(empresa_id, codigo, nombre, legacy_code, activo, source, "
            "created_at, updated_at) VALUES (%s, %s, %s, %s, 1, 'LOCAL', %s, %s)",
            (context.empresa_id, codigo, nombre, legacy_code, now, now),
        )
        record = _read_local(cursor, context, cursor.lastrowid, lock=True)
        return MasterMutationChange(
            record.id,
            None,
            _audit_snapshot(record),
            ("codigo", "nombre", "legacy_code", "source"),
        )

    return execute_master_mutation(
        context=context,
        metadata=metadata,
        entity_type="LOCAL",
        action="CREATE",
        payload=payload,
        mutate=mutate,
    )


def update_local(
    context: CompanyContext,
    local_id: int,
    data: LocalInput,
    *,
    metadata: MutationMetadata,
) -> MutationResult:
    require_company_context(context)
    require_metadata(metadata)
    if (
        not isinstance(local_id, int)
        or isinstance(local_id, bool)
        or local_id <= 0
    ):
        raise MasterCatalogValidationError("El ID del Local no es válido.")
    codigo, nombre, legacy_code = _normalize_input(data)
    payload = {
        "local_id": local_id,
        "codigo": codigo,
        "nombre": nombre,
        "legacy_code": legacy_code,
        "source": "LOCAL",
        "motivo": metadata.motivo.strip(),
    }
    now = timezone.now()

    def mutate(cursor):
        before = _read_local(cursor, context, local_id, lock=True)
        if before.source == "ERP":
            raise MasterCatalogCapabilityBlocked(
                "Los Locales ERP son inmutables desde este servicio."
            )
        if (
            before.codigo != codigo
            or before.legacy_code != legacy_code
            or before.source != "LOCAL"
        ):
            raise MasterCatalogCapabilityBlocked(
                "El código, legacy_code y origen del Local son inmutables."
            )
        execute_or_raise_database(
            cursor,
            "UPDATE organizacion_local SET nombre=%s, updated_at=%s "
            "WHERE id=%s AND empresa_id=%s",
            (nombre, now, local_id, context.empresa_id),
        )
        after = _read_local(cursor, context, local_id, lock=True)
        return MasterMutationChange(
            local_id,
            _audit_snapshot(before),
            _audit_snapshot(after),
            ("nombre",) if before.nombre != after.nombre else (),
        )

    return execute_master_mutation(
        context=context,
        metadata=metadata,
        entity_type="LOCAL",
        action="UPDATE",
        payload=payload,
        mutate=mutate,
    )


def set_local_active(
    context: CompanyContext,
    local_id: int,
    active: bool,
    *,
    metadata: MutationMetadata,
) -> MutationResult:
    require_company_context(context)
    require_metadata(metadata)
    if not isinstance(local_id, int) or isinstance(local_id, bool) or local_id <= 0:
        raise MasterCatalogValidationError("El ID del Local no es válido.")
    if not isinstance(active, bool):
        raise MasterCatalogValidationError("El estado activo no es válido.")

    def mutate(cursor):
        before = _read_local(cursor, context, local_id, lock=True)
        if before.source != "LOCAL":
            raise MasterCatalogCapabilityBlocked(
                "Los Locales ERP son inmutables desde este servicio."
            )
        execute_or_raise_database(
            cursor,
            "UPDATE organizacion_local SET activo=%s, updated_at=%s "
            "WHERE id=%s AND empresa_id=%s",
            (int(active), timezone.now(), local_id, context.empresa_id),
        )
        after = _read_local(cursor, context, local_id, lock=True)
        return MasterMutationChange(
            local_id,
            _audit_snapshot(before),
            _audit_snapshot(after),
            ("activo",) if before.activo != after.activo else (),
        )

    return execute_master_mutation(
        context=context,
        metadata=metadata,
        entity_type="LOCAL",
        action="RESTORE" if active else "DELETE",
        payload={
            "local_id": local_id,
            "active": active,
            "motivo": metadata.motivo.strip(),
        },
        mutate=mutate,
    )


def delete_local(
    context: CompanyContext,
    local_id: int,
    *,
    metadata: MutationMetadata,
) -> MutationResult:
    require_company_context(context)
    require_metadata(metadata)
    if not isinstance(local_id, int) or isinstance(local_id, bool) or local_id <= 0:
        raise MasterCatalogValidationError("El ID del Local no es válido.")

    def mutate(cursor):
        before = _read_local(cursor, context, local_id, lock=True)
        if before.source != "LOCAL":
            raise MasterCatalogCapabilityBlocked(
                "Los Locales ERP no pueden eliminarse desde este servicio."
            )
        for table in ("tareas_tarea", "tareas_reunionrevision"):
            execute_or_raise_database(
                cursor,
                f"SELECT COUNT(*) FROM {table} WHERE local_id=%s",
                (local_id,),
            )
            if int(cursor.fetchone()[0]):
                raise MasterCatalogConflict(
                    "No es posible eliminar este registro porque está siendo "
                    "utilizado por tareas o reuniones."
                )
        execute_or_raise_database(
            cursor,
            "DELETE FROM organizacion_local WHERE id=%s AND empresa_id=%s",
            (local_id, context.empresa_id),
        )
        if cursor.rowcount != 1:
            raise MasterCatalogDatabaseError(
                "No se eliminó exactamente el Local solicitado."
            )
        return MasterMutationChange(local_id, _audit_snapshot(before), None, ("deleted",))

    return execute_master_mutation(
        context=context,
        metadata=metadata,
        entity_type="LOCAL",
        action="DELETE",
        payload={"local_id": local_id, "motivo": metadata.motivo.strip()},
        mutate=mutate,
    )
