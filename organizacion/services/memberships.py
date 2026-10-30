"""Read-only facts, not fenced authorization snapshots; callers retain ICMEAS checks."""

import logging
from dataclasses import dataclass
from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from django.contrib.auth import get_user_model
from django.db import DEFAULT_DB_ALIAS, DatabaseError
from django.db.models import F

from access_control.models import Empresa
from access_control.services.permissions import get_valid_users_for_empresa
from organizacion.models import ControlOrganizacionEmpresa, Departamento, MembresiaDepartamental

logger = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R")


class OrganizationInputError(ValueError):
    pass


class OrganizationNotFoundError(LookupError):
    pass


class OrganizationUnavailableError(RuntimeError):
    pass


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
