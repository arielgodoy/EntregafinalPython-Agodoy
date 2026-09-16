"""Vistas de la app tareas (Tareas Internas).

Patrones vigentes reutilizados:
- VerificarPermisoMixin (ICMEAS) + LoginRequiredMixin (access_control/views.py).
- Empresa activa desde request.session["empresa_id"]; nunca desde parámetros.
- Querysets filtrados por empresa activa (404 si pertenece a otra empresa).
"""

import logging

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from access_control.models import Empresa
from access_control.decorators import verificar_permiso
from access_control.services.permissions import user_has_permission_for_empresa
from access_control.views import VerificarPermisoMixin

from .forms import (
    AvanceManualForm,
    AvancePonderadoForm,
    CompletarHitoForm,
    DocumentoForm,
    EvidenciaConfigForm,
    EvidenciaRegistroForm,
    HitoCumplimientoForm,
    HitoCrearForm,
    HitoForm,
    HitoReasignacionForm,
    ReunionParticipanteForm,
    ReunionRevisionForm,
    ReunionTareaForm,
    TareaForm,
)
from .models import (
    Avance,
    DocumentoHistorial,
    DocumentoTarea,
    Hito,
    HitoEvidencia,
    EnlaceTarea,
    ReunionRevision,
    Tarea,
    TareaParticipante,
)
from .services.context import get_active_company_id
from .services.hierarchy import get_children, get_parent, is_effectively_annulled
from .services.lifecycle import (
    annul_task,
    approve_closure,
    complete_task,
    publish_task,
    reject_closure,
    reactivate_task,
    transition_task,
)
from .services.documents import (
    configure_closure_evidence,
    create_document,
    register_closure_evidence,
)
from .services.notifications import emit_task_event, task_recipients
from .services.meetings import (
    add_meeting_participant,
    add_task_to_meeting,
    convene_meeting,
    create_meeting,
    mark_meeting_completed,
    update_meeting,
)
from .services.links import (
    TaskLinkAccessError,
    create_task_link,
    resolve_task_link,
    revoke_task_link,
)
from .services.progress import (
    create_milestone,
    complete_milestone,
    delete_milestone_safely,
    milestone_capability,
    reassign_milestone,
    set_manual_progress,
    set_milestone_annulled,
    set_weighted_progress_mode,
    update_milestone,
    weighted_progress,
)
from .services.kpi import (
    DashboardPermissionError,
    get_company_dashboard,
    get_department_dashboard,
    get_general_dashboard,
    get_personal_dashboard,
    get_user_dashboard,
)

logger = logging.getLogger(__name__)


def _get_empresa_id(request):
    """Empresa activa desde la sesión (patrón vigente)."""
    return get_active_company_id(request)


class TareaEmpresaQuerysetMixin:
    """Restringe el queryset a la empresa activa de la sesión."""

    def get_queryset(self):
        empresa_id = _get_empresa_id(self.request)
        qs = Tarea.objects.select_related("empresa", "responsable", "creada_por")
        if not empresa_id:
            return Tarea.objects.none()
        return qs.filter(empresa_id=empresa_id)


class ListarTareasView(VerificarPermisoMixin, LoginRequiredMixin, TareaEmpresaQuerysetMixin, ListView):
    model = Tarea
    template_name = "tareas/tarea_lista.html"
    context_object_name = "tareas"
    vista_nombre = "Tareas"
    permiso_requerido = "ingresar"

    def get_queryset(self):
        return super().get_queryset().order_by("-fecha_creacion")


class MisTareasDashboardView(VerificarPermisoMixin, LoginRequiredMixin, TareaEmpresaQuerysetMixin, View):
    template_name = "tareas/mis_tareas.html"
    vista_nombre = "Tareas - Dashboard personal"
    permiso_requerido = "ingresar"

    def get_context_data(self):
        empresa_id = _get_empresa_id(self.request)
        return get_personal_dashboard(
            user=self.request.user,
            empresa_id=empresa_id,
        )

    def get(self, request):
        return render(request, self.template_name, self.get_context_data())


def _dashboard_filters(request):
    return {
        key: request.GET.get(key)
        for key in ("empresa_id", "departamento_id", "usuario_id", "estado", "prioridad")
        if request.GET.get(key)
    }


