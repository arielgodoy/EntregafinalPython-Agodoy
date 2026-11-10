"""Transactional orchestration and audit reconciliation for master catalogs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Mapping

from .audit import (
    MasterCatalogAuditPermanentError,
    MasterCatalogAuditRetryableError,
    log_master_catalog_operation,
)
from .master_catalog_common import (
    CompanyContext,
    MasterCatalogCommitUnknown,
    MasterCatalogError,
    MasterCatalogValidationError,
    MutationMetadata,
    MutationResult,
    mutation_transaction,
    require_company_context,
    require_metadata,
    verified_base_tareas_connection,
)
from .master_operation_store import (
    MasterOperationOutcomeUnknown,
    MasterOperationNotFound,
    MasterOperationPreviouslyFailed,
    MasterOperationRecord,
    complete_operation,
    get_operation,
    hash_payload,
    list_pending_reconciliation,
    mark_audit_status,
    normalize_operation_id,
    reserve_operation,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MasterMutationChange:
    result_id: int
    before: Mapping[str, object] | None
    after: Mapping[str, object] | None
    changed_fields: tuple[str, ...]


@dataclass(frozen=True)
class ReconciliationReport:
    scanned: int
    attempted: int
    confirmed: int
    retryable_errors: int
    permanent_errors: int
    unknown_operations: int
    pending_operations: int = 0
    manual_review: tuple["OperationReview", ...] = ()


@dataclass(frozen=True)
class OperationReview:
    operation_id: str
    entity_type: str
    empresa_id: int
    status: str
    audit_status: str
    evidence: str
    reason: str


@dataclass(frozen=True)
class _ProjectionResult:
    status: str
    error_code: str = ""


def _validate_operation_context(
    context: CompanyContext,
    metadata: MutationMetadata,
) -> None:
    require_company_context(context)
    require_metadata(metadata)
    if context.actor_id is not None and context.actor_id != metadata.actor_id:
        raise MasterCatalogValidationError(
            "El actor de la operación no coincide con el contexto validado."
        )


def _operation_result_payload(
    change: MasterMutationChange,
    *,
    motivo: str,
) -> dict[str, object]:
    return {
        "id": change.result_id,
        "before": dict(change.before) if change.before is not None else None,
        "after": dict(change.after) if change.after is not None else None,
        "changed_fields": list(change.changed_fields),
        "motivo": motivo,
    }


def _persist_audit_status(
    connection,
    record: MasterOperationRecord,
    *,
    status: str,
    event_id: int | None = None,
    error_code: str = "",
) -> bool:
    try:
        with mutation_transaction(connection):
            cursor = connection.cursor()
            try:
                mark_audit_status(
                    cursor,
                    record.operation_id,
                    audit_status=status,
                    audit_event_id=event_id,
                    audit_error_code=error_code,
                )
            finally:
                cursor.close()
    except MasterCatalogError as exc:
        logger.error(
            "Could not persist master-operation audit status "
            "operation_id=%s status=%s error_type=%s",
            record.operation_id.hex,
            status,
            type(exc).__name__,
        )
        return False
    return True


def _project_audit(
    connection,
    record: MasterOperationRecord,
) -> _ProjectionResult:
    if record.status != "COMMITTED" or record.result_id is None:
        return _ProjectionResult("PENDING", "RETRY_OPERATION_RESULT_UNAVAILABLE")
    if record.audit_status == "CONFIRMED":
        return _ProjectionResult("CONFIRMED")
    if (
        record.audit_status == "ERROR"
        and not record.audit_error_code.startswith("RETRY_")
    ):
        return _ProjectionResult("ERROR", record.audit_error_code)

    try:
        event = log_master_catalog_operation(
            operation_id=record.operation_id,
            entity_type=record.entity_type,
            action=record.action,
            empresa_id=record.empresa_id,
            actor_id=record.actor_id,
            result_id=record.result_id,
            payload_hash=record.payload_hash,
            result_payload=record.result_payload,
        )
    except MasterCatalogAuditRetryableError:
        error_code = "RETRY_AUDIT_STORAGE"
        _persist_audit_status(
            connection,
            record,
            status="ERROR",
            error_code=error_code,
        )
        return _ProjectionResult("ERROR", error_code)
    except MasterCatalogAuditPermanentError as exc:
        _persist_audit_status(
            connection,
            record,
            status="ERROR",
            error_code=exc.code,
        )
        return _ProjectionResult("ERROR", exc.code)

    event_id = getattr(event, "pk", None)
    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
        error_code = "RETRY_AUDIT_EVENT_MISSING"
        _persist_audit_status(
            connection,
            record,
            status="ERROR",
            error_code=error_code,
        )
        return _ProjectionResult("ERROR", error_code)

    if not _persist_audit_status(
        connection,
        record,
        status="CONFIRMED",
        event_id=event_id,
    ):
        return _ProjectionResult("PENDING", "RETRY_AUDIT_STATUS_PERSIST")
    return _ProjectionResult("CONFIRMED")


def _to_mutation_result(
    record: MasterOperationRecord,
    *,
    replayed: bool,
    projection: _ProjectionResult,
) -> MutationResult:
    if record.result_id is None:
        raise MasterOperationOutcomeUnknown(
            "El resultado de la operación no está disponible."
        )
    return MutationResult(
        id=record.result_id,
        operation_id=str(record.operation_id),
        audit_status=projection.status,
        replayed=replayed,
        audit_error_code=projection.error_code,
    )


def _review_from_record(record: MasterOperationRecord, *, reason: str) -> OperationReview:
    evidence = (
        "registro durable presente; no existe confirmación concluyente del "
        "resultado de la mutación"
        if record.status in {"PENDING", "UNKNOWN"}
        else "registro durable no confirmado"
    )
    return OperationReview(
        operation_id=str(record.operation_id),
        entity_type=record.entity_type,
        empresa_id=record.empresa_id,
        status=record.status,
        audit_status=record.audit_status,
        evidence=evidence,
        reason=reason,
    )


def _recover_uncertain_operation(
    operation_id,
    *,
    entity_type: str,
    action: str,
    empresa_id: int,
    actor_id: int,
    payload_hash: str,
) -> MasterOperationRecord | None:
    """Recover only durable confirmation; never replay an uncertain mutation."""
    with verified_base_tareas_connection() as connection:
        cursor = connection.cursor()
        try:
            try:
                record = get_operation(cursor, operation_id)
            except MasterOperationNotFound:
                return None
        finally:
            cursor.close()

        if (
            record.entity_type != entity_type
            or record.action != action
            or record.empresa_id != empresa_id
            or record.actor_id != actor_id
            or record.payload_hash != payload_hash
        ):
            logger.error(
                "Uncertain master-operation evidence does not match request "
                "operation_id=%s",
                operation_id.hex,
            )
            return None

        if record.status != "PENDING":
            return record

        try:
            with mutation_transaction(connection):
                cursor = connection.cursor()
                try:
                    return mark_unknown_operation(cursor, operation_id)
                finally:
                    cursor.close()
        except MasterCatalogError:
            logger.error(
                "Could not persist uncertain master-operation state "
                "operation_id=%s",
                operation_id.hex,
            )
            return record


def execute_master_mutation(
    *,
    context: CompanyContext,
    metadata: MutationMetadata,
    entity_type: str,
    action: str,
    payload: Mapping[str, object],
    mutate: Callable[[object], MasterMutationChange],
) -> MutationResult:
    """Reserve, mutate, and save the replay result in one BASE_TAREAS transaction."""
    _validate_operation_context(context, metadata)
    operation_id = normalize_operation_id(metadata.operation_id)
    payload_hash = hash_payload(payload)
    record = None
    replayed = False

    try:
        with verified_base_tareas_connection() as connection:
            with mutation_transaction(connection):
                cursor = connection.cursor()
                try:
                    reservation = reserve_operation(
                        cursor,
                        operation_id=operation_id,
                        entity_type=entity_type,
                        action=action,
                        empresa_id=context.empresa_id,
                        actor_id=metadata.actor_id,
                        payload=payload,
                    )
                    record = reservation.record
                    replayed = reservation.replayed
                    if replayed:
                        if record.status == "FAILED":
                            raise MasterOperationPreviouslyFailed(
                                "La operación ya fue registrada como fallida."
                            )
                        if record.status != "COMMITTED":
                            raise MasterOperationOutcomeUnknown(
                                "La operación previa no tiene un resultado confirmado."
                            )
                    else:
                        change = mutate(cursor)
                        if not isinstance(change, MasterMutationChange):
                            raise MasterCatalogValidationError(
                                "La mutación no produjo un resultado válido."
                            )
                        record = complete_operation(
                            cursor,
                            operation_id,
                            result_id=change.result_id,
                            result_payload=_operation_result_payload(
                                change,
                                motivo=metadata.motivo.strip(),
                            ),
                        )
                finally:
                    cursor.close()

            projection = _project_audit(connection, record)
    except MasterCatalogCommitUnknown as exc:
        recovered = _recover_uncertain_operation(
            operation_id,
            entity_type=entity_type,
            action=action,
            empresa_id=context.empresa_id,
            actor_id=metadata.actor_id,
            payload_hash=payload_hash,
        )
        if recovered is not None and recovered.status == "COMMITTED":
            with verified_base_tareas_connection() as recovery_connection:
                projection = _project_audit(recovery_connection, recovered)
            return _to_mutation_result(
                recovered,
                replayed=True,
                projection=projection,
            )
        raise MasterOperationOutcomeUnknown(
            "La operación quedó incierta; revise el registro durable "
            "sin repetir la mutación."
        ) from exc

    return _to_mutation_result(
        record,
        replayed=replayed,
        projection=projection,
    )


def reconcile_master_operations(*, limit: int = 100) -> ReconciliationReport:
    """Perform one bounded reconciliation pass; never loops or mutates a catalog."""
    with verified_base_tareas_connection() as connection:
        with mutation_transaction(connection):
            cursor = connection.cursor()
            try:
                records = list_pending_reconciliation(cursor, limit=limit)
            finally:
                cursor.close()

        attempted = confirmed = retryable = permanent = unknown = pending = 0
        manual_review = []
        for record in records:
            if record.status == "UNKNOWN":
                unknown += 1
                manual_review.append(
                    _review_from_record(
                        record,
                        reason="No existe evidencia durable concluyente para resolver UNKNOWN.",
                    )
                )
                continue
            if record.status == "PENDING":
                pending += 1
                manual_review.append(
                    _review_from_record(
                        record,
                        reason="PENDING requiere investigación; no se infiere el resultado por antigüedad.",
                    )
                )
                continue
            if record.status != "COMMITTED":
                continue
            if (
                record.audit_status == "ERROR"
                and not record.audit_error_code.startswith("RETRY_")
            ):
                permanent += 1
                continue

            attempted += 1
            result = _project_audit(connection, record)
            if result.status == "CONFIRMED":
                confirmed += 1
            elif result.error_code.startswith("RETRY_"):
                retryable += 1
            elif result.status == "ERROR":
                permanent += 1
            else:
                retryable += 1

    return ReconciliationReport(
        scanned=len(records),
        attempted=attempted,
        confirmed=confirmed,
        retryable_errors=retryable,
        permanent_errors=permanent,
        unknown_operations=unknown,
        pending_operations=pending,
        manual_review=tuple(manual_review),
    )
