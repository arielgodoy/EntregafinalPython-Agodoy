"""Technical idempotency for future atomic meeting-and-task creation."""

from __future__ import annotations

import hmac
import json
import re
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core import signing
from django.utils import timezone
from django.utils.crypto import salted_hmac

from access_control.models import Empresa
from access_control.services.permissions import (
    get_valid_users_for_empresa,
    user_has_permission_for_empresa,
)

from ..models import ReunionCreationRequest
from .authorization import MEETINGS_VISTA_NAME, has_meeting_creation_permissions
from .reunion_creation_idempotency_storage import (
    CreationRequestRecord,
    ReunionCreationRequestStorageError,
    ReunionCreationRequestUnitOfWork,
    resolve_reunion_creation_request_storage,
)


REVIEW_TOKEN_TTL_SECONDS = 900
NON_COMPLETED_REQUEST_RETENTION_DAYS = 30
PAYLOAD_FINGERPRINT_SALT = "tareas.reunion_creation.payload.v1"
REVIEW_FINGERPRINT_SALT = "tareas.reunion_creation.review.v1"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class ReunionCreationIdempotencyError(RuntimeError):
    """Base error for a technical meeting-creation request."""


class ReunionCreationRequestNotFound(ReunionCreationIdempotencyError):
    """The request is absent or outside the actor/company scope."""


class ReunionCreationRequestConflict(ReunionCreationIdempotencyError):
    """A request key was reused with a different immutable payload."""


class ReunionCreationRequestExpired(ReunionCreationIdempotencyError):
    """The review request expired before it could be completed."""


class ReunionCreationRequestStateError(ReunionCreationIdempotencyError):
    """The request cannot perform the requested state transition."""


class ReunionCreationRequestUnauthorized(ReunionCreationIdempotencyError):
    """The actor cannot access this company's technical request."""


class ReunionCreationRequestOutcomeUnknown(ReunionCreationIdempotencyError):
    """The transaction acknowledgement was lost; resolve using the same request_id."""

    def __init__(self, request_id: UUID):
        self.request_id = request_id
        super().__init__(
            "El resultado transaccional es incierto; consulte la misma solicitud."
        )


class ReunionCreationRequestRetryable(ReunionCreationIdempotencyError):
    """A transient lock or concurrency conflict prevented the operation."""


class ReunionCreationRequestStorageFailure(ReunionCreationIdempotencyError):
    """A storage failure with an explicit commit state for reconciliation."""

    def __init__(
        self,
        message: str,
        *,
        request_id: UUID | None = None,
        commit_confirmed: bool = False,
    ):
        self.request_id = request_id
        self.commit_confirmed = commit_confirmed
        super().__init__(message)


@dataclass(frozen=True)
class ReunionCreationResult:
    request_id: UUID
    task_id: int
    meeting_id: int
    replayed: bool = False


class CreationRequestUnitOfWork(ReunionCreationRequestUnitOfWork, Protocol):
    backend_type: str
    alias: str | None
    connection: object | None


CreationCallback = Callable[
    [CreationRequestUnitOfWork],
    tuple[int, int],
]

_CONFIRMATION_TOKEN_SALT = "tareas.reunion_creation.confirmation.v1"


@contextmanager
def _creation_atomic(storage, request_id: UUID):
    try:
        with storage.atomic() as unit:
            yield unit
    except ReunionCreationRequestStorageError as exc:
        if exc.outcome_unknown or exc.category == "UNKNOWN_COMMIT_RESULT":
            raise ReunionCreationRequestOutcomeUnknown(request_id) from exc
        if exc.commit_confirmed:
            raise ReunionCreationRequestStorageFailure(
                "La operación se confirmó; recupere el resultado con el mismo identificador.",
                request_id=request_id,
                commit_confirmed=True,
            ) from exc
        if exc.category == "CONFLICT":
            raise ReunionCreationRequestConflict(
                "La operación entró en conflicto con otra solicitud."
            ) from exc
        if exc.category == "INVALID_STATE":
            raise ReunionCreationRequestStateError(
                "La operación incumple el estado permitido."
            ) from exc
        if exc.category == "RETRYABLE":
            raise ReunionCreationRequestRetryable(
                "La operación está temporalmente bloqueada; consulte la solicitud."
            ) from exc
        raise ReunionCreationRequestStorageFailure(
            "No se pudo completar la operación de idempotencia.",
            request_id=request_id,
            commit_confirmed=False,
        ) from exc


