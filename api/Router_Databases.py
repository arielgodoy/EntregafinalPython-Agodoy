import logging

logger = logging.getLogger(__name__)  # Configura el logger para tu módulo

class MultiDatabaseRouter:
    def db_for_read(self, model, **hints):
        """Enrutamiento para leer datos."""
        if 'database' in hints:
            return hints['database']  # Usa la base de datos pasada en el hint
        return None

    def db_for_write(self, model, **hints):
        """Enrutamiento para escribir datos."""
        if 'database' in hints:
            return hints['database']
        return None

