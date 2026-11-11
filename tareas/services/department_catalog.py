"""SQL service for the company-scoped Departamentos catalog."""

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
class DepartmentRecord:
    id: int
    empresa_id: int
    codigo: str
    nombre: str
    activo: bool
    source: str
    created_at: object
    updated_at: object


@dataclass(frozen=True)
class DepartmentInput:
    codigo: str
    nombre: str
    source: str = "LOCAL"


def _record(row) -> DepartmentRecord:
    return DepartmentRecord(
        id=row[0],
        empresa_id=row[1],
        codigo=row[2],
        nombre=row[3],
        activo=bool(row[4]),
        source=row[5],
        created_at=row[6],
        updated_at=row[7],
    )


def _read_department(
    cursor,
    context: CompanyContext,
    department_id: int,
    *,
    lock: bool = False,
) -> DepartmentRecord:
    execute_or_raise_database(
        cursor,
        "SELECT id, empresa_id, codigo, nombre, activo, source, "
        "created_at, updated_at FROM organizacion_departamento "
        "WHERE id=%s AND empresa_id=%s" + (" FOR UPDATE" if lock else ""),
        (department_id, context.empresa_id),
    )
    row = cursor.fetchone()
    if row is None:
        raise MasterCatalogNotFound(
            "El Departamento no existe en la Empresa activa."
        )
    return _record(row)


def _audit_snapshot(record: DepartmentRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "empresa_id": record.empresa_id,
        "codigo": record.codigo,
        "nombre": record.nombre,
        "activo": record.activo,
        "source": record.source,
    }


def _normalize_input(data: DepartmentInput) -> tuple[str, str]:
    if not isinstance(data, DepartmentInput):
        raise MasterCatalogValidationError(
            "Los datos del Departamento no son válidos."
        )
    source = normalize_required_text(data.source, "source", 5).upper()
    if source != "LOCAL":
        raise MasterCatalogCapabilityBlocked(
            "La escritura de Departamentos ERP requiere el contrato de sincronización."
        )
    return (
        normalize_required_text(data.codigo, "codigo", 100),
        normalize_required_text(data.nombre, "nombre", 255),
    )


def list_departments(
    context: CompanyContext,
    *,
    active_only: bool = False,
    search: str = "",
) -> tuple[DepartmentRecord, ...]:
    require_company_context(context)
    search = normalize_optional_text(search, "search", 255)
    where = "empresa_id=%s"
    params: list[object] = [context.empresa_id]
    if active_only:
        where += " AND activo=1"
    if search:
        where += " AND (codigo LIKE %s OR nombre LIKE %s)"
        params.extend((f"%{search}%", f"%{search}%"))
    with verified_base_tareas_connection() as connection:
        cursor = connection.cursor()
        try:
            execute_or_raise_database(
                cursor,
                "SELECT id, empresa_id, codigo, nombre, activo, source, "
                "created_at, updated_at FROM organizacion_departamento "
                f"WHERE {where} ORDER BY codigo, id",
                tuple(params),
            )
            return tuple(_record(row) for row in cursor.fetchall())
        finally:
            cursor.close()


def get_department(context: CompanyContext, department_id: int) -> DepartmentRecord:
    require_company_context(context)
    if (
        not isinstance(department_id, int)
        or isinstance(department_id, bool)
        or department_id <= 0
    ):
        raise MasterCatalogValidationError("El ID del Departamento no es válido.")
    with verified_base_tareas_connection() as connection:
        cursor = connection.cursor()
        try:
            execute_or_raise_database(
                cursor,
                "SELECT id, empresa_id, codigo, nombre, activo, source, "
                "created_at, updated_at FROM organizacion_departamento "
                "WHERE id=%s AND empresa_id=%s",
                (department_id, context.empresa_id),
            )
            row = cursor.fetchone()
        finally:
            cursor.close()
    if row is None:
        raise MasterCatalogNotFound(
            "El Departamento no existe en la Empresa activa."
        )
    return _record(row)


def create_department(
    context: CompanyContext,
    data: DepartmentInput,
    *,
    metadata: MutationMetadata,
) -> MutationResult:
    require_company_context(context)
    require_metadata(metadata)
    codigo, nombre = _normalize_input(data)
    payload = {
        "codigo": codigo,
        "nombre": nombre,
        "source": "LOCAL",
        "motivo": metadata.motivo.strip(),
    }
    now = timezone.now()

    def mutate(cursor):
        execute_or_raise_conflict(
            cursor,
            "INSERT INTO organizacion_departamento "
            "(empresa_id, codigo, nombre, activo, source, created_at, updated_at) "
            "VALUES (%s, %s, %s, 1, 'LOCAL', %s, %s)",
            (context.empresa_id, codigo, nombre, now, now),
        )
        record = _read_department(
            cursor,
            context,
            cursor.lastrowid,
            lock=True,
        )
        return MasterMutationChange(
            record.id,
            None,
            _audit_snapshot(record),
            ("codigo", "nombre", "source"),
        )

    return execute_master_mutation(
        context=context,
        metadata=metadata,
        entity_type="DEPARTAMENTO",
        action="CREATE",
        payload=payload,
        mutate=mutate,
    )


