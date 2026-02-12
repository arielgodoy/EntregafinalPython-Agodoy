from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from access_control.models import Permiso, Vista
from control_de_proyectos.models import Proyecto
from notificaciones.models import Notification
from notificaciones.services import create_notification


def _get_recipients(empresa_id):
    vista = Vista.objects.filter(nombre="Control Operacional Dashboard").first()
    if not vista:
        return []
    permisos = Permiso.objects.filter(
        empresa_id=empresa_id,
        vista=vista,
        ingresar=True,
    ).select_related("usuario")
    return [permiso.usuario for permiso in permisos]


def notify_project_created(proyecto, actor):
    empresa = proyecto.empresa_interna
    recipients = _get_recipients(empresa.id)
    if not recipients:
        return 0

    url = reverse("control_de_proyectos:detalle_proyecto", kwargs={"pk": proyecto.id})
    created = 0
    for user in recipients:
        create_notification(
            destinatario=user,
            empresa=empresa,
            tipo=Notification.Tipo.ALERT,
            titulo="Proyecto creado",
            cuerpo=proyecto.nombre,
            url=url,
            actor=actor,
            dedupe_key="",
        )
        created += 1
    return created


def notify_project_overdue(proyecto, actor):
    empresa = proyecto.empresa_interna
    if not proyecto.fecha_termino_estimada or proyecto.fecha_termino_real:
        return 0

    if proyecto.fecha_termino_estimada >= timezone.localdate():
        return 0

    recipients = _get_recipients(empresa.id)
    if not recipients:
        return 0

    url = reverse("control_de_proyectos:detalle_proyecto", kwargs={"pk": proyecto.id})
    dedupe_key = f"project:{proyecto.id}:overdue"
    created = 0

    for user in recipients:
        exists = Notification.objects.filter(
            destinatario=user,
            empresa=empresa,
            dedupe_key=dedupe_key,
        ).exists()
        if exists:
            continue
        create_notification(
            destinatario=user,
            empresa=empresa,
            tipo=Notification.Tipo.ALERT,
            titulo="Proyecto atrasado",
            cuerpo=proyecto.nombre,
            url=url,
            actor=actor,
            dedupe_key=dedupe_key,
        )
        created += 1

    return created


def build_operational_alerts(empresa_id):
    today = timezone.localdate()
    proyectos = Proyecto.objects.filter(empresa_interna_id=empresa_id).only(
        'id',
        'nombre',
        'fecha_inicio_estimada',
        'fecha_termino_estimada',
        'fecha_termino_real',
    )

    alertas = []
    for proyecto in proyectos:
        fecha_inicio = proyecto.fecha_inicio_estimada
        fecha_termino = proyecto.fecha_termino_estimada
        fecha_real = proyecto.fecha_termino_real

        overdue = bool(fecha_termino and fecha_real is None and fecha_termino < today)
        risk = bool(
            fecha_termino
            and fecha_real is None
            and not overdue
            and today > (fecha_termino - timedelta(days=7))
        )

        if overdue:
            alertas.append({
                'key': f"project:{proyecto.id}:overdue",
                'proyecto_id': proyecto.id,
                'proyecto_nombre': proyecto.nombre,
                'severity': 'HIGH',
                'severity_key': 'control_operacional.alerts.severity.high',
                'severity_label': 'Alta',
                'title': 'Proyecto atrasado',
                'title_key': 'control_operacional.alerts.overdue.title',
                'description': 'Fecha de termino estimada vencida',
                'description_key': 'control_operacional.alerts.overdue.description',
                'url': reverse('control_de_proyectos:detalle_proyecto', kwargs={'pk': proyecto.id}),
                'created_at': fecha_termino or today,
            })
        elif risk:
            alertas.append({
                'key': f"project:{proyecto.id}:risk",
                'proyecto_id': proyecto.id,
                'proyecto_nombre': proyecto.nombre,
                'severity': 'MEDIUM',
                'severity_key': 'control_operacional.alerts.severity.medium',
                'severity_label': 'Media',
                'title': 'Proyecto en riesgo',
                'title_key': 'control_operacional.alerts.risk.title',
                'description': 'Fecha de termino estimada en los proximos 7 dias',
                'description_key': 'control_operacional.alerts.risk.description',
                'url': reverse('control_de_proyectos:detalle_proyecto', kwargs={'pk': proyecto.id}),
                'created_at': fecha_termino or today,
            })

        if fecha_inicio is None or fecha_termino is None:
            alertas.append({
                'key': f"project:{proyecto.id}:missing_dates",
                'proyecto_id': proyecto.id,
                'proyecto_nombre': proyecto.nombre,
                'severity': 'LOW',
                'severity_key': 'control_operacional.alerts.severity.low',
                'severity_label': 'Baja',
                'title': 'Proyecto sin fechas',
                'title_key': 'control_operacional.alerts.missing_dates.title',
                'description': 'Completar fechas estimadas del proyecto',
                'description_key': 'control_operacional.alerts.missing_dates.description',
                'url': reverse('control_de_proyectos:detalle_proyecto', kwargs={'pk': proyecto.id}),
                'created_at': today,
            })

    return alertas
