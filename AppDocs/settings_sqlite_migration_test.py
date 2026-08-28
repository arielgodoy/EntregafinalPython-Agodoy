"""Settings for applying a pending migration to a disposable SQLite copy."""

import os
from pathlib import Path

from .settings import *  # noqa: F403,F401


MIGRATION_TEST_DB = Path(
    os.getenv("DJANGO_SQLITE_MIGRATION_TEST_PATH", "")
).expanduser().resolve()
ORIGINAL_DB = (Path(BASE_DIR) / "db.sqlite3").resolve()

if not MIGRATION_TEST_DB.is_file():
    raise RuntimeError("DJANGO_SQLITE_MIGRATION_TEST_PATH must point to an existing copy")
if MIGRATION_TEST_DB == ORIGINAL_DB:
    raise RuntimeError("The migration test settings cannot use the original SQLite database")

DATABASES["default"] = {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": str(MIGRATION_TEST_DB),
}
SYSTEM_DATABASE_ALIASES = {"default"}