def _update_department_name(
    context: CompanyContext,
    department_id: int,
    nombre: str,
    *,
    metadata: MutationMetadata,
    expected_codigo: str | None = None,
    expected_source: str | None = None,
) -> MutationResult:
    require_company_context(context)
    require_metadata(metadata)
    if (
        not isinstance(department_id, int)
        or isinstance(department_id, bool)
        or department_id <= 0
    ):
        raise MasterCatalogValidationError("El ID del Departamento no es válido.")
    normalized_name = normalize_required_text(nombre, "nombre", 255)
    payload: dict[str, object] = {
        "department_id": department_id,
        "nombre": normalized_name,
        "motivo": metadata.motivo.strip(),
    }
    if expected_codigo is not None:
        payload["codigo"] = expected_codigo
    if expected_source is not None:
        payload["source"] = expected_source

    def mutate(cursor):
        before = _read_department(cursor, context, department_id, lock=True)
        if before.source == "ERP":
            raise MasterCatalogCapabilityBlocked(
                "Los Departamentos ERP son inmutables desde este servicio."
            )
        if before.source != "LOCAL":
            raise MasterCatalogCapabilityBlocked(
                "El origen del Departamento no está habilitado para edición."
            )
        if (
            expected_codigo is not None
            and before.codigo != expected_codigo
        ) or (
            expected_source is not None
            and before.source != expected_source
        ):
            raise MasterCatalogCapabilityBlocked(
                "El código, Empresa y source del Departamento son inmutables."
            )
        execute_or_raise_database(
            cursor,
            "UPDATE organizacion_departamento SET nombre=%s, updated_at=%s "
            "WHERE id=%s AND empresa_id=%s",
            (normalized_name, timezone.now(), department_id, context.empresa_id),
        )
        after = _read_department(cursor, context, department_id, lock=True)
        return MasterMutationChange(
            department_id,
            _audit_snapshot(before),
            _audit_snapshot(after),
            ("nombre",) if before.nombre != after.nombre else (),
        )

    return execute_master_mutation(
        context=context,
        metadata=metadata,
        entity_type="DEPARTAMENTO",
        action="UPDATE",
        payload=payload,
        mutate=mutate,
    )


def update_department_name(
    context: CompanyContext,
    department_id: int,
    nombre: str,
    *,
    metadata: MutationMetadata,
) -> MutationResult:
    return _update_department_name(
        context,
        department_id,
        nombre,
        metadata=metadata,
    )


def update_department(
    context: CompanyContext,
    department_id: int,
    data: DepartmentInput,
    *,
    metadata: MutationMetadata,
) -> MutationResult:
    if not isinstance(data, DepartmentInput):
        raise MasterCatalogValidationError(
            "Los datos del Departamento no son válidos."
        )
    codigo, nombre = _normalize_input(data)
    return _update_department_name(
        context,
        department_id,
        nombre,
        metadata=metadata,
        expected_codigo=codigo,
        expected_source="LOCAL",
    )


def set_department_active(
    context: CompanyContext,
    department_id: int,
    active: bool,
    *,
    metadata: MutationMetadata,
) -> MutationResult:
    require_company_context(context)
    require_metadata(metadata)
    if (
        not isinstance(department_id, int)
        or isinstance(department_id, bool)
        or department_id <= 0
    ):
        raise MasterCatalogValidationError("El ID del Departamento no es válido.")
    if not isinstance(active, bool):
        raise MasterCatalogValidationError("El estado activo no es válido.")

    def mutate(cursor):
        before = _read_department(cursor, context, department_id, lock=True)
        if before.source != "LOCAL":
            raise MasterCatalogCapabilityBlocked(
                "Los Departamentos ERP son inmutables desde este servicio."
            )
        execute_or_raise_database(
            cursor,
            "UPDATE organizacion_departamento SET activo=%s, updated_at=%s "
            "WHERE id=%s AND empresa_id=%s",
            (int(active), timezone.now(), department_id, context.empresa_id),
        )
        after = _read_department(cursor, context, department_id, lock=True)
        return MasterMutationChange(
            department_id,
            _audit_snapshot(before),
            _audit_snapshot(after),
            ("activo",) if before.activo != after.activo else (),
        )

    return execute_master_mutation(
        context=context,
        metadata=metadata,
        entity_type="DEPARTAMENTO",
        action="RESTORE" if active else "DELETE",
        payload={
            "department_id": department_id,
            "active": active,
            "motivo": metadata.motivo.strip(),
        },
        mutate=mutate,
    )


def delete_department(
    context: CompanyContext,
    department_id: int,
    *,
    metadata: MutationMetadata,
) -> MutationResult:
    require_company_context(context)
    require_metadata(metadata)
    if (
        not isinstance(department_id, int)
        or isinstance(department_id, bool)
        or department_id <= 0
    ):
        raise MasterCatalogValidationError("El ID del Departamento no es válido.")

    def mutate(cursor):
        before = _read_department(cursor, context, department_id, lock=True)
        if before.source != "LOCAL":
            raise MasterCatalogCapabilityBlocked(
                "Los Departamentos ERP no pueden eliminarse desde este servicio."
            )
        for table in ("tareas_tarea", "tareas_reunionrevision"):
            execute_or_raise_database(
                cursor,
                f"SELECT COUNT(*) FROM {table} WHERE departamento_id=%s",
                (department_id,),
            )
            if int(cursor.fetchone()[0]):
                raise MasterCatalogConflict(
                    "No es posible eliminar este registro porque está siendo "
                    "utilizado por tareas o reuniones."
                )
        execute_or_raise_database(
            cursor,
            "DELETE FROM organizacion_departamento WHERE id=%s AND empresa_id=%s",
            (department_id, context.empresa_id),
        )
        if cursor.rowcount != 1:
            raise MasterCatalogDatabaseError(
                "No se eliminó exactamente el Departamento solicitado."
            )
        return MasterMutationChange(
            department_id,
            _audit_snapshot(before),
            None,
            ("deleted",),
        )

    return execute_master_mutation(
        context=context,
        metadata=metadata,
        entity_type="DEPARTAMENTO",
        action="DELETE",
        payload={"department_id": department_id, "motivo": metadata.motivo.strip()},
        mutate=mutate,
    )
