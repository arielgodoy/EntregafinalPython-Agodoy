from django.views import View
from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from access_control.views import VerificarPermisoMixin
from auditoria.models import AuditoriaBibliotecaEvent, AuditoriaGestionDTEEvent, UserPresence
from auditoria.permissions import get_archivable_company_ids, get_auditable_company_ids, get_auditable_companies
from auditoria.services import AuditoriaService
from django.shortcuts import get_object_or_404, render
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from datetime import datetime, time, timedelta
import logging
logger = logging.getLogger(__name__)
from access_control.models import Vista, Permiso
from auditoria.archive_service import AuditArchiveService
from auditoria.models import AuditArchiveBatch
from auditoria.purge_service import AuditArchivePurgeService


class AuditoriaPermissionMixin:
    def dispatch(self, request, *args, **kwargs):
        self.auditable_company_ids = get_auditable_company_ids(
            request.user,
            self.vista_nombre,
            self.permiso_requerido,
        )
        if not self.auditable_company_ids:
            return VerificarPermisoMixin.handle_no_permission(
                self,
                request,
                f"No tienes permiso para '{self.permiso_requerido}' en {self.vista_nombre}.",
            )
        return super().dispatch(request, *args, **kwargs)


class AuditoriaBibliotecaListView(AuditoriaPermissionMixin, ListView):
    model = AuditoriaBibliotecaEvent
    template_name = "auditoria/auditoria_biblioteca_list.html"
    context_object_name = "eventos"
    paginate_by = 25
    permiso_requerido = "ingresar"
    vista_nombre = "Auditoría - Biblioteca"
    audit_title = "Auditoría Biblioteca"
    audit_list_url_name = "auditoria:auditoria_biblioteca_list"
    audit_detail_url_name = "auditoria:auditoria_biblioteca_detail"
    audit_app_label = "biblioteca"
    audit_latest_views_url_name = "auditoria:auditoria_biblioteca_latest_views"

    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        # inicio exec
        logger.info("AUDIT_EXEC_START path=%s user=%s empresa_id=%s",
                    request.path,
                    getattr(request.user, "username", None),
                    request.session.get("empresa_id"))

        # verificar existencia de Vista y permiso asignado (diagnóstico)
        try:
            vista_nombre_lookup = getattr(self, "vista_nombre", "Auditoría - Biblioteca")
            vista = Vista.objects.filter(nombre=vista_nombre_lookup).first()
            if vista:
                has_perm = Permiso.objects.filter(usuario=request.user, empresa_id=request.session.get('empresa_id'), vista=vista, ingresar=True).exists()
            else:
                has_perm = False
            logger.info("AUDIT_CHECK vista_exists=%s has_ingresar=%s vista_nombre=%s", bool(vista), has_perm, vista_nombre_lookup)
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
        self.empresa_selected = True
        qs = self.model.objects.select_related("user").filter(
            empresa_id__in=self.auditable_company_ids
        )

        empresa_id = self.request.GET.get("empresa")
        if empresa_id:
            try:
                empresa_id = int(empresa_id)
            except (ValueError, TypeError):
                raise Http404
            if empresa_id not in self.auditable_company_ids:
                raise Http404
            qs = qs.filter(empresa_id=empresa_id)

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
        # Para los filtros mostramos valores únicos en todo el conjunto de la empresa
        empresa_id = self.request.session.get("empresa_id")
        base_qs = self.model.objects.filter(empresa_id__in=self.auditable_company_ids)
        context["acciones"] = list(base_qs.values_list("action", flat=True).distinct().order_by("action"))
        context["usuarios"] = list(base_qs.values_list("user__username", flat=True).distinct().order_by("user__username"))
        # Valores únicos para el filtro de vistas y paths
        context["vistas"] = list(base_qs.values_list("vista_nombre", flat=True).distinct().order_by("vista_nombre"))
        context["paths"] = list(base_qs.values_list("path", flat=True).distinct().order_by("path"))
        # indicar si hay empresa seleccionada
        context["empresa_selected"] = getattr(self, "empresa_selected", False)
        context["empresa_id"] = self.request.GET.get("empresa")
        context["empresas_autorizadas"] = get_auditable_companies(
            self.request.user,
            self.vista_nombre,
            self.permiso_requerido,
        )
        context["presencias"] = UserPresence.objects.select_related("user").filter(
            app_label=self.audit_app_label,
            empresa_id__in=self.auditable_company_ids,
        ).order_by("-last_seen")
        context["audit_latest_views_url_name"] = self.audit_latest_views_url_name
        context["audit_title"] = self.audit_title
        context["audit_list_url_name"] = self.audit_list_url_name
        context["audit_detail_url_name"] = self.audit_detail_url_name
        context["archive_url_name"] = (
            "auditoria:auditoria_biblioteca_archive"
            if self.audit_app_label == "biblioteca"
            else "auditoria:auditoria_gestiondte_archive"
        )
        context["archivable_company_ids"] = get_archivable_company_ids(
            self.request.user,
            self.vista_nombre,
        )
        return context

