"""Operational reference data, separate from the frozen MySQL structure."""

import logging

from settings.services.mysql_connections import open_mysql_connection

from .connection_roles import get_tarea_connection, get_tarea_mysql_connection

logger = logging.getLogger(__name__)

BASE_DELAY_CAUSES = (
    ("IMPOSIBILIDAD_TECNICA", "Imposibilidad técnica"),
    ("ATRASO_IMPORTACION", "Atraso importación"),
    ("PERMISOS_MUNICIPALES", "Permisos municipales"),
    ("PROBLEMAS_ESCRITURAS", "Problemas de escrituras"),
    ("CAUSAS_INTERNAS", "Causas internas"),
    ("CAUSAS_EXTERNAS", "Causas externas"),
)


class BaseTareasReferenceDataError(RuntimeError):
    """Controlled failure; never includes connection or raw database errors."""


class BaseTareasCauseConflict(BaseTareasReferenceDataError):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Conflicto en la causa base {code}; no se modificó el catálogo.")


def ensure_mysql_delay_causes(connection) -> int:
    """Insert missing official causes in one transaction on the supplied connection."""
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT ENGINE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s",
            ("tareas_causaatraso",),
        )
        engine = cursor.fetchone()
        if not engine or str(engine[0]).upper() != "INNODB":
            raise BaseTareasReferenceDataError(
                "El catálogo de causas de BASE_TAREAS requiere una tabla InnoDB."
            )
        cursor.execute("START TRANSACTION")
        missing = []
        for code, name in BASE_DELAY_CAUSES:
            cursor.execute(
                "SELECT codigo, nombre FROM tareas_causaatraso "
                "WHERE codigo=%s OR nombre=%s FOR UPDATE",
                (code, name),
            )
            rows = cursor.fetchall()
            if any(tuple(row) != (code, name) for row in rows):
                logger.error("Base Tareas cause conflict: code=%s", code)
                raise BaseTareasCauseConflict(code)
            if not rows:
                missing.append((code, name))
        for code, name in missing:
            cursor.execute(
                "INSERT INTO tareas_causaatraso (codigo, nombre) VALUES (%s,%s)",
                (code, name),
            )
        connection.commit()
        return len(missing)
    except Exception as exc:
        connection.rollback()
        if isinstance(exc, BaseTareasReferenceDataError):
            raise
        logger.error("Base Tareas cause seed failed; transaction rolled back")
        raise BaseTareasReferenceDataError(
            "No se pudo preparar el catálogo base de causas de Tareas."
        ) from exc
    finally:
        cursor.close()


def ensure_base_tareas_reference_data() -> int:
    """Resolve BASE_TAREAS strictly; never creates or changes connection settings."""
    try:
        source = get_tarea_connection("BASE_TAREAS")
        if source["type"] != "MYSQL_CONFIG":
            raise BaseTareasReferenceDataError(
                "El seed operacional MySQL requiere BASE_TAREAS MYSQL_CONFIG."
            )
        with open_mysql_connection(
            get_tarea_mysql_connection("BASE_TAREAS"),
            database_name=source["database_name"],
        ) as connection:
            return ensure_mysql_delay_causes(connection)
    except BaseTareasReferenceDataError:
        raise
    except Exception as exc:
        logger.error("Could not resolve or open BASE_TAREAS for cause seed")
        raise BaseTareasReferenceDataError(
            "No se pudo resolver o abrir BASE_TAREAS para preparar sus causas."
        ) from exc
