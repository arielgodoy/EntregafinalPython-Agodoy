"""Central classification for configured Django database aliases."""

from enum import Enum

from django.conf import settings


class DatabaseClassification(str, Enum):
    SYSTEM = "SYSTEM"
    LEGACY = "LEGACY"
    UNKNOWN = "UNKNOWN"


SYSTEM_DATABASE_ALIASES = frozenset({"default"})
LEGACY_DATABASE_ALIASES = frozenset(
    {
        "dinamica",
        "eltit_gestion",
        "movimientos_cabeza_19",
    }
)
LEGACY_ALIAS_PREFIXES = (
    "maestro_check_",
    "movimientos_",
    "eltit_",
)


def get_database_classification(alias):
    """Return the conservative classification for a database alias."""
    if not isinstance(alias, str) or not alias:
        return DatabaseClassification.UNKNOWN
    configured_system_aliases = getattr(
        settings,
        "SYSTEM_DATABASE_ALIASES",
        SYSTEM_DATABASE_ALIASES,
    )
    if alias in configured_system_aliases:
        return DatabaseClassification.SYSTEM
    if alias in LEGACY_DATABASE_ALIASES or alias.startswith(LEGACY_ALIAS_PREFIXES):
        return DatabaseClassification.LEGACY
    return DatabaseClassification.UNKNOWN