def _serialize_dashboard_value(value):
    if isinstance(value, Tarea):
        return {
            "id": value.pk,
            "correlativo": value.correlativo,
            "titulo": value.titulo,
            "estado": value.estado,
            "prioridad": value.prioridad,
            "responsable_id": value.responsable_id,
            "empresa_id": value.empresa_id,
            "tipo_ambito": value.tipo_ambito,
            "departamento_id": value.departamento_id,
            "local_id": value.local_id,
            "fecha_publicacion": value.fecha_publicacion,
            "fecha_tope": value.fecha_tope,
            "fecha_cumplimiento": value.fecha_cumplimiento,
            "detalle_url": str(reverse_lazy("tareas:detalle_tarea", kwargs={"pk": value.pk})),
        }
    if isinstance(value, (Empresa, User)):
        return {"id": value.pk, "label": str(value)}
    if hasattr(value, "_meta") and hasattr(value, "pk"):
        return {"id": value.pk, "label": str(value)}
    if isinstance(value, dict):
        return {key: _serialize_dashboard_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_dashboard_value(item) for item in value]
    return value


class TareasDashboardGeneralView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Tareas"
    permiso_requerido = "supervisor"
    verificar_vicmeas_en_dispatch = False
    crear_permiso_faltante = False

    def get(self, request):
        context = get_general_dashboard(
            user=request.user,
            filters=_dashboard_filters(request),
        )
        if not context["rows"]:
            return self.handle_no_permission(request, "No tienes Empresas autorizadas para este dashboard.")
        return JsonResponse(_serialize_dashboard_value(context))


class TareasDashboardEmpresaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Tareas"
    permiso_requerido = "supervisor"
    verificar_vicmeas_en_dispatch = False
    crear_permiso_faltante = False

    def get(self, request, empresa_id):
        try:
            context = get_company_dashboard(
                user=request.user,
                empresa_id=empresa_id,
                filters=_dashboard_filters(request),
            )
        except DashboardPermissionError as error:
            return self.handle_no_permission(request, str(error))
        return JsonResponse(_serialize_dashboard_value(context))


class TareasDashboardDepartamentoView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Tareas"
    permiso_requerido = "supervisor"
    verificar_vicmeas_en_dispatch = False
    crear_permiso_faltante = False

    def get(self, request, empresa_id, departamento_id):
        try:
            context = get_department_dashboard(
                user=request.user,
                empresa_id=empresa_id,
                departamento_id=departamento_id,
                filters=_dashboard_filters(request),
            )
        except DashboardPermissionError as error:
            return self.handle_no_permission(request, str(error))
        return JsonResponse(_serialize_dashboard_value(context))


class TareasDashboardUsuarioView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Tareas"
    permiso_requerido = "supervisor"
    verificar_vicmeas_en_dispatch = False
    crear_permiso_faltante = False

    def get(self, request, empresa_id, usuario_id):
        try:
            context = get_user_dashboard(
                user=request.user,
                empresa_id=empresa_id,
                usuario_id=usuario_id,
                filters=_dashboard_filters(request),
            )
        except DashboardPermissionError as error:
            return self.handle_no_permission(request, str(error))
        return JsonResponse(_serialize_dashboard_value(context))


class DetalleTareaView(VerificarPermisoMixin, LoginRequiredMixin, TareaEmpresaQuerysetMixin, DetailView):
    model = Tarea
    template_name = "tareas/tarea_detalle.html"
    context_object_name = "tarea"
    vista_nombre = "Tareas"
    permiso_requerido = "ingresar"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        parent = get_parent(self.object)
        context["tarea_padre"] = (
            parent if parent and parent.empresa_id == self.object.empresa_id else None
        )
        context["tareas_hijas"] = get_children(self.object).filter(
            empresa_id=self.object.empresa_id
        )
        context["tarea_anulada_efectivamente"] = is_effectively_annulled(self.object)
        context["puede_configurar_evidencia"] = user_has_permission_for_empresa(
            user=self.request.user,
            empresa=self.object.empresa,
            vista_nombre="Tareas",
            accion="modificar",
        )
        context["evidencia_config_form"] = kwargs.get(
            "evidencia_config_form",
            EvidenciaConfigForm(
                initial={
                    "requiere_evidencia_cierre": self.object.requiere_evidencia_cierre
                }
            ),
        )
        return context

    @method_decorator(verificar_permiso("Tareas", "modificar"))
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = EvidenciaConfigForm(request.POST)
        if form.is_valid():
            configure_closure_evidence(
                tarea=self.object,
                usuario=request.user,
                requiere_evidencia_cierre=form.cleaned_data["requiere_evidencia_cierre"],
            )
            messages.success(request, "Configuración de evidencia actualizada.")
            return redirect("tareas:detalle_tarea", pk=self.object.pk)
        context = self.get_context_data(object=self.object)
        context["evidencia_config_form"] = form
        return self.render_to_response(context)


class CrearEnlaceTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Tareas"
    permiso_requerido = "modificar"
    crear_permiso_faltante = False

    def post(self, request, tarea_id):
        empresa_id = _get_empresa_id(request)
        tarea = get_object_or_404(
            Tarea.objects.select_related("empresa"),
            pk=tarea_id,
            empresa_id=empresa_id,
        )
        destinatario_id = request.POST.get("destinatario_id")
        if not destinatario_id:
            return JsonResponse(
                {"success": False, "message_key": "tareas.links.create_error"},
                status=400,
            )
        destinatario = get_object_or_404(User, pk=destinatario_id)
        fecha_expiracion = parse_datetime(request.POST.get("fecha_expiracion", ""))
        if fecha_expiracion is not None and timezone.is_naive(fecha_expiracion):
            fecha_expiracion = timezone.make_aware(fecha_expiracion)
        try:
            enlace, token = create_task_link(
                tarea=tarea,
                destinatario=destinatario,
                creado_por=request.user,
                fecha_expiracion=fecha_expiracion,
            )
        except ValidationError:
            return JsonResponse(
                {"success": False, "message_key": "tareas.links.create_error"},
                status=400,
            )
        return JsonResponse(
            {
                "success": True,
                "message_key": "tareas.links.created",
                "token": token,
                "url": request.build_absolute_uri(
                    reverse_lazy("tareas:enlace_tarea", kwargs={"token": token})
                ),
                "enlace_id": enlace.pk,
            },
            status=201,
        )


class AbrirEnlaceTareaView(LoginRequiredMixin, View):
    template_name = "tareas/enlace_tarea_lectura.html"

    def get(self, request, token):
        empresa_id = _get_empresa_id(request)
        try:
            enlace = resolve_task_link(
                token=token,
                usuario=request.user,
                empresa=empresa_id,
            )
        except TaskLinkAccessError:
            return HttpResponseForbidden("No es posible acceder al enlace.")
        return render(request, self.template_name, {"tarea": enlace.tarea})


class RevocarEnlaceTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Tareas"
    permiso_requerido = "modificar"
    crear_permiso_faltante = False

    def post(self, request, enlace_id):
        empresa_id = _get_empresa_id(request)
        enlace = get_object_or_404(
            EnlaceTarea.objects.select_related("tarea", "tarea__empresa"),
            pk=enlace_id,
            tarea__empresa_id=empresa_id,
        )
        try:
            revoke_task_link(enlace=enlace, actor=request.user)
        except ValidationError:
            return JsonResponse(
                {"success": False, "message_key": "tareas.links.revoke_error"},
                status=400,
            )
        return JsonResponse(
            {"success": True, "message_key": "tareas.links.revoked"}
        )


class CrearTareaView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = Tarea
    form_class = TareaForm
    template_name = "tareas/tarea_form.html"
    vista_nombre = "Tareas"
    permiso_requerido = "crear"

    def form_valid(self, form):
        form.instance.empresa_id = _get_empresa_id(self.request)
        form.instance.creada_por = self.request.user
        response = super().form_valid(form)
        if self.object.responsable is not None:
            emit_task_event(
                tarea=self.object,
                event="asignacion",
                recipients=task_recipients(
                    self.object,
                    actor=self.request.user,
                    include_responsible=True,
                ),
                title="Tarea asignada",
                body="Se te asignó una nueva tarea.",
                actor=self.request.user,
            )
        return response


