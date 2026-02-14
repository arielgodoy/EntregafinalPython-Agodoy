from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from chat.services.unread import get_unread_count
from access_control.models import Empresa, Permiso, Vista
from access_control.views import VerificarPermisoMixin
from access_control.services.access_requests import build_access_request_context
from notificaciones.models import Notification
from notificaciones.services import get_topbar_counts, get_topbar_notifications, mark_read, mark_all_read


def _get_empresa_id(request):
    return request.session.get("empresa_id")


def user_has_any_permission_in_company(user_id, empresa_id):
    """Verifica si el usuario tiene AL MENOS un Permiso en la empresa objetivo."""
    return Permiso.objects.filter(usuario_id=user_id, empresa_id=empresa_id).exists()


def ensure_user_minimal_permission_in_company(user_id, empresa_id, actor_user_id=None, vista_nombre="notificaciones.mis_notificaciones"):
    """Crea un Permiso mínimo si el usuario no tiene ninguno en la empresa objetivo."""
    if user_has_any_permission_in_company(user_id, empresa_id):
        return

    vista, _ = Vista.objects.get_or_create(
        nombre=vista_nombre,
        defaults={"descripcion": "Vista mínima de notificaciones"}
    )

    Permiso.objects.create(
        usuario_id=user_id,
        empresa_id=empresa_id,
        vista=vista,
        ingresar=True,
        crear=False,
        modificar=False,
        eliminar=False,
        autorizar=False,
        supervisor=False,
    )


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


def _require_notificaciones_ingresar(request):
    empresa_id = _get_empresa_id(request)
    vista_nombre = "Notificaciones"
    Vista.objects.get_or_create(
        nombre=vista_nombre,
        defaults={"descripcion": "Vista de notificaciones"},
    )
    if not empresa_id:
        contexto = build_access_request_context(
            request,
            vista_nombre,
            "No tienes permisos suficientes para acceder a esta página.",
        )
        return render(request, "access_control/403_forbidden.html", contexto, status=403)
    has_perm = Permiso.objects.filter(
        usuario=request.user,
        empresa_id=empresa_id,
        vista__nombre=vista_nombre,
        ingresar=True,
    ).exists()
    if not has_perm:
        contexto = build_access_request_context(
            request,
            vista_nombre,
            "No tienes permisos suficientes para acceder a esta página.",
        )
        return render(request, "access_control/403_forbidden.html", contexto, status=403)
    return None


@login_required
def topbar(request):
    permiso_response = _require_notificaciones_ingresar(request)
    if permiso_response:
        return permiso_response
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
    permiso_response = _require_notificaciones_ingresar(request)
    if permiso_response:
        return permiso_response
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
    permiso_response = _require_notificaciones_ingresar(request)
    if permiso_response:
        return permiso_response
    empresa_id = _get_empresa_id(request)
    count = mark_all_read(request.user, empresa_id)
    return JsonResponse({"success": True, "updated": count})


@login_required
def mis_notificaciones(request):
    permiso_response = _require_notificaciones_ingresar(request)
    if permiso_response:
        return permiso_response
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
    permiso_response = _require_notificaciones_ingresar(request)
    if permiso_response:
        return permiso_response
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


