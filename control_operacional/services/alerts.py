from django.urls import reverse
from django.utils import timezone

from access_control.models import Permiso, Vista
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
