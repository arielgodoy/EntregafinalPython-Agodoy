"""Vistas de la app tareas (Tareas Internas).

Patrones vigentes reutilizados:
- VerificarPermisoMixin (ICMEAS) + LoginRequiredMixin (access_control/views.py).
- Empresa activa desde request.session["empresa_id"]; nunca desde parámetros.
- Querysets filtrados por empresa activa (404 si pertenece a otra empresa).
"""

import logging
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import urlparse

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q, prefetch_related_objects
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View
from tareas.services.minitask_storage import (
    CreateMiniTaskCommand, CloseMiniTaskCommand, ReopenMiniTaskCommand,
    DeleteMiniTaskCommand, MiniTaskNotFound, resolve_minitask_storage,
)

from acounts.models import Avatar
from access_control.models import Empresa, Permiso, Vista
from access_control.decorators import verificar_permiso
from access_control.services.permissions import (
    get_valid_users_for_empresa,
    user_has_permission_for_empresa,
)
from access_control.views import VerificarPermisoMixin

from .forms import (
    AvanceManualForm,
    AvancePonderadoForm,
    CompletarHitoForm,
    ComentarioForm,
    DocumentoForm,
    EvidenciaConfigForm,
    EvidenciaRegistroForm,
    HitoCumplimientoForm,
    HitoCrearForm,
    HitoForm,
    HitoReasignacionForm,
    MotivoComentarioForm,
    MiniTareaCloseForm,
    MiniTareaCreateForm,
    MiniTareaReopenForm,
    ParticipanteTareaAdminForm,
    ParticipanteRolForm,
    ResponsableTareaForm,
    ReconocerComentariosForm,
    ReunionParticipanteForm,
    ReunionRevisionForm,
    ReunionTareaForm,
    TareaForm,
    TaskEditForm,
    ReprogramTaskForm,
    TareaConnectionRoleForm,
)
from .models import (
    Comentario,
    DocumentoHistorial,
    DocumentoTarea,
    EvaluacionSimilitud,
    EnlaceTarea,
    MiniTareaEvento,
    MiniTarea,
    ReunionRevision,
    Tarea,
    TareaConnectionRole,
    TareaParticipante,
)
from .services.context import get_active_company_id
from .services.participant_storage import (
    AddParticipantCommand,
    ChangeParticipantRoleCommand,
    ReassignResponsibleCommand,
    RemoveParticipantCommand,
    add_task_participant,
    change_participant_role,
    reassign_responsible,
    remove_task_participant,
)
from .services.authorization import can_manage_task
from .services.closure import (
    can_create_mini_task,
)
from .services.comments import create_comment, edit_comment, hide_comment, restore_comment
from .services.reading import (
    COMMENT_PAGE_SIZE,
    count_pending_comments,
    get_first_pending_comment,
    get_initial_comment_page,
    get_previous_comment_page,
    recognize_loaded_comments,
)
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
from .services.participants import effective_participant_ids, is_effective_participant
from .services.similarity import (
    confirm_similarity,
    evaluate_task_similarity,
    get_similarity_threshold,
)
from .services.similarity_storage import SimilarityStorageError, resolve_similarity_storage
from .services.meetings import (
    add_meeting_participant,
    add_task_to_meeting,
    convene_meeting,
    create_meeting,
    mark_meeting_completed,
    update_meeting,
)
from .services.meeting_storage import MeetingNotFound, resolve_meeting_storage
from .services.links import (
    TaskLinkAccessError,
    create_task_link,
    resolve_task_link,
    revoke_task_link,
    revoke_task_link_by_id,
)
from .services.comment_storage import CommentPageCommand, resolve_comment_storage
from .services.connection_roles import get_tarea_connection_status
from .services.task_storage import (
    CreateTaskDraftInput,
    TaskStorageError,
    TaskStorageBackendNotImplemented,
    TaskListFilters,
    DjangoTaskStorage,
    EditTaskNotFound,
    LifecycleSimilarityUnsupported,
    MySQLTaskStorage,
    TaskEditData,
    UpdateTaskCommand,
    create_task_draft,
    ensure_existing_task_backend_supported,
    resolve_edit_storage,
    resolve_list_storage,
)
from .services.detail_storage import (
    DetailTaskNotFound,
    DjangoTaskDetailStorage,
    TaskDetailSections,
    TaskStorageBackendNotImplemented,
    resolve_detail_storage,
)
from .services.closure_storage import ClosureCommand, resolve_closure_storage
from .services.document_storage import (
    DocumentCreateCommand,
    EvidenceCreateCommand,
    resolve_document_storage,
)
from .services.reprogramming_storage import (
    ALLOWED_REPROGRAMMING_STATES,
    ReprogramTaskCommand,
    reprogram_task,
)
from .services.hierarchy_lifecycle_storage import (
    HierarchyLifecycleCommand,
    resolve_hierarchy_lifecycle_storage,
)
from .services.base_tareas_schema import (
    BaseTareasSchemaInstallError,
    install_base_tareas_schema,
)
from .services.milestone_storage import (
    CreateMilestoneCommand, UpdateMilestoneCommand, CompleteMilestoneCommand,
    ReassignMilestoneCommand, SetMilestoneAnnulledCommand, DeleteMilestoneCommand,
    MilestoneNotFound, resolve_milestone_storage,
    UpdateManualProgressCommand, SetWeightedProgressModeCommand,
)
from .services.kpi import (
    DashboardPermissionError,
    get_company_dashboard,
    get_department_dashboard,
    get_general_dashboard,
    get_personal_dashboard,
    get_task_dashboard,
    get_user_dashboard,
)

logger = logging.getLogger(__name__)


def _get_empresa_id(request):
    """Empresa activa desde la sesión (patrón vigente)."""
    return get_active_company_id(request)


def _comment_error_response(status=400):
    return JsonResponse(
        {"success": False, "message_key": "tareas.messages.generic_error"},
        status=status,
    )


def _comment_actor_is_linked(tarea, usuario):
    return usuario.is_active and is_effective_participant(tarea, usuario)


def _comment_actor_has_permission(tarea, usuario, accion):
    return user_has_permission_for_empresa(
        user=usuario,
        empresa=tarea.empresa,
        vista_nombre="Tareas",
        accion=accion,
    )


def _require_task_administration(tarea, actor):
    if not can_manage_task(tarea=tarea, actor=actor):
        raise PermissionDenied("No tienes autorización para administrar esta tarea.")


def _unlinked_comment_page(*, tarea, before_comment=None):
    storage = resolve_comment_storage()
    command = CommentPageCommand(
        tarea.pk, tarea.empresa_id, 0,
        before_id=before_comment.pk if before_comment is not None else None,
        page_size=COMMENT_PAGE_SIZE,
    )
    return storage.list(command)


def _comment_document_data(documento):
    archivo_nombre = ""
    if documento.archivo:
        archivo_nombre = documento.archivo.name.replace("\\", "/").rsplit("/", 1)[-1]
    elif documento.url:
        archivo_nombre = urlparse(documento.url).path.rstrip("/").rsplit("/", 1)[-1]
    return {
        "id": documento.pk,
        "tipo": documento.tipo,
        "tipo_i18n_key": f"tareas.documents.type.{documento.tipo.lower()}",
        "formato_archivo": documento.formato_archivo,
        "url": documento.url,
        "archivo_url": documento.archivo.url if documento.archivo else "",
        "nombre_archivo": archivo_nombre,
    }


def _comment_data(comentario, usuario, puede_supervisar, avatar_url=None):
    def related_items(value):
        return value.all() if hasattr(value, "all") else value

    es_autor = comentario.autor_id == usuario.pk
    puede_ver_contenido = puede_supervisar or not comentario.oculto
    puede_ver_historial = puede_supervisar or (es_autor and not comentario.oculto)
    if comentario.oculto and not puede_ver_contenido:
        return {
            "id": comentario.pk,
            "created_at": comentario.created_at.isoformat(),
            "updated_at": comentario.updated_at.isoformat(),
            "oculto": True,
            "tombstone": True,
        }

    adjuntos = []
    for adjunto in related_items(comentario.adjuntos):
        adjuntos.append(_comment_document_data(adjunto.documento))

    historial = []
    if puede_ver_historial:
        for version in related_items(comentario.versiones):
            historial.append(
                {
                    "evento": version.evento,
                    "numero_version": version.numero_version,
                    "contenido": version.contenido,
                    "actor": {
                        "id": version.actor_id,
                        "username": version.actor.username,
                    },
                    "fecha": version.fecha.isoformat(),
                    "motivo": version.motivo,
                    "adjuntos": [
                        _comment_document_data(relacion.documento)
                        for relacion in related_items(version.documentos)
                    ],
                }
            )

    if avatar_url is None:
        avatar_url = ""
        avatar = getattr(comentario.autor, "avatar", None)
        if (
            avatar is not None
            and avatar.imagen
            and avatar.imagen.name
        ):
            try:
                avatar_url = avatar.imagen.url
            except (OSError, ValueError):
                avatar_url = ""

    return {
        "id": comentario.pk,
        "contenido": comentario.contenido,
        "created_at": comentario.created_at.isoformat(),
        "updated_at": comentario.updated_at.isoformat(),
        "autor": {
            "id": comentario.autor_id,
            "username": comentario.autor.username,
            "avatar_url": avatar_url,
        },
        "oculto": comentario.oculto,
        "editado": any(
            version.numero_version is not None and version.numero_version > 1
            for version in comentario.versiones.all()
        ),
        "puede_ver_historial": puede_ver_historial,
        "historial": historial,
        "tombstone": False,
        "adjuntos": adjuntos,
    }


def _mini_task_event_attachments(evento, puede_supervisar):
    comentario = evento.comentario_feed
    if evento.tipo != MiniTareaEvento.Tipo.CIERRE or comentario is None:
        return []
    if comentario.oculto and not puede_supervisar:
        return []
    return [_comment_document_data(adjunto.documento) for adjunto in comentario.adjuntos.all()]


def _detail_mini_task_policy(core, hierarchy, mini_task, actor, empresa):
    if not actor or not actor.is_active:
        return replace(
            mini_task,
            puede_cerrar_t104=False,
            puede_reabrir_t104=False,
            puede_eliminar_t105=False,
        )
    can_modify = user_has_permission_for_empresa(
        user=actor,
        empresa=empresa,
        vista_nombre="Tareas",
        accion="modificar",
    )
    is_supervisor = user_has_permission_for_empresa(
        user=actor,
        empresa=empresa,
        vista_nombre="Tareas",
        accion="supervisor",
    )
    operational = core.estado in {Tarea.Estado.ACTIVA, Tarea.Estado.GESTION}
    allowed_responsible = actor.pk == core.responsable_id or is_supervisor
    return replace(
        mini_task,
        puede_cerrar_t104=bool(
            can_modify
            and (actor.pk == mini_task.persona_id or allowed_responsible)
            and operational
            and not hierarchy.effectively_annulled
            and not mini_task.hecho
        ),
        puede_reabrir_t104=bool(
            can_modify
            and allowed_responsible
            and operational
            and not hierarchy.effectively_annulled
            and mini_task.hecho
        ),
        puede_eliminar_t105=bool(
            can_modify
            and allowed_responsible
            and operational
            and not hierarchy.effectively_annulled
            and not mini_task.hecho
            and not mini_task.eventos_t104
        ),
    )


