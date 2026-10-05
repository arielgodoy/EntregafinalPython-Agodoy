"""Initial Detail read storage boundary for Tareas."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
import json

from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Prefetch
from django.utils import timezone

from acounts.models import Avatar

from ..models import (
    ComentarioAdjunto,
    DocumentoHistorial,
    DocumentoTarea,
    EnlaceTarea,
    Avance,
    Hito,
    HitoEvidencia,
    EvidenciaCierre,
    MiniTarea,
    MiniTareaEvento,
    Tarea,
    TareaParticipante,
    TareaRelacion,
)
from .connection_roles import TareaConnectionError, get_tarea_connection
from .connection_roles import get_tarea_mysql_connection
from .task_storage import TaskStorageBackendNotImplemented, TaskStorageError
from .reprogramming_storage import (
    ReprogrammingCause,
    ReprogrammingHistory,
    django_reprogramming_detail,
    mysql_reprogramming_detail,
)
from settings.services.mysql_connections import open_mysql_connection


class DetailTaskNotFound(TaskStorageError):
    """The task is absent or outside the authorized company scope."""


@dataclass(frozen=True)
class TaskDetailSections:
    mini_tasks: bool = True
    links: bool = True
    milestones: bool = False
    documents: bool = False


@dataclass(frozen=True)
class TaskDetailTaskReference:
    id: int
    correlativo: str
    titulo: str
    estado: str
    anulada: bool

    @property
    def pk(self):
        return self.id


@dataclass(frozen=True)
class TaskDetailHierarchy:
    parent: TaskDetailTaskReference | None
    children: tuple[TaskDetailTaskReference, ...]
    effectively_annulled: bool


@dataclass(frozen=True)
class TaskDetailParticipant:
    user_id: int
    username: str
    rol: str
    avatar_url: str = ""


@dataclass(frozen=True)
class TaskDetailAttachment:
    id: int
    nombre_archivo: str
    tipo: str
    formato_archivo: str
    url: str
    archivo_url: str


@dataclass(frozen=True)
class TaskDetailProgress:
    configured: bool
    mode: str
    mode_display: str
    percentage: Decimal
    weighted_percentage: Decimal


@dataclass(frozen=True)
class TaskDetailDocumentHistory:
    id: int
    accion: str
    usuario_id: int
    usuario_username: str
    fecha: object


@dataclass(frozen=True)
class TaskDetailDocument:
    id: int
    tipo: str
    tipo_display: str
    formato_archivo: str
    formato_archivo_display: str
    nombre_archivo: str
    archivo_url: str
    url: str
    fecha_documento: object
    fecha_vencimiento: object | None
    usuario_id: int
    usuario_username: str
    historial: tuple[TaskDetailDocumentHistory, ...]

    @property
    def pk(self):
        return self.id


@dataclass(frozen=True)
class TaskDetailClosureEvidence:
    id: int
    formato_archivo: str
    formato_archivo_display: str
    nombre_archivo: str
    archivo_url: str
    url: str
    usuario_id: int
    usuario_username: str
    fecha: object

    @property
    def pk(self):
        return self.id


@dataclass(frozen=True)
class TaskDetailMilestoneEvidence:
    id: int
    formato_archivo: str
    nombre_archivo: str
    url: str
    archivo_url: str
    usuario_id: int
    usuario_username: str
    fecha: object


@dataclass(frozen=True)
class TaskDetailMilestoneHistory:
    id: int
    tipo_evento: str
    usuario_id: int
    usuario_username: str
    fecha: object
    datos_anteriores: dict
    datos_nuevos: dict
    motivo: str


@dataclass(frozen=True)
class TaskDetailMilestone:
    id: int
    nombre: str
    responsable_id: int
    responsable_username: str
    responsable_avatar_url: str
    anulado: bool
    completado: bool
    completado_por_id: int | None
    completado_por_username: str
    cumplimiento: Decimal
    peso: Decimal
    fecha_creacion: object
    fecha_completado: object | None
    resena_cierre: str
    evidencias: tuple[TaskDetailMilestoneEvidence, ...]
    puede_gestionar: bool = False
    puede_actualizar: bool = False
    puede_completar: bool = False
    puede_eliminar: bool = False
    historial: tuple[TaskDetailMilestoneHistory, ...] = ()

    @property
    def pk(self):
        return self.id


@dataclass(frozen=True)
class TaskDetailMiniTaskEvent:
    id: int
    tipo: str
    fecha: object
    comentario: str
    comentario_oculto: bool
    attachments: tuple[TaskDetailAttachment, ...]
    actor_id: int | None = None
    actor_username: str = ""
    comentario_feed_id: int | None = None
    destinatarios_notificacion: tuple[int, ...] = ()
    destinatarios_email: tuple[int, ...] = ()


@dataclass(frozen=True)
class TaskDetailMiniTask:
    id: int
    descripcion: str
    persona_id: int
    persona_username: str
    persona_avatar_url: str
    hecho: bool
    fecha_creacion: object
    fecha_completado: object
    eventos_t104: tuple[TaskDetailMiniTaskEvent, ...]
    ultimo_cierre_adjuntos_t104: tuple[TaskDetailAttachment, ...]
    puede_cerrar_t104: bool = False
    puede_reabrir_t104: bool = False
    puede_eliminar_t105: bool = False

    @property
    def pk(self):
        return self.id


@dataclass(frozen=True)
class TaskDetailLink:
    id: int
    destinatario_id: int
    destinatario_username: str
    destinatario_avatar_url: str
    creado_por_id: int
    creado_por_username: str
    revocado_por_id: int | None
    revocado_por_username: str
    fecha_creacion: object
    fecha_expiracion: object
    fecha_revocacion: object | None
    estado: str

    @property
    def pk(self):
        return self.id


@dataclass(frozen=True)
class TaskDetailCore:
    id: int
    empresa_id: int
    correlativo: str
    titulo: str
    descripcion: str
    estado: str
    prioridad: str
    anulada: bool
    fechas_pendientes_confirmacion: bool
    requiere_evidencia_cierre: bool
    fecha_creacion: object
    fecha_publicacion: object
    fecha_asignacion: object
    fecha_tope: object
    fecha_cumplimiento: object
    responsable_id: int | None
    creada_por_id: int
    creada_por_username: str
    creada_por_avatar_url: str
    responsable_username: str
    responsable_avatar_url: str


@dataclass(frozen=True)
class TaskDetailResult:
    core: TaskDetailCore
    hierarchy: TaskDetailHierarchy
    participants: tuple[TaskDetailParticipant, ...]
    mini_tasks: tuple[TaskDetailMiniTask, ...] = ()
    links: tuple[TaskDetailLink, ...] = ()
    progress: TaskDetailProgress | None = None
    milestones: tuple[TaskDetailMilestone, ...] = ()
    documents: tuple[TaskDetailDocument, ...] = ()
    closure_evidence: tuple[TaskDetailClosureEvidence, ...] = ()
    reprogramming_causes: tuple[ReprogrammingCause, ...] = ()
    reprogramming_history: tuple[ReprogrammingHistory, ...] = ()
    effective_user_ids: tuple[int, ...] = ()


def _avatar_url(user) -> str:
    try:
        avatar = user.avatar
    except ObjectDoesNotExist:
        return ""
    if not avatar or not avatar.imagen:
        return ""
    try:
        return avatar.imagen.url
    except (OSError, ValueError):
        return ""


def _attachment_dto(documento) -> TaskDetailAttachment:
    filename = ""
    if documento.archivo:
        filename = documento.archivo.name.replace("\\", "/").rsplit("/", 1)[-1]
    elif documento.url:
        filename = documento.url.rstrip("/").rsplit("/", 1)[-1]
    try:
        archivo_url = documento.archivo.url if documento.archivo else ""
    except (OSError, ValueError):
        archivo_url = ""
    return TaskDetailAttachment(
        id=documento.pk,
        nombre_archivo=filename,
        tipo=documento.tipo,
        formato_archivo=documento.formato_archivo,
        url=documento.url,
        archivo_url=archivo_url,
    )


def _link_status(*, revocado_at, fecha_expiracion, now=None) -> str:
    now = now or timezone.now()
    if revocado_at is not None:
        return "REVOCADO"
    if fecha_expiracion <= now:
        return "EXPIRADO"
    return "ACTIVO"


def _milestone_evidence_dto(evidence, users_by_id) -> TaskDetailMilestoneEvidence:
    filename = ""
    if evidence.archivo:
        filename = evidence.archivo.name.replace("\\", "/").rsplit("/", 1)[-1]
    elif evidence.url:
        filename = evidence.url.rstrip("/").rsplit("/", 1)[-1]
    try:
        archivo_url = evidence.archivo.url if evidence.archivo else ""
    except (OSError, ValueError):
        archivo_url = ""
    return TaskDetailMilestoneEvidence(
        id=evidence.pk,
        formato_archivo=evidence.formato_archivo,
        nombre_archivo=filename,
        url=evidence.url,
        archivo_url=archivo_url,
        usuario_id=evidence.usuario_id,
        usuario_username=users_by_id.get(evidence.usuario_id).username
        if evidence.usuario_id in users_by_id
        else "",
        fecha=evidence.fecha,
    )


def _file_metadata(source) -> tuple[str, str]:
    filename = ""
    if source.archivo:
        filename = source.archivo.name.replace("\\", "/").rsplit("/", 1)[-1]
    elif source.url:
        filename = source.url.rstrip("/").rsplit("/", 1)[-1]
    try:
        file_url = source.archivo.url if source.archivo else ""
    except (OSError, ValueError):
        file_url = ""
    return filename, file_url


def _choice_label(choices, value) -> str:
    return dict(choices).get(value, value)


def _event_attachments(event) -> tuple[TaskDetailAttachment, ...]:
    if event.comentario_feed is None:
        return ()
    return tuple(
        _attachment_dto(adjunto.documento)
        for adjunto in event.comentario_feed.adjuntos.all()
    )


def _last_closure_attachments(events) -> tuple[TaskDetailAttachment, ...]:
    for event in reversed(events):
        if event.tipo == MiniTareaEvento.Tipo.CIERRE:
            return _event_attachments(event)
    return ()


class DjangoTaskDetailStorage:
    def __init__(self, alias: str):
        self.alias = alias

    def get_task_detail(
        self,
        *,
        task_id: int,
        empresa_id: int,
        sections: TaskDetailSections,
    ) -> TaskDetailResult:
        try:
            task = (
                Tarea.objects.using(self.alias)
                .select_related("empresa", "responsable", "creada_por")
                .get(pk=task_id, empresa_id=empresa_id)
            )
        except Tarea.DoesNotExist as exc:
            raise DetailTaskNotFound from exc
        core = TaskDetailCore(
            id=task.pk,
            empresa_id=task.empresa_id,
            correlativo=task.correlativo,
            titulo=task.titulo,
            descripcion=task.descripcion,
            estado=task.estado,
            prioridad=task.prioridad,
            anulada=task.anulada,
            fechas_pendientes_confirmacion=task.fechas_pendientes_confirmacion,
            requiere_evidencia_cierre=task.requiere_evidencia_cierre,
            fecha_creacion=task.fecha_creacion,
            fecha_publicacion=task.fecha_publicacion,
            fecha_asignacion=task.fecha_asignacion,
            fecha_tope=task.fecha_tope,
            fecha_cumplimiento=task.fecha_cumplimiento,
            responsable_id=task.responsable_id,
            creada_por_id=task.creada_por_id,
            creada_por_username=task.creada_por.username,
            creada_por_avatar_url=_avatar_url(task.creada_por),
            responsable_username=task.responsable.username if task.responsable else "",
            responsable_avatar_url=_avatar_url(task.responsable) if task.responsable else "",
        )
        parent = (
            TareaRelacion.objects.using(self.alias)
            .filter(hija_id=task.pk, hija__empresa_id=empresa_id)
            .select_related("padre")
            .first()
        )
        parent_reference = None
        if parent is not None:
            parent_reference = TaskDetailTaskReference(
                id=parent.padre_id,
                correlativo=parent.padre.correlativo,
                titulo=parent.padre.titulo,
                estado=parent.padre.estado,
                anulada=parent.padre.anulada,
            )
        children = tuple(
            TaskDetailTaskReference(
                id=child.pk,
                correlativo=child.correlativo,
                titulo=child.titulo,
                estado=child.estado,
                anulada=child.anulada,
            )
            for child in Tarea.objects.using(self.alias)
            .filter(relaciones_padre__padre_id=task.pk, empresa_id=empresa_id)
            .order_by("id")
        )
        ancestor_annulled = bool(task.anulada)
        current_parent = parent.padre if parent is not None else None
        for _level in range(2):
            if current_parent is None:
                break
            ancestor_annulled = ancestor_annulled or current_parent.anulada
            current_parent = (
                TareaRelacion.objects.using(self.alias)
                .filter(hija_id=current_parent.pk, hija__empresa_id=empresa_id)
                .select_related("padre")
                .first()
            )
            current_parent = current_parent.padre if current_parent else None

        participant_rows = list(
            TareaParticipante.objects.using(self.alias)
            .filter(tarea_id=task.pk)
            .order_by("usuario__username")
            .values_list("usuario_id", "rol")
        )
        effective_user_ids = set(
            Hito.objects.using(self.alias).filter(tarea_id=task.pk, anulado=False)
            .values_list("responsable_id", flat=True)
        )
        effective_user_ids.update(
            MiniTarea.objects.using(self.alias).filter(tarea_id=task.pk)
            .values_list("persona_id", flat=True)
        )
        avance_row = None
        milestone_rows = []
        progress = None
        if sections.milestones:
            avance_row = (
                Avance.objects.using(self.alias)
                .filter(tarea_id=task.pk, tarea__empresa_id=empresa_id)
                .first()
            )
            evidence_queryset = HitoEvidencia.objects.using(self.alias).order_by(
                "fecha", "pk"
            )
            milestone_rows = list(
                Hito.objects.using(self.alias)
                .filter(tarea_id=task.pk, tarea__empresa_id=empresa_id)
                .prefetch_related(
                    Prefetch("evidencias", queryset=evidence_queryset, to_attr="detail_evidence"),
                )
                .order_by("fecha_creacion", "pk")
            )
            active_milestones = [milestone for milestone in milestone_rows if not milestone.anulado]
            total_weight = sum(
                (milestone.peso for milestone in active_milestones),
                Decimal("0"),
            )
            weighted_percentage = (
                sum(
                    (milestone.cumplimiento * milestone.peso for milestone in active_milestones),
                    Decimal("0"),
                )
                / total_weight
                if total_weight
                else Decimal("0")
            ).quantize(Decimal("0.01"))
            progress = TaskDetailProgress(
                configured=avance_row is not None,
                mode=avance_row.modo if avance_row else "",
                mode_display=avance_row.get_modo_display() if avance_row else "",
                percentage=avance_row.porcentaje if avance_row else Decimal("0.00"),
                weighted_percentage=weighted_percentage,
            )
        document_rows = []
        closure_evidence_rows = []
        if sections.documents:
            history_queryset = DocumentoHistorial.objects.using(self.alias).order_by(
                "fecha", "pk"
            )
            document_rows = list(
                DocumentoTarea.objects.using(self.alias)
                .filter(tarea_id=task.pk, tarea__empresa_id=empresa_id)
                .prefetch_related(
                    Prefetch("historial", queryset=history_queryset, to_attr="detail_history")
                )
                .order_by("pk")
            )
            closure_evidence_rows = list(
                EvidenciaCierre.objects.using(self.alias)
                .filter(tarea_id=task.pk, tarea__empresa_id=empresa_id)
                .order_by("-fecha", "-pk")
            )
        mini_task_rows = []
        if sections.mini_tasks:
            events_queryset = (
                MiniTareaEvento.objects.using(self.alias)
                .select_related("comentario_feed")
                .prefetch_related(
                    Prefetch(
                        "comentario_feed__adjuntos",
                        queryset=ComentarioAdjunto.objects.using(self.alias).select_related(
                            "documento"
                        ),
                    )
                )
            )
            mini_task_rows = list(
                MiniTarea.objects.using(self.alias)
                .filter(tarea_id=task.pk, tarea__empresa_id=empresa_id)
                .prefetch_related(Prefetch("eventos", queryset=events_queryset, to_attr="detail_events"))
                .order_by("fecha_creacion", "pk")
            )
        link_rows = []
        if sections.links:
            link_rows = list(
                EnlaceTarea.objects.using(self.alias)
                .filter(tarea_id=task.pk, tarea__empresa_id=empresa_id)
                .order_by("-fecha_creacion", "-pk")
            )
        reprogramming_causes, reprogramming_history = django_reprogramming_detail(
            self.alias, task.pk, empresa_id
        )
        user_ids = {user_id for user_id, _role in participant_rows}
        user_ids.update(item.usuario_id for item in reprogramming_history)
        user_ids.update(mini.persona_id for mini in mini_task_rows)
        user_ids.update(
            event.actor_id for mini in mini_task_rows
            for event in getattr(mini, "detail_events", ())
        )
        for milestone in milestone_rows:
            user_ids.add(milestone.responsable_id)
            if milestone.completado_por_id:
                user_ids.add(milestone.completado_por_id)
            user_ids.update(
                evidence.usuario_id
                for evidence in getattr(milestone, "detail_evidence", ())
            )
        for document in document_rows:
            user_ids.add(document.usuario_id)
            user_ids.update(
                history.usuario_id
                for history in getattr(document, "detail_history", ())
            )
        user_ids.update(evidence.usuario_id for evidence in closure_evidence_rows)
        for link in link_rows:
            user_ids.update((link.destinatario_id, link.creado_por_id))
            if link.revocado_por_id:
                user_ids.add(link.revocado_por_id)
        users = User.objects.using("default").filter(pk__in=user_ids)
        users_by_id = {user.pk: user for user in users}
        avatars = Avatar.objects.using("default").filter(user_id__in=user_ids).select_related("user")
        avatars_by_user = {avatar.user_id: _avatar_url(avatar.user) for avatar in avatars}
        participants = tuple(
            TaskDetailParticipant(
                user_id=user_id,
                username=users_by_id[user_id].username if user_id in users_by_id else str(user_id),
                rol=role,
                avatar_url=avatars_by_user.get(user_id, ""),
            )
            for user_id, role in participant_rows
        )
        hierarchy = TaskDetailHierarchy(
            parent=parent_reference,
            children=children,
            effectively_annulled=ancestor_annulled,
        )
        mini_tasks = tuple(
            TaskDetailMiniTask(
                id=mini.pk,
                descripcion=mini.descripcion,
                persona_id=mini.persona_id,
                persona_username=users_by_id.get(mini.persona_id).username
                if mini.persona_id in users_by_id
                else "",
                persona_avatar_url=avatars_by_user.get(mini.persona_id, ""),
                hecho=mini.hecho,
                fecha_creacion=mini.fecha_creacion,
                fecha_completado=mini.fecha_completado,
                eventos_t104=tuple(
                    TaskDetailMiniTaskEvent(
                        id=event.pk,
                        tipo=event.tipo,
                        fecha=event.fecha,
                        comentario=event.comentario,
                        comentario_oculto=bool(
                            event.comentario_feed and event.comentario_feed.oculto
                        ),
                        attachments=_event_attachments(event),
                        actor_id=event.actor_id,
                        actor_username=users_by_id[event.actor_id].username
                        if event.actor_id in users_by_id else str(event.actor_id),
                        comentario_feed_id=event.comentario_feed_id,
                        destinatarios_notificacion=tuple(event.destinatarios_notificacion),
                        destinatarios_email=tuple(event.destinatarios_email),
                    )
                    for event in getattr(mini, "detail_events", ())
                ),
                ultimo_cierre_adjuntos_t104=(
                    _last_closure_attachments(getattr(mini, "detail_events", ()))
                    if mini.hecho
                    else ()
                ),
            )
            for mini in mini_task_rows
        )
        links = tuple(
            TaskDetailLink(
                id=link.pk,
                destinatario_id=link.destinatario_id,
                destinatario_username=users_by_id.get(link.destinatario_id).username
                if link.destinatario_id in users_by_id
                else "",
                destinatario_avatar_url=avatars_by_user.get(link.destinatario_id, ""),
                creado_por_id=link.creado_por_id,
                creado_por_username=users_by_id.get(link.creado_por_id).username
                if link.creado_por_id in users_by_id
                else "",
                revocado_por_id=link.revocado_por_id,
                revocado_por_username=users_by_id.get(link.revocado_por_id).username
                if link.revocado_por_id in users_by_id
                else "",
                fecha_creacion=link.fecha_creacion,
                fecha_expiracion=link.fecha_expiracion,
                fecha_revocacion=link.revocado_at,
                estado=_link_status(
                    revocado_at=link.revocado_at,
                    fecha_expiracion=link.fecha_expiracion,
                ),
            )
            for link in link_rows
        )
        milestones = tuple(
            TaskDetailMilestone(
                id=milestone.pk,
                nombre=milestone.nombre,
                responsable_id=milestone.responsable_id,
                responsable_username=users_by_id.get(milestone.responsable_id).username
                if milestone.responsable_id in users_by_id
                else "",
                responsable_avatar_url=avatars_by_user.get(milestone.responsable_id, ""),
                anulado=milestone.anulado,
                completado=milestone.completado,
                completado_por_id=milestone.completado_por_id,
                completado_por_username=users_by_id.get(milestone.completado_por_id).username
                if milestone.completado_por_id in users_by_id
                else "",
                cumplimiento=milestone.cumplimiento,
                peso=milestone.peso,
                fecha_creacion=milestone.fecha_creacion,
                fecha_completado=milestone.fecha_completado,
                resena_cierre=milestone.resena_cierre,
                evidencias=tuple(
                    _milestone_evidence_dto(evidence, users_by_id)
                    for evidence in getattr(milestone, "detail_evidence", ())
                ),
            )
            for milestone in milestone_rows
        )
        documents = tuple(
            TaskDetailDocument(
                id=document.pk,
                tipo=document.tipo,
                tipo_display=_choice_label(DocumentoTarea.Tipo.choices, document.tipo),
                formato_archivo=document.formato_archivo,
                formato_archivo_display=_choice_label(
                    DocumentoTarea.FormatoArchivo.choices,
                    document.formato_archivo,
                ),
                nombre_archivo=_file_metadata(document)[0],
                archivo_url=_file_metadata(document)[1],
                url=document.url,
                fecha_documento=document.fecha_documento,
                fecha_vencimiento=document.fecha_vencimiento,
                usuario_id=document.usuario_id,
                usuario_username=users_by_id.get(document.usuario_id).username
                if document.usuario_id in users_by_id
                else "",
                historial=tuple(
                    TaskDetailDocumentHistory(
                        id=history.pk,
                        accion=history.accion,
                        usuario_id=history.usuario_id,
                        usuario_username=users_by_id.get(history.usuario_id).username
                        if history.usuario_id in users_by_id
                        else "",
                        fecha=history.fecha,
                    )
                    for history in getattr(document, "detail_history", ())
                ),
            )
            for document in document_rows
        )
        closure_evidence = tuple(
            TaskDetailClosureEvidence(
                id=evidence.pk,
                formato_archivo=evidence.formato_archivo,
                formato_archivo_display=_choice_label(
                    DocumentoTarea.FormatoArchivo.choices,
                    evidence.formato_archivo,
                ),
                nombre_archivo=_file_metadata(evidence)[0],
                archivo_url=_file_metadata(evidence)[1],
                url=evidence.url,
                usuario_id=evidence.usuario_id,
                usuario_username=users_by_id.get(evidence.usuario_id).username
                if evidence.usuario_id in users_by_id
                else "",
                fecha=evidence.fecha,
            )
            for evidence in closure_evidence_rows
        )
        return TaskDetailResult(
            core=core,
            hierarchy=hierarchy,
            participants=participants,
            effective_user_ids=tuple(sorted(pk for pk in effective_user_ids if pk is not None)),
            mini_tasks=mini_tasks,
            links=links,
            progress=progress,
            milestones=milestones,
            documents=documents,
            closure_evidence=closure_evidence,
            reprogramming_causes=reprogramming_causes,
            reprogramming_history=tuple(replace(
                item,
                usuario_username=users_by_id[item.usuario_id].username
                if item.usuario_id in users_by_id else "",
                usuario_avatar_url=avatars_by_user.get(item.usuario_id, ""),
            ) for item in reprogramming_history),
        )


def _mysql_file_metadata(filename, url):
    filename = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not filename and url:
        filename = url.rstrip("/").rsplit("/", 1)[-1]
    return filename, "" if not filename or not filename == (filename or "") else ""


def _milestone_file_url(filename):
    if not filename:
        return ""
    try:
        return HitoEvidencia._meta.get_field("archivo").storage.url(filename)
    except (ValueError, NotImplementedError):
        return ""


class MySQLTaskDetailStorage:
    """Read-only Detail storage backed by the frozen BASE_TAREAS schema."""

    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    @staticmethod
    def _rows(cursor, sql, params=()):
        cursor.execute(sql, tuple(params))
        columns = [item[0] for item in cursor.description or ()]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    @staticmethod
    def _users(user_ids):
        users = User.objects.using("default").filter(pk__in=user_ids)
        users_by_id = {user.pk: user for user in users}
        avatars = Avatar.objects.using("default").filter(user_id__in=user_ids).select_related("user")
        avatars_by_id = {avatar.user_id: _avatar_url(avatar.user) for avatar in avatars}
        return users_by_id, avatars_by_id

    @staticmethod
    def _file(filename, url):
        name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        if not name and url:
            name = url.rstrip("/").rsplit("/", 1)[-1]
        return name, ""

    def get_task_detail(self, *, task_id: int, empresa_id: int, sections: TaskDetailSections):
        try:
            return self._get_task_detail(
                task_id=task_id,
                empresa_id=empresa_id,
                sections=sections,
            )
        except DetailTaskNotFound:
            raise
        except TaskStorageError:
            raise
        except Exception as exc:
            raise TaskStorageError(
                "No se pudo leer el detalle desde el almacenamiento de tareas."
            ) from exc

    def _get_task_detail(self, *, task_id: int, empresa_id: int, sections: TaskDetailSections):
        user_ids = set()
        with open_mysql_connection(
            self.connection_config,
            database_name=self.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                task_rows = self._rows(
                    cursor,
                    "SELECT id, titulo, descripcion, prioridad, correlativo, anulada, "
                    "fechas_pendientes_confirmacion, requiere_evidencia_cierre, estado, "
                    "responsable_id, empresa_id, creada_por_id, fecha_creacion, "
                    "fecha_publicacion, fecha_asignacion, fecha_tope, fecha_cumplimiento "
                    "FROM tareas_tarea WHERE id = %s AND empresa_id = %s",
                    (task_id, empresa_id),
                )
                if not task_rows:
                    raise DetailTaskNotFound
                task = task_rows[0]
                reprogramming_causes, reprogramming_history = mysql_reprogramming_detail(
                    cursor, task_id, empresa_id
                )
                user_ids.update(item.usuario_id for item in reprogramming_history)
                user_ids.update((task["creada_por_id"], task["responsable_id"]))

                parent_rows = self._rows(
                    cursor,
                    "SELECT p.id, p.correlativo, p.titulo, p.estado, p.anulada "
                    "FROM tareas_tarearelacion r JOIN tareas_tarea p ON p.id = r.padre_id "
                    "WHERE r.hija_id = %s AND p.empresa_id = %s LIMIT 1",
                    (task_id, empresa_id),
                )
                child_rows = self._rows(
                    cursor,
                    "SELECT c.id, c.correlativo, c.titulo, c.estado, c.anulada "
                    "FROM tareas_tarearelacion r JOIN tareas_tarea c ON c.id = r.hija_id "
                    "WHERE r.padre_id = %s AND c.empresa_id = %s ORDER BY c.id",
                    (task_id, empresa_id),
                )
                participant_rows = self._rows(
                    cursor,
                    "SELECT usuario_id, rol FROM tareas_tareaparticipante "
                    "WHERE tarea_id = %s ORDER BY id",
                    (task_id,),
                )
                user_ids.update(row["usuario_id"] for row in participant_rows)
                effective_rows = self._rows(
                    cursor,
                    "SELECT responsable_id AS usuario_id FROM tareas_hito "
                    "WHERE tarea_id = %s AND anulado = 0",
                    (task_id,),
                )
                effective_rows.extend(self._rows(
                    cursor,
                    "SELECT persona_id AS usuario_id FROM tareas_minitarea "
                    "WHERE tarea_id = %s",
                    (task_id,),
                ))
                effective_user_ids = {
                    row["usuario_id"] for row in effective_rows if row["usuario_id"] is not None
                }

                ancestor_annulled = bool(task["anulada"])
                current_parent_id = parent_rows[0]["id"] if parent_rows else None
                for _level in range(2):
                    if current_parent_id is None:
                        break
                    ancestor_rows = self._rows(
                        cursor,
                        "SELECT p.id, p.anulada FROM tareas_tarearelacion r "
                        "JOIN tareas_tarea p ON p.id = r.padre_id "
                        "WHERE r.hija_id = %s AND p.empresa_id = %s LIMIT 1",
                        (current_parent_id, empresa_id),
                    )
                    if not ancestor_rows:
                        break
                    ancestor_annulled = ancestor_annulled or bool(ancestor_rows[0]["anulada"])
                    current_parent_id = ancestor_rows[0]["id"]

                mini_rows = []
                event_rows = []
                event_attachments = {}
                if sections.mini_tasks:
                    mini_rows = self._rows(
                        cursor,
                        "SELECT id, descripcion, persona_id, hecho, fecha_creacion, fecha_completado "
                        "FROM tareas_minitarea WHERE tarea_id = %s ORDER BY fecha_creacion, id",
                        (task_id,),
                    )
                    mini_ids = [row["id"] for row in mini_rows]
                    user_ids.update(row["persona_id"] for row in mini_rows)
                    if mini_ids:
                        marks = ", ".join("%s" for _ in mini_ids)
                        event_rows = self._rows(
                            cursor,
                            "SELECT e.id, e.mini_tarea_id, e.comentario_feed_id, e.tipo, "
                            "e.actor_id, e.fecha, e.comentario, c.oculto, "
                            "e.destinatarios_notificacion, e.destinatarios_email "
                            "FROM tareas_minitareaevento e LEFT JOIN tareas_comentario c "
                            "ON c.id = e.comentario_feed_id "
                            f"WHERE e.mini_tarea_id IN ({marks}) ORDER BY e.mini_tarea_id, e.fecha, e.id",
                            mini_ids,
                        )
                        user_ids.update(row["actor_id"] for row in event_rows)
                        event_ids = [row["comentario_feed_id"] for row in event_rows if row["comentario_feed_id"]]
                        if event_ids:
                            marks = ", ".join("%s" for _ in event_ids)
                            attachment_rows = self._rows(
                                cursor,
                                "SELECT ca.comentario_id, d.id, d.tipo, d.formato_archivo, "
                                "d.archivo, d.url FROM tareas_comentarioadjunto ca "
                                "JOIN tareas_documentotarea d ON d.id = ca.documento_id "
                                f"WHERE ca.comentario_id IN ({marks}) ORDER BY ca.id",
                                event_ids,
                            )
                            for row in attachment_rows:
                                event_attachments.setdefault(row["comentario_id"], []).append(row)

                link_rows = []
                if sections.links:
                    link_rows = self._rows(
                        cursor,
                        "SELECT id, destinatario_id, creado_por_id, revocado_por_id, "
                        "fecha_creacion, fecha_expiracion, revocado_at FROM tareas_enlacetarea "
                        "WHERE tarea_id = %s ORDER BY fecha_creacion DESC, id DESC",
                        (task_id,),
                    )
                    for row in link_rows:
                        user_ids.update(
                            item for item in (
                                row["destinatario_id"], row["creado_por_id"], row["revocado_por_id"]
                            ) if item is not None
                        )

                avance = None
                milestone_rows = []
                milestone_evidence = {}
                if sections.milestones:
                    avance_rows = self._rows(
                        cursor,
                        "SELECT modo, porcentaje FROM tareas_avance WHERE tarea_id = %s",
                        (task_id,),
                    )
                    avance = avance_rows[0] if avance_rows else None
                    milestone_rows = self._rows(
                        cursor,
                        "SELECT id, nombre, responsable_id, anulado, completado, completado_por_id, "
                        "fecha_completado, resena_cierre, cumplimiento, peso, fecha_creacion "
                        "FROM tareas_hito WHERE tarea_id = %s ORDER BY fecha_creacion, id",
                        (task_id,),
                    )
                    hito_ids = [row["id"] for row in milestone_rows]
                    user_ids.update(row["responsable_id"] for row in milestone_rows)
                    user_ids.update(row["completado_por_id"] for row in milestone_rows if row["completado_por_id"])
                    if hito_ids:
                        marks = ", ".join("%s" for _ in hito_ids)
                        evidence_rows = self._rows(
                            cursor,
                            "SELECT id, hito_id, formato_archivo, archivo, url, usuario_id, fecha "
                            f"FROM tareas_hitoevidencia WHERE hito_id IN ({marks}) ORDER BY fecha, id",
                            hito_ids,
                        )
                        for row in evidence_rows:
                            milestone_evidence.setdefault(row["hito_id"], []).append(row)
                            user_ids.add(row["usuario_id"])

                document_rows = []
                document_history = {}
                closure_rows = []
                if sections.documents:
                    document_rows = self._rows(
                        cursor,
                        "SELECT id, tipo, formato_archivo, archivo, url, fecha_documento, "
                        "fecha_vencimiento, usuario_id FROM tareas_documentotarea "
                        "WHERE tarea_id = %s ORDER BY id",
                        (task_id,),
                    )
                    document_ids = [row["id"] for row in document_rows]
                    user_ids.update(row["usuario_id"] for row in document_rows)
                    if document_ids:
                        marks = ", ".join("%s" for _ in document_ids)
                        history_rows = self._rows(
                            cursor,
                            "SELECT id, documento_id, accion, usuario_id, fecha "
                            f"FROM tareas_documentohistorial WHERE documento_id IN ({marks}) ORDER BY fecha, id",
                            document_ids,
                        )
                        for row in history_rows:
                            document_history.setdefault(row["documento_id"], []).append(row)
                            user_ids.add(row["usuario_id"])
                    closure_rows = self._rows(
                        cursor,
                        "SELECT id, formato_archivo, archivo, url, usuario_id, fecha "
                        "FROM tareas_evidenciacierre WHERE tarea_id = %s ORDER BY fecha DESC, id DESC",
                        (task_id,),
                    )
                    user_ids.update(row["usuario_id"] for row in closure_rows)
            finally:
                cursor.close()

        users_by_id, avatars_by_id = self._users({item for item in user_ids if item is not None})
        creator = users_by_id.get(task["creada_por_id"])
        responsible = users_by_id.get(task["responsable_id"])
        core = TaskDetailCore(
            id=task["id"], empresa_id=task["empresa_id"], correlativo=task["correlativo"],
            titulo=task["titulo"], descripcion=task["descripcion"], estado=task["estado"],
            prioridad=task["prioridad"], anulada=bool(task["anulada"]),
            fechas_pendientes_confirmacion=bool(task["fechas_pendientes_confirmacion"]),
            requiere_evidencia_cierre=bool(task["requiere_evidencia_cierre"]),
            fecha_creacion=task["fecha_creacion"], fecha_publicacion=task["fecha_publicacion"],
            fecha_asignacion=task["fecha_asignacion"], fecha_tope=task["fecha_tope"],
            fecha_cumplimiento=task["fecha_cumplimiento"], responsable_id=task["responsable_id"],
            creada_por_id=task["creada_por_id"], creada_por_username=creator.username if creator else "",
            creada_por_avatar_url=avatars_by_id.get(task["creada_por_id"], ""),
            responsable_username=responsible.username if responsible else "",
            responsable_avatar_url=avatars_by_id.get(task["responsable_id"], ""),
        )
        parent = None
        if parent_rows:
            row = parent_rows[0]
            parent = TaskDetailTaskReference(row["id"], row["correlativo"], row["titulo"], row["estado"], bool(row["anulada"]))
        hierarchy = TaskDetailHierarchy(
            parent=parent,
            children=tuple(TaskDetailTaskReference(row["id"], row["correlativo"], row["titulo"], row["estado"], bool(row["anulada"])) for row in child_rows),
            effectively_annulled=ancestor_annulled,
        )
        participants = tuple(
            TaskDetailParticipant(
                row["usuario_id"],
                users_by_id[row["usuario_id"]].username if row["usuario_id"] in users_by_id else str(row["usuario_id"]),
                row["rol"], avatars_by_id.get(row["usuario_id"], ""),
            )
            for row in sorted(participant_rows, key=lambda item: users_by_id.get(item["usuario_id"]).username if users_by_id.get(item["usuario_id"]) else "")
        )
        event_by_mini = {}
        for event in event_rows:
            attachments = tuple(
                TaskDetailAttachment(
                    id=item["id"], nombre_archivo=self._file(item["archivo"], item["url"])[0],
                    tipo=item["tipo"], formato_archivo=item["formato_archivo"],
                    url=item["url"], archivo_url=(
                        DocumentoTarea._meta.get_field("archivo").storage.url(item["archivo"])
                        if item["archivo"] else ""
                    ),
                ) for item in event_attachments.get(event["comentario_feed_id"], [])
            )
            event_by_mini.setdefault(event["mini_tarea_id"], []).append(
                TaskDetailMiniTaskEvent(
                    event["id"], event["tipo"], event["fecha"], event["comentario"],
                    bool(event["oculto"]), attachments,
                    actor_id=event["actor_id"],
                    actor_username=users_by_id[event["actor_id"]].username
                    if event["actor_id"] in users_by_id else str(event["actor_id"]),
                    comentario_feed_id=event["comentario_feed_id"],
                    destinatarios_notificacion=tuple(json.loads(event["destinatarios_notificacion"])),
                    destinatarios_email=tuple(json.loads(event["destinatarios_email"])),
                )
            )
        mini_tasks = []
        for row in mini_rows:
            events = tuple(event_by_mini.get(row["id"], ()))
            closures = [event.attachments for event in reversed(events) if event.tipo == "CIERRE"]
            mini_tasks.append(TaskDetailMiniTask(
                id=row["id"], descripcion=row["descripcion"], persona_id=row["persona_id"],
                persona_username=users_by_id.get(row["persona_id"]).username if row["persona_id"] in users_by_id else "",
                persona_avatar_url=avatars_by_id.get(row["persona_id"], ""), hecho=bool(row["hecho"]),
                fecha_creacion=row["fecha_creacion"], fecha_completado=row["fecha_completado"],
                eventos_t104=events,
                ultimo_cierre_adjuntos_t104=closures[0] if row["hecho"] and closures else (),
            ))
        links = tuple(TaskDetailLink(
            id=row["id"], destinatario_id=row["destinatario_id"],
            destinatario_username=users_by_id.get(row["destinatario_id"]).username if row["destinatario_id"] in users_by_id else "",
            destinatario_avatar_url=avatars_by_id.get(row["destinatario_id"], ""), creado_por_id=row["creado_por_id"],
            creado_por_username=users_by_id.get(row["creado_por_id"]).username if row["creado_por_id"] in users_by_id else "",
            revocado_por_id=row["revocado_por_id"], revocado_por_username=users_by_id.get(row["revocado_por_id"]).username if row["revocado_por_id"] in users_by_id else "",
            fecha_creacion=row["fecha_creacion"], fecha_expiracion=row["fecha_expiracion"], fecha_revocacion=row["revocado_at"],
            estado=_link_status(revocado_at=row["revocado_at"], fecha_expiracion=row["fecha_expiracion"]),
        ) for row in link_rows)
        active = [row for row in milestone_rows if not row["anulado"]]
        weight = sum((Decimal(str(row["peso"])) for row in active), Decimal("0"))
        weighted = (sum((Decimal(str(row["cumplimiento"])) * Decimal(str(row["peso"])) for row in active), Decimal("0")) / weight if weight else Decimal("0")).quantize(Decimal("0.01"))
        progress = None
        if sections.milestones:
            progress = TaskDetailProgress(
                configured=avance is not None, mode=avance["modo"] if avance else "",
                mode_display=dict(Avance.Modo.choices).get(avance["modo"], avance["modo"]) if avance else "",
                percentage=Decimal(str(avance["porcentaje"])) if avance else Decimal("0.00"), weighted_percentage=weighted,
            )
        milestones = tuple(TaskDetailMilestone(
            id=row["id"], nombre=row["nombre"], responsable_id=row["responsable_id"],
            responsable_username=users_by_id.get(row["responsable_id"]).username if row["responsable_id"] in users_by_id else "",
            responsable_avatar_url=avatars_by_id.get(row["responsable_id"], ""), anulado=bool(row["anulado"]), completado=bool(row["completado"]),
            completado_por_id=row["completado_por_id"], completado_por_username=users_by_id.get(row["completado_por_id"]).username if row["completado_por_id"] in users_by_id else "",
            cumplimiento=Decimal(str(row["cumplimiento"])), peso=Decimal(str(row["peso"])), fecha_creacion=row["fecha_creacion"], fecha_completado=row["fecha_completado"], resena_cierre=row["resena_cierre"],
            evidencias=tuple(TaskDetailMilestoneEvidence(
                id=item["id"], formato_archivo=item["formato_archivo"], nombre_archivo=self._file(item["archivo"], item["url"])[0], url=item["url"], archivo_url=_milestone_file_url(item["archivo"]), usuario_id=item["usuario_id"], usuario_username=users_by_id.get(item["usuario_id"]).username if item["usuario_id"] in users_by_id else "", fecha=item["fecha"]
            ) for item in milestone_evidence.get(row["id"], ()))
        ) for row in milestone_rows)
        documents = tuple(TaskDetailDocument(
            id=row["id"], tipo=row["tipo"], tipo_display=dict(DocumentoTarea.Tipo.choices).get(row["tipo"], row["tipo"]), formato_archivo=row["formato_archivo"], formato_archivo_display=dict(DocumentoTarea.FormatoArchivo.choices).get(row["formato_archivo"], row["formato_archivo"]), nombre_archivo=self._file(row["archivo"], row["url"])[0], archivo_url="", url=row["url"], fecha_documento=row["fecha_documento"], fecha_vencimiento=row["fecha_vencimiento"], usuario_id=row["usuario_id"], usuario_username=users_by_id.get(row["usuario_id"]).username if row["usuario_id"] in users_by_id else "", historial=tuple(TaskDetailDocumentHistory(item["id"], item["accion"], item["usuario_id"], users_by_id.get(item["usuario_id"]).username if item["usuario_id"] in users_by_id else "", item["fecha"]) for item in document_history.get(row["id"], ()))
        ) for row in document_rows)
        closure_evidence = tuple(TaskDetailClosureEvidence(
            id=row["id"], formato_archivo=row["formato_archivo"], formato_archivo_display=dict(DocumentoTarea.FormatoArchivo.choices).get(row["formato_archivo"], row["formato_archivo"]), nombre_archivo=self._file(row["archivo"], row["url"])[0], archivo_url="", url=row["url"], usuario_id=row["usuario_id"], usuario_username=users_by_id.get(row["usuario_id"]).username if row["usuario_id"] in users_by_id else "", fecha=row["fecha"]
        ) for row in closure_rows)
        return TaskDetailResult(
            core=core, hierarchy=hierarchy, participants=participants,
            effective_user_ids=tuple(sorted(effective_user_ids)),
            mini_tasks=tuple(mini_tasks), links=links, progress=progress,
            milestones=milestones, documents=documents, closure_evidence=closure_evidence,
            reprogramming_causes=reprogramming_causes,
            reprogramming_history=tuple(replace(
                item,
                usuario_username=users_by_id[item.usuario_id].username
                if item.usuario_id in users_by_id else "",
                usuario_avatar_url=avatars_by_id.get(item.usuario_id, ""),
            ) for item in reprogramming_history),
        )


def resolve_detail_storage() -> DjangoTaskDetailStorage:
    try:
        source = get_tarea_connection("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise TaskStorageError("No se pudo resolver el almacenamiento de tareas.") from exc
    if source["type"] == "MYSQL_CONFIG":
        try:
            return MySQLTaskDetailStorage(
                get_tarea_mysql_connection("BASE_TAREAS"),
                source["database_name"],
            )
        except TareaConnectionError as exc:
            raise TaskStorageError(
                "No se pudo resolver el almacenamiento de tareas."
            ) from exc
    if source["type"] != "DJANGO":
        raise TaskStorageError("El backend de BASE_TAREAS no es válido.")
    return DjangoTaskDetailStorage(source["alias"])
