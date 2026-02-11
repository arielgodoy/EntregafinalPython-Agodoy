from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse, Http404
from django.shortcuts import redirect, render

from chat.services.unread import get_unread_count
from notificaciones.models import Notification
from notificaciones.services import mark_read, mark_all_read


def _get_empresa_id(request):
    return request.session.get("empresa_id")


def _base_queryset(user, empresa_id):
    if empresa_id:
        return Notification.objects.filter(destinatario=user).filter(
            Q(empresa_id=empresa_id) | Q(empresa__isnull=True)
        )
    return Notification.objects.filter(destinatario=user)


def _base_queryset_scope(user, empresa_id, scope):
    if scope == "only_global":
        return Notification.objects.filter(destinatario=user, empresa__isnull=True)
    if scope == "only_active":
        if not empresa_id:
            return Notification.objects.none()
        return Notification.objects.filter(destinatario=user, empresa_id=empresa_id)
    return _base_queryset(user, empresa_id)


@login_required
def topbar(request):
    empresa_id = _get_empresa_id(request)
    qs = _base_queryset(request.user, empresa_id)

    items = list(qs.order_by("-created_at")[:10])
    unread_total = qs.filter(is_read=False).count()
    unread_messages = get_unread_count(request.user, empresa_id)
    unread_alerts = qs.filter(is_read=False, tipo=Notification.Tipo.ALERT).count()
    unread_system = qs.filter(is_read=False, tipo=Notification.Tipo.SYSTEM).count()
    unread_notification_messages = qs.filter(is_read=False, tipo=Notification.Tipo.MESSAGE).count()

    data = {
        "unread_count_total": unread_total,
        "unread_messages": unread_messages,
        "unread_alerts": unread_alerts,
        "unread_system": unread_system,
        "unread_all": unread_total,
        "unread_notification_messages": unread_notification_messages,
        "items": [
            {
                "id": item.id,
                "tipo": item.tipo,
                "titulo": item.titulo,
                "cuerpo": item.cuerpo,
                "url": item.url,
                "is_read": item.is_read,
                "created_at_iso": item.created_at.isoformat() if item.created_at else "",
            }
            for item in items
        ],
    }
    return JsonResponse(data)


@login_required
def mark_read_view(request, notification_id):
    empresa_id = _get_empresa_id(request)
    qs = _base_queryset(request.user, empresa_id)
    notification = qs.filter(id=notification_id).first()
    if not notification:
        raise Http404()
    if not mark_read(notification, request.user):
        raise Http404()
    return JsonResponse({"success": True})


@login_required
def mark_all_read_view(request):
    empresa_id = _get_empresa_id(request)
    count = mark_all_read(request.user, empresa_id)
    return JsonResponse({"success": True, "updated": count})


@login_required
def mis_notificaciones(request):
    empresa_id = _get_empresa_id(request)
    qs = _base_queryset(request.user, empresa_id)

    tipo = (request.GET.get("tipo") or "all").lower()
    estado = (request.GET.get("estado") or "all").lower()

    if tipo in ("message", "alert", "system"):
        qs = qs.filter(tipo=tipo.upper())

    if estado == "unread":
        qs = qs.filter(is_read=False)
    elif estado == "read":
        qs = qs.filter(is_read=True)

    qs = qs.order_by("-created_at")
    paginator = Paginator(qs, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "current_tipo": tipo,
        "current_estado": estado,
        "current_scope": "active",
        "show_scope": False,
    }
    return render(request, "notificaciones/mis_notificaciones.html", context)


@login_required
def ver_notificacion(request, pk):
    empresa_id = _get_empresa_id(request)
    qs = _base_queryset(request.user, empresa_id)
    notification = qs.filter(id=pk).first()
    if not notification:
        raise Http404()

    mark_read(notification, request.user)

    only_mark = request.GET.get("only_mark") == "1"
    if only_mark or not notification.url:
        return redirect("notificaciones:mis_notificaciones")
    return redirect(notification.url)


@login_required
def centro_alertas(request):
    empresa_id = _get_empresa_id(request)
    scope = (request.GET.get("scope") or "active").lower()
    if scope not in ("active", "only_active", "only_global"):
        scope = "active"

    qs = _base_queryset_scope(request.user, empresa_id, scope)

    tipo = (request.GET.get("tipo") or "alert").lower()
    estado = (request.GET.get("estado") or "all").lower()

    if tipo in ("message", "alert", "system"):
        qs = qs.filter(tipo=tipo.upper())
    elif tipo != "all":
        tipo = "alert"
        qs = qs.filter(tipo=Notification.Tipo.ALERT)

    if estado == "unread":
        qs = qs.filter(is_read=False)
    elif estado == "read":
        qs = qs.filter(is_read=True)

    qs = qs.order_by("-created_at")
    paginator = Paginator(qs, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "current_tipo": tipo,
        "current_estado": estado,
        "current_scope": scope,
        "show_scope": True,
    }
    return render(request, "notificaciones/mis_notificaciones.html", context)