def _detail_milestone_context(detail_result, empresa, actor, **form_overrides):
    core = detail_result.core
    explicit_roles = {
        item.rol for item in detail_result.participants if item.user_id == actor.pk
    }
    actor_is_valid = bool(
        actor
        and actor.is_active
        and get_valid_users_for_empresa(empresa).filter(pk=actor.pk).exists()
    )
    manager = bool(
        actor_is_valid
        and (
            actor.pk in {core.creada_por_id, core.responsable_id}
            or explicit_roles.intersection(
                {
                    TareaParticipante.Rol.RESPONSABLE_LIDER,
                    TareaParticipante.Rol.SUPERVISOR,
                    TareaParticipante.Rol.AUTORIZADOR,
                }
            )
            or user_has_permission_for_empresa(
                user=actor,
                empresa=empresa,
                vista_nombre="Tareas - Hitos",
                accion="supervisor",
            )
            or user_has_permission_for_empresa(
                user=actor,
                empresa=empresa,
                vista_nombre="Tareas - Hitos",
                accion="autorizar",
            )
        )
    )
    writable = (
        core.estado in {Tarea.Estado.BORRADOR, Tarea.Estado.ACTIVA, Tarea.Estado.GESTION}
        and not detail_result.hierarchy.effectively_annulled
        and not core.anulada
    )
    permissions = {
        action: actor_is_valid and user_has_permission_for_empresa(
            user=actor, empresa=empresa, vista_nombre="Tareas - Hitos", accion=action,
        )
        for action in ("crear", "modificar", "eliminar")
    }
    milestones = []
    for milestone in detail_result.milestones:
        capability = (
            "manage"
            if manager
            else "progress"
            if actor_is_valid and milestone.responsable_id == actor.pk
            else "read"
        )
        milestones.append(
            replace(
                milestone,
                puede_gestionar=writable and permissions["modificar"] and capability == "manage",
                puede_actualizar=(
                    writable and permissions["modificar"]
                    and capability in {"progress", "manage"}
                    and not milestone.anulado and not milestone.completado
                ),
                puede_completar=(
                    writable and permissions["modificar"]
                    and capability in {"progress", "manage"}
                    and not milestone.completado and not milestone.anulado
                ),
                puede_eliminar=(
                    writable and permissions["eliminar"] and manager
                    and not milestone.completado
                ),
            )
        )
    modal_id = form_overrides.get("modal_abierto_hito_id")
    modal_action = form_overrides.get("modal_abierto_accion")
    modal_milestone = next((item for item in milestones if item.pk == modal_id), None)
    modal_allowed = bool(
        modal_milestone and (
            modal_milestone.puede_completar if modal_action == "completar_hito"
            else modal_milestone.puede_actualizar if modal_action == "cumplimiento_hito"
            else modal_milestone.puede_gestionar
            and not modal_milestone.completado and not modal_milestone.anulado
        )
    )
    return {
        "hitos": tuple(milestones),
        "puede_crear_hito": writable and permissions["crear"] and manager,
        "puede_modificar_avance": writable and permissions["modificar"],
        "progress": detail_result.progress,
        "avance": detail_result.progress,
        "avance_calculado": (
            detail_result.progress.weighted_percentage
            if detail_result.progress is not None
            else "0.00"
        ),
        "hito_form": form_overrides.get(
            "hito_form", HitoCrearForm(empresa=empresa)
        ),
        "responsables_validos": HitoCrearForm(empresa=empresa).fields[
            "responsable"
        ].queryset,
        "editar_form": form_overrides.get("editar_form", HitoForm()),
        "reasignar_form": form_overrides.get(
            "reasignar_form", HitoReasignacionForm(empresa=empresa)
        ),
        "completar_form": form_overrides.get("completar_form", CompletarHitoForm()),
        "modal_abierto_hito_id": modal_id if modal_allowed else None,
        "modal_abierto_accion": modal_action if modal_allowed else None,
        "manual_form": form_overrides.get("manual_form", AvanceManualForm()),
        "ponderado_form": form_overrides.get(
            "ponderado_form", AvancePonderadoForm()
        ),
    }


def _detail_document_context(detail_result, **form_overrides):
    return {
        "documentos": detail_result.documents,
        "evidencias": detail_result.closure_evidence,
        "document_form": form_overrides.get("document_form", DocumentoForm()),
        "evidencia_registro_form": form_overrides.get(
            "evidencia_registro_form", EvidenciaRegistroForm()
        ),
    }


def _detail_task_presentation(core, empresa, effective_ids=None):
    responsable = (
        SimpleNamespace(
            pk=core.responsable_id,
            username=core.responsable_username,
        )
        if core.responsable_id
        else None
    )
    return SimpleNamespace(
        pk=core.id,
        empresa_id=core.empresa_id,
        titulo=core.titulo,
        descripcion=core.descripcion,
        correlativo=core.correlativo,
        estado=core.estado,
        prioridad=core.prioridad,
        anulada=core.anulada,
        fechas_pendientes_confirmacion=core.fechas_pendientes_confirmacion,
        requiere_evidencia_cierre=core.requiere_evidencia_cierre,
        fecha_creacion=core.fecha_creacion,
        fecha_publicacion=core.fecha_publicacion,
        fecha_asignacion=core.fecha_asignacion,
        fecha_tope=core.fecha_tope,
        fecha_cumplimiento=core.fecha_cumplimiento,
        responsable_id=core.responsable_id,
        responsable=responsable,
        empresa=empresa,
        creada_por_id=core.creada_por_id,
        _tareas_effective_user_ids=effective_ids,
    )


def _detail_effective_participant_ids(detail_result):
    ids = {detail_result.core.creada_por_id, detail_result.core.responsable_id}
    ids.update(detail_result.effective_user_ids)
    ids.update(item.user_id for item in detail_result.participants)
    ids.update(item.persona_id for item in detail_result.mini_tasks)
    ids.update(
        item.responsable_id
        for item in detail_result.milestones
        if not item.anulado
    )
    return {item_id for item_id in ids if item_id is not None}


def _detail_can_manage_task(detail_result, actor, empresa):
    return bool(
        actor
        and actor.is_active
        and get_valid_users_for_empresa(empresa, active_only=True)
        .filter(pk=actor.pk)
        .exists()
        and user_has_permission_for_empresa(
            user=actor,
            empresa=empresa,
            vista_nombre="Tareas",
            accion="modificar",
        )
        and (
            actor.pk == detail_result.core.creada_por_id
            or user_has_permission_for_empresa(
                user=actor,
                empresa=empresa,
                vista_nombre="Tareas",
                accion="supervisor",
            )
        )
    )


def _detail_can_create_minitask(detail_result, actor, empresa):
    is_supervisor = user_has_permission_for_empresa(
        user=actor,
        empresa=empresa,
        vista_nombre="Tareas",
        accion="supervisor",
    )
    return bool(
        actor
        and actor.is_active
        and user_has_permission_for_empresa(
            user=actor,
            empresa=empresa,
            vista_nombre="Tareas",
            accion="crear",
        )
        and (actor.pk == detail_result.core.responsable_id or is_supervisor)
        and detail_result.core.estado in {Tarea.Estado.ACTIVA, Tarea.Estado.GESTION}
        and not detail_result.hierarchy.effectively_annulled
    )


class ExistingTaskBackendGuardMixin:
    """Block legacy existing-task flows before their ORM lookup."""

    backend_guard_operation = "existing_task_operation"

    def dispatch(self, request, *args, **kwargs):
        try:
            ensure_existing_task_backend_supported(self.backend_guard_operation)
        except TaskStorageBackendNotImplemented as exc:
            return HttpResponse(str(exc), status=503)
        return super().dispatch(request, *args, **kwargs)


def _get_operational_similarity_task(task_id, empresa_id):
    try:
        resolve_detail_storage().get_task_detail(
            task_id=task_id,
            empresa_id=empresa_id,
            sections=TaskDetailSections(
                mini_tasks=False,
                links=False,
                milestones=False,
                documents=False,
            ),
        )
        with resolve_similarity_storage().atomic() as unit:
            return unit.get_task(task_id, company_id=empresa_id)
    except DetailTaskNotFound as exc:
        raise Http404 from exc
    except (TaskStorageError, SimilarityStorageError) as exc:
        raise TaskStorageError(
            "No se pudo leer el almacenamiento de tareas configurado."
        ) from exc


