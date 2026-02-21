from django.apps import AppConfig


class AccessControlConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'access_control'

    def ready(self):
        # Registrar señales opcionales (post_migrate seed)
        try:
            import access_control.signals  # noqa: F401
        except Exception:
            # No fallar el arranque si hay un problema; se puede revisar logs si es necesario
            pass
