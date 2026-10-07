from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.db import connections

from common.database_classification import DatabaseClassification, get_database_classification

from ..models import TareaConnectionRole
from settings.models import SettingsMySQLConnection


REQUIRED_CONNECTION_ROLES = tuple(role for role, _label in TareaConnectionRole.ROLE_CHOICES)
TASKS_CONNECTIONS_COMPANY_CODE = "00"


class TareaConnectionError(RuntimeError):
    """Base exception for invalid or unavailable Tareas connections."""


class TareaConnectionRoleNotFoundError(TareaConnectionError):
    pass


class TareaConnectionAliasUnavailableError(TareaConnectionError):
    pass


class TareaConnectionInactiveError(TareaConnectionError):
    pass


class TareaConnectionSourceError(TareaConnectionError):
    pass


@dataclass(frozen=True)
class BackendContext:
    logical_role: str
    backend_type: str
    django_alias: str | None = None
    mysql_connection: SettingsMySQLConnection | None = None
    database_name: str | None = None
    vendor: str | None = None

    def as_legacy_mapping(self) -> dict[str, object]:
        if self.backend_type == "DJANGO":
            return {
                "type": self.backend_type,
                "alias": self.django_alias,
                "vendor": self.vendor,
                "classification": DatabaseClassification.SYSTEM.value,
            }
        connection = self.mysql_connection
        return {
            "type": self.backend_type,
            "connection_id": connection.pk if connection is not None else None,
            "empresa_id": connection.empresa_id if connection is not None else None,
            "empresa_codigo": connection.empresa.codigo if connection is not None else None,
            "nombre_logico": connection.nombre_logico if connection is not None else None,
            "engine": connection.engine if connection is not None else None,
            "database_name": self.database_name,
        }


def _database_vendor(alias: str, config: dict) -> str:
    try:
        return connections[alias].vendor
    except Exception:
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
                "vendor": _database_vendor(alias, config),
                "classification": DatabaseClassification.SYSTEM.value,
            }
        )
    return tuple(catalog)


def get_active_mysql_connection_catalog():
    return (
        SettingsMySQLConnection.objects.filter(
            empresa__codigo=TASKS_CONNECTIONS_COMPANY_CODE,
            is_active=True,
        )
        .select_related("empresa")
        .order_by("empresa__codigo", "nombre_logico", "pk")
    )


def is_allowed_mysql_connection(connection: SettingsMySQLConnection | None) -> bool:
    return bool(
        connection is not None
        and connection.is_active
        and connection.empresa.codigo == TASKS_CONNECTIONS_COMPANY_CODE
    )


def _valid_database_name(database_name: str | None) -> bool:
    return bool(
        database_name
        and TareaConnectionRole.DATABASE_NAME_PATTERN.fullmatch(database_name)
    )


def get_tarea_connection_status() -> dict[str, object]:
    system_catalog = {item["alias"]: item for item in get_system_database_catalog()}
    configured_roles = {
        item.role: item
        for item in TareaConnectionRole.objects.select_related(
            "mysql_connection", "mysql_connection__empresa"
        ).filter(role__in=REQUIRED_CONNECTION_ROLES)
    }
    roles = []
    missing_roles = []
    invalid_roles = []

    for role, label in TareaConnectionRole.ROLE_CHOICES:
        config = configured_roles.get(role)
        item = {
            "role": role,
            "label": label,
            "status": "missing",
            "source_type": None,
            "metadata": {},
        }
        if config is None:
            missing_roles.append(role)
        elif config.source_type == "DJANGO":
            alias = (config.django_alias or "").strip()
            metadata = system_catalog.get(alias)
            if not alias or metadata is None:
                item["status"] = "invalid"
                item["source_type"] = "DJANGO"
                item["metadata"] = {"alias": alias or None}
                invalid_roles.append(role)
            else:
                item["status"] = "configured"
                item["source_type"] = "DJANGO"
                item["metadata"] = metadata
        elif config.source_type == "MYSQL_CONFIG":
            connection = config.mysql_connection
            database_name = (
                config.database_name
                if role in TareaConnectionRole.DATABASE_CONFIGURABLE_ROLES
                else connection.db_name if connection else None
            )
            if (
                not is_allowed_mysql_connection(connection)
                or not _valid_database_name(database_name)
            ):
                item["status"] = "invalid"
                item["source_type"] = "MYSQL_CONFIG"
                invalid_roles.append(role)
            else:
                item["status"] = "configured"
                item["source_type"] = "MYSQL_CONFIG"
                item["metadata"] = {
                    "empresa": f"{connection.empresa.codigo} - "
                    f"{connection.empresa.descripcion or 'Sin descripción'}",
                    "nombre_logico": connection.nombre_logico,
                    "database_name": database_name,
                    "is_active": connection.is_active,
                }
        else:
            item["status"] = "invalid"
            item["source_type"] = config.source_type
            invalid_roles.append(role)
        roles.append(item)

    return {
        "configured": not missing_roles and not invalid_roles,
        "roles": roles,
        "missing_roles": missing_roles,
        "invalid_roles": invalid_roles,
    }


