"""Backend-neutral latest movement reads for Tareas KPI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone as datetime_timezone

from django.db.models import Max, OuterRef, Subquery
from django.utils import timezone

from ..models import DocumentoHistorial, HitoHistorial, Tarea, TareaTransicion
from .connection_roles import resolve_operational_backend
from .task_storage import TaskStorageError
from settings.services.mysql_connections import open_mysql_connection


@dataclass(frozen=True)
class TaskMovement:
    task_id: int
    publication: object
    transition: object
    milestone: object
    document: object


class DjangoMovementStorage:
    def __init__(self, alias: str):
        self.alias = alias

    def latest_movements(self, *, empresa_id: int, task_ids):
        task_ids = tuple(task_ids)
        if not task_ids:
            return ()
        transition = TareaTransicion.objects.using(self.alias).filter(
            tarea_id=OuterRef("pk")
        ).order_by("-timestamp").values("timestamp")[:1]
        milestone = HitoHistorial.objects.using(self.alias).filter(
            hito__tarea_id=OuterRef("pk")
        ).order_by("-fecha").values("fecha")[:1]
        document = DocumentoHistorial.objects.using(self.alias).filter(
            documento__tarea_id=OuterRef("pk")
        ).order_by("-fecha").values("fecha")[:1]
        rows = Tarea.objects.using(self.alias).filter(
            pk__in=task_ids, empresa_id=empresa_id,
        ).annotate(
            latest_transition=Subquery(transition),
            latest_milestone=Subquery(milestone),
            latest_document=Subquery(document),
        ).values(
            "pk", "fecha_publicacion", "latest_transition",
            "latest_milestone", "latest_document",
        )
        return tuple(
            TaskMovement(
                task_id=row["pk"],
                publication=row["fecha_publicacion"],
                transition=row["latest_transition"],
                milestone=row["latest_milestone"],
                document=row["latest_document"],
            )
            for row in rows
        )


class MySQLMovementStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    def latest_movements(self, *, empresa_id: int, task_ids):
        task_ids = tuple(task_ids)
        if not task_ids:
            return ()
        placeholders = ", ".join("%s" for _ in task_ids)
        sql = (
            "SELECT t.id, t.fecha_publicacion, MAX(tr.timestamp), "
            "MAX(hh.fecha), MAX(dh.fecha) "
            "FROM tareas_tarea t "
            "LEFT JOIN tareas_tareatransicion tr ON tr.tarea_id=t.id "
            "LEFT JOIN tareas_hito h ON h.tarea_id=t.id "
            "LEFT JOIN tareas_hitohistorial hh ON hh.hito_id=h.id "
            "LEFT JOIN tareas_documentotarea d ON d.tarea_id=t.id "
            "LEFT JOIN tareas_documentohistorial dh ON dh.documento_id=d.id "
            f"WHERE t.empresa_id=%s AND t.id IN ({placeholders}) "
            "GROUP BY t.id, t.fecha_publicacion"
        )
        with open_mysql_connection(
            self.connection_config, database_name=self.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(sql, (empresa_id, *task_ids))
                rows = cursor.fetchall()
            finally:
                cursor.close()
        return tuple(
            TaskMovement(
                task_id=row[0],
                publication=_aware(row[1]),
                transition=_aware(row[2]),
                milestone=_aware(row[3]),
                document=_aware(row[4]),
            )
            for row in rows
        )


def _aware(value):
    if value is not None and timezone.is_naive(value):
        return timezone.make_aware(value, datetime_timezone.utc)
    return value


def resolve_movement_storage():
    context = resolve_operational_backend("BASE_TAREAS")
    if context.backend_type == "DJANGO":
        return DjangoMovementStorage(context.django_alias)
    if context.backend_type == "MYSQL_CONFIG":
        return MySQLMovementStorage(context.mysql_connection, context.database_name)
    raise TaskStorageError("El backend de BASE_TAREAS no es válido.")
