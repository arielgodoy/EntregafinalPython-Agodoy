from django.apps import AppConfig


class ControlDeProyectosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'control_de_proyectos'
    verbose_name = 'Control de Proyectos'    
    def ready(self):
        """Registrar signals cuando la app está lista"""
        import control_de_proyectos.signals  # noqa