class ListarTareasView(VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = Tarea
    template_name = "tareas/tarea_lista.html"
    context_object_name = "tareas"
    vista_nombre = "Tareas"
    permiso_requerido = "ingresar"

    def get(self, request, *args, **kwargs):
        empresa_id = _get_empresa_id(request)
        filters = TaskListFilters(
            search=request.GET.get("tarea_busqueda", "").strip(),
            estado=request.GET.get("estado", "").strip(),
            prioridad=request.GET.get("prioridad", "").strip(),
        )
        context = {
            "tareas_busqueda": filters.search,
            "tareas_estado": filters.estado,
            "tareas_prioridad": filters.prioridad,
            "tarea_estados": Tarea.Estado.choices,
            "tarea_prioridades": Tarea.Prioridad.choices,
            "tareas": (),
            "tareas_summary": {
                "total": 0,
                "activas": 0,
                "gestion": 0,
                "cerradas": 0,
            },
        }
        try:
            result = resolve_list_storage().list_tasks(
                empresa_id=empresa_id,
                filters=filters,
            )
        except TaskStorageBackendNotImplemented as exc:
            context["storage_error"] = str(exc)
            return render(request, self.template_name, context, status=503)
        except TaskStorageError as exc:
            context["storage_error"] = str(exc)
            return render(request, self.template_name, context, status=503)
        context["tareas"] = result.items
        context["tareas_summary"] = result.summary
        return render(request, self.template_name, context)


class TareaConnectionRoleView(VerificarPermisoMixin, LoginRequiredMixin, View):
    template_name = "tareas/tarea_conexiones_sql.html"
    vista_nombre = "Tareas - Conexiones SQL"
    permiso_requerido = "ingresar"
    verificar_vicmeas_en_dispatch = False

    def _role_instances(self):
        existing = {
            item.role: item
            for item in TareaConnectionRole.objects.select_related(
                "mysql_connection", "mysql_connection__empresa"
            )
        }
        return [
            (role, label, existing.get(role))
            for role, label in TareaConnectionRole.ROLE_CHOICES
        ]

    def _context(self, forms):
        connection_status = get_tarea_connection_status()
        base_tareas_status = next(
            (
                item
                for item in connection_status["roles"]
                if item["role"] == "BASE_TAREAS"
            ),
            None,
        )
        vista = Vista.objects.filter(nombre=self.vista_nombre).first()
        empresa_id = self.request.session.get("empresa_id")
        can_install_base_tareas = bool(
            base_tareas_status
            and base_tareas_status["status"] == "configured"
            and base_tareas_status["source_type"] == "MYSQL_CONFIG"
            and base_tareas_status["metadata"].get("database_name")
            and vista
            and empresa_id
            and Permiso.objects.filter(
                usuario=self.request.user,
                empresa_id=empresa_id,
                vista=vista,
                supervisor=True,
            ).exists()
        )
        return {
            "role_forms": forms,
            "connection_status": connection_status,
            "can_install_base_tareas": can_install_base_tareas,
            "base_tareas_database_name": (
                base_tareas_status["metadata"].get("database_name")
                if base_tareas_status
                else None
            ),
            "vista_nombre": self.vista_nombre,
        }

    @method_decorator(verificar_permiso(vista_nombre, "ingresar"))
    def get(self, request):
        forms = []
        for role, label, instance in self._role_instances():
            form = TareaConnectionRoleForm(
                prefix=f"role-{role}",
                instance=instance or TareaConnectionRole(role=role),
                role=role,
            )
            forms.append({"role": role, "label": label, "form": form})
        return render(request, self.template_name, self._context(forms))

    @method_decorator(verificar_permiso(vista_nombre, "modificar"))
    def post(self, request):
        forms = []
        for role, label, instance in self._role_instances():
            form = TareaConnectionRoleForm(
                request.POST,
                prefix=f"role-{role}",
                instance=instance or TareaConnectionRole(role=role),
                role=role,
            )
            forms.append({"role": role, "label": label, "form": form})

        if not all(item["form"].is_valid() for item in forms):
            return render(request, self.template_name, self._context(forms), status=400)

        with transaction.atomic():
            for item in forms:
                item["form"].save()
        messages.success(request, "La configuración de conexiones SQL fue guardada.")
        return redirect(reverse("tareas:conexiones_sql"))


@method_decorator(
    verificar_permiso("Tareas - Conexiones SQL", "supervisor"),
    name="dispatch",
)
class BaseTareasSchemaInstallView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            install_base_tareas_schema()
        except BaseTareasSchemaInstallError:
            messages.error(request, "tareas.connection_roles.bootstrap.error")
        else:
            messages.success(
                request,
                "tareas.connection_roles.bootstrap.success",
            )
        return redirect(reverse("tareas:conexiones_sql"))


class MisTareasDashboardView(VerificarPermisoMixin, LoginRequiredMixin, View):
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
        try:
            context = self.get_context_data()
        except TaskStorageError:
            logger.error("Assigned MiniTask storage failure")
            return HttpResponse(
                render(request, self.template_name, {"mini_storage_error": True}).content,
                status=503,
            )
        return render(request, self.template_name, context)


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
        return render(request, "tareas/dashboard_general.html", context)


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
        return render(request, "tareas/dashboard_empresa.html", context)


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
        return render(request, "tareas/dashboard_departamento.html", context)


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
        return render(request, "tareas/dashboard_usuario.html", context)


class DetalleTareaView(VerificarPermisoMixin, LoginRequiredMixin, DetailView):
    model = Tarea
    template_name = "tareas/tarea_detalle.html"
    context_object_name = "tarea"
    vista_nombre = "Tareas"
    permiso_requerido = "ingresar"

    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(request, *args, **kwargs)
        except TaskStorageBackendNotImplemented:
            return HttpResponse(
                "El backend MYSQL de Detail aún no está implementado.",
                status=503,
            )
        except TaskStorageError:
            return HttpResponse(
                "No se pudo leer el almacenamiento de tareas configurado.",
                status=503,
            )

    def get_object(self, queryset=None):
        empresa_id = _get_empresa_id(self.request)
        try:
            empresa = Empresa.objects.get(pk=empresa_id)
        except Empresa.DoesNotExist as exc:
            raise Http404 from exc
        puede_ver_hitos = user_has_permission_for_empresa(
            user=self.request.user,
            empresa=empresa,
            vista_nombre="Tareas - Hitos",
            accion="ingresar",
        )
        puede_ver_documentos = user_has_permission_for_empresa(
            user=self.request.user,
            empresa=empresa,
            vista_nombre="Tareas - Documentos y evidencia",
            accion="modificar",
        )
        try:
            result = resolve_detail_storage().get_task_detail(
                task_id=self.kwargs["pk"],
                empresa_id=empresa_id,
                sections=TaskDetailSections(
                    milestones=puede_ver_hitos,
                    documents=puede_ver_documentos,
                ),
            )
        except DetailTaskNotFound as exc:
            raise Http404 from exc
        self.detail_result = result
        self.detail_empresa = empresa
        return _detail_task_presentation(result.core, empresa, _detail_effective_participant_ids(result))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["detail_core"] = self.detail_result.core
        context["reprogramming_history"] = self.detail_result.reprogramming_history
        context["puede_reprogramar"] = bool(
            self.request.user.is_active
            and self.detail_result.core.estado in ALLOWED_REPROGRAMMING_STATES
            and not self.detail_result.hierarchy.effectively_annulled
            and get_valid_users_for_empresa(
                self.detail_empresa, active_only=True
            ).filter(pk=self.request.user.pk).exists()
            and user_has_permission_for_empresa(
                user=self.request.user, empresa=self.detail_empresa,
                vista_nombre="Tareas", accion="modificar",
            )
        )
        context["reprogramming_form"] = ReprogramTaskForm(
            causes=self.detail_result.reprogramming_causes
        )
        hierarchy = self.detail_result.hierarchy
        context["tarea_padre"] = hierarchy.parent
        context["tareas_hijas"] = hierarchy.children
        context["tarea_anulada_efectivamente"] = hierarchy.effectively_annulled
        effective_ids = _detail_effective_participant_ids(self.detail_result)
        comentarios_vinculado = (
            self.request.user.is_active and self.request.user.pk in effective_ids
        )
        comentarios_puede_ver = self.request.user.is_active and user_has_permission_for_empresa(
            user=self.request.user,
            empresa=self.detail_empresa,
            vista_nombre="Tareas",
            accion="ingresar",
        )
        comentarios_puede_crear = comentarios_vinculado and user_has_permission_for_empresa(
            user=self.request.user,
            empresa=self.detail_empresa,
            vista_nombre="Tareas",
            accion="crear",
        )
        comentarios_puede_modificar = comentarios_vinculado and user_has_permission_for_empresa(
            user=self.request.user,
            empresa=self.detail_empresa,
            vista_nombre="Tareas",
            accion="modificar",
        )
        comentarios_puede_supervisar = comentarios_vinculado and user_has_permission_for_empresa(
            user=self.request.user,
            empresa=self.detail_empresa,
            vista_nombre="Tareas",
            accion="supervisor",
        )
        context["comentarios_puede_ver"] = comentarios_puede_ver
        context["comentarios_vinculado"] = comentarios_vinculado
        context["comentarios_puede_crear"] = comentarios_puede_crear
        context["comentarios_puede_modificar"] = comentarios_puede_modificar
        context["comentarios_puede_supervisar"] = comentarios_puede_supervisar
        comentarios_lifecycle_interactivo = (
            self.detail_result.core.estado
            in {
                Tarea.Estado.ACTIVA,
                Tarea.Estado.GESTION,
                Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
            }
            and not context["tarea_anulada_efectivamente"]
        )
        context["comentarios_lifecycle_interactivo"] = comentarios_lifecycle_interactivo
        context["comentarios_mutables"] = (
            comentarios_puede_crear
            and comentarios_lifecycle_interactivo
        )
        context["comentarios_editables"] = (
            comentarios_puede_modificar
            and comentarios_lifecycle_interactivo
        )
        context["puede_administrar_tarea"] = _detail_can_manage_task(
            self.detail_result,
            self.request.user,
            self.detail_empresa,
        )
        context["puede_configurar_evidencia"] = user_has_permission_for_empresa(
            user=self.request.user,
            empresa=self.detail_empresa,
            vista_nombre="Tareas",
            accion="modificar",
        )
        context["evidencia_config_form"] = kwargs.get(
            "evidencia_config_form",
            EvidenciaConfigForm(
                initial={
                    "requiere_evidencia_cierre": self.detail_result.core.requiere_evidencia_cierre
                }
            ),
        )
        context["enlaces"] = self.detail_result.links
        context["destinatarios_enlace"] = get_valid_users_for_empresa(
            self.detail_empresa, active_only=True
        ).exclude(pk=self.request.user.pk)
        participantes_explicitos = self.detail_result.participants
        context["participantes_explicitos"] = participantes_explicitos
        implicit_ids = {
            self.detail_result.core.creada_por_id,
            self.detail_result.core.responsable_id,
        }
        explicit_ids = {item.user_id for item in participantes_explicitos}
        context["participantes_elegibles"] = get_valid_users_for_empresa(
            self.detail_empresa, active_only=True
        ).exclude(pk__in=implicit_ids | explicit_ids)
        context["puede_administrar_participantes"] = (
            context["puede_administrar_tarea"]
            and self.detail_result.core.estado in {
                Tarea.Estado.BORRADOR, Tarea.Estado.ACTIVA,
                Tarea.Estado.GESTION, Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
            }
            and not hierarchy.effectively_annulled
        )
        context["participantes_visuales"] = tuple(
            item for item in participantes_explicitos
            if item.user_id not in implicit_ids
        )
        context["participante_form"] = kwargs.get(
            "participante_form",
            ParticipanteTareaAdminForm(
                empresa=self.detail_empresa, active_only=True,
                excluded_ids=implicit_ids | explicit_ids,
            ),
        )
        context["responsable_form"] = kwargs.get(
            "responsable_form",
            ResponsableTareaForm(
                empresa=self.detail_empresa,
                responsable_id=self.detail_result.core.responsable_id,
                estado=self.detail_result.core.estado,
            ),
        )
        context["responsables_validos"] = get_valid_users_for_empresa(
            self.detail_empresa,
            active_only=True,
        )
        puede_supervisar_adjuntos = user_has_permission_for_empresa(
            user=self.request.user,
            empresa=self.detail_empresa,
            vista_nombre="Tareas",
            accion="supervisor",
        )
        mini_tareas = []
        for mini_tarea in self.detail_result.mini_tasks:
            if not puede_supervisar_adjuntos:
                last_close = next((
                    event for event in reversed(mini_tarea.eventos_t104)
                    if event.tipo == MiniTareaEvento.Tipo.CIERRE
                ), None)
                mini_tarea = replace(
                    mini_tarea,
                    ultimo_cierre_adjuntos_t104=(
                        last_close.attachments
                        if mini_tarea.hecho and last_close and not last_close.comentario_oculto else ()
                    ),
                )
            mini_tareas.append(
                _detail_mini_task_policy(
                    self.detail_result.core,
                    self.detail_result.hierarchy,
                    mini_tarea,
                    self.request.user,
                    self.detail_empresa,
                )
            )
        context["mini_tareas"] = tuple(mini_tareas)
        context["puede_crear_minitarea"] = _detail_can_create_minitask(
            self.detail_result,
            self.request.user,
            self.detail_empresa,
        )
        context["mini_tarea_create_form"] = MiniTareaCreateForm(
            empresa=self.detail_empresa,
        )
        context["mini_tarea_destinatarios"] = get_valid_users_for_empresa(
            self.detail_empresa,
            active_only=True,
        ).filter(pk__in=_detail_effective_participant_ids(self.detail_result)).exclude(
            pk=self.request.user.pk
        ).order_by("username")
        context["puede_ver_hitos"] = user_has_permission_for_empresa(
            user=self.request.user,
            empresa=self.detail_empresa,
            vista_nombre="Tareas - Hitos",
            accion="ingresar",
        )
        if context["puede_ver_hitos"]:
            context.update(
                _detail_milestone_context(
                    self.detail_result,
                    self.detail_empresa,
                    self.request.user,
                )
            )
            context["hitos_action_url"] = reverse(
                "tareas:hitos_tarea",
                kwargs={"pk": self.detail_result.core.id},
            )
            context["hitos_return_to_detail"] = True
        context["puede_ver_documentos"] = user_has_permission_for_empresa(
            user=self.request.user,
            empresa=self.detail_empresa,
            vista_nombre="Tareas - Documentos y evidencia",
            accion="modificar",
        )
        if context["puede_ver_documentos"]:
            context.update(_detail_document_context(self.detail_result))
            context["documents_action_url"] = reverse(
                "tareas:documentos_tarea",
                kwargs={"pk": self.detail_result.core.id},
            )
            context["documents_return_to_detail"] = True
            context.setdefault("documentos_tab_activo", False)
        return context

    @method_decorator(verificar_permiso("Tareas", "modificar"))
    def post(self, request, *args, **kwargs):
        task_id = kwargs["pk"]
        empresa_id = _get_empresa_id(request)
        form = EvidenciaConfigForm(request.POST)
        if form.is_valid():
            try:
                resolve_document_storage().configure_evidence(
                    task_id=task_id,
                    empresa_id=empresa_id,
                    usuario_id=request.user.pk,
                    required=form.cleaned_data["requiere_evidencia_cierre"],
                )
            except EditTaskNotFound as exc:
                raise Http404 from exc
            messages.success(request, "tareas.messages.evidence_configuration_updated")
            return redirect("tareas:detalle_tarea", pk=task_id)
        self.object = self.get_object()
        context = self.get_context_data(object=self.object)
        context["evidencia_config_form"] = form
        return self.render_to_response(context)


class ReprogramarTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Tareas"
    permiso_requerido = "modificar"
    crear_permiso_faltante = False
    http_method_names = ["post"]

    def post(self, request, pk):
        form = ReprogramTaskForm(request.POST)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
        else:
            try:
                reprogram_task(ReprogramTaskCommand(
                    task_id=pk, empresa_id=_get_empresa_id(request),
                    actor_id=request.user.pk,
                    fecha_tope_nueva=form.cleaned_data["fecha_tope_nueva"],
                    justificacion=form.cleaned_data["justificacion"],
                    causa_ids=form.cleaned_data["causa_ids"],
                ))
            except EditTaskNotFound as exc:
                raise Http404 from exc
            except PermissionDenied:
                return self.handle_no_permission(request)
            except ValidationError as exc:
                for message in exc.messages:
                    messages.error(request, message)
            except TaskStorageError as exc:
                logger.error("Reprogramming storage failure: task=%s", pk)
                messages.error(request, str(exc))
            else:
                messages.success(request, "tareas.reprogramming.success")
        return redirect(
            reverse("tareas:detalle_tarea", kwargs={"pk": pk}) + "#tarea-reprogramaciones"
        )


class MiniTareaEndpointMixin:
    crear_permiso_faltante = False

    def dispatch(self, request, *args, **kwargs):
        try:
            self.mini_storage = resolve_minitask_storage()
            return super().dispatch(request, *args, **kwargs)
        except MiniTaskNotFound as exc:
            raise Http404 from exc
        except PermissionDenied:
            return self.handle_no_permission(request)
        except TaskStorageError:
            logger.error("MiniTask endpoint storage failure")
            messages.error(request, "tareas.messages.generic_error")
            return HttpResponse(
                render(request, "tareas/mini_tarea_historial.html", {"storage_error": True}).content,
                status=503,
            )

    def scope(self, request, tarea_id):
        return dict(task_id=tarea_id, empresa_id=_get_empresa_id(request), actor_id=request.user.pk)

    def get_tarea(self, request, tarea_id):
        empresa = get_object_or_404(Empresa.objects.using("default"), pk=_get_empresa_id(request))
        detail = self.mini_storage.detail(task_id=tarea_id, empresa_id=empresa.pk)
        return _detail_task_presentation(
            detail.core, empresa, _detail_effective_participant_ids(detail)
        ), detail

    def redirect_to_detail(self, tarea):
        return redirect("tareas:detalle_tarea", pk=tarea.pk)

    def reject(self, request, tarea):
        messages.error(request, "tareas.messages.generic_error")
        return self.redirect_to_detail(tarea)


class CrearMiniTareaView(
    VerificarPermisoMixin,
    LoginRequiredMixin,
    MiniTareaEndpointMixin,
    View,
):
    vista_nombre = "Tareas"
    permiso_requerido = "crear"
    crear_permiso_faltante = False

    def post(self, request, tarea_id):
        tarea, _detail = self.get_tarea(request, tarea_id)
        form = MiniTareaCreateForm(request.POST, empresa=tarea.empresa)
        if not form.is_valid():
            return self.reject(request, tarea)
        try:
            self.mini_storage.create(CreateMiniTaskCommand(
                **self.scope(request, tarea_id), descripcion=form.cleaned_data["descripcion"],
                persona_id=form.cleaned_data["persona"].pk,
            ))
        except ValidationError:
            return self.reject(request, tarea)
        messages.success(request, "tareas.messages.lifecycle_action_applied")
        return self.redirect_to_detail(tarea)


class CerrarMiniTareaView(
    VerificarPermisoMixin,
    LoginRequiredMixin,
    MiniTareaEndpointMixin,
    View,
):
    vista_nombre = "Tareas"
    permiso_requerido = "modificar"
    crear_permiso_faltante = False

    def post(self, request, tarea_id, mini_tarea_id):
        tarea, detail = self.get_tarea(request, tarea_id)
        if not any(mini.id == mini_tarea_id for mini in detail.mini_tasks):
            raise Http404
        form = MiniTareaCloseForm(
            request.POST,
            request.FILES,
            empresa=tarea.empresa, effective_ids=_detail_effective_participant_ids(detail),
            actor=request.user,
        )
        if not form.is_valid():
            return self.reject(request, tarea)
        try:
            result = self.mini_storage.close(CloseMiniTaskCommand(
                **self.scope(request, tarea_id), mini_task_id=mini_tarea_id,
                comentario=form.cleaned_data["comentario"],
                notification_recipient_ids=tuple(
                    user.pk
                    for user in form.cleaned_data["destinatarios_notificacion"]
                ),
                email_recipient_ids=tuple(
                    user.pk for user in form.cleaned_data["destinatarios_email"]
                ),
                uploaded_files=tuple(form.cleaned_data["archivos"]),
            ))
        except ValidationError:
            return self.reject(request, tarea)
        messages.success(request, "tareas.messages.lifecycle_action_applied")
        if result.delivery.failed:
            messages.warning(request, "tareas.minitareas.communication_failed")
        return self.redirect_to_detail(tarea)


class ReabrirMiniTareaView(
    VerificarPermisoMixin,
    LoginRequiredMixin,
    MiniTareaEndpointMixin,
    View,
):
    vista_nombre = "Tareas"
    permiso_requerido = "modificar"
    crear_permiso_faltante = False

    def post(self, request, tarea_id, mini_tarea_id):
        tarea, _detail = self.get_tarea(request, tarea_id)
        form = MiniTareaReopenForm(request.POST)
        if not form.is_valid():
            return self.reject(request, tarea)
        try:
            self.mini_storage.reopen(ReopenMiniTaskCommand(
                **self.scope(request, tarea_id), mini_task_id=mini_tarea_id,
                comentario=form.cleaned_data["comentario"],
            ))
        except ValidationError:
            return self.reject(request, tarea)
        messages.success(request, "tareas.messages.lifecycle_action_applied")
        return self.redirect_to_detail(tarea)


class EliminarMiniTareaView(
    VerificarPermisoMixin,
    LoginRequiredMixin,
    MiniTareaEndpointMixin,
    View,
):
    vista_nombre = "Tareas"
    permiso_requerido = "modificar"
    crear_permiso_faltante = False

    def post(self, request, tarea_id, mini_tarea_id):
        tarea, _detail = self.get_tarea(request, tarea_id)
        try:
            self.mini_storage.delete(DeleteMiniTaskCommand(
                **self.scope(request, tarea_id), mini_task_id=mini_tarea_id,
            ))
        except ValidationError:
            return self.reject(request, tarea)
        messages.success(request, "tareas.messages.minitask_deleted")
        return self.redirect_to_detail(tarea)


class HistorialMiniTareaView(
    VerificarPermisoMixin,
    LoginRequiredMixin,
    MiniTareaEndpointMixin,
    View,
):
    vista_nombre = "Tareas"
    permiso_requerido = "ingresar"
    crear_permiso_faltante = False

    def get(self, request, tarea_id, mini_tarea_id):
        detail, mini_tarea = self.mini_storage.history(
            **self.scope(request, tarea_id), mini_task_id=mini_tarea_id,
        )
        empresa = get_object_or_404(Empresa.objects.using("default"), pk=_get_empresa_id(request))
        tarea = _detail_task_presentation(detail.core, empresa, _detail_effective_participant_ids(detail))
        supervisor = user_has_permission_for_empresa(
            user=request.user, empresa=empresa, vista_nombre="Tareas", accion="supervisor",
        )
        eventos = [SimpleNamespace(
            actor_username=event.actor_username, fecha=event.fecha, tipo=event.tipo,
            comentario=event.comentario,
            adjuntos_t104=event.attachments if supervisor or not event.comentario_oculto else (),
        ) for event in mini_tarea.eventos_t104]
        return render(
            request,
            "tareas/mini_tarea_historial.html",
            {"tarea": tarea, "mini_tarea": mini_tarea, "eventos": eventos},
        )


class TareaComentariosView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Tareas"
    crear_permiso_faltante = False

    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(request, *args, **kwargs)
        except Http404:
            raise
        except ValidationError:
            return _comment_error_response()
        except Exception as error:
            logger.error(
                "Tareas comment endpoint failed (%s)",
                type(error).__name__,
            )
            return _comment_error_response(status=500)

    def get_tarea(self, request, tarea_id):
        empresa_id = _get_empresa_id(request)
        try:
            detail = resolve_detail_storage().get_task_detail(
                task_id=tarea_id,
                empresa_id=empresa_id,
                sections=TaskDetailSections(
                    milestones=False, documents=False, links=False,
                ),
            )
        except DetailTaskNotFound as exc:
            raise Http404 from exc
        empresa = get_object_or_404(Empresa, pk=empresa_id)
        core = detail.core
        effective_ids = set(detail.effective_user_ids)
        effective_ids.update(participant.user_id for participant in detail.participants)
        effective_ids.update(
            item for item in (core.creada_por_id, core.responsable_id) if item is not None
        )
        tarea = SimpleNamespace(
            pk=core.id, empresa_id=core.empresa_id, empresa=empresa,
            estado=core.estado, anulada=core.anulada,
            responsable_id=core.responsable_id, creada_por_id=core.creada_por_id,
            _tareas_effective_user_ids=effective_ids,
        )
        return tarea


class ListarComentariosView(TareaComentariosView):
    permiso_requerido = "ingresar"

    def get(self, request, tarea_id):
        tarea = self.get_tarea(request, tarea_id)
        after_id = request.GET.get("after_id")
        updated_after = request.GET.get("updated_after")
        updated_after_id = request.GET.get("updated_after_id", "0")
        updated_cursor = None
        if updated_after:
            updated_cursor = parse_datetime(updated_after)
            if updated_cursor is None:
                return _comment_error_response()
            try:
                updated_after_id = int(updated_after_id)
            except (TypeError, ValueError):
                return _comment_error_response()
            if updated_after_id < 0:
                return _comment_error_response()
        if after_id is not None:
            try:
                after_id = int(after_id)
            except (TypeError, ValueError):
                return _comment_error_response()
            if after_id < 0:
                return _comment_error_response()
            comentarios = resolve_comment_storage().list(CommentPageCommand(
                tarea.pk, tarea.empresa_id, request.user.pk,
                after_id=after_id, page_size=COMMENT_PAGE_SIZE,
                updated_after=updated_cursor,
                updated_after_id=updated_after_id,
            ))
            if comentarios and not hasattr(comentarios[0], "author_id"):
                prefetch_related_objects(
                    comentarios,
                    "autor__avatar",
                    "adjuntos__documento",
                    "versiones__actor",
                    "versiones__documentos__documento",
                )
            comentarios_vinculado = _comment_actor_is_linked(tarea, request.user)
            pendientes = 0
            primer_pendiente = None
            comentarios_reconocibles = []
            if comentarios and comentarios_vinculado:
                try:
                    pendientes = count_pending_comments(tarea=tarea, usuario=request.user)
                    primer_pendiente = get_first_pending_comment(
                        tarea=tarea,
                        usuario=request.user,
                    )
                    if primer_pendiente is not None:
                        comentarios_reconocibles = get_initial_comment_page(
                            tarea=tarea,
                            usuario=request.user,
                        )
                except ValidationError:
                    return _comment_error_response()
            puede_supervisar = user_has_permission_for_empresa(
                user=request.user,
                empresa=tarea.empresa,
                vista_nombre="Tareas",
                accion="supervisor",
            )
            payload = {
                "success": True,
                "comentarios": [
                    _comment_data(comentario, request.user, puede_supervisar)
                    for comentario in comentarios
                ],
                "pendientes": pendientes,
                "primer_pendiente_id": (
                    primer_pendiente.pk if primer_pendiente is not None else None
                ),
                "page_size": len(comentarios),
                "before_comment_id": None,
            }
            if comentarios:
                payload["comentarios_reconocibles_ids"] = [
                    comentario.pk for comentario in comentarios_reconocibles
                ]
            return JsonResponse(payload)
        comentarios_vinculado = _comment_actor_is_linked(tarea, request.user)
        before = request.GET.get("before")
        if before:
            try:
                before_id = int(before)
            except (TypeError, ValueError):
                return _comment_error_response()
            before_comment = resolve_comment_storage().get(
                before_id, tarea.pk, tarea.empresa_id,
            )
            if comentarios_vinculado:
                try:
                    comentarios = get_previous_comment_page(
                        tarea=tarea,
                        usuario=request.user,
                        before_comment=before_comment,
                    )
                except ValidationError:
                    return _comment_error_response()
            else:
                comentarios = _unlinked_comment_page(
                    tarea=tarea,
                    before_comment=before_comment,
                )
        else:
            if comentarios_vinculado:
                try:
                    comentarios = get_initial_comment_page(
                        tarea=tarea,
                        usuario=request.user,
                    )
                except ValidationError:
                    return _comment_error_response()
            else:
                comentarios = _unlinked_comment_page(tarea=tarea)

        if comentarios_vinculado:
            try:
                pendientes = count_pending_comments(tarea=tarea, usuario=request.user)
                primer_pendiente = get_first_pending_comment(
                    tarea=tarea,
                    usuario=request.user,
                )
                comentarios_reconocibles = (
                    get_initial_comment_page(tarea=tarea, usuario=request.user)
                    if primer_pendiente is not None
                    else []
                )
            except ValidationError:
                return _comment_error_response()
        else:
            pendientes = 0
            primer_pendiente = None
            comentarios_reconocibles = []

        if comentarios and not hasattr(comentarios[0], "author_id"):
            prefetch_related_objects(
                comentarios,
                "autor__avatar",
                "adjuntos__documento",
                "versiones__actor",
                "versiones__documentos__documento",
            )

        puede_supervisar = user_has_permission_for_empresa(
            user=request.user,
            empresa=tarea.empresa,
            vista_nombre="Tareas",
            accion="supervisor",
        )
        return JsonResponse(
            {
                "success": True,
                "comentarios": [
                    _comment_data(comentario, request.user, puede_supervisar)
                    for comentario in comentarios
                ],
                "pendientes": pendientes,
                "primer_pendiente_id": (
                    primer_pendiente.pk if primer_pendiente is not None else None
                ),
                "comentarios_reconocibles_ids": [
                    comentario.pk for comentario in comentarios_reconocibles
                ],
                "page_size": COMMENT_PAGE_SIZE,
                "before_comment_id": comentarios[0].pk if comentarios else None,
            }
        )


class MarcarComentariosLeidosView(TareaComentariosView):
    permiso_requerido = "ingresar"

    def post(self, request, tarea_id):
        # Personal reading state: allowed on closed/annulled tasks (FR-T08).
        tarea = self.get_tarea(request, tarea_id)
        if not _comment_actor_is_linked(tarea, request.user):
            return _comment_error_response(status=403)
        form = ReconocerComentariosForm(request.POST, tarea=tarea)
        if not form.is_valid():
            return _comment_error_response()
        if not _comment_actor_has_permission(tarea, request.user, "ingresar"):
            return _comment_error_response(status=403)
        lectura = recognize_loaded_comments(
            tarea=tarea,
            usuario=request.user,
            comentario_ids=form.cleaned_data["comentario_ids"],
        )
        pendientes = count_pending_comments(tarea=tarea, usuario=request.user)
        return JsonResponse(
            {
                "success": True,
                "comentario_leido_hasta_id": lectura.comentario_leido_hasta_id,
                "pendientes": pendientes,
            }
        )


class CrearComentarioView(TareaComentariosView):
    permiso_requerido = "crear"

    def post(self, request, tarea_id):
        tarea = self.get_tarea(request, tarea_id)
        if not _comment_actor_is_linked(tarea, request.user):
            return _comment_error_response(status=403)
        form = ComentarioForm(request.POST, request.FILES, tarea=tarea)
        if not form.is_valid():
            return _comment_error_response()
        try:
            comentario = create_comment(
                tarea=tarea,
                usuario=request.user,
                contenido=form.cleaned_data.get("contenido", ""),
                documentos=form.cleaned_data["documentos"],
                documentos_nuevos=form.nuevos_documentos(),
            )
        except ValidationError:
            return _comment_error_response()
        avatar = Avatar.objects.filter(user_id=request.user.pk).first()
        request.user.avatar = avatar
        puede_supervisar = user_has_permission_for_empresa(
            user=request.user,
            empresa=tarea.empresa,
            vista_nombre="Tareas",
            accion="supervisor",
        )
        return JsonResponse(
            {
                "success": True,
                "comentario": _comment_data(
                    comentario,
                    request.user,
                    puede_supervisar,
                    avatar_url=(
                        avatar.imagen.url
                        if avatar is not None
                        and avatar.imagen
                        else ""
                    ),
                ),
            }
        )


class EditarComentarioView(TareaComentariosView):
    permiso_requerido = "modificar"

    def post(self, request, tarea_id, comentario_id):
        tarea = self.get_tarea(request, tarea_id)
        if not _comment_actor_is_linked(tarea, request.user):
            return _comment_error_response(status=403)
        comentario = resolve_comment_storage().get(
            comentario_id, tarea.pk, tarea.empresa_id,
        )
        if comentario.autor_id != request.user.pk:
            return _comment_error_response(status=403)
        form = ComentarioForm(request.POST, request.FILES, tarea=tarea)
        if not form.is_valid():
            return _comment_error_response()
        cambios = {
            "comentario": comentario,
            "usuario": request.user,
            "documentos_nuevos": form.nuevos_documentos(),
        }
        if "contenido" in request.POST:
            cambios["contenido"] = form.cleaned_data.get("contenido", "")
        if "documentos_modificados" in request.POST or "documentos" in request.POST:
            cambios["documentos"] = form.cleaned_data["documentos"]
        try:
            comentario = edit_comment(**cambios)
        except ValidationError:
            return _comment_error_response()
        puede_supervisar = user_has_permission_for_empresa(
            user=request.user,
            empresa=tarea.empresa,
            vista_nombre="Tareas",
            accion="supervisor",
        )
        return JsonResponse(
            {
                "success": True,
                "comentario": _comment_data(comentario, request.user, puede_supervisar),
            }
        )


class _CambiarVisibilidadComentarioView(TareaComentariosView):
    permiso_requerido = "supervisor"
    servicio = None

    def post(self, request, tarea_id, comentario_id):
        tarea = self.get_tarea(request, tarea_id)
        if not _comment_actor_is_linked(tarea, request.user):
            return _comment_error_response(status=403)
        comentario = resolve_comment_storage().get(
            comentario_id, tarea.pk, tarea.empresa_id,
        )
        form = MotivoComentarioForm(request.POST)
        if not form.is_valid():
            return _comment_error_response()
        try:
            comentario = self.servicio(
                comentario=comentario,
                usuario=request.user,
                motivo=form.cleaned_data["motivo"],
            )
        except ValidationError:
            return _comment_error_response()
        return JsonResponse(
            {
                "success": True,
                "comentario": _comment_data(comentario, request.user, True),
            }
        )


class OcultarComentarioView(_CambiarVisibilidadComentarioView):
    servicio = staticmethod(hide_comment)


class RestaurarComentarioView(_CambiarVisibilidadComentarioView):
    servicio = staticmethod(restore_comment)


class ParticipantAdministrationView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Tareas"
    permiso_requerido = "modificar"
    crear_permiso_faltante = False
    http_method_names = ["post"]
    json_response = False

    def post(self, request, tarea_id, **kwargs):
        try:
            result = self.execute(request, tarea_id, **kwargs)
        except EditTaskNotFound as exc:
            raise Http404 from exc
        except PermissionDenied:
            if self.json_response:
                return JsonResponse({
                    "success": False, "message_key": "tareas.assignment.errors.permission",
                }, status=403)
            return self.handle_no_permission(request)
        except (ValidationError, TaskStorageError) as exc:
            key = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
            if self.json_response:
                status = 400
                if key == "tareas.assignment.errors.invalid_user" or key == "tareas.assignment.errors.missing":
                    status = 404
                elif key == "tareas.assignment.errors.duplicate":
                    status = 409
                elif isinstance(exc, TaskStorageError):
                    status = 503
                return JsonResponse({"success": False, "message_key": key}, status=status)
            messages.error(request, key)
        else:
            if self.json_response:
                data = {
                    "success": True, "message_key": "tareas.assignment.success",
                    "changed": result.changed,
                }
                if isinstance(self, VincularParticipanteView):
                    user = User.objects.using("default").filter(pk=result.user_id).first()
                    data["participante"] = {
                        "id": result.user_id, "username": user.username if user else str(result.user_id),
                    }
                else:
                    data["participante_id"] = result.user_id
                return JsonResponse(data)
            messages.success(request, "tareas.assignment.success")
        return redirect("tareas:detalle_tarea", pk=tarea_id)

    def scope(self, request, tarea_id):
        return {
            "task_id": tarea_id, "empresa_id": _get_empresa_id(request),
            "actor_id": request.user.pk,
        }


class VincularParticipanteDetalleView(ParticipantAdministrationView):
    def execute(self, request, tarea_id, **kwargs):
        try:
            user_id = int(request.POST.get("usuario", ""))
        except (TypeError, ValueError) as exc:
            raise ValidationError("tareas.assignment.errors.invalid_user") from exc
        return add_task_participant(AddParticipantCommand(
            **self.scope(request, tarea_id), user_id=user_id,
            role=request.POST.get("rol", TareaParticipante.Rol.PARTICIPANTE),
        ))


class VincularParticipanteView(ParticipantAdministrationView):
    json_response = True

    def execute(self, request, tarea_id, usuario_id):
        return add_task_participant(AddParticipantCommand(
            **self.scope(request, tarea_id), user_id=usuario_id,
        ))


class DesvincularParticipanteDetalleView(ParticipantAdministrationView):
    def execute(self, request, tarea_id, usuario_id):
        return remove_task_participant(RemoveParticipantCommand(
            **self.scope(request, tarea_id), user_id=usuario_id,
        ))


class DesvincularParticipanteView(DesvincularParticipanteDetalleView):
    json_response = True


class CambiarRolParticipanteView(ParticipantAdministrationView):
    def execute(self, request, tarea_id, usuario_id):
        form = ParticipanteRolForm(request.POST)
        if not form.is_valid():
            raise ValidationError("tareas.assignment.errors.invalid_role")
        return change_participant_role(ChangeParticipantRoleCommand(
            **self.scope(request, tarea_id), user_id=usuario_id,
            new_role=form.cleaned_data["rol"],
        ))


class AdministrarResponsableDetalleView(ParticipantAdministrationView):
    def execute(self, request, tarea_id):
        value = request.POST.get("responsable", "")
        try:
            new_id = int(value) if value else None
        except (TypeError, ValueError) as exc:
            raise ValidationError("tareas.assignment.errors.invalid_user") from exc
        return reassign_responsible(ReassignResponsibleCommand(
            **self.scope(request, tarea_id), new_responsible_id=new_id,
            reason=request.POST.get("motivo", ""),
        ))


class CrearEnlaceTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Tareas"
    permiso_requerido = "modificar"
    crear_permiso_faltante = False

    def post(self, request, tarea_id):
        empresa_id = _get_empresa_id(request)
        empresa = get_object_or_404(Empresa, pk=empresa_id)
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
                tarea_id=tarea_id,
                empresa=empresa,
                destinatario=destinatario,
                creado_por=request.user,
                fecha_expiracion=fecha_expiracion,
            )
        except (ValidationError, TaskStorageError):
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
        try:
            revoke_task_link_by_id(
                link_id=enlace_id, empresa_id=empresa_id, actor=request.user,
            )
        except (ValidationError, TaskStorageError):
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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        empresa_id = _get_empresa_id(self.request)
        kwargs["active_company"] = get_object_or_404(Empresa, pk=empresa_id)
        return kwargs

    def form_valid(self, form):
        empresa = self.get_form_kwargs()["active_company"]
        data = CreateTaskDraftInput(
            titulo=form.cleaned_data["titulo"],
            descripcion=form.cleaned_data.get("descripcion", ""),
            prioridad=(
                form.cleaned_data.get("prioridad") or Tarea.Prioridad.NORMAL
            ),
            responsable_id=(
                form.cleaned_data["responsable"].pk
                if form.cleaned_data.get("responsable") is not None
                else None
            ),
            fecha_tope=form.cleaned_data["fecha_tope"],
        )
        try:
            result = create_task_draft(
                data,
                active_company=empresa,
                actor=self.request.user,
            )
        except (TaskStorageError, ValidationError) as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        self.object = result.task
        return redirect("tareas:detalle_tarea", pk=result.id)


class EditarTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    template_name = "tareas/tarea_form.html"
    vista_nombre = "Tareas"
    permiso_requerido = "modificar"
    crear_permiso_faltante = False

    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(request, *args, **kwargs)
        except PermissionDenied:
            return self.handle_no_permission(request)
        except TaskStorageError:
            logger.error("Task edit storage resolution failed: task=%s", kwargs.get("pk"))
            return HttpResponse("No se pudo resolver el almacenamiento de tareas.", status=503)

    def _empresa(self):
        return get_object_or_404(Empresa, pk=_get_empresa_id(self.request))

    def _load(self):
        try:
            data = resolve_edit_storage().get_task_for_edit(
                task_id=self.kwargs["pk"],
                empresa_id=self._empresa().pk,
            )
            self.edit_detail = resolve_detail_storage().get_task_detail(
                task_id=data.id, empresa_id=data.empresa_id,
                sections=TaskDetailSections(
                    mini_tasks=False, links=False, milestones=False, documents=False,
                ),
            )
            if not _detail_can_manage_task(self.edit_detail, self.request.user, self._empresa()):
                raise PermissionDenied
            return data
        except EditTaskNotFound as exc:
            raise Http404 from exc

    def _presentation(self, data, empresa):
        return SimpleNamespace(
            pk=data.id,
            estado=data.estado,
            titulo=data.titulo,
            descripcion=data.descripcion,
            prioridad=data.prioridad,
            responsable_id=data.responsable_id,
            fecha_tope=data.fecha_tope,
            empresa=empresa,
        )

    def _form(self, data, *, bound_data=None):
        empresa = self._empresa()
        initial = {
            "titulo": data.titulo,
            "descripcion": data.descripcion,
            "prioridad": data.prioridad,
            "responsable": data.responsable_id,
            "fecha_tope": data.fecha_tope,
        }
        form = TaskEditForm(
            bound_data,
            initial=initial,
            active_company=empresa,
            task_state=data.estado,
        )
        if data.estado == Tarea.Estado.CERRADA or self.edit_detail.hierarchy.effectively_annulled:
            form.fields["responsable"].widget.attrs["disabled"] = True
        return form

    def _render(self, data, form):
        return render(
            self.request,
            self.template_name,
            {"object": self._presentation(data, self._empresa()), "form": form},
        )

    def get(self, request, *args, **kwargs):
        data = self._load()
        return self._render(data, self._form(data))

    def post(self, request, *args, **kwargs):
        data = self._load()
        form = self._form(data, bound_data=request.POST)
        if not form.is_valid():
            return self._render(data, form)
        command = UpdateTaskCommand(
            task_id=data.id,
            empresa_id=data.empresa_id,
            titulo=form.cleaned_data["titulo"],
            descripcion=form.cleaned_data["descripcion"],
            prioridad=form.cleaned_data["prioridad"] or Tarea.Prioridad.NORMAL,
            responsable_id=(
                form.cleaned_data["responsable"].pk
                if form.cleaned_data["responsable"] is not None
                else None
            ),
            fecha_tope=form.cleaned_data["fecha_tope"],
        )
        storage = resolve_edit_storage()
        try:
            reassign_responsible(ReassignResponsibleCommand(
                task_id=data.id, empresa_id=data.empresa_id, actor_id=request.user.pk,
                new_responsible_id=command.responsable_id,
                reason=form.cleaned_data["motivo"], edit=command,
            ))
        except EditTaskNotFound as exc:
            raise Http404 from exc
        except PermissionDenied:
            return self.handle_no_permission(request)
        except (ValidationError, TaskStorageError) as exc:
            for error in exc.messages if isinstance(exc, ValidationError) else [str(exc)]:
                form.add_error(None, error)
            return self._render(data, form)
        updated = storage.get_task_for_edit(task_id=data.id, empresa_id=data.empresa_id)
        if isinstance(storage, DjangoTaskStorage):
            task = Tarea.objects.using(storage.alias).get(
                pk=updated.id,
                empresa_id=updated.empresa_id,
            )
            relevant = {"fecha_tope", "prioridad"}.intersection(
                form.changed_data
            )
            if relevant:
                emit_task_event(
                    tarea=task,
                    event="cambio_relevante",
                    recipients=task_recipients(
                        task,
                        actor=request.user,
                        include_responsible=True,
                        participant_roles=list(TareaParticipante.Rol),
                    ),
                    title="Cambio relevante en la tarea",
                    body="Se actualizó información funcional de la tarea.",
                    actor=request.user,
                )
        elif isinstance(storage, MySQLTaskStorage) and {"fecha_tope", "prioridad"}.intersection(form.changed_data):
            detail = resolve_detail_storage().get_task_detail(
                task_id=updated.id,
                empresa_id=updated.empresa_id,
                sections=TaskDetailSections(
                    mini_tasks=False,
                    links=False,
                    milestones=False,
                    documents=False,
                ),
            )
            recipient_ids = {
                item.user_id
                for item in detail.participants
                if item.rol in {role for role, _label in TareaParticipante.Rol.choices}
            }
            if detail.core.responsable_id is not None:
                recipient_ids.add(detail.core.responsable_id)
            recipients = list(
                User.objects.using("default").filter(pk__in=recipient_ids)
                .exclude(pk=request.user.pk)
            )
            emit_task_event(
                tarea=SimpleNamespace(
                    pk=updated.id, empresa=self._empresa(), prioridad=updated.prioridad,
                ),
                event="cambio_relevante",
                recipients=recipients,
                title="Cambio relevante en la tarea",
                body="Se actualizó información funcional de la tarea.",
                actor=request.user,
            )
        return redirect("tareas:detalle_tarea", pk=updated.id)


class PublicarTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    """Publica un borrador (FR-007/FR-008, Q1). Publicación irreversible (Q2)."""

    vista_nombre = "Tareas - Ciclo de vida"
    permiso_requerido = "modificar"

    def post(self, request, *args, **kwargs):
        storage = resolve_edit_storage()
        empresa_id = _get_empresa_id(request)
        task_id = kwargs["pk"]
        if isinstance(storage, DjangoTaskStorage):
            tarea = _get_operational_similarity_task(task_id, empresa_id)
            empresa = Empresa.objects.get(pk=empresa_id)
            try:
                evaluations = evaluate_task_similarity(
                    tarea=tarea,
                    threshold=get_similarity_threshold(empresa),
                )
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
                return redirect("tareas:detalle_tarea", pk=tarea.pk)
            pending = [
                evaluation
                for evaluation in evaluations
                if evaluation.supera_umbral
                and evaluation.decision == EvaluacionSimilitud.Decision.PENDIENTE
            ]
            if pending:
                messages.warning(request, "tareas.messages.publication_requires_similarity_review")
                return redirect("tareas:similitud_tarea", tarea_id=tarea.pk)
        try:
            result = storage.publish_task(
                task_id=task_id,
                empresa_id=empresa_id,
                actor_id=request.user.pk,
            )
        except EditTaskNotFound as exc:
            raise Http404 from exc
        except LifecycleSimilarityUnsupported as exc:
            return HttpResponse(str(exc), status=503)
        except TaskStorageError as exc:
            messages.error(request, str(exc))
            return redirect("tareas:detalle_tarea", pk=task_id)
        except ValidationError as e:
            mensaje = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
            messages.error(request, mensaje)
            return redirect("tareas:detalle_tarea", pk=task_id)
        else:
            messages.success(request, "tareas.messages.task_published")
        return redirect("tareas:detalle_tarea", pk=result.task_id)


class SimilitudTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    template_name = "tareas/tarea_similitud.html"
    vista_nombre = "Tareas - Ciclo de vida"
    permiso_requerido = "modificar"

    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(request, *args, **kwargs)
        except TaskStorageError:
            return HttpResponse(
                "No se pudo leer el almacenamiento de tareas configurado.",
                status=503,
            )

    def get(self, request, tarea_id):
        tarea = _get_operational_similarity_task(tarea_id, _get_empresa_id(request))
        empresa = Empresa.objects.get(pk=_get_empresa_id(request))
        try:
            evaluations = evaluate_task_similarity(
                tarea=tarea,
                threshold=get_similarity_threshold(empresa),
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("tareas:detalle_tarea", pk=tarea.pk)
        evaluations = [evaluation for evaluation in evaluations if evaluation.supera_umbral]
        return render(
            request,
            self.template_name,
            {
                "tarea": tarea,
                "evaluaciones": evaluations,
                "hay_pendientes": any(
                    evaluation.decision == EvaluacionSimilitud.Decision.PENDIENTE
                    for evaluation in evaluations
                ),
            },
        )


class ConfirmarSimilitudView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Tareas - Ciclo de vida"
    permiso_requerido = "modificar"

    def post(self, request, tarea_id, evaluacion_id):
        tarea = _get_operational_similarity_task(tarea_id, _get_empresa_id(request))
        try:
            with resolve_similarity_storage().atomic() as unit:
                evaluation = unit.get_evaluation(evaluacion_id)
                if (
                    evaluation.tarea_id != tarea.pk
                    or not evaluation.supera_umbral
                    or evaluation.tarea.empresa_id != tarea.empresa_id
                    or evaluation.tarea_candidata.empresa_id != tarea.empresa_id
                ):
                    raise Http404
        except SimilarityStorageError as exc:
            raise Http404 from exc
        decision = request.POST.get("decision")
        if decision not in {
            EvaluacionSimilitud.Decision.MISMO_PROBLEMA,
            EvaluacionSimilitud.Decision.DISTINTO_PROBLEMA,
        }:
            messages.error(request, "tareas.messages.similarity_decision_invalid")
            return redirect("tareas:similitud_tarea", tarea_id=tarea.pk)
        try:
            confirm_similarity(
                evaluacion=evaluation,
                decision=decision,
                actor=request.user,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("tareas:similitud_tarea", tarea_id=tarea.pk)
        with resolve_similarity_storage().atomic() as unit:
            pending = any(
                evaluation.supera_umbral
                and evaluation.decision == EvaluacionSimilitud.Decision.PENDIENTE
                for evaluation in unit.list_evaluations(tarea.pk)
            )
        if pending:
            return redirect("tareas:similitud_tarea", tarea_id=tarea.pk)
        try:
            publish_task(tarea, request.user)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("tareas:detalle_tarea", pk=tarea.pk)
        messages.success(request, "tareas.messages.similarity_confirmed_and_published")
        return redirect("tareas:detalle_tarea", pk=tarea.pk)


class TareaLifecycleView(VerificarPermisoMixin, LoginRequiredMixin, View):
    """Protected Phase 2 action endpoint for one task."""

    permiso_requerido = "modificar"
    accion = None
    vista_nombre = "Tareas - Ciclo de vida"

    def post(self, request, *args, **kwargs):
        if self.accion in {"anular", "reactivar"}:
            storage = resolve_hierarchy_lifecycle_storage()
            command = HierarchyLifecycleCommand(
                task_id=kwargs["pk"],
                empresa_id=_get_empresa_id(request),
                actor_id=request.user.pk,
                motivo=request.POST.get("motivo", "").strip(),
            )
            try:
                result = storage.annul(command) if self.accion == "anular" else storage.reactivate(command)
            except EditTaskNotFound as exc:
                raise Http404 from exc
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
                return redirect("tareas:detalle_tarea", pk=command.task_id)
            except TaskStorageError as exc:
                messages.error(request, str(exc))
                return redirect("tareas:detalle_tarea", pk=command.task_id)
            messages.success(request, "tareas.messages.lifecycle_action_applied")
            return redirect("tareas:detalle_tarea", pk=result.task_id)
        if self.accion in {"completar", "aprobar", "rechazar"}:
            storage = resolve_closure_storage()
            command = ClosureCommand(
                task_id=kwargs["pk"],
                empresa_id=_get_empresa_id(request),
                actor_id=request.user.pk,
                comentario=request.POST.get("comentario", "").strip(),
            )
            try:
                if self.accion == "completar":
                    result = storage.complete(command)
                elif self.accion == "aprobar":
                    result = storage.approve(command)
                else:
                    result = storage.reject(command)
            except EditTaskNotFound as exc:
                raise Http404 from exc
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
                return redirect("tareas:detalle_tarea", pk=command.task_id)
            except TaskStorageError as exc:
                messages.error(request, str(exc))
                return redirect("tareas:detalle_tarea", pk=command.task_id)
            messages.success(request, "tareas.messages.lifecycle_action_applied")
            return redirect("tareas:detalle_tarea", pk=result.task_id)
        if self.accion == "gestion":
            storage = resolve_edit_storage()
            try:
                result = storage.enter_management(
                    task_id=kwargs["pk"],
                    empresa_id=_get_empresa_id(request),
                    actor_id=request.user.pk,
                )
            except EditTaskNotFound as exc:
                raise Http404 from exc
            except TaskStorageError as exc:
                messages.error(request, str(exc))
                return redirect("tareas:detalle_tarea", pk=kwargs["pk"])
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
                return redirect("tareas:detalle_tarea", pk=kwargs["pk"])
            messages.success(request, "tareas.messages.lifecycle_action_applied")
            return redirect("tareas:detalle_tarea", pk=result.task_id)
        raise ValidationError(
            "tareas.messages.lifecycle_action_not_configured",
            code="tareas.messages.lifecycle_action_not_configured",
        )


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


def _build_hitos_context(tarea, actor, **form_overrides):
    detail = resolve_milestone_storage().detail(
        task_id=tarea.pk, empresa_id=tarea.empresa_id, actor_id=actor.pk,
    )
    empresa = Empresa.objects.get(pk=detail.core.empresa_id)
    return {
        "tarea": _detail_task_presentation(detail.core, empresa),
        **_detail_milestone_context(detail, empresa, actor, **form_overrides),
    }


class HitosTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Tareas - Hitos"
    permiso_requerido = "ingresar"

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST":
            action = request.POST.get("accion")
            self.permiso_requerido = (
                "crear" if action == "hito"
                else "eliminar" if action == "eliminar_hito"
                else "modificar"
            )
        try:
            return super().dispatch(request, *args, **kwargs)
        except (MilestoneNotFound, DetailTaskNotFound):
            raise Http404
        except PermissionDenied:
            return self.handle_no_permission(request)
        except TaskStorageError:
            return HttpResponse(
                render(request, "tareas/tarea_hitos.html", {"storage_error": True}).content,
                status=503,
            )

    def get_tarea(self, pk):
        self.storage = resolve_milestone_storage()
        self.detail_result = self.storage.detail(
            task_id=pk, empresa_id=get_active_company_id(self.request),
            actor_id=self.request.user.pk,
        )
        self.empresa = Empresa.objects.get(pk=self.detail_result.core.empresa_id)
        return _detail_task_presentation(self.detail_result.core, self.empresa)

    def redirect_after_post(self, request, tarea):
        if request.POST.get("next") == "detalle":
            return redirect(
                f"{reverse('tareas:detalle_tarea', kwargs={'pk': tarea.pk})}#tarea-pane-hitos"
            )
        return redirect("tareas:hitos_tarea", pk=tarea.pk)

    def get_context(self, tarea, **forms):
        if not hasattr(self, "detail_with_history"):
            self.detail_with_history = replace(
                self.detail_result,
                milestones=tuple(
                    replace(
                        milestone,
                        historial=self.storage.history(
                            task_id=tarea.pk, empresa_id=tarea.empresa_id,
                            actor_id=self.request.user.pk, milestone_id=milestone.pk,
                        ),
                    )
                    for milestone in self.detail_result.milestones
                ),
            )
        return {
            "tarea": tarea,
            **_detail_milestone_context(self.detail_with_history, self.empresa, self.request.user, **forms),
            "puede_ver_historial_hitos": True,
        }

    def get(self, request, pk):
        tarea = self.get_tarea(pk)
        context = self.get_context(tarea)
        modal_context = {}
        accion = request.GET.get("accion")
        hito_id = request.GET.get("hito_id")
        if accion in {"cumplimiento_hito", "completar_hito"} and hito_id:
            try:
                hito = next(
                    (item for item in context["hitos"] if item.pk == int(hito_id)),
                    None,
                )
            except ValueError:
                hito = None
            if hito is not None and (
                hito.puede_actualizar if accion == "cumplimiento_hito" else hito.puede_completar
            ):
                modal_context = {
                    "modal_abierto_hito_id": hito.pk,
                    "modal_abierto_accion": accion,
                }
        return render(
            request,
            "tareas/tarea_hitos.html",
            {**context, **modal_context},
        )

    def post(self, request, pk):
        tarea = self.get_tarea(pk)
        accion = request.POST.get("accion")
        if accion == "hito":
            form = HitoCrearForm(request.POST, empresa=self.empresa)
            if form.is_valid():
                try:
                    self.storage.execute(CreateMilestoneCommand(
                        task_id=tarea.pk, empresa_id=tarea.empresa_id, actor_id=request.user.pk,
                        nombre=form.cleaned_data["nombre"],
                        cumplimiento=form.cleaned_data["cumplimiento"],
                        peso=form.cleaned_data["peso"],
                        responsable_id=form.cleaned_data["responsable"].pk,
                    ))
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "tareas.messages.milestone_created")
                    return self.redirect_after_post(request, tarea)
            return render(request, "tareas/tarea_hitos.html", self.get_context(tarea, hito_form=form))
        hito = None
        if request.POST.get("hito_id"):
            try:
                hito_id = int(request.POST["hito_id"])
            except (TypeError, ValueError):
                raise Http404
            hito = next((item for item in self.detail_result.milestones if item.pk == hito_id), None)
            if hito is None:
                raise Http404
        if accion.endswith("_hito") and hito is None:
            raise Http404
        if accion == "completar_hito":
            form = CompletarHitoForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    self.storage.execute(CompleteMilestoneCommand(
                        task_id=tarea.pk, empresa_id=tarea.empresa_id, actor_id=request.user.pk,
                        milestone_id=hito.pk,
                        resena_cierre=form.cleaned_data["resena_cierre"],
                        formato_archivo=form.cleaned_data["formato_archivo"],
                        archivo=form.cleaned_data.get("archivo"),
                        url=form.cleaned_data.get("url", ""),
                    ))
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "tareas.messages.milestone_completed")
                    return self.redirect_after_post(request, tarea)
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
            form = HitoForm(request.POST)
            if form.is_valid():
                try:
                    self.storage.execute(UpdateMilestoneCommand(
                        task_id=tarea.pk, empresa_id=tarea.empresa_id, actor_id=request.user.pk,
                        milestone_id=hito.pk,
                        nombre=form.cleaned_data["nombre"],
                        cumplimiento=form.cleaned_data["cumplimiento"],
                        peso=form.cleaned_data["peso"],
                    ))
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "tareas.messages.milestone_updated")
                    return self.redirect_after_post(request, tarea)
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
            form = HitoCumplimientoForm(request.POST)
            if form.is_valid():
                try:
                    self.storage.execute(UpdateMilestoneCommand(
                        task_id=tarea.pk, empresa_id=tarea.empresa_id, actor_id=request.user.pk,
                        milestone_id=hito.pk,
                        cumplimiento=form.cleaned_data["cumplimiento"],
                    ))
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "tareas.messages.milestone_progress_updated")
                    return self.redirect_after_post(request, tarea)
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
            form = HitoReasignacionForm(request.POST, empresa=self.empresa)
            if form.is_valid():
                try:
                    self.storage.execute(ReassignMilestoneCommand(
                        task_id=tarea.pk, empresa_id=tarea.empresa_id, actor_id=request.user.pk,
                        milestone_id=hito.pk,
                        responsable_id=form.cleaned_data["responsable"].pk,
                        motivo=form.cleaned_data["motivo"],
                    ))
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "tareas.messages.milestone_reassigned")
                    return self.redirect_after_post(request, tarea)
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
                self.storage.execute(SetMilestoneAnnulledCommand(
                    task_id=tarea.pk, empresa_id=tarea.empresa_id, actor_id=request.user.pk,
                    milestone_id=hito.pk, anulado=accion == "anular_hito",
                ))
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, "tareas.messages.milestone_status_updated")
            return self.redirect_after_post(request, tarea)
        if accion == "eliminar_hito":
            try:
                self.storage.execute(DeleteMilestoneCommand(
                    task_id=tarea.pk, empresa_id=tarea.empresa_id, actor_id=request.user.pk,
                    milestone_id=hito.pk,
                ))
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.success(request, "tareas.messages.milestone_deleted_or_annulled")
            return self.redirect_after_post(request, tarea)
        if accion == "manual":
            form = AvanceManualForm(request.POST)
            if form.is_valid():
                try:
                    self.storage.execute(UpdateManualProgressCommand(
                        task_id=tarea.pk, empresa_id=tarea.empresa_id, actor_id=request.user.pk,
                        porcentaje=form.cleaned_data["porcentaje"],
                    ))
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "tareas.messages.manual_progress_updated")
                    return self.redirect_after_post(request, tarea)
            return render(request, "tareas/tarea_hitos.html", self.get_context(tarea, manual_form=form))
        if accion == "ponderado":
            form = AvancePonderadoForm(request.POST)
            if form.is_valid():
                try:
                    self.storage.execute(SetWeightedProgressModeCommand(
                        task_id=tarea.pk, empresa_id=tarea.empresa_id, actor_id=request.user.pk,
                    ))
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "tareas.messages.weighted_mode_configured")
                    return self.redirect_after_post(request, tarea)
            return render(request, "tareas/tarea_hitos.html", self.get_context(tarea, ponderado_form=form))
        messages.error(request, "tareas.messages.progress_action_not_configured")
        return self.redirect_after_post(request, tarea)


