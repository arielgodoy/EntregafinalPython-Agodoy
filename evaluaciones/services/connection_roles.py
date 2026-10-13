from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator, Protocol, TypedDict, cast

from django.conf import settings
from django.db import connections

from common.database_classification import (
    DatabaseClassification,
    get_database_classification,
)
from settings.models import SettingsMySQLConnection
from settings.services.mysql_connections import open_mysql_connection

from ..models import EvaluacionConnectionRole


REQUIRED_CONNECTION_ROLES = tuple(
    item[0] for item in EvaluacionConnectionRole.ROLE_CHOICES
)
SUPPORTED_MYSQL_ENGINES = frozenset(
    {
        SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
        SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL,
    }
)


class EvaluacionesConnectionError(RuntimeError):
    pass


class EvaluacionesConnectionRoleNotFoundError(EvaluacionesConnectionError):
    pass


class EvaluacionesConnectionAliasUnavailableError(EvaluacionesConnectionError):
    pass


class EvaluacionesConnectionInactiveError(EvaluacionesConnectionError):
    pass


class EvaluacionesConnectionSourceError(EvaluacionesConnectionError):
    pass


class EvaluacionesDatabaseNameError(EvaluacionesConnectionError):
    pass


class EvaluacionesCursor(Protocol):
    def execute(self, query: str) -> object: ...

    def close(self) -> None: ...


class EvaluacionesConnection(Protocol):
    def cursor(self) -> EvaluacionesCursor: ...


class EvaluacionesRoleStatus(TypedDict):
    role: str
    label: str
    status: str
    source_type: str | None
    metadata: dict[str, str | bool | None]


class EvaluacionesConnectionStatus(TypedDict):
    configured: bool
    roles: list[EvaluacionesRoleStatus]
    missing_roles: list[str]
    invalid_roles: list[str]


@dataclass(frozen=True)
class EvaluacionesBackendContext:
    logical_role: str
    backend_type: str
    django_alias: str | None = None
    mysql_connection: SettingsMySQLConnection | None = None
    database_name: str | None = None
    vendor: str | None = None


def _database_vendor(config: dict[str, object]) -> str:
    engine = str(config.get("ENGINE") or "")
    if "sqlite" in engine:
        return "sqlite"
    if "mysql" in engine:
        return "mysql"
    if "postgresql" in engine:
        return "postgresql"
    return engine.rsplit(".", 1)[-1] or "unknown"


def get_system_database_catalog() -> tuple[dict[str, str], ...]:
    catalog = []
    for alias, config in getattr(settings, "DATABASES", {}).items():
        if get_database_classification(alias) != DatabaseClassification.SYSTEM:
            continue
        catalog.append(
            {
                "alias": alias,
                "vendor": _database_vendor(config),
                "classification": DatabaseClassification.SYSTEM.value,
            }
        )
    return tuple(catalog)


def get_mysql_connection_catalog():
    return (
        SettingsMySQLConnection.objects.filter(is_active=True)
        .select_related("empresa")
        .order_by("empresa__codigo", "nombre_logico", "pk")
    )


def _valid_database_name(database_name: str | None) -> bool:
    return bool(
        database_name
        and EvaluacionConnectionRole.DATABASE_NAME_PATTERN.fullmatch(database_name)
    )


def _resolve_role_config(
    role_config: EvaluacionConnectionRole,
) -> EvaluacionesBackendContext:
    if role_config.role not in REQUIRED_CONNECTION_ROLES:
        raise EvaluacionesConnectionRoleNotFoundError(
            f"Rol de Evaluaciones desconocido: {role_config.role!r}."
        )

    if role_config.source_type == EvaluacionConnectionRole.SOURCE_DJANGO:
        if role_config.role in EvaluacionConnectionRole.LEGACY_MYSQL_ROLES:
            raise EvaluacionesConnectionSourceError(
                f"El rol {role_config.role!r} requiere una conexión MYSQL_CONFIG."
            )

        alias = (role_config.django_alias or "").strip()
        metadata_by_alias = {
            item["alias"]: item for item in get_system_database_catalog()
        }
        metadata = metadata_by_alias.get(alias)
        if not alias or metadata is None:
            raise EvaluacionesConnectionAliasUnavailableError(
                f"El alias Django del rol {role_config.role!r} "
                "no está disponible como SYSTEM."
            )
        if role_config.mysql_connection is not None:
            raise EvaluacionesConnectionSourceError(
                f"El rol {role_config.role!r} combina fuentes de conexión."
            )
        return EvaluacionesBackendContext(
            logical_role=role_config.role,
            backend_type=EvaluacionConnectionRole.SOURCE_DJANGO,
            django_alias=metadata["alias"],
            vendor=metadata["vendor"],
        )

    if role_config.source_type != EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG:
        raise EvaluacionesConnectionSourceError(
            f"Tipo de conexión inválido para el rol {role_config.role!r}."
        )

    connection = role_config.mysql_connection
    if connection is None or not connection.is_active:
        raise EvaluacionesConnectionInactiveError(
            f"La conexión del rol {role_config.role!r} está inactiva o no existe."
        )
    if (
        SettingsMySQLConnection.normalize_engine(connection.engine)
        not in SUPPORTED_MYSQL_ENGINES
    ):
        raise EvaluacionesConnectionSourceError(
            f"El motor de la conexión del rol {role_config.role!r} "
            "no es compatible."
        )
    if role_config.django_alias:
        raise EvaluacionesConnectionSourceError(
            f"El rol {role_config.role!r} combina fuentes de conexión."
        )

    if role_config.role in EvaluacionConnectionRole.DATABASE_CONFIGURABLE_ROLES:
        database_name = role_config.database_name
    elif role_config.role in EvaluacionConnectionRole.LEGACY_MYSQL_ROLES:
        database_name = connection.db_name
    else:
        raise EvaluacionesConnectionRoleNotFoundError(
            f"Rol de Evaluaciones desconocido: {role_config.role!r}."
        )
    if not _valid_database_name(database_name):
        raise EvaluacionesDatabaseNameError(
            f"El nombre de base del rol {role_config.role!r} no es válido."
        )

    return EvaluacionesBackendContext(
        logical_role=role_config.role,
        backend_type=EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG,
        mysql_connection=connection,
        database_name=database_name,
    )


