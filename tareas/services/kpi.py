from collections import OrderedDict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa
from access_control.services.permissions import (
    get_valid_users_for_empresa,
    user_has_permission_for_empresa,
)

from ..models import (
    MiniTarea,
    Tarea,
    TareaParticipante,
)
from .dashboard_storage import DashboardTask, resolve_dashboard_storage


PUBLISHED_STATES = (
    Tarea.Estado.ACTIVA,
    Tarea.Estado.GESTION,
    Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
    Tarea.Estado.CERRADA,
)
OPEN_STATES = PUBLISHED_STATES[:-1]
PRIORITIES = (
    Tarea.Prioridad.CRITICA,
    Tarea.Prioridad.URGENTE,
    Tarea.Prioridad.NORMAL,
    Tarea.Prioridad.SIMPLE,
)
KPI_KEYS = (
    "por_estado",
    "atrasadas",
    "proximas_vencer",
    "sin_movimiento",
    "esperando_aprobacion",
    "carga_por_responsable",
    "cumplimiento",
    "tiempo_promedio_cierre_horas",
)


class DashboardPermissionError(PermissionError):
    pass


def _decimal_hours(duration):
    hours = Decimal(str(duration.total_seconds())) / Decimal("3600")
    return hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_kpis(*, tasks=None, queryset=None, reference_date=None, reference_now=None):
    """Calculate the eight T059 KPI from an already scoped task collection."""
    reference_date = reference_date or timezone.localdate()
    reference_now = reference_now or timezone.now()
    if tasks is None:
        tasks = tuple(_dashboard_task_from_model(task) for task in (queryset or ()))
    operational = tuple(task for task in tasks if not task.anulada)
    open_tasks = tuple(task for task in operational if task.estado in OPEN_STATES)

    by_state = OrderedDict(
        (state, sum(task.estado == state for task in operational))
        for state in PUBLISHED_STATES
    )
    overdue = sum(
        task.fecha_tope is not None
        and task.fecha_tope < reference_date
        and task.fecha_cumplimiento is None
        for task in open_tasks
    )
    due_soon = sum(
        task.fecha_tope is not None
        and reference_date <= task.fecha_tope <= reference_date + timedelta(days=7)
        and task.fecha_cumplimiento is None
        for task in open_tasks
    )

    movement_cutoff = reference_now - timedelta(days=7)
    from .movement_storage import resolve_movement_storage
    movement_storage = resolve_movement_storage()
    task_rows = [(task.pk, task.empresa_id) for task in open_tasks]
    movements = {}
    for empresa_id in {row[1] for row in task_rows}:
        empresa_task_ids = [
            row[0] for row in task_rows if row[1] == empresa_id
        ]
        movements.update({
            item.task_id: item
            for item in movement_storage.latest_movements(
                empresa_id=empresa_id, task_ids=empresa_task_ids,
            )
        })
    without_movement = 0
    for task_id, _empresa_id in task_rows:
        movement = movements.get(task_id)
        if movement is None:
            continue
        timestamps = [
            value
            for value in (
                movement.publication,
                movement.transition,
                movement.milestone,
                movement.document,
            )
            if value is not None
        ]
        if timestamps and max(timestamps) <= movement_cutoff:
            without_movement += 1

    load_counts = {}
    for task in open_tasks:
        if task.responsable_id is not None:
            key = (task.responsable_username, task.responsable_id)
            load_counts[key] = load_counts.get(key, 0) + 1
    load = [
        {
            "responsable_id": responsable_id,
            "username": username,
            "cantidad": cantidad,
        }
        for (username, responsable_id), cantidad in sorted(load_counts.items())
    ]

    total_published = len(operational)
    closed = by_state[Tarea.Estado.CERRADA]
    compliance = (
        (Decimal(closed) * Decimal("100") / Decimal(total_published))
        if total_published
        else Decimal("0.00")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    durations = [
        task.fecha_cumplimiento - task.fecha_publicacion
        for task in operational
        if task.estado == Tarea.Estado.CERRADA
        and task.fecha_publicacion is not None
        and task.fecha_cumplimiento is not None
    ]
    average_closing_time = (
        sum(
            (Decimal(str(duration.total_seconds())) for duration in durations),
            Decimal("0"),
        )
        / Decimal("3600")
        / Decimal(len(durations))
        if durations
        else Decimal("0.00")
    )
    average_closing_time = Decimal(str(average_closing_time)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return {
        "por_estado": by_state,
        "atrasadas": overdue,
        "proximas_vencer": due_soon,
        "sin_movimiento": without_movement,
        "esperando_aprobacion": sum(
            task.estado == Tarea.Estado.PENDIENTE_APROBACION_CIERRE
            for task in operational
        ),
        "carga_por_responsable": load,
        "cumplimiento": compliance,
        "tiempo_promedio_cierre_horas": average_closing_time,
    }


def get_personal_dashboard(*, user, empresa_id, reference_date=None):
    reference_date = reference_date or timezone.localdate()
    from .task_storage import resolve_list_storage

    task_storage = resolve_list_storage()
    tareas = list(
        task_storage.list_personal_tasks(empresa_id=empresa_id, user_id=user.pk)
    )
    task_ids = [tarea.pk for tarea in tareas]
    participant_roles = task_storage.personal_participant_roles(
        task_ids=task_ids, user_id=user.pk,
    )
    read_status = task_storage.personal_read_status(
        task_ids=task_ids, user_id=user.pk,
    )
    for tarea in tareas:
        if tarea.responsable_id == user.pk:
            tarea.assignment_type = "RESPONSABLE"
        else:
            tarea.assignment_type = participant_roles.get(
                tarea.pk, TareaParticipante.Rol.PARTICIPANTE
            )
        tarea.leido = read_status.get(tarea.pk, False)
        tarea.proxima_vencer = bool(
            tarea.fecha_tope
            and reference_date <= tarea.fecha_tope <= reference_date + timedelta(days=7)
            and tarea.fecha_cumplimiento is None
            and tarea.estado in OPEN_STATES
        )

    from .milestone_storage import resolve_milestone_storage
    hitos = resolve_milestone_storage().assigned(empresa_id=empresa_id, actor_id=user.pk)
    from tareas.services.minitask_storage import resolve_minitask_storage
    mini_tareas = resolve_minitask_storage().assigned(empresa_id=empresa_id, actor_id=user.pk)
    task_groups = {priority: [] for priority in PRIORITIES}
    milestone_groups = {priority: [] for priority in PRIORITIES}
    for tarea in tareas:
        task_groups[tarea.prioridad].append(tarea)
    for hito in hitos:
        milestone_groups[hito.tarea.prioridad].append(hito)

    return {
        "priority_groups": [
            {
                "value": priority,
                "label": Tarea.Prioridad(priority).label,
                "tareas": task_groups[priority],
                "hitos": milestone_groups[priority],
            }
            for priority in PRIORITIES
        ],
        "tareas": tareas,
        "hitos": hitos,
        "puede_ver_hitos": user_has_permission_for_empresa(
            user=user, empresa=empresa_id, vista_nombre="Tareas - Hitos", accion="ingresar",
        ),
        "puede_modificar_hitos": user_has_permission_for_empresa(
            user=user, empresa=empresa_id, vista_nombre="Tareas - Hitos", accion="modificar",
        ),
        "mini_tareas": mini_tareas,
        "mini_tareas_pendientes": [mini_tarea for mini_tarea in mini_tareas if not mini_tarea.hecho],
        "mini_tareas_hechas": [mini_tarea for mini_tarea in mini_tareas if mini_tarea.hecho],
        "read_status": read_status,
        "upcoming_tasks": [tarea for tarea in tareas if tarea.proxima_vencer],
        "filters": {"empresa_id": empresa_id, "reference_date": reference_date},
    }


def _authorized_companies(*, user):
    return Empresa.objects.filter(
        permiso__usuario=user,
        permiso__vista__nombre="Tareas",
        permiso__supervisor=True,
    ).distinct().order_by("codigo", "pk")


def _dashboard_tasks(*, empresa_id=None, empresa_ids=None, filters=None):
    storage_filters = dict(filters or {})
    if empresa_id is not None:
        storage_filters["empresa_id"] = empresa_id
    if empresa_ids is not None:
        storage_filters["empresa_ids"] = tuple(empresa_ids)
    return resolve_dashboard_storage().list_dashboard_tasks(filters=storage_filters)


def _dashboard_task_from_model(task):
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
        responsable_username=task.responsable.username if task.responsable_id else "",
        fecha_tope=task.fecha_tope,
        fecha_publicacion=task.fecha_publicacion,
        fecha_cumplimiento=task.fecha_cumplimiento,
        tipo_ambito=task.tipo_ambito,
        local_id=task.local_id,
        local_label=str(task.local) if task.local_id else "",
        departamento_id=task.departamento_id,
        departamento_label=str(task.departamento) if task.departamento_id else "",
    )


def _company_row(empresa, queryset):
    summary = get_kpis(tasks=queryset)
    return {
        "empresa_id": empresa.pk,
        "codigo": empresa.codigo,
        "empresa": str(empresa),
        "resumen": summary,
        "kpis": summary,
        "next_dimension": "empresa",
        "url_name": "tareas:dashboard_general_empresa",
        "url_kwargs": {"empresa_id": empresa.pk},
    }


def _task_row(tarea):
    return {
        "id": tarea.pk,
        "correlativo": tarea.correlativo,
        "titulo": tarea.titulo,
        "descripcion": tarea.descripcion,
        "estado": tarea.estado,
        "prioridad": tarea.prioridad,
        "responsable": tarea.responsable_username,
        "responsable_id": tarea.responsable_id,
        "fecha_tope": tarea.fecha_tope,
        "fecha_publicacion": tarea.fecha_publicacion,
        "tipo_ambito": tarea.tipo_ambito,
        "local": tarea.local_label,
        "departamento": tarea.departamento_label,
        "url_detalle": reverse("tareas:detalle_tarea", kwargs={"pk": tarea.pk}),
    }


def get_general_dashboard(*, user, filters=None):
    companies = list(_authorized_companies(user=user))
    company_ids = [empresa.pk for empresa in companies]
    tasks = _dashboard_tasks(empresa_ids=company_ids, filters=filters)
    return {
        "dimension_actual": "General",
        "filters": filters or {},
        "kpis": get_kpis(tasks=tasks),
        "rows": [
            _company_row(
                empresa,
                _dashboard_tasks(empresa_id=empresa.pk, filters=filters),
            )
            for empresa in companies
        ],
        "links": {"empresa": "tareas:dashboard_general_empresa"},
    }


def _require_supervisor(*, user, empresa_id):
    empresa = Empresa.objects.filter(pk=empresa_id).first()
    if empresa is None or not user_has_permission_for_empresa(
        user=user,
        empresa=empresa,
        vista_nombre="Tareas",
        accion="supervisor",
    ):
        raise DashboardPermissionError("Dashboard no autorizado para la Empresa.")
    return empresa


def get_company_dashboard(*, user, empresa_id, filters=None):
    empresa = _require_supervisor(user=user, empresa_id=empresa_id)
    tasks = _dashboard_tasks(empresa_id=empresa.pk, filters=filters)
    from organizacion.models import Departamento

    departamentos = Departamento.objects.filter(empresa=empresa).order_by("codigo", "pk")
    outside_tasks = [
        task for task in tasks
        if task.departamento_id is None
        and task.tipo_ambito in (Tarea.Ambito.LOCAL, None, "")
    ]
    return {
        "dimension_actual": "Empresa",
        "empresa": empresa,
        "filters": filters or {},
        "kpis": get_kpis(tasks=tasks),
        "rows": [
            {
                "departamento_id": departamento.pk,
                "departamento": str(departamento),
                "url_name": "tareas:dashboard_general_departamento",
                "url_kwargs": {
                    "empresa_id": empresa.pk,
                    "departamento_id": departamento.pk,
                },
            }
            for departamento in departamentos
        ],
        "outside_department_tasks": [_task_row(tarea) for tarea in outside_tasks],
        "links": {
            "departamento": "tareas:dashboard_general_departamento",
            "usuario": "tareas:dashboard_general_usuario",
        },
    }


def get_department_dashboard(*, user, empresa_id, departamento_id, filters=None):
    empresa = _require_supervisor(user=user, empresa_id=empresa_id)
    from organizacion.models import Departamento

    departamento = Departamento.objects.filter(
        pk=departamento_id,
        empresa_id=empresa.pk,
    ).first()
    if departamento is None:
        raise DashboardPermissionError("Departamento no pertenece a la Empresa.")
    local_filters = dict(filters or {}, departamento_id=departamento.pk)
    tasks = _dashboard_tasks(empresa_id=empresa.pk, filters=local_filters)
    responsible_rows = sorted(
        {
            (task.responsable_id, task.responsable_username)
            for task in tasks
            if task.tipo_ambito == Tarea.Ambito.DEPARTAMENTO
            and task.departamento_id == departamento.pk
            and task.responsable_id is not None
        },
        key=lambda row: (row[1], row[0]),
    )
    return {
        "dimension_actual": "Departamento",
        "empresa": empresa,
        "departamento": departamento,
        "filters": local_filters,
        "kpis": get_kpis(tasks=tasks),
        "rows": [
            {
                "usuario_id": responsable_id,
                "usuario": username,
                "url_name": "tareas:dashboard_general_usuario",
                "url_kwargs": {
                    "empresa_id": empresa.pk,
                    "usuario_id": responsable_id,
                },
            }
            for responsable_id, username in responsible_rows
        ],
        "links": {"usuario": "tareas:dashboard_general_usuario"},
    }


def get_user_dashboard(*, user, empresa_id, usuario_id, filters=None):
    empresa = _require_supervisor(user=user, empresa_id=empresa_id)
    target = get_valid_users_for_empresa(empresa, active_only=False).filter(
        pk=usuario_id
    ).first()
    if target is None:
        raise DashboardPermissionError("Usuario no pertenece a la Empresa.")
    local_filters = dict(filters or {}, usuario_id=target.pk)
    tasks = _dashboard_tasks(empresa_id=empresa.pk, filters=local_filters)
    return {
        "dimension_actual": "Usuario",
        "empresa": empresa,
        "usuario": target,
        "filters": local_filters,
        "kpis": get_kpis(tasks=tasks),
        "rows": [_task_row(tarea) for tarea in tasks],
        "links": {"tarea": "tareas:detalle_tarea"},
    }


def get_task_dashboard(*, user, empresa_id, tarea_id, filters=None):
    empresa = _require_supervisor(user=user, empresa_id=empresa_id)
    tasks = _dashboard_tasks(empresa_id=empresa.pk, filters=filters)
    tarea = next((task for task in tasks if task.pk == tarea_id), None)
    if tarea is None:
        raise DashboardPermissionError("Tarea no pertenece a la Empresa o no es operativa.")
    return {
        "dimension_actual": "Tarea",
        "empresa": empresa,
        "tarea": tarea,
        "filters": filters or {},
        "kpis": get_kpis(tasks=(tarea,)),
        "rows": [_task_row(tarea)],
        "links": {
            "detalle": reverse("tareas:detalle_tarea", kwargs={"pk": tarea.pk})
        },
    }