def new_creation_request_id() -> UUID:
    return uuid4()


def fingerprint_payload(
    payload: Mapping[str, object],
    *,
    purpose: str = PAYLOAD_FINGERPRINT_SALT,
) -> str:
    """Create a keyed, deterministic fingerprint without persisting payload data."""
    canonical = _canonical_json(payload)
    return salted_hmac(
        purpose,
        canonical,
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


def fingerprint_matches(
    payload: Mapping[str, object],
    expected: str,
    *,
    purpose: str,
) -> bool:
    canonical = _canonical_json(payload)
    for secret in (
        settings.SECRET_KEY,
        *getattr(settings, "SECRET_KEY_FALLBACKS", ()),
    ):
        if hmac.compare_digest(
            salted_hmac(
                purpose,
                canonical,
                secret=secret,
                algorithm="sha256",
            ).hexdigest(),
            expected,
        ):
            return True
    return False


def _canonical_json(payload: Mapping[str, object]) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("El payload debe ser un mapping.")
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("El payload no tiene una forma canónica válida.") from exc


def _normalize_request_id(value) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("request_id debe ser un UUID válido.") from exc


def _positive_id(value, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} debe ser un entero positivo.")
    return value


def _fingerprint(value, field_name: str) -> str:
    if not isinstance(value, str) or not _HEX_64.fullmatch(value):
        raise ValueError(f"{field_name} debe ser una huella hexadecimal de 64 caracteres.")
    return value


def _aware_datetime(value, field_name: str) -> datetime:
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise ValueError(f"{field_name} debe ser un datetime con zona horaria.")
    return value


def _validate_expiration(expires_at: datetime, *, now: datetime | None = None) -> None:
    current = now or timezone.now()
    if expires_at <= current:
        raise ReunionCreationRequestExpired(
            "La solicitud de revisión ya expiró."
        )
    if expires_at > current + timedelta(seconds=REVIEW_TOKEN_TTL_SECONDS):
        raise ValueError("La expiración excede el TTL máximo de revisión.")


def _authorize_actor_company(
    *,
    empresa_id: int,
    actor_id: int,
    require_meeting_create: bool = False,
    required_permission: tuple[str, str] | None = None,
) -> None:
    company = (
        Empresa.objects.using("default")
        .filter(pk=empresa_id)
        .first()
    )
    actor = (
        get_user_model()
        ._default_manager.using("default")
        .filter(pk=actor_id, is_active=True)
        .first()
    )
    if (
        company is None
        or actor is None
        or not get_valid_users_for_empresa(
            company,
            active_only=True,
        )
        .filter(pk=actor_id)
        .exists()
    ):
        raise ReunionCreationRequestUnauthorized(
            "El actor no está activo o no pertenece a la empresa."
        )
    if require_meeting_create and not has_meeting_creation_permissions(
        actor=actor,
        empresa=company,
    ):
        raise ReunionCreationRequestUnauthorized(
            "El actor no tiene permisos para crear reuniones y su tarea planificada."
        )
    if required_permission is not None and not user_has_permission_for_empresa(
        user=actor,
        empresa=company,
        vista_nombre=required_permission[0],
        accion=required_permission[1],
    ):
        raise ReunionCreationRequestUnauthorized(
            "El actor no tiene el permiso requerido para esta solicitud."
        )


def new_request_expiration(*, now: datetime | None = None) -> datetime:
    current = now or timezone.now()
    return current + timedelta(seconds=REVIEW_TOKEN_TTL_SECONDS)


def _confirmation_payload(
    record: CreationRequestRecord,
) -> dict[str, object]:
    return {
        "version": 1,
        "confirmed": True,
        "request_id": record.request_id.hex,
        "empresa_id": record.empresa_id,
        "actor_id": record.actor_id,
        "payload_hash": record.payload_hash,
        "review_fingerprint": record.review_fingerprint,
        "expires_at": record.expires_at.isoformat(),
    }


def issue_creation_confirmation(
    *,
    request_id,
    empresa_id: int,
    actor_id: int,
    payload_hash: str,
    review_fingerprint: str,
    confirmed: bool,
) -> str:
    request_id = _normalize_request_id(request_id)
    empresa_id = _positive_id(empresa_id, "empresa_id")
    actor_id = _positive_id(actor_id, "actor_id")
    payload_hash = _fingerprint(payload_hash, "payload_hash")
    review_fingerprint = _fingerprint(
        review_fingerprint,
        "review_fingerprint",
    )
    if confirmed is not True:
        raise ReunionCreationRequestStateError(
            "La solicitud requiere confirmación explícita."
        )
    _authorize_actor_company(
        empresa_id=empresa_id,
        actor_id=actor_id,
        require_meeting_create=True,
    )
    record = _load_creation_request_record(
        request_id=request_id,
        empresa_id=empresa_id,
        actor_id=actor_id,
    )
    _assert_same_request(
        record,
        request_id=request_id,
        empresa_id=empresa_id,
        actor_id=actor_id,
        payload_hash=payload_hash,
    )
    if record.status != ReunionCreationRequest.Estado.REVISION_PENDIENTE:
        raise ReunionCreationRequestStateError(
            "Solo se puede confirmar una revisión pendiente."
        )
    if record.review_fingerprint != review_fingerprint:
        raise ReunionCreationRequestConflict(
            "La revisión de similitud cambió; vuelva a previsualizar."
        )
    if record.expires_at <= timezone.now():
        raise ReunionCreationRequestExpired(
            "La solicitud expiró antes de ser confirmada."
        )
    return signing.dumps(
        _confirmation_payload(record),
        salt=_CONFIRMATION_TOKEN_SALT,
        compress=True,
    )


def _validate_confirmation_token(
    token: str,
    record: CreationRequestRecord,
) -> None:
    if not isinstance(token, str) or not token:
        raise ReunionCreationRequestStateError(
            "Falta la confirmación firmada de la solicitud."
        )
    try:
        payload = signing.loads(
            token,
            salt=_CONFIRMATION_TOKEN_SALT,
            max_age=REVIEW_TOKEN_TTL_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise ReunionCreationRequestExpired(
            "La confirmación de la solicitud expiró."
        ) from exc
    except signing.BadSignature as exc:
        raise ReunionCreationRequestStateError(
            "La confirmación firmada no es válida."
        ) from exc
    if payload != _confirmation_payload(record):
        raise ReunionCreationRequestConflict(
            "La confirmación no corresponde a la revisión vigente."
        )
    if record.expires_at <= timezone.now():
        raise ReunionCreationRequestExpired(
            "La solicitud expiró antes de iniciar la creación."
        )


def create_review_request(
    *,
    request_id,
    empresa_id: int,
    actor_id: int,
    payload_hash: str,
    review_fingerprint: str,
    expires_at: datetime,
) -> CreationRequestRecord:
    request_id = _normalize_request_id(request_id)
    empresa_id = _positive_id(empresa_id, "empresa_id")
    actor_id = _positive_id(actor_id, "actor_id")
    payload_hash = _fingerprint(payload_hash, "payload_hash")
    review_fingerprint = _fingerprint(
        review_fingerprint,
        "review_fingerprint",
    )
    expires_at = _aware_datetime(expires_at, "expires_at")
    _validate_expiration(expires_at)
    _authorize_actor_company(
        empresa_id=empresa_id,
        actor_id=actor_id,
        require_meeting_create=True,
    )

    storage = resolve_reunion_creation_request_storage()
    now = timezone.now()
    proposed = CreationRequestRecord(
        request_id=request_id,
        empresa_id=empresa_id,
        actor_id=actor_id,
        payload_hash=payload_hash,
        review_fingerprint=review_fingerprint,
        status=ReunionCreationRequest.Estado.REVISION_PENDIENTE,
        expires_at=expires_at,
        task_id=None,
        meeting_id=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
        audit_status=ReunionCreationRequest.EstadoAuditoria.NO_ENCOLADA,
        audit_event_id=None,
        audit_error_code="",
    )
    with _creation_atomic(storage, request_id) as unit:
        existing = unit.insert_or_get_request(proposed)
        _assert_same_request(
            existing,
            request_id=request_id,
            empresa_id=empresa_id,
            actor_id=actor_id,
            payload_hash=payload_hash,
        )
        if existing.status == ReunionCreationRequest.Estado.EN_PROGRESO:
            raise ReunionCreationRequestStateError(
                "La solicitud quedó en un estado transaccional inesperado."
            )
        if existing.status == ReunionCreationRequest.Estado.REVISION_PENDIENTE:
            if existing.review_fingerprint != review_fingerprint:
                raise ReunionCreationRequestConflict(
                    "La huella de revisión cambió; actualice la previsualización."
                )
            if existing.expires_at <= timezone.now():
                if not unit.transition_request(
                    request_id,
                    expected_status=existing.status,
                    values={"status": ReunionCreationRequest.Estado.EXPIRADA},
                ):
                    raise ReunionCreationRequestStateError(
                        "La solicitud cambió durante su expiración."
                    )
                return _record_with(
                    existing,
                    status=ReunionCreationRequest.Estado.EXPIRADA,
                    updated_at=timezone.now(),
                )
        return existing


def refresh_review_request(
    *,
    request_id,
    empresa_id: int,
    actor_id: int,
    payload_hash: str,
    review_fingerprint: str,
    expires_at: datetime,
) -> CreationRequestRecord:
    request_id = _normalize_request_id(request_id)
    empresa_id = _positive_id(empresa_id, "empresa_id")
    actor_id = _positive_id(actor_id, "actor_id")
    payload_hash = _fingerprint(payload_hash, "payload_hash")
    review_fingerprint = _fingerprint(
        review_fingerprint,
        "review_fingerprint",
    )
    expires_at = _aware_datetime(expires_at, "expires_at")
    _validate_expiration(expires_at)
    _authorize_actor_company(
        empresa_id=empresa_id,
        actor_id=actor_id,
        require_meeting_create=True,
    )

    storage = resolve_reunion_creation_request_storage()
    with _creation_atomic(storage, request_id) as unit:
        existing = unit.get_request(request_id, lock=True)
        if existing is None:
            raise ReunionCreationRequestNotFound(
                "La solicitud no existe en la empresa activa."
            )
        _assert_same_request(
            existing,
            request_id=request_id,
            empresa_id=empresa_id,
            actor_id=actor_id,
            payload_hash=payload_hash,
        )
        if existing.status != ReunionCreationRequest.Estado.REVISION_PENDIENTE:
            raise ReunionCreationRequestStateError(
                "Solo se pueden actualizar solicitudes pendientes."
            )
        if existing.expires_at <= timezone.now():
            raise ReunionCreationRequestExpired(
                "La solicitud expiró; inicie una nueva."
            )
        if (
            existing.review_fingerprint == review_fingerprint
            and existing.expires_at == expires_at
        ):
            return existing
        if not unit.transition_request(
            request_id,
            expected_status=existing.status,
            values={
                "review_fingerprint": review_fingerprint,
                "expires_at": expires_at,
            },
        ):
            raise ReunionCreationRequestStateError(
                "La solicitud cambió durante la actualización."
            )
        refreshed = unit.get_request(request_id, lock=True)
        if refreshed is None:
            raise ReunionCreationRequestStorageError(
                "No se pudo recuperar la previsualización actualizada."
            )
        return refreshed


def _load_creation_request_record(
    *,
    request_id: UUID,
    empresa_id: int,
    actor_id: int,
) -> CreationRequestRecord:
    storage = resolve_reunion_creation_request_storage()
    with _creation_atomic(storage, request_id) as unit:
        record = unit.get_request(request_id)
    if record is None or (
        record.empresa_id != empresa_id or record.actor_id != actor_id
    ):
        raise ReunionCreationRequestNotFound(
            "La solicitud no existe en la empresa activa."
        )
    return record


def get_creation_request(
    *,
    request_id,
    empresa_id: int,
    actor_id: int,
) -> CreationRequestRecord:
    request_id = _normalize_request_id(request_id)
    empresa_id = _positive_id(empresa_id, "empresa_id")
    actor_id = _positive_id(actor_id, "actor_id")
    _authorize_actor_company(
        empresa_id=empresa_id,
        actor_id=actor_id,
        required_permission=(MEETINGS_VISTA_NAME, "ingresar"),
    )
    return _load_creation_request_record(
        request_id=request_id,
        empresa_id=empresa_id,
        actor_id=actor_id,
    )


def cancel_creation_request(
    *,
    request_id,
    empresa_id: int,
    actor_id: int,
) -> CreationRequestRecord:
    request_id = _normalize_request_id(request_id)
    empresa_id = _positive_id(empresa_id, "empresa_id")
    actor_id = _positive_id(actor_id, "actor_id")
    _authorize_actor_company(
        empresa_id=empresa_id,
        actor_id=actor_id,
        required_permission=("Tareas", "crear"),
    )
    storage = resolve_reunion_creation_request_storage()
    with _creation_atomic(storage, request_id) as unit:
        record = unit.get_request(request_id, lock=True)
        if record is None or (
            record.empresa_id != empresa_id or record.actor_id != actor_id
        ):
            raise ReunionCreationRequestNotFound(
                "La solicitud no existe en la empresa activa."
            )
        if record.status == ReunionCreationRequest.Estado.CANCELADA:
            return record
        if record.status != ReunionCreationRequest.Estado.REVISION_PENDIENTE:
            raise ReunionCreationRequestStateError(
                "Solo se puede cancelar una revisión pendiente."
            )
        expired = record.expires_at <= timezone.now()
        target_status = (
            ReunionCreationRequest.Estado.EXPIRADA
            if expired
            else ReunionCreationRequest.Estado.CANCELADA
        )
        if not unit.transition_request(
            request_id,
            expected_status=record.status,
            values={"status": target_status},
        ):
            raise ReunionCreationRequestStateError(
                "La solicitud cambió durante la cancelación."
            )
        return _record_with(
            record,
            status=target_status,
            updated_at=timezone.now(),
        )


def expire_creation_request(
    *,
    request_id,
    empresa_id: int,
    actor_id: int,
    now: datetime | None = None,
) -> CreationRequestRecord:
    request_id = _normalize_request_id(request_id)
    empresa_id = _positive_id(empresa_id, "empresa_id")
    actor_id = _positive_id(actor_id, "actor_id")
    _authorize_actor_company(
        empresa_id=empresa_id,
        actor_id=actor_id,
        required_permission=("Tareas", "crear"),
    )
    now = _aware_datetime(now or timezone.now(), "now")
    storage = resolve_reunion_creation_request_storage()
    with _creation_atomic(storage, request_id) as unit:
        record = unit.get_request(request_id, lock=True)
        if record is None or (
            record.empresa_id != empresa_id or record.actor_id != actor_id
        ):
            raise ReunionCreationRequestNotFound(
                "La solicitud no existe en la empresa activa."
            )
        if record.status == ReunionCreationRequest.Estado.EXPIRADA:
            return record
        if record.status != ReunionCreationRequest.Estado.REVISION_PENDIENTE:
            raise ReunionCreationRequestStateError(
                "Solo se puede expirar una revisión pendiente."
            )
        if now < record.expires_at:
            raise ReunionCreationRequestStateError(
                "La solicitud todavía no expiró."
            )
        if not unit.transition_request(
            request_id,
            expected_status=record.status,
            values={"status": ReunionCreationRequest.Estado.EXPIRADA},
        ):
            raise ReunionCreationRequestStateError(
                "La solicitud cambió durante la expiración."
            )
        return _record_with(
            record,
            status=ReunionCreationRequest.Estado.EXPIRADA,
            updated_at=now,
        )


def get_completed_result(
    *,
    request_id,
    empresa_id: int,
    actor_id: int,
) -> ReunionCreationResult:
    record = get_creation_request(
        request_id=request_id,
        empresa_id=empresa_id,
        actor_id=actor_id,
    )
    if record.status != ReunionCreationRequest.Estado.COMPLETADA:
        raise ReunionCreationRequestStateError(
            "La solicitud todavía no tiene un resultado completado."
        )
    if record.task_id is None or record.meeting_id is None:
        raise ReunionCreationRequestStorageError(
            "La solicitud completada no tiene un resultado íntegro."
        )
    return ReunionCreationResult(
        request_id=record.request_id,
        task_id=record.task_id,
        meeting_id=record.meeting_id,
        replayed=True,
    )


def record_audit_delivery(
    *,
    request_id,
    empresa_id: int,
    actor_id: int,
    audit_status: str,
    audit_event_id: int | None = None,
    audit_error_code: str = "",
) -> CreationRequestRecord:
    request_id = _normalize_request_id(request_id)
    empresa_id = _positive_id(empresa_id, "empresa_id")
    actor_id = _positive_id(actor_id, "actor_id")
    if audit_status not in {
        ReunionCreationRequest.EstadoAuditoria.PENDIENTE,
        ReunionCreationRequest.EstadoAuditoria.CONFIRMADA,
        ReunionCreationRequest.EstadoAuditoria.ERROR,
    }:
        raise ValueError("audit_status no es válido.")
    if audit_status == ReunionCreationRequest.EstadoAuditoria.CONFIRMADA:
        audit_event_id = _positive_id(audit_event_id, "audit_event_id")
        audit_error_code = ""
    elif audit_event_id is not None:
        raise ValueError("audit_event_id solo se permite si la auditoría se confirmó.")
    if not isinstance(audit_error_code, str) or len(audit_error_code) > 64:
        raise ValueError("audit_error_code no es válido.")
    _authorize_actor_company(
        empresa_id=empresa_id,
        actor_id=actor_id,
    )

    storage = resolve_reunion_creation_request_storage()
    with _creation_atomic(storage, request_id) as unit:
        record = unit.get_request(request_id, lock=True)
        if record is None or (
            record.empresa_id != empresa_id or record.actor_id != actor_id
        ):
            raise ReunionCreationRequestNotFound(
                "La solicitud no existe en la empresa activa."
            )
        if record.status not in {
            ReunionCreationRequest.Estado.COMPLETADA,
            ReunionCreationRequest.Estado.CANCELADA,
        }:
            raise ReunionCreationRequestStateError(
                "La auditoría solo se actualiza para una operación terminal."
            )
        if record.audit_status == ReunionCreationRequest.EstadoAuditoria.CONFIRMADA:
            if (
                audit_status != record.audit_status
                or audit_event_id != record.audit_event_id
            ):
                raise ReunionCreationRequestConflict(
                    "La auditoría ya fue confirmada con otro evento."
                )
            return record
        if (
            record.audit_status == audit_status
            and record.audit_event_id == audit_event_id
            and record.audit_error_code == audit_error_code
        ):
            return record
        if not unit.transition_request(
            request_id,
            expected_status=record.status,
            values={
                "audit_status": audit_status,
                "audit_event_id": audit_event_id,
                "audit_error_code": audit_error_code,
            },
        ):
            raise ReunionCreationRequestStateError(
                "No se pudo actualizar el estado técnico de auditoría."
            )
        updated = unit.get_request(request_id, lock=True)
        if updated is None:
            raise ReunionCreationRequestStorageError(
                "No se pudo recuperar el estado de auditoría actualizado."
            )
        return updated


def execute_idempotent_creation(
    *,
    request_id,
    empresa_id: int,
    actor_id: int,
    payload_hash: str,
    review_fingerprint: str,
    create_callback: CreationCallback,
    confirmation_token: str,
) -> ReunionCreationResult:
    request_id = _normalize_request_id(request_id)
    empresa_id = _positive_id(empresa_id, "empresa_id")
    actor_id = _positive_id(actor_id, "actor_id")
    payload_hash = _fingerprint(payload_hash, "payload_hash")
    review_fingerprint = _fingerprint(
        review_fingerprint,
        "review_fingerprint",
    )
    if not callable(create_callback):
        raise TypeError("create_callback debe ser invocable.")
    _authorize_actor_company(
        empresa_id=empresa_id,
        actor_id=actor_id,
        require_meeting_create=True,
    )

    storage = resolve_reunion_creation_request_storage()
    now = timezone.now()

    with _creation_atomic(storage, request_id) as unit:
        record = unit.get_request(request_id, lock=True)
        if record is None:
            raise ReunionCreationRequestNotFound(
                "No existe una solicitud técnica reservada."
            )
        _assert_same_request(
            record,
            request_id=request_id,
            empresa_id=empresa_id,
            actor_id=actor_id,
            payload_hash=payload_hash,
        )
        if record.review_fingerprint != review_fingerprint:
            raise ReunionCreationRequestConflict(
                "La revisión de similitud cambió; vuelva a confirmar."
            )
        if record.status == ReunionCreationRequest.Estado.COMPLETADA:
            if record.task_id is None or record.meeting_id is None:
                raise ReunionCreationRequestStorageError(
                    "La solicitud completada no tiene un resultado íntegro."
                )
            return ReunionCreationResult(
                request_id=record.request_id,
                task_id=record.task_id,
                meeting_id=record.meeting_id,
                replayed=True,
            )
        if record.status == ReunionCreationRequest.Estado.CANCELADA:
            raise ReunionCreationRequestStateError(
                "La solicitud fue cancelada y no puede reactivarse."
            )
        if record.status == ReunionCreationRequest.Estado.EXPIRADA:
            raise ReunionCreationRequestExpired(
                "La solicitud expiró y no puede completarse."
            )
        if record.expires_at <= now:
            raise ReunionCreationRequestExpired(
                "La solicitud expiró antes de iniciar la creación."
            )
        if record.status == ReunionCreationRequest.Estado.EN_PROGRESO:
            raise ReunionCreationRequestStateError(
                "La solicitud ya tiene una operación transaccional en curso."
            )
        if record.status != ReunionCreationRequest.Estado.REVISION_PENDIENTE:
            raise ReunionCreationRequestStateError(
                "La solicitud no está pendiente de confirmación."
            )
        _validate_confirmation_token(confirmation_token, record)
        if not unit.transaction_active:
            raise ReunionCreationRequestStateError(
                "La unidad de trabajo no tiene una transacción activa."
            )

        if not unit.transition_request(
            request_id,
            expected_status=record.status,
            values={"status": ReunionCreationRequest.Estado.EN_PROGRESO},
        ):
            raise ReunionCreationRequestStateError(
                "La solicitud cambió antes de iniciar la creación."
            )

        result_ids = create_callback(unit)
        if (
            not isinstance(result_ids, tuple)
            or len(result_ids) != 2
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 1
                for value in result_ids
            )
        ):
            raise ValueError(
                "create_callback debe devolver (task_id, meeting_id) positivos."
            )
        task_id, meeting_id = result_ids
        if not unit.validate_creation_result(
            request_id=request_id,
            empresa_id=empresa_id,
            task_id=task_id,
            meeting_id=meeting_id,
        ):
            raise ReunionCreationRequestStateError(
                "El callback no produjo una tarea y reunión relacionadas en la empresa."
            )
        completed_at = timezone.now()
        if not unit.transition_request(
            request_id,
            expected_status=ReunionCreationRequest.Estado.EN_PROGRESO,
            values={
                "status": ReunionCreationRequest.Estado.COMPLETADA,
                "task_id": task_id,
                "meeting_id": meeting_id,
                "completed_at": completed_at,
            },
        ):
            raise ReunionCreationRequestStateError(
                "No se pudo completar la solicitud dentro de la transacción."
            )

    return ReunionCreationResult(
        request_id=request_id,
        task_id=task_id,
        meeting_id=meeting_id,
        replayed=False,
    )


def _assert_same_request(
    record: CreationRequestRecord,
    *,
    request_id: UUID,
    empresa_id: int,
    actor_id: int,
    payload_hash: str,
) -> None:
    if (
        record.request_id != request_id
        or record.empresa_id != empresa_id
        or record.actor_id != actor_id
        or not hmac.compare_digest(record.payload_hash, payload_hash)
    ):
        raise ReunionCreationRequestConflict(
            "request_id ya pertenece a otra empresa, actor o payload."
        )


def _record_with(record: CreationRequestRecord, **changes) -> CreationRequestRecord:
    return replace(record, **changes)


__all__ = [
    "CreationCallback",
    "CreationRequestUnitOfWork",
    "NON_COMPLETED_REQUEST_RETENTION_DAYS",
    "REVIEW_TOKEN_TTL_SECONDS",
    "ReunionCreationIdempotencyError",
    "ReunionCreationRequestConflict",
    "ReunionCreationRequestExpired",
    "ReunionCreationRequestNotFound",
    "ReunionCreationRequestOutcomeUnknown",
    "ReunionCreationRequestRetryable",
    "ReunionCreationRequestStateError",
    "ReunionCreationRequestStorageFailure",
    "ReunionCreationRequestUnauthorized",
    "ReunionCreationResult",
    "cancel_creation_request",
    "create_review_request",
    "execute_idempotent_creation",
    "expire_creation_request",
    "fingerprint_matches",
    "fingerprint_payload",
    "get_completed_result",
    "get_creation_request",
    "issue_creation_confirmation",
    "new_creation_request_id",
    "new_request_expiration",
    "record_audit_delivery",
    "refresh_review_request",
]