class AuditoriaBibliotecaDetailView(AuditoriaPermissionMixin, DetailView):
    model = AuditoriaBibliotecaEvent
    template_name = "auditoria/auditoria_biblioteca_detail.html"
    context_object_name = "evento"
    permiso_requerido = "ingresar"
    vista_nombre = "Auditoría - Biblioteca"
    audit_title = "Auditoría Biblioteca"
    audit_list_url_name = "auditoria:auditoria_biblioteca_list"
    audit_app_label = "biblioteca"

    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        logger.info("AUDIT_EXEC_START path=%s user=%s empresa_id=%s",
                    request.path,
                    getattr(request.user, "username", None),
                    request.session.get("empresa_id"))

        try:
            vista_nombre_lookup = getattr(self, "vista_nombre", "Auditoría - Biblioteca Detalle")
            vista = Vista.objects.filter(nombre=vista_nombre_lookup).first()
            if vista:
                has_perm = Permiso.objects.filter(usuario=request.user, empresa_id=request.session.get('empresa_id'), vista=vista, ingresar=True).exists()
            else:
                has_perm = False
            logger.info("AUDIT_CHECK vista_exists=%s has_ingresar=%s vista_nombre=%s", bool(vista), has_perm, vista_nombre_lookup)
        except Exception as e:
            logger.info("AUDIT_CHECK error=%s", e)

        response = super().dispatch(request, *args, **kwargs)

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

    def get_object(self, queryset=None):
        obj = get_object_or_404(
            self.model,
            pk=self.kwargs["pk"],
            empresa_id__in=self.auditable_company_ids,
        )
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
        context["audit_title"] = self.audit_title
        context["audit_list_url_name"] = self.audit_list_url_name
        return context


class AuditoriaGestionDTEListView(AuditoriaBibliotecaListView):
    model = AuditoriaGestionDTEEvent
    vista_nombre = "Auditoría - Gestión DTE"
    audit_title = "Auditoría Gestión DTE"
    audit_list_url_name = "auditoria:auditoria_gestiondte_list"
    audit_detail_url_name = "auditoria:auditoria_gestiondte_detail"
    audit_app_label = "gestiondte"
    audit_latest_views_url_name = "auditoria:auditoria_gestiondte_latest_views"


class AuditoriaGestionDTEDetailView(AuditoriaBibliotecaDetailView):
    model = AuditoriaGestionDTEEvent
    vista_nombre = "Auditoría - Gestión DTE"
    audit_title = "Auditoría Gestión DTE"
    audit_list_url_name = "auditoria:auditoria_gestiondte_list"
    audit_app_label = "gestiondte"


class AuditoriaBibliotecaLatestViewsView(AuditoriaPermissionMixin, View):
    vista_nombre = "Auditoría - Biblioteca"
    permiso_requerido = "ingresar"
    model = AuditoriaBibliotecaEvent
    audit_app_label = "biblioteca"

    def get(self, request, user_id):
        company_ids = self.auditable_company_ids
        eventos = self.model.objects.filter(
            user_id=user_id,
            action="VIEW",
            empresa_id__in=company_ids,
        ).order_by("-created_at")[:10]
        return render(request, "auditoria/auditoria_latest_views.html", {
            "eventos": eventos,
            "audit_title": f"Últimas vistas - {self.vista_nombre}",
            "back_url_name": (
                "auditoria:auditoria_biblioteca_list"
                if self.audit_app_label == "biblioteca"
                else "auditoria:auditoria_gestiondte_list"
            ),
        })


class AuditoriaGestionDTELatestViewsView(AuditoriaBibliotecaLatestViewsView):
    vista_nombre = "Auditoría - Gestión DTE"
    model = AuditoriaGestionDTEEvent
    audit_app_label = "gestiondte"


