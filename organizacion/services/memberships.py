"""Read-only facts, not fenced authorization snapshots; callers retain ICMEAS checks."""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Callable, ParamSpec, TypeVar
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DEFAULT_DB_ALIAS, DatabaseError, IntegrityError
from django.db.models import F

from access_control.models import Empresa
from access_control.services.permissions import (
    get_valid_users_for_empresa,
    user_has_permission_for_empresa,
)
from auditoria.services import AuditoriaService
from organizacion.services.coordination import (
    OrganizationCoordinationBusyError,
    OrganizationCoordinationInputError,
    OrganizationCoordinationUnavailableError,
    is_sqlite_busy_locked_error,
    organization_guard,
)
from organizacion.models import (
    ControlOrganizacionEmpresa,
    Departamento,
    EventoMembresia,
    MembresiaDepartamental,
)

logger = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R")


class OrganizationInputError(ValueError):
    pass


class OrganizationNotFoundError(LookupError):
    pass


class OrganizationUnavailableError(RuntimeError):
    pass


class MembershipConflict(RuntimeError):
    pass


class MembershipPermissionDenied(PermissionError):
    pass


class MembershipOperation(str, Enum):
    CREATE = "ALTA"
    CHANGE_ROLE = "CAMBIO_ROL"
    SUSPEND = "SUSPENSION"
    REACTIVATE = "REACTIVACION"
    LOGICAL_DELETE = "BAJA"


@dataclass(frozen=True)
class MembershipCommand:
    company_id: int
    actor_id: int
    user_id: int
    department_id: int
    operation_id: UUID | str
    action: MembershipOperation | str
    reason: str
    target_role: str | None
    expected_membership_version: int | None
    expected_organization_revision: int | None


@dataclass(frozen=True)
class _NormalizedMembershipCommand:
    company_id: int
    actor_id: int
    user_id: int
    department_id: int
    operation_id: UUID
    action: MembershipOperation
    reason: str
    target_role: str | None
    expected_membership_version: int | None
    expected_organization_revision: int | None


@dataclass(frozen=True)
class MembershipCommandResult:
    membership_id: int
    company_id: int
    department_id: int
    user_id: int
    role: str
    state: str
    membership_version: int
    organization_revision: int
    operation_id: UUID
    event_id: int
    replayed: bool = False


@dataclass(frozen=True)
class MembershipHistoryEvent:
    id: int
    membership_id: int
    company_id: int
    department_id: int
    user_id: int
    actor_id: int
    created_at: datetime
    operation_id: UUID
    sequence: int
    action: str
    reason: str
    role_before: str | None
    state_before: str | None
    membership_version_before: int | None
    role_after: str
    state_after: str
    membership_version_after: int
    expected_organization_revision: int | None
    organization_revision: int | None


@dataclass(frozen=True)
class DepartmentDTO:
    id: int
    empresa_id: int
    codigo: str
    nombre: str


@dataclass(frozen=True)
class MembershipDTO:
    id: int
    empresa_id: int
    departamento_id: int
    usuario_id: int
    rol: str
    estado: str
    version: int


@dataclass(frozen=True)
class MembershipSnapshot:
    memberships: tuple[MembershipDTO, ...]
    revision: int | None


@dataclass(frozen=True)
class EligibilityResult:
    elegible: bool
    causas: tuple[str, ...]
    departamentos: tuple[int, ...]
    revision: int | None


@dataclass(frozen=True)
class DepartmentLeadership:
    jefe: MembershipDTO | None
    supervisores: tuple[MembershipDTO, ...]


