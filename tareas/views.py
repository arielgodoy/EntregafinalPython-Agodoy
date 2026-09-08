"""Vistas de la app tareas (Tareas Internas).

Patrones vigentes reutilizados:
- VerificarPermisoMixin (ICMEAS) + LoginRequiredMixin (access_control/views.py).
- Empresa activa desde request.session["empresa_id"]; nunca desde parámetros.
- Querysets filtrados por empresa activa (404 si pertenece a otra empresa).
"""

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from access_control.views import VerificarPermisoMixin

from .forms import TareaForm
from .models import Tarea
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
    vista_nombre = "Tareas - Listado"
    permiso_requerido = "ingresar"

    def get_queryset(self):
        return super().get_queryset().order_by("-fecha_creacion")


class DetalleTareaView(VerificarPermisoMixin, LoginRequiredMixin, TareaEmpresaQuerysetMixin, DetailView):
    model = Tarea
    template_name = "tareas/tarea_detalle.html"
    context_object_name = "tarea"
    vista_nombre = "Tareas - Detalle"
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
        return context


class CrearTareaView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = Tarea
    form_class = TareaForm
    template_name = "tareas/tarea_form.html"
    vista_nombre = "Tareas - Crear tarea"
    permiso_requerido = "crear"

    def form_valid(self, form):
        form.instance.empresa_id = _get_empresa_id(self.request)
        form.instance.creada_por = self.request.user
        return super().form_valid(form)


class EditarTareaView(VerificarPermisoMixin, LoginRequiredMixin, TareaEmpresaQuerysetMixin, UpdateView):
    model = Tarea
    form_class = TareaForm
    template_name = "tareas/tarea_form.html"
    vista_nombre = "Tareas - Editar tarea"
    permiso_requerido = "modificar"


class PublicarTareaView(VerificarPermisoMixin, LoginRequiredMixin, TareaEmpresaQuerysetMixin, View):
    """Publica un borrador (FR-007/FR-008, Q1). Publicación irreversible (Q2)."""

    vista_nombre = "Tareas - Publicar tarea"
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
    vista_nombre = "Tareas - Transición"

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
    vista_nombre = "Tareas - Iniciar gestión"


class CompletarTareaView(TareaLifecycleView):
    accion = "completar"
    vista_nombre = "Tareas - Completar tarea"


class AprobarCierreView(TareaLifecycleView):
    accion = "aprobar"
    vista_nombre = "Tareas - Aprobar cierre"


class RechazarCierreView(TareaLifecycleView):
    accion = "rechazar"
    vista_nombre = "Tareas - Rechazar cierre"


class AnularTareaView(TareaLifecycleView):
    accion = "anular"
    vista_nombre = "Tareas - Anular tarea"


class ReactivarTareaView(TareaLifecycleView):
    accion = "reactivar"
    vista_nombre = "Tareas - Reactivar tarea"