class EditarTareaView(VerificarPermisoMixin, LoginRequiredMixin, TareaEmpresaQuerysetMixin, UpdateView):
    model = Tarea
    form_class = TareaForm
    template_name = "tareas/tarea_form.html"
    vista_nombre = "Tareas"
    permiso_requerido = "modificar"

    def form_valid(self, form):
        campos_relevantes = {"responsable", "fecha_tope", "prioridad"}
        cambio_relevante = bool(campos_relevantes.intersection(form.changed_data))
        response = super().form_valid(form)
        if cambio_relevante:
            emit_task_event(
                tarea=self.object,
                event="cambio_relevante",
                recipients=task_recipients(
                    self.object,
                    actor=self.request.user,
                    include_responsible=True,
                    participant_roles=list(TareaParticipante.Rol),
                ),
                title="Cambio relevante en la tarea",
                body="Se actualizó información funcional de la tarea.",
                actor=self.request.user,
            )
        return response


class PublicarTareaView(VerificarPermisoMixin, LoginRequiredMixin, TareaEmpresaQuerysetMixin, View):
    """Publica un borrador (FR-007/FR-008, Q1). Publicación irreversible (Q2)."""

    vista_nombre = "Tareas - Ciclo de vida"
    permiso_requerido = "modificar"

    def post(self, request, *args, **kwargs):
        tarea = self.get_queryset().filter(pk=kwargs["pk"]).first()
        if tarea is None:
            from django.http import Http404

            raise Http404
        try:
            publish_task(tarea, request.user)
        except ValidationError as e:
            mensaje = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
            messages.error(request, mensaje)
        else:
            messages.success(request, "Tarea publicada correctamente.")
        return redirect("tareas:detalle_tarea", pk=tarea.pk)


class TareaLifecycleView(VerificarPermisoMixin, LoginRequiredMixin, TareaEmpresaQuerysetMixin, View):
    """Protected Phase 2 action endpoint for one task."""

    permiso_requerido = "modificar"
    accion = None
    vista_nombre = "Tareas - Ciclo de vida"

    def post(self, request, *args, **kwargs):
        tarea = self.get_queryset().filter(pk=kwargs["pk"]).first()
        if tarea is None:
            from django.http import Http404

            raise Http404
        try:
            if self.accion == "gestion":
                transition_task(tarea, Tarea.Estado.GESTION, request.user, "INICIAR_GESTION")
            elif self.accion == "completar":
                complete_task(tarea, request.user)
            elif self.accion == "aprobar":
                approve_closure(tarea, request.user)
            elif self.accion == "rechazar":
                reject_closure(tarea, request.user)
            elif self.accion == "anular":
                annul_task(tarea, request.user)
            elif self.accion == "reactivar":
                reactivate_task(tarea, request.user)
            else:
                raise ValidationError("Acción de ciclo no configurada.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Acción de ciclo aplicada correctamente.")
        return redirect("tareas:detalle_tarea", pk=tarea.pk)


class IniciarGestionView(TareaLifecycleView):
    accion = "gestion"


class CompletarTareaView(TareaLifecycleView):
    accion = "completar"


class AprobarCierreView(TareaLifecycleView):
    accion = "aprobar"


class RechazarCierreView(TareaLifecycleView):
    accion = "rechazar"


class AnularTareaView(TareaLifecycleView):
    accion = "anular"


class ReactivarTareaView(TareaLifecycleView):
    accion = "reactivar"