class CentroAlertasView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Centro de Alertas"
    permiso_requerido = "ingresar"

    def dispatch(self, request, *args, **kwargs):
        Vista.objects.get_or_create(
            nombre=self.vista_nombre,
            defaults={"descripcion": "Centro de Alertas"},
        )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
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

    # Determinar empresa_objetivo: primero desde form (GET/POST), luego desde session
    empresa_objetivo_id_raw = request.GET.get("empresa_objetivo_id") or request.POST.get("empresa_objetivo_id")
    
    if empresa_objetivo_id_raw:
        try:
            empresa_objetivo = Empresa.objects.get(id=int(empresa_objetivo_id_raw))
        except (Empresa.DoesNotExist, ValueError):
            empresa_objetivo = None
    else:
        # Fallback: empresa activa en session
        empresa_id_session = request.session.get("empresa_id")
        if empresa_id_session:
            try:
                empresa_objetivo = Empresa.objects.get(id=empresa_id_session)
            except Empresa.DoesNotExist:
                empresa_objetivo = None
        else:
            empresa_objetivo = None

    # Construccion destinatarios segun empresa_objetivo
    # CAMBIO: filtrar por Permiso (usuario + empresa + vista) en lugar de UsuarioPerfilEmpresa
    destinatarios = []
    if empresa_objetivo:
        from access_control.models import Permiso
        from django.contrib.auth.models import User
        
        # Obtener usuarios con AL MENOS un Permiso en la empresa objetivo
        destinatarios_qs = User.objects.filter(
            permiso__empresa_id=empresa_objetivo.id,
            is_active=True
        ).distinct().order_by("username")
        
        destinatarios = list(destinatarios_qs)
        
        # Fallback: si request.user es staff y no está en destinatarios, agregarlo
        if request.user.is_staff and request.user not in destinatarios:
            destinatarios.append(request.user)

    # Validaciones
    tiene_empresa_objetivo = empresa_objetivo is not None
    tiene_destinatarios = len(destinatarios) > 0
    
    warning_key = ""
    if not tiene_empresa_objetivo:
        warning_key = "notifications.force.warning.select_company"
    elif not tiene_destinatarios:
        warning_key = "notifications.force.warning.no_users"
    
    # destinatario_id default: si hay users, usar request.user si esta en la lista, sino el primero
    destinatario_id_default = None
    if tiene_destinatarios:
        user_ids = [u.id for u in destinatarios]
        if request.user.id in user_ids:
            destinatario_id_default = request.user.id
        else:
            destinatario_id_default = destinatarios[0].id

    # Contexto
    empresas = Empresa.objects.all().order_by("codigo")
    context = {
        "empresas": empresas,
        "empresa_objetivo": empresa_objetivo,
        "empresa_objetivo_id": empresa_objetivo.id if empresa_objetivo else "",
        "tiene_empresa_objetivo": tiene_empresa_objetivo,
        "destinatarios": destinatarios,
        "cantidad": 6,
        "destinatario_id": destinatario_id_default,
        "force_membership": True,
        "error_key": "",
        "success_key": "",
        "warning_key": warning_key,
        "tiene_destinatarios": tiene_destinatarios,
    }

    if request.method == "GET":
        return render(request, "notificaciones/forzar_notificaciones.html", context)

    # POST: validar que hay empresa_objetivo
    if not empresa_objetivo:
        context.update({
            "error_key": "notifications.force.error.no_empresa",
        })
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
    destinatario = UserModel.objects.filter(id=user_id, is_active=True).first()
    if not destinatario:
        context.update({
            "cantidad": cantidad,
            "destinatario_id": destinatario_id_default,
            "force_membership": force_membership,
            "error_key": "notifications.force.error.user_not_found",
        })
        return render(request, "notificaciones/forzar_notificaciones.html", context)

    # Si force_membership=True, asegurar que tenga al menos un Permiso minimo
    if force_membership:
        ensure_user_minimal_permission_in_company(
            user_id=destinatario.id,
            empresa_id=empresa_objetivo.id,
            actor_user_id=request.user.id
        )
    
    # Validar que el usuario tenga AL MENOS un Permiso en la empresa objetivo
    if not user_has_any_permission_in_company(destinatario.id, empresa_objetivo.id):
        context.update({
            "cantidad": cantidad,
            "destinatario_id": destinatario.id,
            "force_membership": force_membership,
            "error_key": "notifications.force.error.no_permissions_in_target_company",
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
                empresa=empresa_objetivo,
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


@login_required
def alerta_personalizada(request):
    if not request.user.is_staff:
        return HttpResponseForbidden()

    UserModel = get_user_model()
    empresas = Empresa.objects.all().order_by("codigo")

    def _get_empresa_objetivo_get():
        empresa_id_raw = request.GET.get("empresa")
        empresa_obj = None
        if empresa_id_raw:
            try:
                empresa_obj = Empresa.objects.get(id=int(empresa_id_raw))
            except (Empresa.DoesNotExist, ValueError):
                empresa_obj = None
        if not empresa_obj:
            empresa_id_session = request.session.get("empresa_id")
            if empresa_id_session:
                empresa_obj = Empresa.objects.filter(id=empresa_id_session).first()
        if not empresa_obj:
            empresa_obj = empresas.first() if empresas else None
        return empresa_obj

    def _build_destinatarios(empresa_objetivo):
        if not empresa_objetivo:
            return []
        destinatarios_qs = UserModel.objects.filter(
            permiso__empresa_id=empresa_objetivo.id,
            is_active=True,
        ).distinct().order_by("username")
        destinatarios_list = list(destinatarios_qs)
        if (
            request.user.is_staff
            and request.user not in destinatarios_list
            and user_has_any_permission_in_company(request.user.id, empresa_objetivo.id)
        ):
            destinatarios_list.append(request.user)
        return destinatarios_list

    if request.method == "GET":
        empresa_objetivo = _get_empresa_objetivo_get()
        destinatarios = _build_destinatarios(empresa_objetivo)
        context = {
            "empresas": empresas,
            "empresa_objetivo": empresa_objetivo,
            "empresa_objetivo_id": empresa_objetivo.id if empresa_objetivo else "",
            "destinatarios": destinatarios,
            "tiene_destinatarios": len(destinatarios) > 0,
            "destinatario_id": "",
            "tipo": "ALERT",
            "titulo": "",
            "cuerpo": "",
            "url": "",
            "force_membership": True,
            "error_key": "",
            "success_key": "",
        }
        return render(request, "notificaciones/alerta_personalizada.html", context)

    empresa_objetivo_id_raw = request.POST.get("empresa_objetivo_id")
    destinatario_id_raw = request.POST.get("destinatario_id")
    tipo = (request.POST.get("tipo") or "").strip().upper()
    titulo = (request.POST.get("titulo") or "").strip()
    cuerpo = (request.POST.get("cuerpo") or "").strip()
    url = (request.POST.get("url") or "").strip()
    force_membership = request.POST.get("force_membership") == "on"

    empresa_objetivo = None
    if empresa_objetivo_id_raw:
        try:
            empresa_objetivo = Empresa.objects.get(id=int(empresa_objetivo_id_raw))
        except (Empresa.DoesNotExist, ValueError):
            empresa_objetivo = None

    destinatario = None
    if destinatario_id_raw:
        destinatario = UserModel.objects.filter(id=destinatario_id_raw, is_active=True).first()

    valid_tipos = {"MESSAGE", "ALERT", "SYSTEM"}
    invalid_input = (
        not empresa_objetivo
        or not destinatario
        or tipo not in valid_tipos
        or not titulo
        or not cuerpo
    )

    destinatarios = _build_destinatarios(empresa_objetivo)
    context = {
        "empresas": empresas,
        "empresa_objetivo": empresa_objetivo,
        "empresa_objetivo_id": empresa_objetivo.id if empresa_objetivo else "",
        "destinatarios": destinatarios,
        "tiene_destinatarios": len(destinatarios) > 0,
        "destinatario_id": destinatario.id if destinatario else "",
        "tipo": tipo if tipo in valid_tipos else "ALERT",
        "titulo": titulo,
        "cuerpo": cuerpo,
        "url": url,
        "force_membership": force_membership,
        "error_key": "",
        "success_key": "",
    }

    if invalid_input:
        context["error_key"] = "notifications.custom.error.invalid"
        return render(request, "notificaciones/alerta_personalizada.html", context)

    if force_membership:
        ensure_user_minimal_permission_in_company(
            user_id=destinatario.id,
            empresa_id=empresa_objetivo.id,
            actor_user_id=request.user.id,
            vista_nombre="notificaciones.mis_notificaciones",
        )

    if not user_has_any_permission_in_company(destinatario.id, empresa_objetivo.id):
        context["error_key"] = "notifications.custom.error.no_permissions"
        return render(request, "notificaciones/alerta_personalizada.html", context)

    Notification.objects.create(
        empresa=empresa_objetivo,
        destinatario=destinatario,
        actor=request.user,
        tipo=tipo,
        titulo=titulo,
        cuerpo=cuerpo,
        url=url or "",
        is_read=False,
        dedupe_key="",
    )

    context.update({
        "tipo": "ALERT",
        "titulo": "",
        "cuerpo": "",
        "url": "",
        "force_membership": True,
        "error_key": "",
        "success_key": "notifications.custom.success",
    })
    return render(request, "notificaciones/alerta_personalizada.html", context)
