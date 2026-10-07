"""Backend-neutral storage for the operational dashboard task population."""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.models import User

from organizacion.models import Departamento, Local

from ..models import Tarea
from .connection_roles import TareaConnectionError, resolve_operational_backend
from settings.services.mysql_connections import open_mysql_connection


PUBLISHED_STATES = (
    Tarea.Estado.ACTIVA,
    Tarea.Estado.GESTION,
    Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
    Tarea.Estado.CERRADA,
)


@dataclass(frozen=True)
class DashboardTask:
    id: int
    empresa_id: int
    correlativo: str
    titulo: str
    descripcion: str
    estado: str
    prioridad: str
    anulada: bool
    responsable_id: int | None
    responsable_username: str
    fecha_tope: object
    fecha_publicacion: object
    fecha_cumplimiento: object
    tipo_ambito: str | None
    local_id: int | None
    local_label: str
    departamento_id: int | None
    departamento_label: str

    @property
    def pk(self):
        return self.id


class DjangoDashboardStorage:
    def __init__(self, alias: str):
        self.alias = alias

    def list_dashboard_tasks(self, *, filters=None) -> tuple[DashboardTask, ...]:
        filters = filters or {}
        queryset = Tarea.objects.using(self.alias).filter(
            anulada=False, estado__in=PUBLISHED_STATES
        ).select_related(
            "responsable", "local", "departamento"
        )
        if filters.get("empresa_id") is not None:
            queryset = queryset.filter(empresa_id=filters["empresa_id"])
        if filters.get("empresa_ids") is not None:
            queryset = queryset.filter(empresa_id__in=filters["empresa_ids"])
        if filters.get("departamento_id") is not None:
            queryset = queryset.filter(
                tipo_ambito=Tarea.Ambito.DEPARTAMENTO,
                departamento_id=filters["departamento_id"],
            )
        if filters.get("usuario_id") is not None:
            queryset = queryset.filter(responsable_id=filters["usuario_id"])
        if filters.get("estado") in PUBLISHED_STATES:
            queryset = queryset.filter(estado=filters["estado"])
        if filters.get("prioridad") in Tarea.Prioridad.values:
            queryset = queryset.filter(prioridad=filters["prioridad"])
        return tuple(_dashboard_task(task) for task in queryset)


def _dashboard_task(task) -> DashboardTask:
    return DashboardTask(
        id=task.pk,
        empresa_id=task.empresa_id,
        correlativo=task.correlativo,
        titulo=task.titulo,
        descripcion=task.descripcion,
        estado=task.estado,
        prioridad=task.prioridad,
        anulada=bool(task.anulada),
        responsable_id=task.responsable_id,
        responsable_username=task.responsable.username if task.responsable else "",
        fecha_tope=task.fecha_tope,
        fecha_publicacion=task.fecha_publicacion,
        fecha_cumplimiento=task.fecha_cumplimiento,
        tipo_ambito=task.tipo_ambito,
        local_id=task.local_id,
        local_label=str(task.local) if task.local_id else "",
        departamento_id=task.departamento_id,
        departamento_label=str(task.departamento) if task.departamento_id else "",
    )


class MySQLDashboardStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    def list_dashboard_tasks(self, *, filters=None) -> tuple[DashboardTask, ...]:
        filters = filters or {}
        where = []
        params: list[object] = []
        if filters.get("empresa_id") is not None:
            where.append("t.empresa_id = %s")
            params.append(filters["empresa_id"])
        if filters.get("empresa_ids") is not None:
            company_ids = tuple(filters["empresa_ids"])
            if not company_ids:
                return ()
            where.append("t.empresa_id IN (" + ",".join(["%s"] * len(company_ids)) + ")")
            params.extend(company_ids)
        if filters.get("departamento_id") is not None:
            where.extend(["t.tipo_ambito = %s", "t.departamento_id = %s"])
            params.extend([Tarea.Ambito.DEPARTAMENTO, filters["departamento_id"]])
        if filters.get("usuario_id") is not None:
            where.append("t.responsable_id = %s")
            params.append(filters["usuario_id"])
        if filters.get("estado") in PUBLISHED_STATES:
            where.append("t.estado = %s")
            params.append(filters["estado"])
        if filters.get("prioridad") in Tarea.Prioridad.values:
            where.append("t.prioridad = %s")
            params.append(filters["prioridad"])
        query = (
            "SELECT t.id,t.empresa_id,t.correlativo,t.titulo,t.descripcion,"
            "t.estado,t.prioridad,t.anulada,t.responsable_id,t.fecha_tope,"
            "t.fecha_publicacion,t.fecha_cumplimiento,t.tipo_ambito,t.local_id,"
            "t.departamento_id FROM tareas_tarea t WHERE t.anulada = %s "
            "AND t.estado IN (%s,%s,%s,%s)"
        )
        params = [False, *PUBLISHED_STATES, *params]
        if where:
            query += " AND " + " AND ".join(where)
        query += " ORDER BY t.id"
        with open_mysql_connection(
            self.connection_config,
            database_name=self.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
            finally:
                cursor.close()
        return _mysql_dashboard_tasks(rows)


def _mysql_dashboard_tasks(rows) -> tuple[DashboardTask, ...]:
    user_ids = {row[8] for row in rows if row[8] is not None}
    local_ids = {row[13] for row in rows if row[13] is not None}
    department_ids = {row[14] for row in rows if row[14] is not None}
    users = {
        user.pk: user.username
        for user in User.objects.using("default").filter(pk__in=user_ids)
    }
    locals_by_id = {
        item.pk: str(item)
        for item in Local.objects.using("default").filter(pk__in=local_ids)
    }
    departments_by_id = {
        item.pk: str(item)
        for item in Departamento.objects.using("default").filter(pk__in=department_ids)
    }
    return tuple(
        DashboardTask(
            id=row[0],
            empresa_id=row[1],
            correlativo=row[2],
            titulo=row[3],
            descripcion=row[4],
            estado=row[5],
            prioridad=row[6],
            anulada=bool(row[7]),
            responsable_id=row[8],
            responsable_username=users.get(row[8], ""),
            fecha_tope=row[9],
            fecha_publicacion=row[10],
            fecha_cumplimiento=row[11],
            tipo_ambito=row[12],
            local_id=row[13],
            local_label=locals_by_id.get(row[13], ""),
            departamento_id=row[14],
            departamento_label=departments_by_id.get(row[14], ""),
        )
        for row in rows
    )


def resolve_dashboard_storage() -> DjangoDashboardStorage | MySQLDashboardStorage:
    try:
        context = resolve_operational_backend("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise RuntimeError("No se pudo resolver BASE_TAREAS para el dashboard.") from exc
    if context.backend_type == "DJANGO":
        return DjangoDashboardStorage(context.django_alias)
    if context.backend_type == "MYSQL_CONFIG":
        return MySQLDashboardStorage(context.mysql_connection, context.database_name)
    raise RuntimeError("El backend de BASE_TAREAS no es válido para el dashboard.")
