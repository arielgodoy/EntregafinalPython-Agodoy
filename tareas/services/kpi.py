from collections import OrderedDict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.models import User
from django.db.models import Count, OuterRef, Q, Subquery
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa
from access_control.services.permissions import (
    get_valid_users_for_empresa,
    user_has_permission_for_empresa,
)

from ..models import (
    DocumentoHistorial,
    Hito,
    HitoHistorial,
    Tarea,
    TareaLectura,
    TareaParticipante,
    TareaTransicion,
)


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


def _operational_queryset(queryset):
    return queryset.filter(anulada=False, estado__in=PUBLISHED_STATES)


def _apply_task_filters(queryset, filters=None):
    filters = filters or {}
    if filters.get("empresa_id") is not None:
        queryset = queryset.filter(empresa_id=filters["empresa_id"])
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
    return queryset


def _decimal_hours(duration):
    hours = Decimal(str(duration.total_seconds())) / Decimal("3600")
    return hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _movement_queryset(queryset):
    transition_timestamp = TareaTransicion.objects.filter(
        tarea_id=OuterRef("pk")
    ).order_by("-timestamp").values("timestamp")[:1]
    hito_timestamp = HitoHistorial.objects.filter(
        hito__tarea_id=OuterRef("pk")
    ).order_by("-fecha").values("fecha")[:1]
    document_timestamp = DocumentoHistorial.objects.filter(
        documento__tarea_id=OuterRef("pk")
    ).order_by("-fecha").values("fecha")[:1]
    return queryset.annotate(
        ultimo_transicion=Subquery(transition_timestamp),
        ultimo_hito=Subquery(hito_timestamp),
        ultimo_documento=Subquery(document_timestamp),
    )


def get_kpis(*, queryset, reference_date=None, reference_now=None):
    """Calculate the eight T059 KPI from an already scoped task queryset."""
    reference_date = reference_date or timezone.localdate()
    reference_now = reference_now or timezone.now()
    operational = _operational_queryset(queryset)
    open_tasks = operational.filter(estado__in=OPEN_STATES)

    by_state = OrderedDict(
        (state, operational.filter(estado=state).count())
        for state in PUBLISHED_STATES
    )
    overdue = open_tasks.filter(
        fecha_tope__isnull=False,
        fecha_tope__lt=reference_date,
        fecha_cumplimiento__isnull=True,
    ).count()
    due_soon = open_tasks.filter(
        fecha_tope__isnull=False,
        fecha_tope__gte=reference_date,
        fecha_tope__lte=reference_date + timedelta(days=7),
        fecha_cumplimiento__isnull=True,
    ).count()

    movement_cutoff = reference_now - timedelta(days=7)
    stale_rows = _movement_queryset(open_tasks).values(
        "fecha_publicacion",
        "ultimo_transicion",
        "ultimo_hito",
        "ultimo_documento",
    )
    without_movement = 0
    for row in stale_rows:
        timestamps = [
            value
            for value in (
                row["fecha_publicacion"],
                row["ultimo_transicion"],
                row["ultimo_hito"],
                row["ultimo_documento"],
            )
            if value is not None
        ]
        if timestamps and max(timestamps) <= movement_cutoff:
            without_movement += 1

    load_rows = (
        open_tasks.filter(responsable_id__isnull=False)
        .values("responsable_id", "responsable__username")
        .annotate(cantidad=Count("pk"))
        .order_by("responsable__username", "responsable_id")
    )
    load = [
        {
            "responsable_id": row["responsable_id"],
            "username": row["responsable__username"],
            "cantidad": row["cantidad"],
        }
        for row in load_rows
    ]

    total_published = operational.count()
    closed = by_state[Tarea.Estado.CERRADA]
    compliance = (
        (Decimal(closed) * Decimal("100") / Decimal(total_published))
        if total_published
        else Decimal("0.00")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    closing_rows = operational.filter(
        estado=Tarea.Estado.CERRADA,
        fecha_publicacion__isnull=False,
        fecha_cumplimiento__isnull=False,
    ).values_list("fecha_publicacion", "fecha_cumplimiento")
    durations = [completed - published for published, completed in closing_rows]
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
        "esperando_aprobacion": operational.filter(
            estado=Tarea.Estado.PENDIENTE_APROBACION_CIERRE
        ).count(),
        "carga_por_responsable": load,
        "cumplimiento": compliance,
        "tiempo_promedio_cierre_horas": average_closing_time,
    }