class HitosTareaView(VerificarPermisoMixin, LoginRequiredMixin, TareaEmpresaQuerysetMixin, View):
    vista_nombre = "Tareas - Hitos"
    permiso_requerido = "ingresar"

    def get_tarea(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)

    def get_context(self, tarea, **forms):
        avance = Avance.objects.filter(tarea=tarea).first()
        hitos = list(
            tarea.hitos.select_related("responsable", "completado_por").prefetch_related(
                Prefetch(
                    "evidencias",
                    queryset=HitoEvidencia.objects.select_related("usuario").order_by("fecha", "pk"),
                )
            )
        )
        for hito in hitos:
            capability = milestone_capability(tarea, hito, self.request.user)
            hito.puede_gestionar = capability == "manage"
            hito.puede_actualizar = capability in {
                "progress",
                "manage",
            }
            hito.puede_completar = capability in {"progress", "manage"} and not hito.completado
        return {
            "tarea": tarea,
            "hitos": hitos,
            "responsables_validos": HitoCrearForm(tarea=tarea).fields["responsable"].queryset,
            "avance": avance,
            "avance_calculado": weighted_progress(tarea),
            "hito_form": forms.get("hito_form", HitoCrearForm(tarea=tarea)),
            "editar_form": forms.get("editar_form", HitoForm()),
            "reasignar_form": forms.get("reasignar_form", HitoReasignacionForm(tarea=tarea)),
            "completar_form": forms.get("completar_form", CompletarHitoForm()),
            "modal_abierto_hito_id": forms.get("modal_abierto_hito_id"),
            "modal_abierto_accion": forms.get("modal_abierto_accion"),
            "manual_form": forms.get("manual_form", AvanceManualForm()),
            "ponderado_form": forms.get("ponderado_form", AvancePonderadoForm()),
        }

    def get(self, request, pk):
        tarea = self.get_tarea(pk)
        return render(request, "tareas/tarea_hitos.html", self.get_context(tarea))

    def post(self, request, pk):
        tarea = self.get_tarea(pk)
        accion = request.POST.get("accion")
        if accion == "hito":
            form = HitoCrearForm(request.POST, tarea=tarea)
            if form.is_valid():
                try:
                    create_milestone(
                        tarea,
                        form.cleaned_data["nombre"],
                        form.cleaned_data["cumplimiento"],
                        form.cleaned_data["peso"],
                        form.cleaned_data["responsable"],
                        request.user,
                    )
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "Hito creado correctamente.")
                    return redirect("tareas:hitos_tarea", pk=tarea.pk)
            return render(request, "tareas/tarea_hitos.html", self.get_context(tarea, hito_form=form))
        hito = None
        if request.POST.get("hito_id"):
            hito = get_object_or_404(
                Hito.objects.select_related("tarea", "responsable"),
                pk=request.POST["hito_id"],
                tarea=tarea,
            )
        if accion == "completar_hito":
            form = CompletarHitoForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    complete_milestone(
                        hito,
                        request.user,
                        resena_cierre=form.cleaned_data["resena_cierre"],
                        formato_archivo=form.cleaned_data["formato_archivo"],
                        archivo=form.cleaned_data.get("archivo"),
                        url=form.cleaned_data.get("url", ""),
                    )
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "Hito completado correctamente.")
                    return redirect("tareas:hitos_tarea", pk=tarea.pk)
            return render(
                request,
                "tareas/tarea_hitos.html",
                self.get_context(
                    tarea,
                    completar_form=form,
                    modal_abierto_hito_id=hito.pk,
                    modal_abierto_accion="completar_hito",
                ),
            )
        if accion == "editar_hito":
            form = HitoForm(request.POST, instance=hito)
            if form.is_valid():
                try:
                    update_milestone(
                        hito,
                        request.user,
                        nombre=form.cleaned_data["nombre"],
                        cumplimiento=form.cleaned_data["cumplimiento"],
                        peso=form.cleaned_data["peso"],
                    )
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "Hito actualizado correctamente.")
                    return redirect("tareas:hitos_tarea", pk=tarea.pk)
            return render(
                request,
                "tareas/tarea_hitos.html",
                self.get_context(
                    tarea,
                    editar_form=form,
                    modal_abierto_hito_id=hito.pk,
                    modal_abierto_accion="editar_hito",
                ),
            )
        if accion == "cumplimiento_hito":
            form = HitoCumplimientoForm(request.POST, instance=hito)
            if form.is_valid():
                try:
                    update_milestone(
                        hito,
                        request.user,
                        cumplimiento=form.cleaned_data["cumplimiento"],
                    )
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "Cumplimiento actualizado correctamente.")
                    return redirect("tareas:hitos_tarea", pk=tarea.pk)
            return render(
                request,
                "tareas/tarea_hitos.html",
                self.get_context(
                    tarea,
                    cumplimiento_form=form,
                    modal_abierto_hito_id=hito.pk,
                    modal_abierto_accion="cumplimiento_hito",
                ),
            )
        if accion == "reasignar_hito":
            form = HitoReasignacionForm(request.POST, tarea=tarea)
            if form.is_valid():
                try:
                    reassign_milestone(
                        hito,
                        request.user,
                        form.cleaned_data["responsable"],
                        form.cleaned_data["motivo"],
                    )
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "Hito reasignado correctamente.")
                    return redirect("tareas:hitos_tarea", pk=tarea.pk)
            return render(
                request,
                "tareas/tarea_hitos.html",
                self.get_context(
                    tarea,
                    reasignar_form=form,
                    modal_abierto_hito_id=hito.pk,
                    modal_abierto_accion="reasignar_hito",
                ),
            )
        if accion in {"anular_hito", "reactivar_hito"}:
            try:
                set_milestone_annulled(hito, request.user, accion == "anular_hito")
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, "Estado del hito actualizado correctamente.")
            return redirect("tareas:hitos_tarea", pk=tarea.pk)
        if accion == "eliminar_hito":
            try:
                delete_milestone_safely(hito, request.user)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, "Hito eliminado o anulado correctamente.")
            return redirect("tareas:hitos_tarea", pk=tarea.pk)
        if accion == "manual":
            form = AvanceManualForm(request.POST)
            if form.is_valid():
                try:
                    set_manual_progress(tarea, form.cleaned_data["porcentaje"])
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "Avance manual actualizado.")
                    return redirect("tareas:hitos_tarea", pk=tarea.pk)
            return render(request, "tareas/tarea_hitos.html", self.get_context(tarea, manual_form=form))
        if accion == "ponderado":
            form = AvancePonderadoForm(request.POST)
            if form.is_valid():
                try:
                    set_weighted_progress_mode(tarea)
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "Modo ponderado configurado.")
                    return redirect("tareas:hitos_tarea", pk=tarea.pk)
            return render(request, "tareas/tarea_hitos.html", self.get_context(tarea, ponderado_form=form))
        raise ValidationError("Acción de avance no configurada.")


