from django.apps import AppConfig


class DatabaseManagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'database_manager'
    verbose_name = 'Gestión de Bases del Sistema'
