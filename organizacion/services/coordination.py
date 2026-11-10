"""SQLite writer-first coordination for organizational mutations."""

import logging
import sqlite3
from contextlib import contextmanager
from typing import Generator

from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections, transaction
from django.db.models import F

from organizacion.models import ControlOrganizacionEmpresa

logger = logging.getLogger(__name__)


class OrganizationCoordinationInputError(ValueError):
    pass


class OrganizationCoordinationBusyError(RuntimeError):
    pass


class OrganizationCoordinationUnavailableError(RuntimeError):
    pass


def is_sqlite_busy_locked_error(error: BaseException) -> bool:
    if connections[DEFAULT_DB_ALIAS].vendor != "sqlite":
        return False

    pending: BaseException | None = error
    visited: set[int] = set()
    while pending is not None and id(pending) not in visited:
        visited.add(id(pending))
        code = getattr(pending, "sqlite_errorcode", None)
        if isinstance(code, int) and code & 0xFF in (
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
        ):
            return True
        pending = pending.__cause__ or pending.__context__
    return False


@contextmanager
def organization_guard(*, company_id: int) -> Generator[None, None, None]:
    """Own the outer transaction and acquire SQLite's database-wide writer lock before reads."""
    if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id < 1:
        raise OrganizationCoordinationInputError(
            "organizacion.coordination.invalid_company"
        )

    database = connections[DEFAULT_DB_ALIAS]
    if database.vendor != "sqlite":
        raise OrganizationCoordinationUnavailableError(
            "organizacion.coordination.backend_not_certified"
        )

    with transaction.atomic(using=DEFAULT_DB_ALIAS, durable=True):
        try:
            # SQLite starts a writer transaction for UPDATE even when no row matches.
            rows = ControlOrganizacionEmpresa.objects.using(DEFAULT_DB_ALIAS).filter(
                empresa_id=company_id
            ).update(version=F("version"))
        except DatabaseError as exc:
            if is_sqlite_busy_locked_error(exc):
                logger.warning(
                    "SQLite organization writer busy company_id=%s",
                    company_id,
                )
                raise OrganizationCoordinationBusyError(
                    "organizacion.coordination.sqlite_writer_busy"
                ) from None
            logger.error(
                "Organization writer lock unavailable company_id=%s",
                company_id,
            )
            raise OrganizationCoordinationUnavailableError(
                "organizacion.coordination.unavailable"
            ) from None

        if rows > 1:
            logger.error("Organization control uniqueness violated company_id=%s", company_id)
            raise OrganizationCoordinationUnavailableError(
                "organizacion.coordination.inconsistent_control"
            )
        yield