def _build_document_context(tarea, **form_overrides):
    detail_result = resolve_detail_storage().get_task_detail(
        task_id=tarea.pk,
        empresa_id=tarea.empresa_id,
        sections=TaskDetailSections(
            mini_tasks=False,
            links=False,
            milestones=False,
            documents=True,
        ),
    )
    return {
        "tarea": tarea,
        "documentos": detail_result.documents,
        "evidencias": detail_result.closure_evidence,
        "document_form": form_overrides.get("document_form", DocumentoForm()),
        "evidencia_registro_form": form_overrides.get(
            "evidencia_registro_form", EvidenciaRegistroForm()
        ),
    }


class DocumentosTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Tareas - Documentos y evidencia"
    permiso_requerido = "modificar"

    def get_tarea(self, pk):
        try:
            self.detail_result = resolve_detail_storage().get_task_detail(
                task_id=pk,
                empresa_id=_get_empresa_id(self.request),
                sections=TaskDetailSections(
                    mini_tasks=False,
                    links=False,
                    milestones=False,
                    documents=True,
                ),
            )
        except DetailTaskNotFound as exc:
            raise Http404 from exc
        self.detail_empresa = Empresa.objects.get(pk=self.detail_result.core.empresa_id)
        return _detail_task_presentation(self.detail_result.core, self.detail_empresa)

    def get_context(self, tarea, **forms):
        return {
            "tarea": tarea,
            "documentos": self.detail_result.documents,
            "evidencias": self.detail_result.closure_evidence,
            "document_form": forms.get("document_form", DocumentoForm()),
            "evidencia_registro_form": forms.get(
                "evidencia_registro_form", EvidenciaRegistroForm()
            ),
        }

    def redirect_after_post(self, request, tarea):
        if request.POST.get("next") == "detalle":
            return redirect(
                f"{reverse('tareas:detalle_tarea', kwargs={'pk': tarea.pk})}#tarea-pane-documentos"
            )
        return redirect("tareas:documentos_tarea", pk=tarea.pk)

    def render_invalid(self, request, tarea, **forms):
        if request.POST.get("next") != "detalle":
            return render(request, "tareas/tarea_documentos.html", self.get_context(tarea, **forms))
        detail_view = DetalleTareaView()
        detail_view.request = request
        detail_view.args = ()
        detail_view.kwargs = {"pk": tarea.pk}
        detail_view.object = tarea
        detail_view.detail_empresa = tarea.empresa
        detail_view.detail_result = resolve_detail_storage().get_task_detail(
            task_id=tarea.pk,
            empresa_id=tarea.empresa_id,
            sections=TaskDetailSections(
                mini_tasks=False,
                links=False,
                milestones=False,
                documents=True,
            ),
        )
        context = detail_view.get_context_data(object=tarea)
        context.update(self.get_context(tarea, **forms))
        context["puede_ver_documentos"] = True
        context["documents_action_url"] = reverse(
            "tareas:documentos_tarea",
            kwargs={"pk": tarea.pk},
        )
        context["documents_return_to_detail"] = True
        context["documentos_tab_activo"] = True
        return render(request, "tareas/tarea_detalle.html", context)

    def get(self, request, pk):
        tarea = self.get_tarea(pk)
        return render(request, "tareas/tarea_documentos.html", self.get_context(tarea))

    def post(self, request, pk):
        tarea = self.get_tarea(pk)
        storage = resolve_document_storage()
        accion = request.POST.get("accion")
        if accion == "documento":
            form = DocumentoForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    storage.create_document(DocumentCreateCommand(
                        tarea_id=tarea.pk,
                        empresa_id=tarea.empresa_id,
                        usuario_id=request.user.pk,
                        tipo=form.cleaned_data["tipo"],
                        formato_archivo=form.cleaned_data["formato_archivo"],
                        archivo=form.cleaned_data["archivo"],
                        url=form.cleaned_data["url"],
                        fecha_documento=form.cleaned_data["fecha_documento"],
                        fecha_vencimiento=form.cleaned_data["fecha_vencimiento"],
                    ))
                except ValidationError as exc:
                    form.add_error(None, exc)
                    return self.render_invalid(request, tarea, document_form=form)
                messages.success(request, "tareas.messages.document_registered")
                return self.redirect_after_post(request, tarea)
            return self.render_invalid(request, tarea, document_form=form)
        if accion == "registrar_evidencia":
            form = EvidenciaRegistroForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    storage.register_evidence(EvidenceCreateCommand(
                        tarea_id=tarea.pk,
                        empresa_id=tarea.empresa_id,
                        usuario_id=request.user.pk,
                        formato_archivo=form.cleaned_data["formato_archivo"],
                        archivo=form.cleaned_data["archivo"],
                        url=form.cleaned_data["url"],
                    ))
                except ValidationError as exc:
                    if hasattr(exc, "message_dict"):
                        for campo, mensajes in exc.message_dict.items():
                            campo_formulario = campo if campo in form.fields else None
                            for mensaje in mensajes:
                                form.add_error(campo_formulario, mensaje)
                    else:
                        for mensaje in exc.messages:
                            form.add_error(None, mensaje)
                    return self.render_invalid(request, tarea, evidencia_registro_form=form)
                messages.success(request, "tareas.messages.evidence_registered")
                return self.redirect_after_post(request, tarea)
            return self.render_invalid(request, tarea, evidencia_registro_form=form)
        raise ValidationError(
            "tareas.messages.document_action_not_configured",
            code="tareas.messages.document_action_not_configured",
        )


