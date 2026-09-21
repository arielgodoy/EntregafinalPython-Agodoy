from __future__ import annotations

from django.conf import settings
from django.db import connections

from common.database_classification import DatabaseClassification, get_database_classification

from ..models import GestionDTEConnectionRole


class GestionDTEConnectionError(RuntimeError):
    """Base exception for invalid or unavailable Gestión DTE connections."""


class GestionDTERoleNotFoundError(GestionDTEConnectionError):
    pass


class GestionDTEAliasUnavailableError(GestionDTEConnectionError):
    pass


class GestionDTEConnectionInactiveError(GestionDTEConnectionError):
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
    return {
        'type': 'MYSQL_CONFIG',
        'connection_id': connection.pk,
        'empresa_id': connection.empresa_id,
        'empresa_codigo': connection.empresa.codigo,
        'nombre_logico': connection.nombre_logico,
        'engine': connection.engine,
    }