class DocumentosTareaView(VerificarPermisoMixin, LoginRequiredMixin, TareaEmpresaQuerysetMixin, View):
    vista_nombre = "Tareas - Documentos y evidencia"
    permiso_requerido = "modificar"

    def get_tarea(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)

    def get_context(self, tarea, **forms):
        documentos = tarea.documentos.all().prefetch_related("historial__usuario")
        evidencias = tarea.evidencias_cierre.select_related("usuario").order_by("-fecha", "-pk")
        return {
            "tarea": tarea,
            "documentos": documentos,
            "evidencias": evidencias,
            "document_form": forms.get("document_form", DocumentoForm()),
            "evidencia_registro_form": forms.get(
                "evidencia_registro_form", EvidenciaRegistroForm()
            ),
        }

    def get(self, request, pk):
        tarea = self.get_tarea(pk)
        return render(request, "tareas/tarea_documentos.html", self.get_context(tarea))

    def post(self, request, pk):
        tarea = self.get_tarea(pk)
        accion = request.POST.get("accion")
        if accion == "documento":
            form = DocumentoForm(request.POST, request.FILES)
            if form.is_valid():
                create_document(
                    tarea=tarea,
                    usuario=request.user,
                    tipo=form.cleaned_data["tipo"],
                    formato_archivo=form.cleaned_data["formato_archivo"],
                    archivo=form.cleaned_data["archivo"],
                    url=form.cleaned_data["url"],
                    fecha_documento=form.cleaned_data["fecha_documento"],
                    fecha_vencimiento=form.cleaned_data["fecha_vencimiento"],
                )
                messages.success(request, "Documento registrado correctamente.")
                return redirect("tareas:documentos_tarea", pk=tarea.pk)
            return render(request, "tareas/tarea_documentos.html", self.get_context(tarea, document_form=form))
        if accion == "registrar_evidencia":
            form = EvidenciaRegistroForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    register_closure_evidence(
                        tarea=tarea,
                        usuario=request.user,
                        formato_archivo=form.cleaned_data["formato_archivo"],
                        archivo=form.cleaned_data["archivo"],
                        url=form.cleaned_data["url"],
                    )
                except ValidationError as exc:
                    if hasattr(exc, "message_dict"):
                        for campo, mensajes in exc.message_dict.items():
                            campo_formulario = campo if campo in form.fields else None
                            for mensaje in mensajes:
                                form.add_error(campo_formulario, mensaje)
                    else:
                        for mensaje in exc.messages:
                            form.add_error(None, mensaje)
                    return render(
                        request,
                        "tareas/tarea_documentos.html",
                        self.get_context(tarea, evidencia_registro_form=form),
                    )
                messages.success(request, "Evidencia registrada correctamente.")
                return redirect("tareas:documentos_tarea", pk=tarea.pk)
            return render(request, "tareas/tarea_documentos.html", self.get_context(tarea, evidencia_registro_form=form))
        raise ValidationError("Acción documental no configurada.")