def _read_query(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except DatabaseError:
            logger.error("Organizational query unavailable: %s", function.__name__)
            raise OrganizationUnavailableError("organizacion.memberships.unavailable") from None
    return wrapped


def _identifier(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OrganizationInputError("organizacion.memberships.invalid_identifier")


def _company(empresa_id: int) -> Empresa:
    _identifier(empresa_id)
    try:
        return Empresa.objects.using(DEFAULT_DB_ALIAS).get(pk=empresa_id)
    except Empresa.DoesNotExist:
        raise OrganizationNotFoundError("organizacion.memberships.company_not_found") from None


def _department(empresa_id: int, department_id: int) -> None:
    _identifier(department_id)
    if not Departamento.objects.using(DEFAULT_DB_ALIAS).filter(
        pk=department_id, empresa_id=empresa_id
    ).exists():
        raise OrganizationNotFoundError("organizacion.memberships.department_not_found")


def _user(user_id: int):
    _identifier(user_id)
    model = get_user_model()
    try:
        return model.objects.using(DEFAULT_DB_ALIAS).get(pk=user_id)
    except model.DoesNotExist:
        raise OrganizationNotFoundError("organizacion.memberships.user_not_found") from None


def _rows(empresa_id: int):
    return MembresiaDepartamental.objects.using(DEFAULT_DB_ALIAS).filter(
        empresa_id=empresa_id, departamento__empresa_id=F("empresa_id")
    ).order_by("departamento_id", "usuario_id", "pk")


def _materialize(queryset) -> tuple[MembershipDTO, ...]:
    return tuple(
        MembershipDTO(**row) for row in queryset.values(
            "id", "empresa_id", "departamento_id", "usuario_id", "rol", "estado", "version"
        )
    )


def _effective_rows(company: Empresa):
    valid_users = get_valid_users_for_empresa(company, active_only=True).using(DEFAULT_DB_ALIAS)
    return _rows(company.pk).filter(
        estado=MembresiaDepartamental.Estado.ACTIVA,
        departamento__activo=True,
        usuario_id__in=valid_users.values("pk"),
    )


def _revision(empresa_id: int) -> int | None:
    # Missing coordination is not revision zero and does not create a fence on read.
    return ControlOrganizacionEmpresa.objects.using(DEFAULT_DB_ALIAS).filter(
        empresa_id=empresa_id
    ).values_list("version", flat=True).first()


@_read_query
def list_active_departments(*, empresa_id: int) -> tuple[DepartmentDTO, ...]:
    _company(empresa_id)
    return tuple(DepartmentDTO(**row) for row in Departamento.objects.using(DEFAULT_DB_ALIAS).filter(
        empresa_id=empresa_id, activo=True
    ).order_by("codigo", "pk").values("id", "empresa_id", "codigo", "nombre"))


@_read_query
def list_memberships(
    *, empresa_id: int, user_id: int | None = None, department_id: int | None = None
) -> tuple[MembershipDTO, ...]:
    """Include inactive history-bearing rows; this is not an eligibility decision."""
    _company(empresa_id)
    rows = _rows(empresa_id)
    if user_id is not None:
        _user(user_id)
        rows = rows.filter(usuario_id=user_id)
    if department_id is not None:
        _department(empresa_id, department_id)
        rows = rows.filter(departamento_id=department_id)
    return _materialize(rows)


@_read_query
def get_effective_memberships(*, empresa_id: int, user_id: int) -> MembershipSnapshot:
    company = _company(empresa_id)
    _user(user_id)
    return MembershipSnapshot(
        _materialize(_effective_rows(company).filter(usuario_id=user_id)), _revision(empresa_id)
    )


@_read_query
def check_department_eligibility(*, empresa_id: int, user_id: int) -> EligibilityResult:
    company = _company(empresa_id)
    user = _user(user_id)
    causes = []
    if not user.is_active:
        causes.append("INACTIVE_USER")
    if not get_valid_users_for_empresa(company).using(DEFAULT_DB_ALIAS).filter(pk=user_id).exists():
        causes.append("NO_COMPANY_ACCESS")
    rows = _materialize(_effective_rows(company).filter(usuario_id=user_id))
    if not rows:
        causes.append("NO_EFFECTIVE_MEMBERSHIP")
    return EligibilityResult(
        bool(rows) and not causes, tuple(causes),
        tuple(row.departamento_id for row in rows), _revision(empresa_id),
    )


@_read_query
def get_department_leadership(*, empresa_id: int, department_id: int) -> DepartmentLeadership:
    company = _company(empresa_id)
    _department(empresa_id, department_id)
    rows = _materialize(_effective_rows(company).filter(
        departamento_id=department_id, rol__in=("JEFE", "SUPERVISOR")
    ))
    heads = tuple(row for row in rows if row.rol == "JEFE")
    if len(heads) > 1:
        logger.error("Organizational leadership invariant violated")
        raise OrganizationUnavailableError("organizacion.memberships.inconsistent_leadership")
    return DepartmentLeadership(
        heads[0] if heads else None, tuple(row for row in rows if row.rol == "SUPERVISOR")
    )


_MEMBERSHIP_VIEW = "Tareas - Maestro de departamentos"
_PERMISSION_BY_OPERATION = {
    MembershipOperation.CREATE: "crear",
    MembershipOperation.CHANGE_ROLE: "modificar",
    MembershipOperation.SUSPEND: "modificar",
    MembershipOperation.REACTIVATE: "modificar",
    MembershipOperation.LOGICAL_DELETE: "eliminar",
}
_AUDIT_ACTION_BY_OPERATION = {
    MembershipOperation.CREATE: "CREATE",
    MembershipOperation.CHANGE_ROLE: "UPDATE",
    MembershipOperation.SUSPEND: "UPDATE",
    MembershipOperation.REACTIVATE: "UPDATE",
    MembershipOperation.LOGICAL_DELETE: "DELETE",
}
_AUDIT_MESSAGE_BY_OPERATION = {
    MembershipOperation.CREATE: "organizacion.memberships.created",
    MembershipOperation.CHANGE_ROLE: "organizacion.memberships.role_changed",
    MembershipOperation.SUSPEND: "organizacion.memberships.suspended",
    MembershipOperation.REACTIVATE: "organizacion.memberships.reactivated",
    MembershipOperation.LOGICAL_DELETE: "organizacion.memberships.deleted",
}


def _normalize_membership_command(command: MembershipCommand) -> _NormalizedMembershipCommand:
    if not isinstance(command, MembershipCommand):
        raise OrganizationInputError("organizacion.memberships.invalid_command")

    for value in (command.company_id, command.actor_id, command.user_id, command.department_id):
        _identifier(value)

    try:
        operation_id = UUID(str(command.operation_id))
        action = MembershipOperation(command.action)
    except (TypeError, ValueError, AttributeError):
        raise OrganizationInputError("organizacion.memberships.invalid_command") from None

    if not isinstance(command.reason, str) or not command.reason.strip():
        raise OrganizationInputError("organizacion.memberships.reason_required")
    reason = command.reason.strip()

    role_actions = (MembershipOperation.CREATE, MembershipOperation.CHANGE_ROLE)
    target_role = command.target_role
    if action in role_actions:
        if not isinstance(target_role, str) or target_role not in MembresiaDepartamental.Rol.values:
            raise OrganizationInputError("organizacion.memberships.invalid_role")
    elif target_role is not None:
        raise OrganizationInputError("organizacion.memberships.unexpected_role")

    expected_membership_version = command.expected_membership_version
    if action is MembershipOperation.CREATE:
        if expected_membership_version is not None:
            raise OrganizationInputError("organizacion.memberships.invalid_expected_version")
    else:
        if expected_membership_version is None:
            raise OrganizationInputError("organizacion.memberships.invalid_expected_version")
        _identifier(expected_membership_version)

    expected_organization_revision = command.expected_organization_revision
    if expected_organization_revision is not None:
        _identifier(expected_organization_revision)

    return _NormalizedMembershipCommand(
        company_id=command.company_id,
        actor_id=command.actor_id,
        user_id=command.user_id,
        department_id=command.department_id,
        operation_id=operation_id,
        action=action,
        reason=reason,
        target_role=target_role,
        expected_membership_version=expected_membership_version,
        expected_organization_revision=expected_organization_revision,
    )


def _membership_command_fingerprint(command: _NormalizedMembershipCommand) -> str:
    payload = {
        "format": 1,
        "operation_id": command.operation_id.hex,
        "action": command.action.value,
        "company_id": command.company_id,
        "actor_id": command.actor_id,
        "user_id": command.user_id,
        "department_id": command.department_id,
        "target_role": command.target_role,
        "reason": command.reason,
        "expected_membership_version": command.expected_membership_version,
        "expected_organization_revision": command.expected_organization_revision,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _company_user_is_valid(company: Empresa, user_id: int) -> bool:
    return get_valid_users_for_empresa(company, active_only=True).using(
        DEFAULT_DB_ALIAS
    ).filter(pk=user_id).exists()


def _authorized_actor(company: Empresa, actor_id: int, action: str):
    actor = _user(actor_id)
    if not actor.is_active or not _company_user_is_valid(company, actor.pk):
        raise MembershipPermissionDenied("organizacion.memberships.actor_not_authorized")
    if not user_has_permission_for_empresa(
        user=actor,
        empresa=company,
        vista_nombre=_MEMBERSHIP_VIEW,
        accion=action,
    ):
        raise MembershipPermissionDenied("organizacion.memberships.actor_not_authorized")
    return actor


def _replay_result(
    command: _NormalizedMembershipCommand,
    fingerprint: str,
) -> MembershipCommandResult | None:
    events = list(
        EventoMembresia.objects.using(DEFAULT_DB_ALIAS)
        .filter(operacion_id=command.operation_id)
        .order_by("secuencia", "pk")
    )
    if not events:
        return None
    if len(events) != 1:
        raise MembershipConflict("organizacion.memberships.operation_id_conflict")

    event = events[0]
    matches = (
        event.secuencia == 1
        and event.empresa_id == command.company_id
        and event.autor_id == command.actor_id
        and event.usuario_afectado_id == command.user_id
        and event.departamento_id == command.department_id
        and event.tipo == command.action.value
        and event.motivo == command.reason
        and event.version_antes == command.expected_membership_version
        and event.revision_organizacion_esperada == command.expected_organization_revision
        and event.huella_solicitud == fingerprint
        and event.revision_organizacion is not None
    )
    if not matches:
        raise MembershipConflict("organizacion.memberships.operation_id_conflict")
    if (
        event.pk is None
        or event.membresia_id is None
        or event.empresa_id is None
        or event.departamento_id is None
        or event.usuario_afectado_id is None
        or event.revision_organizacion is None
    ):
        raise MembershipConflict("organizacion.memberships.operation_result_incomplete")

    expected_version_after = 1
    if command.action is not MembershipOperation.CREATE:
        expected_version_before = command.expected_membership_version
        if expected_version_before is None:
            raise MembershipConflict("organizacion.memberships.operation_result_incomplete")
        expected_version_after = expected_version_before + 1
    expected_revision_after = (
        2
        if command.expected_organization_revision is None
        else command.expected_organization_revision + 1
    )
    expected_state_after = {
        MembershipOperation.CREATE: MembresiaDepartamental.Estado.ACTIVA,
        MembershipOperation.SUSPEND: MembresiaDepartamental.Estado.SUSPENDIDA,
        MembershipOperation.REACTIVATE: MembresiaDepartamental.Estado.ACTIVA,
        MembershipOperation.LOGICAL_DELETE: MembresiaDepartamental.Estado.BAJA,
    }.get(command.action)
    state_transition_matches = {
        MembershipOperation.CREATE: (
            event.rol_antes is None
            and event.estado_antes is None
            and event.version_antes is None
        ),
        MembershipOperation.CHANGE_ROLE: (
            event.estado_antes == event.estado_despues
            and event.rol_antes != event.rol_despues
        ),
        MembershipOperation.SUSPEND: (
            event.estado_antes == MembresiaDepartamental.Estado.ACTIVA
            and event.estado_despues == MembresiaDepartamental.Estado.SUSPENDIDA
            and event.rol_antes == event.rol_despues
        ),
        MembershipOperation.REACTIVATE: (
            event.estado_antes in (
                MembresiaDepartamental.Estado.SUSPENDIDA,
                MembresiaDepartamental.Estado.BAJA,
            )
            and event.estado_despues == MembresiaDepartamental.Estado.ACTIVA
            and event.rol_antes == event.rol_despues
        ),
        MembershipOperation.LOGICAL_DELETE: (
            event.estado_antes in (
                MembresiaDepartamental.Estado.ACTIVA,
                MembresiaDepartamental.Estado.SUSPENDIDA,
            )
            and event.estado_despues == MembresiaDepartamental.Estado.BAJA
            and event.rol_antes == event.rol_despues
        ),
    }[command.action]
    if (
        event.version_despues != expected_version_after
        or event.revision_organizacion != expected_revision_after
        or (command.target_role is not None and event.rol_despues != command.target_role)
        or (expected_state_after is not None and event.estado_despues != expected_state_after)
        or not state_transition_matches
    ):
        raise MembershipConflict("organizacion.memberships.operation_result_inconsistent")

    return MembershipCommandResult(
        membership_id=event.membresia_id,
        company_id=event.empresa_id,
        department_id=event.departamento_id,
        user_id=event.usuario_afectado_id,
        role=event.rol_despues,
        state=event.estado_despues,
        membership_version=event.version_despues,
        organization_revision=event.revision_organizacion,
        operation_id=event.operacion_id,
        event_id=event.pk,
        replayed=True,
    )


def _membership_for_command(command: _NormalizedMembershipCommand) -> MembresiaDepartamental:
    try:
        return MembresiaDepartamental.objects.using(DEFAULT_DB_ALIAS).get(
            empresa_id=command.company_id,
            departamento_id=command.department_id,
            departamento__empresa_id=F("empresa_id"),
            usuario_id=command.user_id,
        )
    except MembresiaDepartamental.DoesNotExist:
        raise OrganizationNotFoundError("organizacion.memberships.membership_not_found") from None


def _department_object(company_id: int, department_id: int) -> Departamento:
    try:
        return Departamento.objects.using(DEFAULT_DB_ALIAS).get(
            pk=department_id,
            empresa_id=company_id,
        )
    except Departamento.DoesNotExist:
        raise OrganizationNotFoundError("organizacion.memberships.department_not_found") from None


def _require_target_access(company: Empresa, user_id: int) -> None:
    user = _user(user_id)
    if not user.is_active or not _company_user_is_valid(company, user.pk):
        raise MembershipConflict("organizacion.memberships.target_not_eligible")


def _required_target_role(command: _NormalizedMembershipCommand) -> str:
    if command.target_role is None:
        raise OrganizationInputError("organizacion.memberships.invalid_role")
    return command.target_role


def _ensure_head_is_available(department_id: int, *, exclude_id: int | None = None) -> None:
    heads = MembresiaDepartamental.objects.using(DEFAULT_DB_ALIAS).filter(
        departamento_id=department_id,
        rol=MembresiaDepartamental.Rol.JEFE,
        estado=MembresiaDepartamental.Estado.ACTIVA,
    )
    if exclude_id is not None:
        heads = heads.exclude(pk=exclude_id)
    if heads.exists():
        raise MembershipConflict("organizacion.memberships.active_head_exists")


def _apply_membership_command(
    command: _NormalizedMembershipCommand,
    fingerprint: str,
) -> MembershipCommandResult:
    company = _company(command.company_id)
    actor = _authorized_actor(
        company,
        command.actor_id,
        _PERMISSION_BY_OPERATION[command.action],
    )

    replay = _replay_result(command, fingerprint)
    if replay is not None:
        return replay

    department = _department_object(company.pk, command.department_id)
    target_user = _user(command.user_id)
    if command.action is not MembershipOperation.LOGICAL_DELETE:
        _require_target_access(company, target_user.pk)

    control = ControlOrganizacionEmpresa.objects.using(DEFAULT_DB_ALIAS).filter(
        empresa_id=company.pk
    ).first()
    if control is None:
        if command.expected_organization_revision is not None:
            raise MembershipConflict("organizacion.memberships.stale_organization_revision")
        current_revision = None
    else:
        if (
            command.expected_organization_revision is None
            or command.expected_organization_revision != control.version
        ):
            raise MembershipConflict("organizacion.memberships.stale_organization_revision")
        current_revision = control.version

    member = None
    if command.action is MembershipOperation.CREATE:
        if MembresiaDepartamental.objects.using(DEFAULT_DB_ALIAS).filter(
            empresa_id=company.pk,
            departamento_id=department.pk,
            usuario_id=target_user.pk,
        ).exists():
            raise MembershipConflict("organizacion.memberships.membership_already_exists")
        role_after = _required_target_role(command)
        state_after = MembresiaDepartamental.Estado.ACTIVA
        version_before = None
        role_before = None
        state_before = None
        version_after = 1
        if role_after == MembresiaDepartamental.Rol.JEFE:
            _ensure_head_is_available(department.pk)
    else:
        member = _membership_for_command(command)
        expected_membership_version = command.expected_membership_version
        if expected_membership_version is None:
            raise OrganizationInputError("organizacion.memberships.invalid_expected_version")
        if member.version != expected_membership_version:
            raise MembershipConflict("organizacion.memberships.stale_membership_version")
        role_before = member.rol
        state_before = member.estado
        version_before = member.version
        version_after = member.version + 1

        if command.action is MembershipOperation.CHANGE_ROLE:
            role_after = _required_target_role(command)
            if role_after == member.rol:
                raise MembershipConflict("organizacion.memberships.no_change")
            if role_after == MembresiaDepartamental.Rol.JEFE:
                _ensure_head_is_available(department.pk, exclude_id=member.pk)
            state_after = member.estado
        elif command.action is MembershipOperation.SUSPEND:
            if member.estado != MembresiaDepartamental.Estado.ACTIVA:
                raise MembershipConflict("organizacion.memberships.invalid_transition")
            role_after = member.rol
            state_after = MembresiaDepartamental.Estado.SUSPENDIDA
        elif command.action is MembershipOperation.REACTIVATE:
            if member.estado not in (
                MembresiaDepartamental.Estado.SUSPENDIDA,
                MembresiaDepartamental.Estado.BAJA,
            ):
                raise MembershipConflict("organizacion.memberships.invalid_transition")
            role_after = member.rol
            state_after = MembresiaDepartamental.Estado.ACTIVA
            if role_after == MembresiaDepartamental.Rol.JEFE:
                _ensure_head_is_available(department.pk, exclude_id=member.pk)
        else:
            if member.estado not in (
                MembresiaDepartamental.Estado.ACTIVA,
                MembresiaDepartamental.Estado.SUSPENDIDA,
            ):
                raise MembershipConflict("organizacion.memberships.invalid_transition")
            role_after = member.rol
            state_after = MembresiaDepartamental.Estado.BAJA

    if control is None:
        control = ControlOrganizacionEmpresa.objects.using(DEFAULT_DB_ALIAS).create(
            empresa=company,
            version=1,
        )
    organization_revision = (current_revision or control.version) + 1

    if member is None:
        member = MembresiaDepartamental(
            empresa=company,
            departamento=department,
            usuario=target_user,
            rol=role_after,
            estado=state_after,
            version=version_after,
        )
        member.save(using=DEFAULT_DB_ALIAS, force_insert=True)
    else:
        member.rol = role_after
        member.estado = state_after
        member.version = version_after
        member.save(
            using=DEFAULT_DB_ALIAS,
            update_fields={"rol", "estado", "version", "updated_at"},
        )

    event = EventoMembresia(
        membresia=member,
        empresa=company,
        usuario_afectado=target_user,
        departamento=department,
        autor=actor,
        operacion_id=command.operation_id,
        secuencia=1,
        tipo=command.action.value,
        motivo=command.reason,
        rol_antes=role_before,
        estado_antes=state_before,
        version_antes=version_before,
        rol_despues=role_after,
        estado_despues=state_after,
        version_despues=version_after,
        huella_solicitud=fingerprint,
        revision_organizacion_esperada=command.expected_organization_revision,
        revision_organizacion=organization_revision,
    )
    event.save(using=DEFAULT_DB_ALIAS)
    if event.pk is None or member.pk is None:
        raise OrganizationUnavailableError("organizacion.memberships.persistence_incomplete")

    control.version = organization_revision
    control.save(using=DEFAULT_DB_ALIAS, update_fields={"version"})

    before = None
    if version_before is not None:
        before = {
            "rol": role_before,
            "estado": state_before,
            "version": version_before,
        }
    after = {
        "membresia_id": member.pk,
        "departamento_id": department.pk,
        "usuario_id": target_user.pk,
        "rol": role_after,
        "estado": state_after,
        "version": version_after,
        "revision_organizacion": organization_revision,
    }
    try:
        central_event = AuditoriaService.log_event(
            "organizacion",
            action=_AUDIT_ACTION_BY_OPERATION[command.action],
            user=actor,
            empresa_id=company.pk,
            object_type="MembresiaDepartamental",
            object_id=str(member.pk),
            method="INTERNAL",
            path="internal/organizacion/membresias",
            vista_nombre=_MEMBERSHIP_VIEW,
            message_key=_AUDIT_MESSAGE_BY_OPERATION[command.action],
            meta={
                "operation_id": str(command.operation_id),
                "operation": command.action.value,
                "reason": command.reason,
            },
            before=before,
            after=after,
        )
    except Exception:
        logger.error(
            "Central audit raised for membership operation_id=%s",
            command.operation_id.hex,
        )
        raise OrganizationUnavailableError("organizacion.memberships.audit_unavailable") from None
    if central_event is None:
        logger.error(
            "Central audit unavailable for membership operation_id=%s",
            command.operation_id.hex,
        )
        raise OrganizationUnavailableError("organizacion.memberships.audit_unavailable")

    return MembershipCommandResult(
        membership_id=member.pk,
        company_id=company.pk,
        department_id=department.pk,
        user_id=target_user.pk,
        role=role_after,
        state=state_after,
        membership_version=version_after,
        organization_revision=organization_revision,
        operation_id=command.operation_id,
        event_id=event.pk,
    )


def change_membership(command: MembershipCommand) -> MembershipCommandResult:
    """Apply one audited transition inside SQLite's database-wide writer guard."""
    normalized = _normalize_membership_command(command)
    fingerprint = _membership_command_fingerprint(normalized)
    try:
        with organization_guard(company_id=normalized.company_id):
            return _apply_membership_command(normalized, fingerprint)
    except (
        OrganizationInputError,
        OrganizationNotFoundError,
        OrganizationUnavailableError,
        MembershipConflict,
        MembershipPermissionDenied,
    ):
        raise
    except OrganizationCoordinationInputError:
        raise OrganizationInputError("organizacion.memberships.invalid_identifier") from None
    except OrganizationCoordinationBusyError:
        logger.warning(
            "SQLite writer contention for membership operation_id=%s",
            normalized.operation_id.hex,
        )
        raise OrganizationUnavailableError(
            "organizacion.memberships.sqlite_writer_busy_retry_same_operation"
        ) from None
    except OrganizationCoordinationUnavailableError:
        logger.error(
            "Organization coordination unavailable operation_id=%s",
            normalized.operation_id.hex,
        )
        raise OrganizationUnavailableError(
            "organizacion.coordination.unavailable"
        ) from None
    except IntegrityError:
        raise MembershipConflict("organizacion.memberships.constraint_conflict") from None
    except DjangoValidationError:
        raise MembershipConflict("organizacion.memberships.invariant_conflict") from None
    except DatabaseError as exc:
        if is_sqlite_busy_locked_error(exc):
            logger.warning(
                "SQLite writer contention during membership operation_id=%s",
                normalized.operation_id.hex,
            )
            raise OrganizationUnavailableError(
                "organizacion.memberships.sqlite_writer_busy_retry_same_operation"
            ) from None
        logger.error(
            "Membership mutation storage unavailable operation_id=%s",
            normalized.operation_id.hex,
        )
        raise OrganizationUnavailableError("organizacion.memberships.unavailable") from None


def get_membership_history(
    *,
    company_id: int,
    actor_id: int,
    membership_id: int,
) -> tuple[MembershipHistoryEvent, ...]:
    """Return one authorized company's immutable, materialized membership history."""
    try:
        _identifier(company_id)
        _identifier(actor_id)
        _identifier(membership_id)
        company = _company(company_id)
        _authorized_actor(company, actor_id, "ingresar")
        member = MembresiaDepartamental.objects.using(DEFAULT_DB_ALIAS).filter(
            pk=membership_id,
            empresa_id=company.pk,
            departamento__empresa_id=F("empresa_id"),
        ).first()
        if member is None:
            raise OrganizationNotFoundError("organizacion.memberships.membership_not_found")

        rows = EventoMembresia.objects.using(DEFAULT_DB_ALIAS).filter(
            membresia_id=member.pk,
            empresa_id=company.pk,
            departamento__empresa_id=F("empresa_id"),
        ).order_by("fecha", "pk").values(
            "id",
            "membresia_id",
            "empresa_id",
            "departamento_id",
            "usuario_afectado_id",
            "autor_id",
            "fecha",
            "operacion_id",
            "secuencia",
            "tipo",
            "motivo",
            "rol_antes",
            "estado_antes",
            "version_antes",
            "rol_despues",
            "estado_despues",
            "version_despues",
            "revision_organizacion_esperada",
            "revision_organizacion",
        )
        return tuple(
            MembershipHistoryEvent(
                id=row["id"],
                membership_id=row["membresia_id"],
                company_id=row["empresa_id"],
                department_id=row["departamento_id"],
                user_id=row["usuario_afectado_id"],
                actor_id=row["autor_id"],
                created_at=row["fecha"],
                operation_id=row["operacion_id"],
                sequence=row["secuencia"],
                action=row["tipo"],
                reason=row["motivo"],
                role_before=row["rol_antes"],
                state_before=row["estado_antes"],
                membership_version_before=row["version_antes"],
                role_after=row["rol_despues"],
                state_after=row["estado_despues"],
                membership_version_after=row["version_despues"],
                expected_organization_revision=row["revision_organizacion_esperada"],
                organization_revision=row["revision_organizacion"],
            )
            for row in rows
        )
    except DatabaseError:
        logger.error(
            "Membership history unavailable company_id=%s membership_id=%s",
            company_id,
            membership_id,
        )
        raise OrganizationUnavailableError("organizacion.memberships.unavailable") from None
