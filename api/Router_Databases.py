import logging

from common.database_classification import (
    DatabaseClassification,
    get_database_classification,
)

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

    def allow_relation(self, obj1, obj2, **hints):
        """Allow relations only when both objects use the same database."""
        db1 = hints.get('database') or obj1._state.db
        db2 = hints.get('database') or obj2._state.db
        if db1 and db2:
            return db1 == db2
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Block migrations on legacy and unknown database aliases."""
        classification = get_database_classification(db)
        if classification is not DatabaseClassification.SYSTEM:
            return False

        model = hints.get('model')
        if model is not None and not model._meta.managed:
            return False
        return True

