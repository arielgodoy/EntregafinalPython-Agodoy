from django.views.generic import ListView, DetailView
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from access_control.views import VerificarPermisoMixin
from auditoria.models import AuditoriaBibliotecaEvent
from auditoria.services import AuditoriaService
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from datetime import datetime, time, timedelta
import logging
logger = logging.getLogger(__name__)
from access_control.models import Vista, Permiso

class AuditoriaBibliotecaListView(VerificarPermisoMixin, ListView):
    model = AuditoriaBibliotecaEvent
    template_name = "auditoria/auditoria_list.html"
    context_object_name = "eventos"
    paginate_by = 25
    permiso_requerido = "ingresar"
    vista_nombre = "Auditoría - Listar"

    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        # inicio exec
        logger.info("AUDIT_EXEC_START path=%s user=%s empresa_id=%s",
                    request.path,
                    getattr(request.user, "username", None),
                    request.session.get("empresa_id"))

        # verificar existencia de Vista y permiso asignado (diagnóstico)
        try:
            vista = Vista.objects.filter(nombre="Auditoría - Listar").first()
            if vista:
                has_perm = Permiso.objects.filter(usuario=request.user, empresa_id=request.session.get('empresa_id'), vista=vista, ingresar=True).exists()
            else:
                has_perm = False
            logger.info("AUDIT_CHECK vista_exists=%s has_ingresar=%s vista_nombre=%s", bool(vista), has_perm, getattr(vista, 'nombre', None))
        except Exception as e:
            logger.info("AUDIT_CHECK error=%s", e)

        response = super().dispatch(request, *args, **kwargs)

        # fin exec: información de respuesta
        try:
            status = getattr(response, 'status_code', None)
            cls_name = response.__class__.__name__
            template_name = getattr(response, 'template_name', None)
            redirect_url = getattr(response, 'url', None)
            logger.info("AUDIT_EXEC_END status=%s response_class=%s template=%s url=%s", status, cls_name, template_name, redirect_url)
            if status in (302, 403):
                logger.info("AUDIT_INTERCEPTED redirect_or_forbidden status=%s", status)
        except Exception as e:
            logger.info("AUDIT_EXEC_END error=%s", e)

        return response

    def get_queryset(self):
        empresa_id_raw = self.request.session.get("empresa_id")
        try:
            empresa_id = int(empresa_id_raw) if empresa_id_raw is not None else None
        except (ValueError, TypeError):
            empresa_id = None

        self.empresa_selected = bool(empresa_id)
        if not empresa_id:
            return AuditoriaBibliotecaEvent.objects.none()

        qs = AuditoriaBibliotecaEvent.objects.select_related("user").filter(empresa_id=empresa_id)

        # Filtros GET (mantener compatibilidad)
        action = self.request.GET.get("action")
        user = self.request.GET.get("user")
        object_type = self.request.GET.get("object_type")
        object_id = self.request.GET.get("object_id")
        vista_nombre = self.request.GET.get("vista_nombre")
        path = self.request.GET.get("path")
        date_from = self.request.GET.get("date_from")
        date_to = self.request.GET.get("date_to")

        if action:
            qs = qs.filter(action=action)

        if user:
            if user.isdigit():
                qs = qs.filter(user_id=int(user))
            else:
                qs = qs.filter(user__username__icontains=user)

        if object_type:
            qs = qs.filter(object_type__icontains=object_type)

        if object_id:
            qs = qs.filter(object_id=str(object_id))

        if vista_nombre:
            qs = qs.filter(vista_nombre__icontains=vista_nombre)

        if path:
            qs = qs.filter(path__icontains=path)

        # Manejo seguro de fechas (YYYY-MM-DD)
        if date_from:
            parsed = parse_date(date_from)
            if parsed:
                start_dt = datetime.combine(parsed, time.min)
                if timezone.is_naive(start_dt):
                    start_dt = timezone.make_aware(start_dt)
                qs = qs.filter(created_at__gte=start_dt)

        if date_to:
            parsed = parse_date(date_to)
            if parsed:
                next_day = parsed + timedelta(days=1)
                end_dt = datetime.combine(next_day, time.min)
                if timezone.is_naive(end_dt):
                    end_dt = timezone.make_aware(end_dt)
                qs = qs.filter(created_at__lt=end_dt)

        # registro diagnóstico final (BORRAR DESPUÉS)
        logger.info("AUDIT_LIST queryset empresa_id=%s count=%s params=%s",
                    self.request.session.get('empresa_id'),
                    qs.count(),
                    dict(self.request.GET))

        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.object_list
        context["acciones"] = qs.values_list("action", flat=True).distinct()
        context["usuarios"] = qs.values_list("user__username", flat=True).distinct()
        # indicar si hay empresa seleccionada
        context["empresa_selected"] = getattr(self, "empresa_selected", False)
        context["empresa_id"] = self.request.session.get("empresa_id")
        return context

class AuditoriaBibliotecaDetailView(VerificarPermisoMixin, DetailView):
    model = AuditoriaBibliotecaEvent
    template_name = "auditoria/auditoria_detail.html"
    context_object_name = "evento"
    permiso_requerido = "ingresar"
    vista_nombre = "Auditoría - Detalle"

    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        empresa_id = self.request.session.get("empresa_id")
        obj = get_object_or_404(AuditoriaBibliotecaEvent, pk=self.kwargs["pk"], empresa_id=empresa_id)
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        evento = context["evento"]
        meta = evento.meta or {}
        before = evento.before or {}
        after = evento.after or {}
        changes = meta.get("changes")
        if not changes and before and after:
            changes = AuditoriaService.diff_snapshots(before, after)
        context["changes"] = changes
        return context