class ReunionEmpresaQuerysetMixin:
    def get_queryset(self):
        empresa_id = _get_empresa_id(self.request)
        if not empresa_id:
            return []
        return resolve_meeting_storage().list_meetings(empresa_id)

    def get_meeting(self, pk):
        try:
            meeting = resolve_meeting_storage().get_meeting(pk)
        except MeetingNotFound:
            raise Http404
        if meeting.empresa_id != _get_empresa_id(self.request):
            raise Http404
        meeting._prefetched_objects_cache = {
            "agenda": resolve_meeting_storage().get_agenda(meeting.pk),
            "participantes": resolve_meeting_storage().get_participants(meeting.pk),
        }
        return meeting


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

    def get_object(self, queryset=None):
        return self.get_meeting(self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["participante_form"] = ReunionParticipanteForm(empresa=self.object.empresa)
        context["tarea_form"] = ReunionTareaForm(empresa=self.object.empresa)
        return context


class EditarReunionRevisionView(VerificarPermisoMixin, LoginRequiredMixin, ReunionEmpresaQuerysetMixin, View):
    template_name = "tareas/reunion_revision_form.html"
    vista_nombre = "Tareas"
    permiso_requerido = "modificar"

    def get_reunion(self, pk):
        return self.get_meeting(pk)

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
        reunion = self.get_meeting(pk)
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
                raise ValidationError(
                    "tareas.messages.meeting_action_not_configured",
                    code="tareas.messages.meeting_action_not_configured",
                )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        return redirect("tareas:reunion_revision_detalle", pk=reunion.pk)