class AuditoriaArchiveView(VerificarPermisoMixin, LoginRequiredMixin, View):
    app_label = None
    vista_nombre = None
    audit_title = None
    archive_template = 'auditoria/auditoria_archive.html'

    def _authorized_company_ids(self, request):
        return get_archivable_company_ids(request.user, self.vista_nombre)

    def _visible_batches(self, request, company_ids):
        batches = AuditArchiveBatch.objects.filter(app_label=self.app_label).order_by('-created_at')
        visible = []
        for batch in batches:
            if not set(batch.company_ids or []).issubset(company_ids):
                continue
            batch.archive_error_display = {
                'FAILED': 'El snapshot no pudo completarse.',
                'PURGE_FAILED': 'La limpieza quedó incompleta y requiere revisión.',
            }.get(batch.status, '')
            visible.append(batch)
        return visible

    def _parse_cutoff(self, value):
        try:
            cutoff = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            raise ValueError('La fecha de corte no es válida.') from None
        if timezone.is_naive(cutoff):
            cutoff = timezone.make_aware(cutoff)
        return cutoff

    def _context(self, request, company_ids, **extra):
        context = {
            'archive_title': self.audit_title,
            'archive_app_label': self.app_label,
            'archive_batches': self._visible_batches(request, company_ids),
            'archivable_companies': get_auditable_companies(
                request.user,
                self.vista_nombre,
                'autorizar',
            ),
            'archive_error': None,
            'archive_success': None,
            'snapshot_preview': None,
            'purge_preview': None,
            'dry_run_result': None,
        }
        context.update(extra)
        return context

    def _batch_for_action(self, request, company_ids):
        batch_id = (request.POST.get('batch_id') or '').strip()
        batch = get_object_or_404(AuditArchiveBatch, batch_id=batch_id, app_label=self.app_label)
        if not set(batch.company_ids or []).issubset(company_ids):
            raise PermissionError('No tienes autorización para todas las empresas del batch.')
        return batch

    def get(self, request, *args, **kwargs):
        company_ids = self._authorized_company_ids(request)
        if not company_ids:
            return VerificarPermisoMixin.handle_no_permission(
                self, request, f"No tienes permiso para 'autorizar' en {self.vista_nombre}.",
            )
        return render(request, self.archive_template, self._context(request, company_ids))

    def post(self, request, *args, **kwargs):
        company_ids = self._authorized_company_ids(request)
        if not company_ids:
            return VerificarPermisoMixin.handle_no_permission(
                self, request, f"No tienes permiso para 'autorizar' en {self.vista_nombre}.",
            )
        context = self._context(request, company_ids)
        action = request.POST.get('action')
        try:
            if action in {'preview_snapshot', 'create_snapshot'}:
                requested_ids = [int(value) for value in request.POST.getlist('company_ids')]
                if not requested_ids or not set(requested_ids).issubset(company_ids):
                    raise PermissionError('Las empresas seleccionadas no están autorizadas.')
                cutoff = self._parse_cutoff(request.POST.get('cutoff_datetime'))
                preview = AuditArchiveService.preview_snapshot(
                    self.app_label, cutoff, requested_ids, request.user, self.vista_nombre,
                )
                if action == 'preview_snapshot':
                    context['snapshot_preview'] = preview
                elif not preview['source_count']:
                    context['archive_error'] = 'No hay eventos elegibles para crear el snapshot.'
                else:
                    batch = AuditArchiveService.run_batch(
                        self.app_label,
                        cutoff,
                        max_source_id=preview['max_source_id'],
                        requested_company_ids=requested_ids,
                        user=request.user,
                        vista_nombre=self.vista_nombre,
                    )
                    from auditoria.helpers import audit_log

                    audit_log(
                        request,
                        'EXECUTE',
                        self.app_label,
                        object_type='audit_archive_batch',
                        object_id=batch.batch_id,
                        vista_nombre=self.vista_nombre,
                        message_key='auditoria.snapshot.creado',
                        meta={
                            'batch_id': batch.batch_id,
                            'source_count': batch.source_count,
                            'company_ids': batch.company_ids,
                            'cutoff': batch.cutoff_datetime.isoformat(),
                        },
                    )
                    context['archive_success'] = f'Snapshot creado y validado: {batch.batch_id}'
            elif action in {'preview_purge', 'dry_run'}:
                batch = self._batch_for_action(request, company_ids)
                if action == 'preview_purge':
                    context['purge_preview'] = AuditArchivePurgeService.preview(batch.batch_id, request.user)
                else:
                    context['dry_run_result'] = AuditArchivePurgeService.purge(
                        batch.batch_id, request.user, dry_run=True,
                    )
        except PermissionError as exc:
            context['archive_error'] = str(exc)
            return render(request, self.archive_template, context, status=403)
        except ValueError as exc:
            context['archive_error'] = 'No fue posible completar la operación de archivado.'
        except Exception:
            context['archive_error'] = 'No fue posible validar la operación de archivado.'
        return render(request, self.archive_template, context)


class AuditoriaBibliotecaArchiveView(AuditoriaArchiveView):
    app_label = 'biblioteca'
    vista_nombre = 'Auditoría - Biblioteca'
    audit_title = 'Auditoría Biblioteca - Archivado'


class AuditoriaGestionDTEArchiveView(AuditoriaArchiveView):
    app_label = 'gestiondte'
    vista_nombre = 'Auditoría - Gestión DTE'
    audit_title = 'Auditoría Gestión DTE - Archivado'
