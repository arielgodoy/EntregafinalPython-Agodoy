from __future__ import annotations

from django.conf import settings
from django.db import connections

from common.database_classification import DatabaseClassification, get_database_classification

from ..models import GestionDTEConnectionRole


REQUIRED_CONNECTION_ROLES = tuple(role for role, _label in GestionDTEConnectionRole.ROLE_CHOICES)


class GestionDTEConnectionError(RuntimeError):
    """Base exception for invalid or unavailable Gestión DTE connections."""


class GestionDTERoleNotFoundError(GestionDTEConnectionError):
    pass


class GestionDTEAliasUnavailableError(GestionDTEConnectionError):
    pass


class GestionDTEConnectionInactiveError(GestionDTEConnectionError):
    pass


class GestionDTEConnectionSourceError(GestionDTEConnectionError):
    pass


def _database_vendor(alias: str, config: dict) -> str:
    try:
        return connections[alias].vendor
    except Exception:
        engine = str(config.get('ENGINE') or '')
        if 'sqlite' in engine:
            return 'sqlite'
        if 'mysql' in engine:
            return 'mysql'
        if 'postgresql' in engine:
            return 'postgresql'
        return engine.rsplit('.', 1)[-1] or 'unknown'


def get_system_database_catalog() -> tuple[dict[str, str], ...]:
    catalog = []
    for alias, config in getattr(settings, 'DATABASES', {}).items():
        if get_database_classification(alias) != DatabaseClassification.SYSTEM:
            continue
        catalog.append(
            {
                'alias': alias,
                'vendor': _database_vendor(alias, config),
                'classification': DatabaseClassification.SYSTEM.value,
            }
        )
    return tuple(catalog)


def get_active_mysql_connection_catalog():
    return (
        GestionDTEConnectionRole._meta.get_field('mysql_connection').remote_field.model.objects
        .filter(is_active=True)
        .select_related('empresa')
        .order_by('empresa__codigo', 'nombre_logico', 'pk')
    )


def get_gestiondte_connection_status() -> dict[str, object]:
    """Return the global role configuration status without opening connections."""
    system_catalog = {item['alias']: item for item in get_system_database_catalog()}
    configured_roles = {
        item.role: item
        for item in GestionDTEConnectionRole.objects.select_related(
            'mysql_connection', 'mysql_connection__empresa'
        ).filter(role__in=REQUIRED_CONNECTION_ROLES)
    }
    roles = []
    missing_roles = []
    invalid_roles = []

    for role, label in GestionDTEConnectionRole.ROLE_CHOICES:
        config = configured_roles.get(role)
        item = {
            'role': role,
            'label': label,
            'status': 'missing',
            'source_type': None,
            'metadata': {},
        }
        if config is None:
            missing_roles.append(role)
        elif config.source_type == 'DJANGO':
            alias = (config.django_alias or '').strip()
            metadata = system_catalog.get(alias)
            if not alias or metadata is None:
                item['status'] = 'invalid'
                item['source_type'] = 'DJANGO'
                item['metadata'] = {'alias': alias or None}
                invalid_roles.append(role)
            else:
                item['status'] = 'configured'
                item['source_type'] = 'DJANGO'
                item['metadata'] = {
                    'alias': metadata['alias'],
                    'vendor': metadata['vendor'],
                    'classification': metadata['classification'],
                }
        elif config.source_type == 'MYSQL_CONFIG':
            connection = config.mysql_connection
            database_name = config.database_name
            database_name_valid = (
                config.role not in GestionDTEConnectionRole.DATABASE_CONFIGURABLE_ROLES
                or bool(
                    database_name
                    and GestionDTEConnectionRole.DATABASE_NAME_PATTERN.fullmatch(database_name)
                )
            )
            if connection is None or not connection.is_active or not database_name_valid:
                item['status'] = 'invalid'
                item['source_type'] = 'MYSQL_CONFIG'
                invalid_roles.append(role)
            else:
                item['status'] = 'configured'
                item['source_type'] = 'MYSQL_CONFIG'
                item['metadata'] = {
                    'empresa': f'{connection.empresa.codigo} - {connection.empresa.descripcion or "Sin descripción"}',
                    'nombre_logico': connection.nombre_logico,
                    'database_name': config.database_name,
                    'is_active': connection.is_active,
                }
        else:
            item['status'] = 'invalid'
            item['source_type'] = config.source_type
            invalid_roles.append(role)
        roles.append(item)

    return {
        'configured': not missing_roles and not invalid_roles,
        'roles': roles,
        'missing_roles': missing_roles,
        'invalid_roles': invalid_roles,
    }


def get_gestiondte_connection(role: str) -> dict[str, object]:
    try:
        role_config = GestionDTEConnectionRole.objects.select_related(
            'mysql_connection', 'mysql_connection__empresa'
        ).get(role=role)
    except GestionDTEConnectionRole.DoesNotExist as exc:
        raise GestionDTERoleNotFoundError(
            f'No existe configuración para el rol {role!r}.'
        ) from exc

    if role_config.source_type == 'DJANGO':
        catalog = {item['alias']: item for item in get_system_database_catalog()}
        metadata = catalog.get(role_config.django_alias)
        if metadata is None:
            raise GestionDTEAliasUnavailableError(
                f'configured alias unavailable: {role_config.django_alias}'
            )
        return {
            'type': 'DJANGO',
            'alias': metadata['alias'],
            'vendor': metadata['vendor'],
            'classification': metadata['classification'],
        }

    connection = role_config.mysql_connection
    if connection is None or not connection.is_active:
        raise GestionDTEConnectionInactiveError(
            f'La conexión MySQL del rol {role!r} está inactiva o no existe.'
        )
    if (
        role in GestionDTEConnectionRole.DATABASE_CONFIGURABLE_ROLES
        and (
            not role_config.database_name
            or not GestionDTEConnectionRole.DATABASE_NAME_PATTERN.fullmatch(
                role_config.database_name
            )
        )
    ):
        raise GestionDTEConnectionSourceError(
            f'El rol {role!r} no tiene una base de datos válida configurada.'
        )
    return {
        'type': 'MYSQL_CONFIG',
        'connection_id': connection.pk,
        'empresa_id': connection.empresa_id,
        'empresa_codigo': connection.empresa.codigo,
        'nombre_logico': connection.nombre_logico,
        'engine': connection.engine,
        'database_name': role_config.database_name,
    }


def get_gestiondte_mysql_connection(role: str):
    role_config = GestionDTEConnectionRole.objects.select_related(
        'mysql_connection', 'mysql_connection__empresa'
    ).get(role=role)
    if role_config.source_type != 'MYSQL_CONFIG':
        raise GestionDTEConnectionSourceError(
            f'El rol {role!r} no utiliza una conexión MYSQL_CONFIG.'
        )
    connection = role_config.mysql_connection
    if connection is None or not connection.is_active:
        raise GestionDTEConnectionInactiveError(
            f'La conexión MySQL del rol {role!r} está inactiva o no existe.'
        )
    return connection