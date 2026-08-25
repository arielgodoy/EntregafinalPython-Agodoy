import os
from pathlib import Path

from .settings import *


class CloneDatabaseConfigurationError(RuntimeError):
    pass


_clone_db_value = os.getenv('DJANGO_CLONE_DB_PATH', '').strip()
_clone_archive_value = os.getenv('DJANGO_CLONE_ARCHIVE_ROOT', '').strip()
if not _clone_db_value or not _clone_archive_value:
    raise CloneDatabaseConfigurationError(
        'DJANGO_CLONE_DB_PATH y DJANGO_CLONE_ARCHIVE_ROOT son obligatorios.'
    )

_clone_db_path = Path(_clone_db_value).expanduser().resolve()
_original_db_path = (Path(BASE_DIR) / 'db.sqlite3').resolve()
if not _clone_db_path.is_file():
    raise CloneDatabaseConfigurationError(
        f'La base clonada no existe: {_clone_db_path}'
    )
if _clone_db_path == _original_db_path:
    raise CloneDatabaseConfigurationError(
        'La configuración del clon apunta a la base SQLite original.'
    )

DATABASES['default']['NAME'] = str(_clone_db_path)
AUDIT_ARCHIVE_ROOT = Path(_clone_archive_value).expanduser().resolve()
