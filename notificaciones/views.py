from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from chat.services.unread import get_unread_count
from access_control.models import Empresa, PerfilAcceso, UsuarioPerfilEmpresa
from notificaciones.models import Notification
from notificaciones.services import get_topbar_counts, get_topbar_notifications, mark_read, mark_all_read


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
    tipo_raw = (request.GET.get("type") or "ALL").upper()
    allowed_types = {"ALL", "MESSAGE", "ALERT", "SYSTEM"}
    if tipo_raw not in allowed_types:
        return JsonResponse({"error": "invalid type"}, status=400)

    try:
        page = int(request.GET.get("page", "1"))
    except (TypeError, ValueError):
        page = 1
    if page < 1:
        page = 1

    try:
        page_size = int(request.GET.get("page_size", "10"))
    except (TypeError, ValueError):
        page_size = 10
    if page_size < 1:
        page_size = 1
    if page_size > 50:
        page_size = 50

    items, has_next = get_topbar_notifications(
        request.user,
        empresa_id,
        tipo=tipo_raw,
        page=page,
        page_size=page_size,
    )
    counts = get_topbar_counts(request.user, empresa_id)
    unread_notification_messages = counts.get("unread_messages", 0)
    unread_alerts = counts.get("unread_alerts", 0)
    unread_system = counts.get("unread_system", 0)
    unread_total = counts.get("unread_all", 0)
    unread_messages = get_unread_count(request.user, empresa_id)

    data = {
        "unread_count_total": unread_total,
        "unread_messages": unread_messages,
        "unread_alerts": unread_alerts,
        "unread_system": unread_system,
        "unread_all": unread_total,
        "unread_notification_messages": unread_notification_messages,
        "page": page,
        "page_size": page_size,
        "has_next": has_next,
        "next_page": (page + 1) if has_next else None,
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


@login_required
def forzar_notificaciones(request):
    if not request.user.is_staff:
        return HttpResponseForbidden()

    empresa_id = request.session.get("empresa_id")
    if not empresa_id:
        return redirect("access_control:seleccionar_empresa")

    empresa = Empresa.objects.get(id=empresa_id)
    memberships = UsuarioPerfilEmpresa.objects.filter(empresa=empresa).select_related("usuario")
    destinatarios = [item.usuario for item in memberships]

    context = {
        "empresa": empresa,
        "destinatarios": destinatarios,
        "cantidad": 6,
        "destinatario_id": request.user.id,
        "force_membership": True,
        "error_key": "",
        "success_key": "",
    }

    if request.method == "GET":
        return render(request, "notificaciones/forzar_notificaciones.html", context)

    user_id = request.POST.get("destinatario_id")
    cantidad_raw = request.POST.get("cantidad", "6")
    force_membership = request.POST.get("force_membership") == "on"

    try:
        cantidad = int(cantidad_raw)
    except (TypeError, ValueError):
        cantidad = 6

    if cantidad < 1:
        cantidad = 1
    if cantidad > 50:
        cantidad = 50

    UserModel = get_user_model()
    destinatario = UserModel.objects.filter(id=user_id).first()
    if not destinatario:
        context.update({
            "cantidad": cantidad,
            "destinatario_id": request.user.id,
            "force_membership": force_membership,
            "error_key": "notifications.force.error.no_membership",
        })
        return render(request, "notificaciones/forzar_notificaciones.html", context)

    membership_qs = UsuarioPerfilEmpresa.objects.filter(usuario=destinatario, empresa=empresa)
    if not membership_qs.exists():
        if force_membership:
            perfil = PerfilAcceso.objects.order_by("id").first()
            if not perfil:
                context.update({
                    "cantidad": cantidad,
                    "destinatario_id": destinatario.id,
                    "force_membership": force_membership,
                    "error_key": "notifications.force.error.no_membership",
                })
                return render(request, "notificaciones/forzar_notificaciones.html", context)

            UsuarioPerfilEmpresa.objects.get_or_create(
                usuario=destinatario,
                empresa=empresa,
                defaults={
                    "perfil": perfil,
                    "asignado_por": request.user,
                },
            )
        else:
            context.update({
                "cantidad": cantidad,
                "destinatario_id": destinatario.id,
                "force_membership": force_membership,
                "error_key": "notifications.force.error.no_membership",
            })
            return render(request, "notificaciones/forzar_notificaciones.html", context)

    tipos = ["MESSAGE", "ALERT", "SYSTEM"]
    offset_map = {
        "MESSAGE": 0,
        "ALERT": 100,
        "SYSTEM": 200,
    }

    for tipo in tipos:
        for i in range(1, cantidad + 1):
            notification = Notification.objects.create(
                empresa=empresa,
                destinatario=destinatario,
                actor=request.user,
                tipo=tipo,
                titulo=f"[DEMO {tipo}] Notificacion {i}",
                cuerpo=f"Notificacion de prueba tipo {tipo} numero {i} para validar UI topbar.",
                url="/notificaciones/mis-notificaciones/",
                dedupe_key="",
                is_read=False,
            )
            created_at = timezone.now() - timedelta(minutes=(i + offset_map[tipo]))
            Notification.objects.filter(id=notification.id).update(created_at=created_at)

    messages.success(request, "ok", extra_tags="notifications.force.success")
    return redirect("notificaciones:forzar_notificaciones")