def _personal_task_queryset(*, empresa_id, user):
    direct_ids = Tarea.objects.filter(
        empresa_id=empresa_id,
        responsable=user,
    ).values("pk")
    participant_ids = TareaParticipante.objects.filter(
        tarea__empresa_id=empresa_id,
        usuario=user,
    ).values("tarea_id")
    return _operational_queryset(
        Tarea.objects.filter(Q(pk__in=direct_ids) | Q(pk__in=participant_ids))
    ).select_related("empresa", "responsable", "creada_por").distinct()


def get_personal_dashboard(*, user, empresa_id, reference_date=None):
    reference_date = reference_date or timezone.localdate()
    tareas = list(
        _personal_task_queryset(empresa_id=empresa_id, user=user).order_by(
            "prioridad", "fecha_tope", "pk"
        )
    )
    participant_roles = dict(
        TareaParticipante.objects.filter(
            tarea_id__in=[tarea.pk for tarea in tareas],
            usuario=user,
        ).values_list("tarea_id", "rol")
    )
    read_status = dict(
        TareaLectura.objects.filter(
            tarea_id__in=[tarea.pk for tarea in tareas],
            usuario=user,
        ).values_list("tarea_id", "leido")
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

    hitos = list(
        Hito.objects.filter(
            tarea__empresa_id=empresa_id,
            tarea__estado__in=PUBLISHED_STATES,
            tarea__anulada=False,
            responsable=user,
            anulado=False,
        )
        .select_related("tarea", "tarea__empresa", "tarea__responsable", "responsable")
        .order_by("tarea__prioridad", "tarea__pk", "fecha_creacion", "pk")
    )
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


def _dashboard_queryset(*, empresa_id, filters=None):
    queryset = Tarea.objects.filter(empresa_id=empresa_id)
    return _apply_task_filters(queryset, filters)


def _company_row(empresa, queryset):
    return {
        "empresa_id": empresa.pk,
        "empresa": str(empresa),
        "kpis": get_kpis(queryset=queryset),
        "next_dimension": "empresa",
        "url_name": "tareas:dashboard_general_empresa",
        "url_kwargs": {"empresa_id": empresa.pk},
    }


def get_general_dashboard(*, user, filters=None):
    companies = list(_authorized_companies(user=user))
    queryset = _dashboard_queryset(
        empresa_id=None,
        filters=filters,
    ).filter(empresa_id__in=[empresa.pk for empresa in companies])
    return {
        "dimension_actual": "General",
        "filters": filters or {},
        "kpis": get_kpis(queryset=queryset),
        "rows": [
            _company_row(
                empresa,
                _dashboard_queryset(empresa_id=empresa.pk, filters=filters),
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
    queryset = _dashboard_queryset(empresa_id=empresa.pk, filters=filters)
    return {
        "dimension_actual": "Empresa",
        "empresa": empresa,
        "filters": filters or {},
        "kpis": get_kpis(queryset=queryset),
        "rows": [],
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
    queryset = _dashboard_queryset(empresa_id=empresa.pk, filters=local_filters)
    return {
        "dimension_actual": "Departamento",
        "empresa": empresa,
        "departamento": departamento,
        "filters": local_filters,
        "kpis": get_kpis(queryset=queryset),
        "rows": [],
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
    queryset = _dashboard_queryset(empresa_id=empresa.pk, filters=local_filters)
    return {
        "dimension_actual": "Usuario",
        "empresa": empresa,
        "usuario": target,
        "filters": local_filters,
        "kpis": get_kpis(queryset=queryset),
        "rows": [],
        "links": {"tarea": "tareas:detalle_tarea"},
    }


def get_task_dashboard(*, user, empresa_id, tarea_id, filters=None):
    empresa = _require_supervisor(user=user, empresa_id=empresa_id)
    queryset = _dashboard_queryset(empresa_id=empresa.pk, filters=filters)
    tarea = queryset.select_related(
        "empresa", "responsable", "departamento", "local"
    ).filter(pk=tarea_id).first()
    if tarea is None:
        raise DashboardPermissionError("Tarea no pertenece a la Empresa o no es operativa.")
    return {
        "dimension_actual": "Tarea",
        "empresa": empresa,
        "tarea": tarea,
        "filters": filters or {},
        "kpis": get_kpis(queryset=queryset.filter(pk=tarea.pk)),
        "rows": [],
        "links": {
            "detalle": reverse("tareas:detalle_tarea", kwargs={"pk": tarea.pk})
        },
    }