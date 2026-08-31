"""Declarative architectural classification for installed Django apps."""

DJANGO_APPS = (
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
)

THIRD_PARTY_APPS = (
    "ckeditor",
    "crispy_forms",
    "crispy_bootstrap5",
    "rest_framework",
    "channels",
)

CORE_SYSTEM_APPS = (
    "access_control",
    "acounts",
    "settings",
    "api",
    "auditoria",
    "database_manager",
)

SYSTEM_SUPPORT_APPS = (
    "dashboard",
    "chat",
    "core_search",
    "notificaciones",
)

SYSTEM_APPS = CORE_SYSTEM_APPS + SYSTEM_SUPPORT_APPS

APPLICATION_APPS = (
    "biblioteca",
    "gestiondte",
    "evaluaciones",
    "control_de_proyectos",
    "control_operacional",
)

PROJECT_APPS = SYSTEM_APPS + APPLICATION_APPS