def resolve_operational_backend(role: str) -> BackendContext:
    if role not in REQUIRED_CONNECTION_ROLES:
        raise TareaConnectionRoleNotFoundError(f"Rol de Tareas desconocido: {role!r}.")

    try:
        role_config = TareaConnectionRole.objects.select_related(
            "mysql_connection", "mysql_connection__empresa"
        ).get(role=role)
    except TareaConnectionRole.DoesNotExist as exc:
        raise TareaConnectionRoleNotFoundError(
            f"No existe configuración para el rol {role!r}."
        ) from exc

    if role_config.source_type == "DJANGO":
        if role in TareaConnectionRole.LEGACY_MYSQL_ROLES:
            raise TareaConnectionSourceError(
                f"El rol {role!r} requiere una conexión MYSQL_CONFIG."
            )
        catalog = {item["alias"]: item for item in get_system_database_catalog()}
        metadata = catalog.get(role_config.django_alias)
        if metadata is None:
            raise TareaConnectionAliasUnavailableError(
                f"El alias Django del rol {role!r} no está disponible como SYSTEM."
            )
        return BackendContext(
            logical_role=role,
            backend_type="DJANGO",
            django_alias=metadata["alias"],
            vendor=metadata["vendor"],
        )

    if role_config.source_type != "MYSQL_CONFIG":
        raise TareaConnectionSourceError(
            f"Tipo de conexión inválido para el rol {role!r}."
        )

    connection = role_config.mysql_connection
    if connection is None or not connection.is_active:
        raise TareaConnectionInactiveError(
            f"La conexión MySQL del rol {role!r} está inactiva o no existe."
        )
    if connection.empresa.codigo != TASKS_CONNECTIONS_COMPANY_CODE:
        raise TareaConnectionSourceError(
            f"La conexión MySQL del rol {role!r} no pertenece al catálogo Empresa 00."
        )
    database_name = (
        role_config.database_name
        if role in TareaConnectionRole.DATABASE_CONFIGURABLE_ROLES
        else connection.db_name
    )
    if not _valid_database_name(database_name):
        raise TareaConnectionSourceError(
            f"El rol {role!r} no tiene una base de datos válida configurada."
        )
    return BackendContext(
        logical_role=role,
        backend_type="MYSQL_CONFIG",
        mysql_connection=connection,
        database_name=database_name,
    )


def get_tarea_connection(role: str) -> dict[str, object]:
    return resolve_operational_backend(role).as_legacy_mapping()


def get_tarea_mysql_connection(role: str) -> SettingsMySQLConnection:
    context = resolve_operational_backend(role)
    if context.backend_type != "MYSQL_CONFIG" or context.mysql_connection is None:
        raise TareaConnectionSourceError(
            f"El rol {role!r} no utiliza una conexión MYSQL_CONFIG."
        )
    return context.mysql_connection
