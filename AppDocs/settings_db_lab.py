"""Settings for the disposable modern database laboratory."""

import os

from .settings import *  # noqa: F403,F401


DB_LAB_NAME = os.getenv("DB_LAB_NAME", "").strip()
if not DB_LAB_NAME:
    raise RuntimeError("DB_LAB_NAME is required for the database laboratory")

DATABASES["DB_laboratorio"] = {
    "ENGINE": "django.db.backends.mysql",
    "NAME": DB_LAB_NAME,
    "USER": os.getenv("DB_LAB_USER", "").strip(),
    "PASSWORD": os.getenv("DB_LAB_PASSWORD", ""),
    "HOST": os.getenv("DB_LAB_HOST", "127.0.0.1").strip(),
    "PORT": os.getenv("DB_LAB_PORT", "3306").strip(),
    "OPTIONS": {
        "charset": "utf8mb4",
        "init_command": "SET SESSION sql_mode='STRICT_TRANS_TABLES'",
    },
    "CONN_MAX_AGE": 0,
    "CONN_HEALTH_CHECKS": False,
    "ATOMIC_REQUESTS": False,
}

SYSTEM_DATABASE_ALIASES = {"default", "DB_laboratorio"}