class ReunionEmpresaQuerysetMixin:
    def get_queryset(self):
        empresa_id = _get_empresa_id(self.request)
        if not empresa_id:
            return ReunionRevision.objects.none()
        return ReunionRevision.objects.filter(empresa_id=empresa_id).select_related(
            "empresa", "local", "departamento", "tarea_planificada", "creada_por"
        )


class ListarReunionesRevisionView(VerificarPermisoMixin, LoginRequiredMixin, ReunionEmpresaQuerysetMixin, ListView):
    model = ReunionRevision
    template_name = "tareas/reunion_revision_lista.html"
    context_object_name = "reuniones"
    vista_nombre = "Tareas"
    permiso_requerido = "ingresar"


class CrearReunionRevisionView(VerificarPermisoMixin, LoginRequiredMixin, View):
    template_name = "tareas/reunion_revision_form.html"
    vista_nombre = "Tareas"
    permiso_requerido = "crear"

    def get(self, request):
        return render(request, self.template_name, {"form": ReunionRevisionForm()})

    def post(self, request):
        form = ReunionRevisionForm(request.POST)
        if form.is_valid():
            try:
                create_meeting(
                    empresa=Empresa.objects.get(pk=_get_empresa_id(request)),
                    creada_por=request.user,
                    **form.cleaned_data,
                )
            except (ValidationError, TypeError) as exc:
                form.add_error(None, str(exc))
            else:
                return redirect("tareas:reunion_revision_lista")
        return render(request, self.template_name, {"form": form})


class DetalleReunionRevisionView(VerificarPermisoMixin, LoginRequiredMixin, ReunionEmpresaQuerysetMixin, DetailView):
    model = ReunionRevision
    template_name = "tareas/reunion_revision_detalle.html"
    context_object_name = "reunion"
    vista_nombre = "Tareas"
    permiso_requerido = "ingresar"


class EditarReunionRevisionView(VerificarPermisoMixin, LoginRequiredMixin, ReunionEmpresaQuerysetMixin, View):
    template_name = "tareas/reunion_revision_form.html"
    vista_nombre = "Tareas"
    permiso_requerido = "modificar"

    def get_reunion(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)

    def get(self, request, pk):
        reunion = self.get_reunion(pk)
        return render(request, self.template_name, {"form": ReunionRevisionForm(instance=reunion), "object": reunion})

    def post(self, request, pk):
        reunion = self.get_reunion(pk)
        form = ReunionRevisionForm(request.POST, instance=reunion)
        if form.is_valid():
            try:
                update_meeting(reunion, **form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None, str(exc))
            else:
                return redirect("tareas:reunion_revision_detalle", pk=reunion.pk)
        return render(request, self.template_name, {"form": form, "object": reunion})


class ReunionRevisionActionView(VerificarPermisoMixin, LoginRequiredMixin, ReunionEmpresaQuerysetMixin, View):
    vista_nombre = "Tareas - Ciclo de vida"
    permiso_requerido = "modificar"

    def post(self, request, pk):
        reunion = get_object_or_404(self.get_queryset(), pk=pk)
        try:
            accion = request.POST.get("accion")
            if accion == "CONVOCAR":
                convene_meeting(reunion, actor=request.user)
            elif accion == "REALIZADA":
                comentarios = {
                    item.pk: request.POST.get(f"comentario_cierre_{item.pk}", "")
                    for item in reunion.agenda.all()
                }
                mark_meeting_completed(reunion, comentarios=comentarios)
            elif accion == "PARTICIPANTE":
                form = ReunionParticipanteForm(request.POST, empresa=reunion.empresa)
                if not form.is_valid():
                    raise ValidationError(form.errors.as_text())
                add_meeting_participant(reunion=reunion, usuario=form.cleaned_data["usuario"])
            elif accion == "TAREA":
                form = ReunionTareaForm(request.POST, empresa=reunion.empresa)
                if not form.is_valid():
                    raise ValidationError(form.errors.as_text())
                add_task_to_meeting(reunion=reunion, **form.cleaned_data)
            else:
                raise ValidationError("Acción de reunión no configurada.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return redirect("tareas:reunion_revision_detalle", pk=reunion.pk)