def get_evaluaciones_connection_status() -> EvaluacionesConnectionStatus:
    configured_roles = {
        item.role: item
        for item in EvaluacionConnectionRole.objects.select_related(
            "mysql_connection", "mysql_connection__empresa"
        ).filter(role__in=REQUIRED_CONNECTION_ROLES)
    }
    roles = []
    missing_roles = []
    invalid_roles = []

    for role, label in EvaluacionConnectionRole.ROLE_CHOICES:
        role_config = configured_roles.get(role)
        item: EvaluacionesRoleStatus = {
            "role": role,
            "label": label,
            "status": "missing",
            "source_type": None,
            "metadata": {},
        }
        if role_config is None:
            missing_roles.append(role)
        else:
            item["source_type"] = role_config.source_type
            if role_config.source_type == EvaluacionConnectionRole.SOURCE_DJANGO:
                alias = (role_config.django_alias or "").strip()
                metadata = {
                    entry["alias"]: entry for entry in get_system_database_catalog()
                }.get(alias)
                item["metadata"] = (
                    {"alias": alias, **metadata}
                    if metadata is not None
                    else {"alias": alias or None}
                )
            elif role_config.source_type == EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG:
                connection = role_config.mysql_connection
                if connection is not None:
                    item["metadata"] = {
                        "empresa": connection.empresa.codigo,
                        "nombre_logico": connection.nombre_logico,
                        "database_name": (
                            role_config.database_name
                            if role in EvaluacionConnectionRole.DATABASE_CONFIGURABLE_ROLES
                            else connection.db_name
                        ),
                        "is_active": connection.is_active,
                        "engine": SettingsMySQLConnection.normalize_engine(
                            connection.engine
                        ),
                    }
            try:
                _resolve_role_config(role_config)
            except EvaluacionesConnectionError:
                item["status"] = "invalid"
                invalid_roles.append(role)
            else:
                item["status"] = "configured"
        roles.append(item)

    return {
        "configured": not missing_roles and not invalid_roles,
        "roles": roles,
        "missing_roles": missing_roles,
        "invalid_roles": invalid_roles,
    }


def resolve_operational_backend(role: str) -> EvaluacionesBackendContext:
    if role not in REQUIRED_CONNECTION_ROLES:
        raise EvaluacionesConnectionRoleNotFoundError(
            f"Rol de Evaluaciones desconocido: {role!r}."
        )

    try:
        role_config = EvaluacionConnectionRole.objects.select_related(
            "mysql_connection", "mysql_connection__empresa"
        ).get(role=role)
    except EvaluacionConnectionRole.DoesNotExist as exc:
        raise EvaluacionesConnectionRoleNotFoundError(
            f"No existe configuración para el rol {role!r}."
        ) from exc

    return _resolve_role_config(role_config)


def get_evaluaciones_mysql_connection(role: str) -> SettingsMySQLConnection:
    context = resolve_operational_backend(role)
    if (
        context.backend_type != EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG
        or context.mysql_connection is None
    ):
        raise EvaluacionesConnectionSourceError(
            f"El rol {role!r} no utiliza una conexión MYSQL_CONFIG."
        )
    return context.mysql_connection


@contextmanager
def open_evaluaciones_connection(
    role: str,
) -> Generator[EvaluacionesConnection, None, None]:
    context = resolve_operational_backend(role)
    if context.backend_type == EvaluacionConnectionRole.SOURCE_DJANGO:
        if context.django_alias is None:
            raise EvaluacionesConnectionAliasUnavailableError(
                f"El rol {role!r} no tiene un alias Django válido."
            )
        yield cast(EvaluacionesConnection, connections[context.django_alias])
        return

    if context.mysql_connection is None or context.database_name is None:
        raise EvaluacionesConnectionSourceError(
            f"El rol {role!r} no tiene una conexión MySQL completa."
        )
    with open_mysql_connection(
        context.mysql_connection,
        database_name=context.database_name,
    ) as connection:
        yield cast(EvaluacionesConnection, connection)
