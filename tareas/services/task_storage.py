"""Storage boundary for creating a Tareas draft."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import logging
import re
from types import SimpleNamespace

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from acounts.models import Avatar
from django.contrib.auth.models import User
from access_control.services.permissions import get_valid_users_for_empresa

from .connection_roles import (
    TareaConnectionError,
    get_tarea_connection,
    resolve_operational_backend,
)
from ..models import Empresa, Tarea, TareaLectura, TareaParticipante, TareaTransicion
from .notifications import emit_task_event, task_recipients
from settings.services.mysql_connections import open_mysql_connection

logger = logging.getLogger(__name__)


class TaskStorageError(RuntimeError):
    """Base error for the Tareas storage boundary."""


class TaskStorageBackendNotImplemented(TaskStorageError):
    """The configured BASE_TAREAS backend is not implemented yet."""


class EditTaskNotFound(TaskStorageError):
    """The task is absent or outside the active company for Edit."""


@dataclass(frozen=True)
class TaskEditData:
    id: int
    empresa_id: int
    titulo: str
    descripcion: str
    prioridad: str
    responsable_id: int | None
    fecha_tope: object
    estado: str


@dataclass(frozen=True)
class UpdateTaskCommand:
    task_id: int
    empresa_id: int
    titulo: str
    descripcion: str
    prioridad: str
    responsable_id: int | None
    fecha_tope: object


class LifecycleSimilarityUnsupported(TaskStorageError):
    """MySQL publication requires the not-yet-portable similarity review flow."""


@dataclass(frozen=True)
class TaskLifecycleResult:
    task_id: int
    empresa_id: int
    previous_state: str
    state: str
    correlativo: str
    fecha_publicacion: object = None
    fecha_asignacion: object = None
    transition_id: int | None = None


def ensure_existing_task_backend_supported(operation: str) -> None:
    """Reject legacy existing-task flows before they can query Django/default."""
    try:
        source = get_tarea_connection("BASE_TAREAS")
    except TareaConnectionError:
        # Preserve legacy Django-only callers when no role has been configured.
        return
    if source["type"] == "MYSQL_CONFIG":
        raise TaskStorageBackendNotImplemented(
            "La operación aún no está disponible para el almacenamiento de tareas configurado."
        )


@dataclass(frozen=True)
class TaskListFilters:
    search: str = ""
    estado: str = ""
    prioridad: str = ""


@dataclass(frozen=True)
class TaskListParticipant:
    user_id: int
    username: str
    rol: str
    avatar_url: str = ""


@dataclass(frozen=True)
class TaskListItem:
    id: int
    empresa_id: int
    correlativo: str
    titulo: str
    prioridad: str
    estado: str
    fecha_tope: object
    fecha_creacion: object
    responsable_id: int | None
    responsable_username: str = ""
    responsable_avatar_url: str = ""
    participantes_visibles: tuple[TaskListParticipant, ...] = ()
    participantes_restantes: int = 0


@dataclass
class PersonalTaskItem:
    id: int
    empresa_id: int
    correlativo: str
    titulo: str
    descripcion: str
    prioridad: str
    estado: str
    anulada: bool
    responsable_id: int | None
    responsable: object
    fecha_tope: object
    fecha_publicacion: object
    fecha_asignacion: object
    fecha_cumplimiento: object
    fecha_creacion: object

    @property
    def pk(self):
        return self.id


@dataclass(frozen=True)
class TaskListResult:
    items: tuple[TaskListItem, ...]
    summary: dict[str, int]


@dataclass(frozen=True)
class CreateTaskDraftInput:
    titulo: str
    descripcion: str
    prioridad: str
    responsable_id: int | None
    fecha_tope: object


@dataclass(frozen=True)
class CreatedTaskResult:
    id: int
    empresa_id: int
    correlativo: str
    estado: str
    task: Tarea | None = None
    responsable_id: int | None = None
    prioridad: str = Tarea.Prioridad.NORMAL


class DjangoTaskStorage:
    def __init__(self, alias: str):
        self.alias = alias

    def create_draft(
        self,
        data: CreateTaskDraftInput,
        *,
        empresa_id: int,
        creador_id: int,
    ) -> CreatedTaskResult:
        task = Tarea(
            titulo=data.titulo,
            descripcion=data.descripcion,
            prioridad=data.prioridad,
            responsable_id=data.responsable_id,
            fecha_tope=data.fecha_tope,
            empresa_id=empresa_id,
            creada_por_id=creador_id,
        )
        try:
            with transaction.atomic(using=self.alias):
                task.save(using=self.alias)
        except Exception as exc:
            raise TaskStorageError(
                "No se pudo crear el borrador de Tarea."
            ) from exc
        return CreatedTaskResult(
            id=task.pk,
            empresa_id=task.empresa_id,
            correlativo=task.correlativo,
            estado=task.estado,
            task=task,
            responsable_id=task.responsable_id,
            prioridad=task.prioridad,
        )

    def get_task_for_edit(self, *, task_id: int, empresa_id: int) -> TaskEditData:
        try:
            task = Tarea.objects.using(self.alias).get(pk=task_id, empresa_id=empresa_id)
        except Tarea.DoesNotExist as exc:
            raise EditTaskNotFound from exc
        return TaskEditData(
            id=task.pk,
            empresa_id=task.empresa_id,
            titulo=task.titulo,
            descripcion=task.descripcion,
            prioridad=task.prioridad,
            responsable_id=task.responsable_id,
            fecha_tope=task.fecha_tope,
            estado=task.estado,
        )

    def update_task(self, command: UpdateTaskCommand) -> TaskEditData:
        try:
            with transaction.atomic(using=self.alias):
                updated = Tarea.objects.using(self.alias).filter(
                    pk=command.task_id,
                    empresa_id=command.empresa_id,
                ).update(
                    titulo=command.titulo,
                    descripcion=command.descripcion,
                    prioridad=command.prioridad,
                    responsable_id=command.responsable_id,
                    fecha_tope=command.fecha_tope,
                )
        except Exception as exc:
            raise TaskStorageError("No se pudo actualizar la Tarea.") from exc
        if not updated:
            raise EditTaskNotFound
        return self.get_task_for_edit(
            task_id=command.task_id,
            empresa_id=command.empresa_id,
        )

    def _locked_row(self, cursor, task_id, empresa_id):
        cursor.execute(
            "SELECT id, empresa_id, correlativo, anulada, estado, responsable_id, "
            "fecha_tope, fecha_publicacion, fecha_asignacion FROM tareas_tarea "
            "WHERE id = %s AND empresa_id = %s FOR UPDATE",
            (task_id, empresa_id),
        )
        return cursor.fetchone()

    def publish_task(self, *, task_id: int, empresa_id: int, actor_id: int) -> TaskLifecycleResult:
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        "SELECT id FROM tareas_tarea WHERE empresa_id = %s "
                        "AND estado IN (%s, %s, %s, %s) AND anulada = %s AND id <> %s LIMIT 1",
                        (empresa_id, Tarea.Estado.ACTIVA, Tarea.Estado.GESTION, Tarea.Estado.PENDIENTE_APROBACION_CIERRE, Tarea.Estado.CERRADA, False, task_id),
                    )
                    if cursor.fetchone() is not None:
                        raise LifecycleSimilarityUnsupported("La publicación MYSQL requiere revisión de similitud no disponible en este backend.")
                    if callable(getattr(connection, "begin", None)):
                        connection.begin()
                    row = self._locked_row(cursor, task_id, empresa_id)
                    if row is None:
                        raise EditTaskNotFound
                    _id, _company, correlativo, annulled, state, responsible_id, due_date, _published, assigned_at = row
                    if state != Tarea.Estado.BORRADOR:
                        raise ValidationError("La tarea ya está publicada.")
                    if annulled:
                        raise ValidationError("La tarea está anulada; no puede publicarse.")
                    empresa = Empresa.objects.using("default").get(pk=empresa_id)
                    if responsible_id is None or not get_valid_users_for_empresa(empresa, active_only=True).filter(pk=responsible_id).exists():
                        raise ValidationError("No se puede publicar: la tarea requiere un responsable válido y activo.")
                    if due_date is None:
                        raise ValidationError("No se puede publicar: la tarea requiere fecha tope.")
                    if not re.fullmatch(r"B[0-9]{7}", correlativo or ""):
                        raise ValidationError("No se puede publicar: el correlativo de borrador no es válido.")
                    now = timezone.now()
                    new_correlativo = f"A{correlativo[1:]}"
                    cursor.execute(
                        "UPDATE tareas_tarea SET estado=%s, correlativo=%s, fecha_publicacion=%s, fecha_asignacion=%s WHERE id=%s AND empresa_id=%s",
                        (Tarea.Estado.ACTIVA, new_correlativo, now, assigned_at or now, task_id, empresa_id),
                    )
                    cursor.execute(
                        "INSERT INTO tareas_tareatransicion (tarea_id, estado_origen, estado_destino, accion_evento, usuario_id, timestamp, motivo) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (task_id, Tarea.Estado.BORRADOR, Tarea.Estado.ACTIVA, "PUBLICAR", actor_id, now, ""),
                    )
                    transition_id = cursor.lastrowid
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except (EditTaskNotFound, LifecycleSimilarityUnsupported, ValidationError):
            raise
        except Exception as exc:
            raise TaskStorageError("No se pudo publicar la Tarea.") from exc
        return TaskLifecycleResult(task_id, empresa_id, Tarea.Estado.BORRADOR, Tarea.Estado.ACTIVA, new_correlativo, now, assigned_at or now, transition_id)

    def enter_management(self, *, task_id: int, empresa_id: int, actor_id: int) -> TaskLifecycleResult:
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor = connection.cursor()
                try:
                    if callable(getattr(connection, "begin", None)):
                        connection.begin()
                    row = self._locked_row(cursor, task_id, empresa_id)
                    if row is None:
                        raise EditTaskNotFound
                    _id, _company, correlativo, annulled, state, _responsible, _due, _published, _assigned = row
                    if state != Tarea.Estado.ACTIVA:
                        raise ValidationError("Transición no permitida: la tarea no está ACTIVA.")
                    if annulled:
                        raise ValidationError("La tarea está anulada; no admite operaciones de ciclo.")
                    now = timezone.now()
                    cursor.execute("UPDATE tareas_tarea SET estado=%s WHERE id=%s AND empresa_id=%s", (Tarea.Estado.GESTION, task_id, empresa_id))
                    cursor.execute(
                        "INSERT INTO tareas_tareatransicion (tarea_id, estado_origen, estado_destino, accion_evento, usuario_id, timestamp, motivo) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (task_id, Tarea.Estado.ACTIVA, Tarea.Estado.GESTION, "INICIAR_GESTION", actor_id, now, ""),
                    )
                    transition_id = cursor.lastrowid
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except (EditTaskNotFound, ValidationError):
            raise
        except Exception as exc:
            raise TaskStorageError("No se pudo iniciar la gestión de la Tarea.") from exc
        return TaskLifecycleResult(task_id, empresa_id, Tarea.Estado.ACTIVA, Tarea.Estado.GESTION, correlativo, transition_id=transition_id)

    def _begin(self, connection):
        begin = getattr(connection, "begin", None)
        if callable(begin):
            begin()

    def _select_locked(self, cursor, task_id, empresa_id):
        cursor.execute(
            "SELECT id, empresa_id, titulo, descripcion, prioridad, correlativo, "
            "anulada, estado, responsable_id, fecha_tope, fecha_publicacion, "
            "fecha_asignacion FROM tareas_tarea "
            "WHERE id = %s AND empresa_id = %s FOR UPDATE",
            (task_id, empresa_id),
        )
        return cursor.fetchone()

    def _validate_mysql_responsible(self, empresa_id, responsible_id):
        if responsible_id is None:
            raise ValidationError("No se puede publicar: la tarea requiere un responsable válido y activo.")
        empresa = Empresa.objects.using("default").get(pk=empresa_id)
        if not get_valid_users_for_empresa(empresa, active_only=True).filter(
            pk=responsible_id,
        ).exists():
            raise ValidationError("No se puede publicar: la tarea requiere un responsable válido y activo.")

    def publish_task(self, *, task_id: int, empresa_id: int, actor_id: int) -> TaskLifecycleResult:
        empresa = Empresa.objects.using("default").get(pk=empresa_id)
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        "SELECT id FROM tareas_tarea WHERE empresa_id = %s "
                        "AND estado IN (%s, %s, %s, %s) AND anulada = %s AND id <> %s LIMIT 1",
                        (empresa_id, Tarea.Estado.ACTIVA, Tarea.Estado.GESTION, Tarea.Estado.PENDIENTE_APROBACION_CIERRE, Tarea.Estado.CERRADA, False, task_id),
                    )
                    if cursor.fetchone() is not None:
                        raise LifecycleSimilarityUnsupported(
                            "La publicación MYSQL requiere revisión de similitud no disponible en este backend."
                        )
                    self._begin(connection)
                    row = self._select_locked(cursor, task_id, empresa_id)
                    if row is None:
                        raise EditTaskNotFound
                    (
                        _id, _empresa_id, _titulo, _descripcion, _priority, correlativo,
                        anulada, state, responsible_id, due_date, published_at, assigned_at,
                    ) = row
                    if state != Tarea.Estado.BORRADOR:
                        raise ValidationError("La tarea ya está publicada.")
                    if anulada:
                        raise ValidationError("La tarea está anulada; no puede publicarse.")
                    self._validate_mysql_responsible(empresa_id, responsible_id)
                    if due_date is None:
                        raise ValidationError("No se puede publicar: la tarea requiere fecha tope.")
                    if not re.fullmatch(r"B[0-9]{7}", correlativo or ""):
                        raise ValidationError("No se puede publicar: el correlativo de borrador no es válido.")
                    now = timezone.now()
                    new_correlativo = f"A{correlativo[1:]}"
                    cursor.execute(
                        "UPDATE tareas_tarea SET estado = %s, correlativo = %s, "
                        "fecha_publicacion = %s, fecha_asignacion = %s "
                        "WHERE id = %s AND empresa_id = %s",
                        (Tarea.Estado.ACTIVA, new_correlativo, now, assigned_at or now, task_id, empresa_id),
                    )
                    cursor.execute(
                        "INSERT INTO tareas_tareatransicion "
                        "(tarea_id, estado_origen, estado_destino, accion_evento, usuario_id, timestamp, motivo) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (task_id, Tarea.Estado.BORRADOR, Tarea.Estado.ACTIVA, "PUBLICAR", actor_id, now, ""),
                    )
                    transition_id = cursor.lastrowid
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except (EditTaskNotFound, LifecycleSimilarityUnsupported, ValidationError):
            raise
        except Exception as exc:
            raise TaskStorageError("No se pudo publicar la Tarea.") from exc
        return TaskLifecycleResult(task_id, empresa_id, Tarea.Estado.BORRADOR, Tarea.Estado.ACTIVA, new_correlativo, now, assigned_at or now, transition_id)

    def enter_management(self, *, task_id: int, empresa_id: int, actor_id: int) -> TaskLifecycleResult:
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor = connection.cursor()
                try:
                    self._begin(connection)
                    row = self._select_locked(cursor, task_id, empresa_id)
                    if row is None:
                        raise EditTaskNotFound
                    _id, _empresa_id, _titulo, _description, _priority, correlativo, anulada, state, _responsible, _due, _published, _assigned = row
                    if state != Tarea.Estado.ACTIVA:
                        raise ValidationError("Transición no permitida: la tarea no está ACTIVA.")
                    if anulada:
                        raise ValidationError("La tarea está anulada; no admite operaciones de ciclo.")
                    now = timezone.now()
                    cursor.execute(
                        "UPDATE tareas_tarea SET estado = %s WHERE id = %s AND empresa_id = %s",
                        (Tarea.Estado.GESTION, task_id, empresa_id),
                    )
                    cursor.execute(
                        "INSERT INTO tareas_tareatransicion "
                        "(tarea_id, estado_origen, estado_destino, accion_evento, usuario_id, timestamp, motivo) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (task_id, Tarea.Estado.ACTIVA, Tarea.Estado.GESTION, "INICIAR_GESTION", actor_id, now, ""),
                    )
                    transition_id = cursor.lastrowid
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except (EditTaskNotFound, ValidationError):
            raise
        except Exception as exc:
            raise TaskStorageError("No se pudo iniciar la gestión de la Tarea.") from exc
        return TaskLifecycleResult(task_id, empresa_id, Tarea.Estado.ACTIVA, Tarea.Estado.GESTION, correlativo, transition_id=transition_id)

    def publish_task(self, *, task_id: int, empresa_id: int, actor_id: int) -> TaskLifecycleResult:
        with transaction.atomic(using=self.alias):
            try:
                task = Tarea.objects.using(self.alias).select_for_update().get(
                    pk=task_id,
                    empresa_id=empresa_id,
                )
            except Tarea.DoesNotExist as exc:
                raise EditTaskNotFound from exc
            if task.estado != Tarea.Estado.BORRADOR:
                raise ValidationError("La tarea ya está publicada.")
            if task.anulada:
                raise ValidationError("La tarea está anulada; no puede publicarse.")
            empresa = Empresa.objects.using("default").get(pk=empresa_id)
            responsible = User.objects.using("default").filter(
                pk=task.responsable_id,
                is_active=True,
            )
            if task.responsable_id is None or not get_valid_users_for_empresa(
                empresa,
                active_only=True,
            ).filter(pk=task.responsable_id).exists():
                raise ValidationError("No se puede publicar: la tarea requiere un responsable válido y activo.")
            if task.fecha_tope is None:
                raise ValidationError("No se puede publicar: la tarea requiere fecha tope.")
            if not re.fullmatch(r"B[0-9]{7}", task.correlativo or ""):
                raise ValidationError("No se puede publicar: el correlativo de borrador no es válido.")
            now = timezone.now()
            updated = Tarea.objects.using(self.alias).filter(
                pk=task_id,
                empresa_id=empresa_id,
                estado=Tarea.Estado.BORRADOR,
            ).update(
                estado=Tarea.Estado.ACTIVA,
                correlativo=f"A{task.correlativo[1:]}",
                fecha_publicacion=now,
                fecha_asignacion=task.fecha_asignacion or now,
            )
            if not updated:
                raise EditTaskNotFound
            transition = TareaTransicion.objects.using(self.alias).create(
                tarea_id=task_id,
                estado_origen=Tarea.Estado.BORRADOR,
                estado_destino=Tarea.Estado.ACTIVA,
                accion_evento="PUBLICAR",
                usuario_id=actor_id,
            )
        return TaskLifecycleResult(
            task_id=task_id,
            empresa_id=empresa_id,
            previous_state=Tarea.Estado.BORRADOR,
            state=Tarea.Estado.ACTIVA,
            correlativo=f"A{task.correlativo[1:]}",
            fecha_publicacion=now,
            fecha_asignacion=task.fecha_asignacion or now,
            transition_id=transition.pk,
        )

    def enter_management(self, *, task_id: int, empresa_id: int, actor_id: int) -> TaskLifecycleResult:
        with transaction.atomic(using=self.alias):
            try:
                task = Tarea.objects.using(self.alias).select_for_update().get(
                    pk=task_id,
                    empresa_id=empresa_id,
                )
            except Tarea.DoesNotExist as exc:
                raise EditTaskNotFound from exc
            if task.estado != Tarea.Estado.ACTIVA:
                raise ValidationError("Transición no permitida: la tarea no está ACTIVA.")
            if task.anulada:
                raise ValidationError("La tarea está anulada; no admite operaciones de ciclo.")
            updated = Tarea.objects.using(self.alias).filter(
                pk=task_id,
                empresa_id=empresa_id,
                estado=Tarea.Estado.ACTIVA,
            ).update(estado=Tarea.Estado.GESTION)
            if not updated:
                raise EditTaskNotFound
            transition = TareaTransicion.objects.using(self.alias).create(
                tarea_id=task_id,
                estado_origen=Tarea.Estado.ACTIVA,
                estado_destino=Tarea.Estado.GESTION,
                accion_evento="INICIAR_GESTION",
                usuario_id=actor_id,
            )
        return TaskLifecycleResult(
            task_id=task_id,
            empresa_id=empresa_id,
            previous_state=Tarea.Estado.ACTIVA,
            state=Tarea.Estado.GESTION,
            correlativo=task.correlativo,
            transition_id=transition.pk,
        )


def _avatar_url(user) -> str:
    try:
        avatar = user.avatar
    except ObjectDoesNotExist:
        avatar = None
    if avatar is None or not avatar.imagen:
        return ""
    try:
        return avatar.imagen.url
    except (OSError, ValueError):
        return ""


def _django_publish_task(self, *, task_id: int, empresa_id: int, actor_id: int) -> TaskLifecycleResult:
    with transaction.atomic(using=self.alias):
        try:
            task = Tarea.objects.using(self.alias).select_for_update().get(pk=task_id, empresa_id=empresa_id)
        except Tarea.DoesNotExist as exc:
            raise EditTaskNotFound from exc
        if task.estado != Tarea.Estado.BORRADOR:
            raise ValidationError("La tarea ya está publicada.")
        if task.anulada:
            raise ValidationError("La tarea está anulada; no puede publicarse.")
        responsible = User.objects.using("default").filter(
            pk=task.responsable_id,
            is_active=True,
        ).first()
        if responsible is None:
            raise ValidationError("No se puede publicar: la tarea requiere un responsable válido y activo.")
        if task.fecha_tope is None or not re.fullmatch(r"B[0-9]{7}", task.correlativo or ""):
            raise ValidationError("No se puede publicar: la tarea requiere fecha tope y correlativo válido.")
        now = timezone.now()
        new_correlativo = f"A{task.correlativo[1:]}"
        Tarea.objects.using(self.alias).filter(pk=task_id, empresa_id=empresa_id, estado=Tarea.Estado.BORRADOR).update(
            estado=Tarea.Estado.ACTIVA,
            correlativo=new_correlativo,
            fecha_publicacion=now,
            fecha_asignacion=task.fecha_asignacion or now,
        )
        transition = TareaTransicion.objects.using(self.alias).create(
            tarea_id=task_id,
            estado_origen=Tarea.Estado.BORRADOR,
            estado_destino=Tarea.Estado.ACTIVA,
            accion_evento="PUBLICAR",
            usuario_id=actor_id,
        )
    return TaskLifecycleResult(task_id, empresa_id, Tarea.Estado.BORRADOR, Tarea.Estado.ACTIVA, new_correlativo, now, task.fecha_asignacion or now, transition.pk)


def _django_enter_management(self, *, task_id: int, empresa_id: int, actor_id: int) -> TaskLifecycleResult:
    with transaction.atomic(using=self.alias):
        try:
            task = Tarea.objects.using(self.alias).select_for_update().get(pk=task_id, empresa_id=empresa_id)
        except Tarea.DoesNotExist as exc:
            raise EditTaskNotFound from exc
        if task.estado != Tarea.Estado.ACTIVA:
            raise ValidationError("Transición no permitida: la tarea no está ACTIVA.")
        if task.anulada:
            raise ValidationError("La tarea está anulada; no admite operaciones de ciclo.")
        Tarea.objects.using(self.alias).filter(pk=task_id, empresa_id=empresa_id, estado=Tarea.Estado.ACTIVA).update(estado=Tarea.Estado.GESTION)
        transition = TareaTransicion.objects.using(self.alias).create(
            tarea_id=task_id,
            estado_origen=Tarea.Estado.ACTIVA,
            estado_destino=Tarea.Estado.GESTION,
            accion_evento="INICIAR_GESTION",
            usuario_id=actor_id,
        )
    return TaskLifecycleResult(task_id, empresa_id, Tarea.Estado.ACTIVA, Tarea.Estado.GESTION, task.correlativo, transition_id=transition.pk)


DjangoTaskStorage.publish_task = _django_publish_task
DjangoTaskStorage.enter_management = _django_enter_management


class DjangoTaskListStorage:
    def __init__(self, alias: str):
        self.alias = alias

    def list_tasks(
        self,
        *,
        empresa_id: int,
        filters: TaskListFilters,
    ) -> TaskListResult:
        base_queryset = Tarea.objects.using(self.alias).filter(empresa_id=empresa_id)
        queryset = base_queryset.select_related(
            "empresa", "responsable", "creada_por"
        ).prefetch_related(
            "responsable__avatar",
            "participantes__usuario__avatar",
        )
        if filters.search:
            queryset = queryset.filter(
                Q(correlativo__icontains=filters.search)
                | Q(titulo__icontains=filters.search)
                | Q(descripcion__icontains=filters.search)
                | Q(responsable__username__icontains=filters.search)
            )
        if filters.estado in {value for value, _label in Tarea.Estado.choices}:
            queryset = queryset.filter(estado=filters.estado)
        if filters.prioridad in {value for value, _label in Tarea.Prioridad.choices}:
            queryset = queryset.filter(prioridad=filters.prioridad)
        queryset = queryset.order_by("-fecha_creacion")

        summary_values = base_queryset.aggregate(
            total=Count("pk"),
            activas=Count("pk", filter=Q(estado=Tarea.Estado.ACTIVA)),
            gestion=Count("pk", filter=Q(estado=Tarea.Estado.GESTION)),
            cerradas=Count("pk", filter=Q(estado=Tarea.Estado.CERRADA)),
        )
        items = []
        for task in queryset:
            participants = []
            seen_ids = {task.responsable_id}
            if task.creada_por_id not in seen_ids:
                participants.append(
                    TaskListParticipant(
                        user_id=task.creada_por_id,
                        username=task.creada_por.username,
                        rol="CREADOR",
                        avatar_url=_avatar_url(task.creada_por),
                    )
                )
                seen_ids.add(task.creada_por_id)
            for participant in task.participantes.all():
                if participant.usuario_id not in seen_ids:
                    participants.append(
                        TaskListParticipant(
                            user_id=participant.usuario_id,
                            username=participant.usuario.username,
                            rol=participant.rol,
                            avatar_url=_avatar_url(participant.usuario),
                        )
                    )
                    seen_ids.add(participant.usuario_id)
            visible = tuple(participants[:4])
            items.append(
                TaskListItem(
                    id=task.pk,
                    empresa_id=task.empresa_id,
                    correlativo=task.correlativo,
                    titulo=task.titulo,
                    prioridad=task.prioridad,
                    estado=task.estado,
                    fecha_tope=task.fecha_tope,
                    fecha_creacion=task.fecha_creacion,
                    responsable_id=task.responsable_id,
                    responsable_username=(
                        task.responsable.username if task.responsable else ""
                    ),
                    responsable_avatar_url=(
                        _avatar_url(task.responsable) if task.responsable else ""
                    ),
                    participantes_visibles=visible,
                    participantes_restantes=max(0, len(participants) - 4),
                )
            )
        return TaskListResult(tuple(items), summary_values)
    def list_personal_tasks(self, *, empresa_id: int, user_id: int):
        queryset = Tarea.objects.using(self.alias).filter(
            empresa_id=empresa_id,
            anulada=False,
            estado__in=(
                Tarea.Estado.ACTIVA,
                Tarea.Estado.GESTION,
                Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
                Tarea.Estado.CERRADA,
            ),
        ).filter(
            Q(responsable_id=user_id) | Q(participantes__usuario_id=user_id)
        ).select_related("responsable").distinct().order_by(
            "prioridad", "fecha_tope", "pk"
        )
        return tuple(
            PersonalTaskItem(
                id=task.pk,
                empresa_id=task.empresa_id,
                correlativo=task.correlativo,
                titulo=task.titulo,
                descripcion=task.descripcion,
                prioridad=task.prioridad,
                estado=task.estado,
                anulada=task.anulada,
                responsable_id=task.responsable_id,
                responsable=task.responsable,
                fecha_tope=task.fecha_tope,
                fecha_publicacion=task.fecha_publicacion,
                fecha_asignacion=task.fecha_asignacion,
                fecha_cumplimiento=task.fecha_cumplimiento,
                fecha_creacion=task.fecha_creacion,
            )
            for task in queryset
        )

    def personal_participant_roles(self, *, task_ids, user_id: int):
        return dict(
            TareaParticipante.objects.using(self.alias).filter(
                tarea_id__in=task_ids, usuario_id=user_id,
            ).values_list("tarea_id", "rol")
        )

    def personal_read_status(self, *, task_ids, user_id: int):
        return dict(
            TareaLectura.objects.using(self.alias).filter(
                tarea_id__in=task_ids, usuario_id=user_id,
            ).values_list("tarea_id", "leido")
        )


class MySQLTaskListStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    @staticmethod
    def _like(value: str) -> str:
        return f"%{value}%"

    @staticmethod
    def _fetch_users(user_ids):
        users = User.objects.using("default").filter(pk__in=user_ids)
        return {user.pk: user for user in users}

    @staticmethod
    def _fetch_avatars(user_ids):
        avatars = Avatar.objects.using("default").filter(user_id__in=user_ids)
        return {avatar.user_id: _avatar_url(avatar.user) for avatar in avatars}

    def list_tasks(
        self,
        *,
        empresa_id: int,
        filters: TaskListFilters,
    ) -> TaskListResult:
        search_user_ids = []
        if filters.search:
            search_user_ids = list(
                User.objects.using("default")
                .filter(username__icontains=filters.search)
                .values_list("pk", flat=True)
            )
        where = ["empresa_id = %s"]
        params: list[object] = [empresa_id]
        if filters.search:
            search_parts = [
                "correlativo LIKE %s",
                "titulo LIKE %s",
                "descripcion LIKE %s",
            ]
            search_params: list[object] = [
                self._like(filters.search),
                self._like(filters.search),
                self._like(filters.search),
            ]
            if search_user_ids:
                placeholders = ", ".join("%s" for _ in search_user_ids)
                search_parts.append(f"responsable_id IN ({placeholders})")
                search_params.extend(search_user_ids)
            where.append("(" + " OR ".join(search_parts) + ")")
            params.extend(search_params)
        if filters.estado in {value for value, _label in Tarea.Estado.choices}:
            where.append("estado = %s")
            params.append(filters.estado)
        if filters.prioridad in {value for value, _label in Tarea.Prioridad.choices}:
            where.append("prioridad = %s")
            params.append(filters.prioridad)

        task_sql = (
            "SELECT id, empresa_id, creada_por_id, responsable_id, correlativo, "
            "titulo, prioridad, estado, fecha_tope, fecha_creacion "
            "FROM tareas_tarea WHERE "
            + " AND ".join(where)
            + " ORDER BY fecha_creacion DESC"
        )
        summary_sql = (
            "SELECT COUNT(*), "
            "SUM(CASE WHEN estado = %s THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN estado = %s THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN estado = %s THEN 1 ELSE 0 END) "
            "FROM tareas_tarea WHERE empresa_id = %s"
        )
        with open_mysql_connection(
            self.connection_config,
            database_name=self.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(task_sql, tuple(params))
                task_rows = cursor.fetchall()
                cursor.execute(
                    summary_sql,
                    (
                        Tarea.Estado.ACTIVA,
                        Tarea.Estado.GESTION,
                        Tarea.Estado.CERRADA,
                        empresa_id,
                    ),
                )
                summary_row = cursor.fetchone() or (0, 0, 0, 0)
                task_ids = [row[0] for row in task_rows]
                participant_rows = []
                if task_ids:
                    placeholders = ", ".join("%s" for _ in task_ids)
                    cursor.execute(
                        "SELECT tarea_id, usuario_id, rol "
                        "FROM tareas_tareaparticipante "
                        f"WHERE tarea_id IN ({placeholders}) ORDER BY tarea_id, id",
                        tuple(task_ids),
                    )
                    participant_rows = cursor.fetchall()
            finally:
                cursor.close()

        participants_by_task = defaultdict(list)
        user_ids = set()
        for task_id, user_id, role in participant_rows:
            participants_by_task[task_id].append((user_id, role))
            user_ids.add(user_id)
        for row in task_rows:
            user_ids.add(row[2])
            if row[3] is not None:
                user_ids.add(row[3])
        users = self._fetch_users(user_ids)
        avatars = self._fetch_avatars(user_ids)
        items = []
        for row in task_rows:
            task_id, row_empresa_id, creator_id, responsible_id = row[:4]
            seen_ids = {responsible_id}
            participants = []
            creator = users.get(creator_id)
            if creator_id not in seen_ids and creator is not None:
                participants.append(
                    TaskListParticipant(
                        user_id=creator_id,
                        username=creator.username,
                        rol="CREADOR",
                        avatar_url=avatars.get(creator_id, ""),
                    )
                )
                seen_ids.add(creator_id)
            for user_id, role in participants_by_task.get(task_id, []):
                if user_id in seen_ids:
                    continue
                user = users.get(user_id)
                if user is not None:
                    participants.append(
                        TaskListParticipant(
                            user_id=user_id,
                            username=user.username,
                            rol=role,
                            avatar_url=avatars.get(user_id, ""),
                        )
                    )
                    seen_ids.add(user_id)
            responsible = users.get(responsible_id)
            items.append(
                TaskListItem(
                    id=task_id,
                    empresa_id=row_empresa_id,
                    correlativo=row[4],
                    titulo=row[5],
                    prioridad=row[6],
                    estado=row[7],
                    fecha_tope=row[8],
                    fecha_creacion=row[9],
                    responsable_id=responsible_id,
                    responsable_username=(responsible.username if responsible else ""),
                    responsable_avatar_url=avatars.get(responsible_id, ""),
                    participantes_visibles=tuple(participants[:4]),
                    participantes_restantes=max(0, len(participants) - 4),
                )
            )
        return TaskListResult(
            tuple(items),
            {
                "total": int(summary_row[0] or 0),
                "activas": int(summary_row[1] or 0),
                "gestion": int(summary_row[2] or 0),
                "cerradas": int(summary_row[3] or 0),
            },
        )
    def list_personal_tasks(self, *, empresa_id: int, user_id: int):
        states = (
            Tarea.Estado.ACTIVA,
            Tarea.Estado.GESTION,
            Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
            Tarea.Estado.CERRADA,
        )
        sql = (
            "SELECT t.id, t.empresa_id, t.correlativo, t.titulo, t.descripcion, "
            "t.prioridad, t.estado, t.anulada, t.responsable_id, "
            "t.fecha_tope, t.fecha_publicacion, t.fecha_asignacion, "
            "t.fecha_cumplimiento, t.fecha_creacion "
            "FROM tareas_tarea t WHERE t.empresa_id=%s AND t.anulada=0 "
            "AND t.estado IN (%s,%s,%s,%s) "
            "AND (t.responsable_id=%s OR EXISTS ("
            "SELECT 1 FROM tareas_tareaparticipante p "
            "WHERE p.tarea_id=t.id AND p.usuario_id=%s)) "
            "ORDER BY t.prioridad, t.fecha_tope, t.id"
        )
        params = (empresa_id, *states, user_id, user_id)
        with open_mysql_connection(
            self.connection_config, database_name=self.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            finally:
                cursor.close()
        users = self._fetch_users({row[8] for row in rows if row[8] is not None})
        return tuple(
            PersonalTaskItem(
                id=row[0], empresa_id=row[1], correlativo=row[2], titulo=row[3],
                descripcion=row[4], prioridad=row[5], estado=row[6], anulada=bool(row[7]),
                responsable_id=row[8], responsable=users.get(row[8]), fecha_tope=row[9],
                fecha_publicacion=row[10], fecha_asignacion=row[11],
                fecha_cumplimiento=row[12], fecha_creacion=row[13],
            )
            for row in rows
        )

    def personal_participant_roles(self, *, task_ids, user_id: int):
        if not task_ids:
            return {}
        placeholders = ", ".join("%s" for _ in task_ids)
        with open_mysql_connection(
            self.connection_config, database_name=self.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT tarea_id, rol FROM tareas_tareaparticipante "
                    f"WHERE tarea_id IN ({placeholders}) AND usuario_id=%s",
                    (*task_ids, user_id),
                )
                return {row[0]: row[1] for row in cursor.fetchall()}
            finally:
                cursor.close()

    def personal_read_status(self, *, task_ids, user_id: int):
        if not task_ids:
            return {}
        placeholders = ", ".join("%s" for _ in task_ids)
        with open_mysql_connection(
            self.connection_config, database_name=self.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT tarea_id, leido FROM tareas_tarealectura "
                    f"WHERE tarea_id IN ({placeholders}) AND usuario_id=%s",
                    (*task_ids, user_id),
                )
                return {row[0]: bool(row[1]) for row in cursor.fetchall()}
            finally:
                cursor.close()


class MySQLTaskStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    @staticmethod
    def _reserve_number(cursor, empresa_id: int) -> int:
        cursor.execute(
            "INSERT INTO tareas_correlativoempresa "
            "(empresa_id, siguiente_numero) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE empresa_id = empresa_id",
            (empresa_id, 1),
        )
        cursor.execute(
            "SELECT siguiente_numero FROM tareas_correlativoempresa "
            "WHERE empresa_id = %s FOR UPDATE",
            (empresa_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise TaskStorageError("No se pudo reservar el correlativo de Tareas.")
        number = int(row[0])
        cursor.execute(
            "UPDATE tareas_correlativoempresa SET siguiente_numero = %s "
            "WHERE empresa_id = %s",
            (number + 1, empresa_id),
        )
        return number

    def create_draft(
        self,
        data: CreateTaskDraftInput,
        *,
        empresa_id: int,
        creador_id: int,
    ) -> CreatedTaskResult:
        try:
            with open_mysql_connection(
                self.connection_config,
                database_name=self.database_name,
            ) as connection:
                cursor = connection.cursor()
                try:
                    number = self._reserve_number(cursor, empresa_id)
                    correlativo = f"B{number:07d}"
                    created_at = timezone.now()
                    cursor.execute(
                        "INSERT INTO tareas_tarea ("
                        "titulo, descripcion, prioridad, correlativo, anulada, "
                        "fechas_pendientes_confirmacion, cierre_completado, "
                        "requiere_evidencia_cierre, estado, responsable_id, "
                        "empresa_id, tipo_ambito, local_id, departamento_id, "
                        "creada_por_id, fecha_creacion, fecha_publicacion, "
                        "fecha_asignacion, fecha_tope, fecha_cumplimiento, "
                        "todo_origen_id, tarea_origen_id"
                        ") VALUES ("
                        "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                        "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
                        ")",
                        (
                            data.titulo,
                            data.descripcion,
                            data.prioridad,
                            correlativo,
                            False,
                            False,
                            False,
                            False,
                            Tarea.Estado.BORRADOR,
                            data.responsable_id,
                            empresa_id,
                            None,
                            None,
                            None,
                            creador_id,
                            created_at,
                            None,
                            None,
                            data.fecha_tope,
                            None,
                            None,
                            None,
                        ),
                    )
                    task_id = cursor.lastrowid
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except TaskStorageError:
            raise
        except Exception as exc:
            raise TaskStorageError(
                "No se pudo crear el borrador de Tarea en MySQL."
            ) from exc
        return CreatedTaskResult(
            id=int(task_id),
            empresa_id=empresa_id,
            correlativo=correlativo,
            estado=Tarea.Estado.BORRADOR,
            responsable_id=data.responsable_id,
            prioridad=data.prioridad,
        )

    def get_task_for_edit(self, *, task_id: int, empresa_id: int) -> TaskEditData:
        try:
            with open_mysql_connection(
                self.connection_config,
                database_name=self.database_name,
            ) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        "SELECT id, empresa_id, titulo, descripcion, prioridad, "
                        "responsable_id, fecha_tope, estado FROM tareas_tarea "
                        "WHERE id = %s AND empresa_id = %s",
                        (task_id, empresa_id),
                    )
                    row = cursor.fetchone()
                finally:
                    cursor.close()
        except EditTaskNotFound:
            raise
        except Exception as exc:
            raise TaskStorageError("No se pudo leer la Tarea para editar.") from exc
        if row is None:
            raise EditTaskNotFound
        return TaskEditData(*row)

    def update_task(self, command: UpdateTaskCommand) -> TaskEditData:
        try:
            with open_mysql_connection(
                self.connection_config,
                database_name=self.database_name,
            ) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        "UPDATE tareas_tarea SET titulo = %s, descripcion = %s, "
                        "prioridad = %s, responsable_id = %s, fecha_tope = %s "
                        "WHERE id = %s AND empresa_id = %s",
                        (
                            command.titulo,
                            command.descripcion,
                            command.prioridad,
                            command.responsable_id,
                            command.fecha_tope,
                            command.task_id,
                            command.empresa_id,
                        ),
                    )
                    if cursor.rowcount == 0:
                        connection.rollback()
                        raise EditTaskNotFound
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except EditTaskNotFound:
            raise
        except Exception as exc:
            raise TaskStorageError("No se pudo actualizar la Tarea.") from exc
        return self.get_task_for_edit(
            task_id=command.task_id,
            empresa_id=command.empresa_id,
        )


def _mysql_publish_task(self, *, task_id: int, empresa_id: int, actor_id: int) -> TaskLifecycleResult:
    try:
        with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
            cursor = connection.cursor()
            try:
                if callable(getattr(connection, "begin", None)):
                    connection.begin()
                cursor.execute(
                    "SELECT id, empresa_id, correlativo, anulada, estado, responsable_id, fecha_tope, fecha_asignacion FROM tareas_tarea WHERE id=%s AND empresa_id=%s FOR UPDATE",
                    (task_id, empresa_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise EditTaskNotFound
                _id, _company, correlativo, annulled, state, responsible_id, due_date, assigned_at = row
                if state != Tarea.Estado.BORRADOR:
                    raise ValidationError("La tarea ya está publicada.")
                if annulled:
                    raise ValidationError("La tarea está anulada; no puede publicarse.")
                empresa = Empresa.objects.using("default").get(pk=empresa_id)
                if responsible_id is None or not get_valid_users_for_empresa(empresa, active_only=True).filter(pk=responsible_id).exists():
                    raise ValidationError("No se puede publicar: la tarea requiere un responsable válido y activo.")
                if due_date is None or not re.fullmatch(r"B[0-9]{7}", correlativo or ""):
                    raise ValidationError("No se puede publicar: la tarea requiere fecha tope y correlativo válido.")
                now = timezone.now()
                new_correlativo = f"A{correlativo[1:]}"
                cursor.execute("UPDATE tareas_tarea SET estado=%s, correlativo=%s, fecha_publicacion=%s, fecha_asignacion=%s WHERE id=%s AND empresa_id=%s", (Tarea.Estado.ACTIVA, new_correlativo, now, assigned_at or now, task_id, empresa_id))
                cursor.execute("INSERT INTO tareas_tareatransicion (tarea_id, estado_origen, estado_destino, accion_evento, usuario_id, timestamp, motivo) VALUES (%s,%s,%s,%s,%s,%s,%s)", (task_id, Tarea.Estado.BORRADOR, Tarea.Estado.ACTIVA, "PUBLICAR", actor_id, now, ""))
                transition_id = cursor.lastrowid
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
    except (EditTaskNotFound, LifecycleSimilarityUnsupported, ValidationError):
        raise
    except Exception as exc:
        raise TaskStorageError("No se pudo publicar la Tarea.") from exc
    return TaskLifecycleResult(task_id, empresa_id, Tarea.Estado.BORRADOR, Tarea.Estado.ACTIVA, new_correlativo, now, assigned_at or now, transition_id)


def _mysql_enter_management(self, *, task_id: int, empresa_id: int, actor_id: int) -> TaskLifecycleResult:
    try:
        with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
            cursor = connection.cursor()
            try:
                if callable(getattr(connection, "begin", None)):
                    connection.begin()
                cursor.execute("SELECT id, empresa_id, correlativo, anulada, estado FROM tareas_tarea WHERE id=%s AND empresa_id=%s FOR UPDATE", (task_id, empresa_id))
                row = cursor.fetchone()
                if row is None:
                    raise EditTaskNotFound
                _id, _company, correlativo, annulled, state = row
                if state != Tarea.Estado.ACTIVA:
                    raise ValidationError("Transición no permitida: la tarea no está ACTIVA.")
                if annulled:
                    raise ValidationError("La tarea está anulada; no admite operaciones de ciclo.")
                now = timezone.now()
                cursor.execute("UPDATE tareas_tarea SET estado=%s WHERE id=%s AND empresa_id=%s", (Tarea.Estado.GESTION, task_id, empresa_id))
                cursor.execute("INSERT INTO tareas_tareatransicion (tarea_id, estado_origen, estado_destino, accion_evento, usuario_id, timestamp, motivo) VALUES (%s,%s,%s,%s,%s,%s,%s)", (task_id, Tarea.Estado.ACTIVA, Tarea.Estado.GESTION, "INICIAR_GESTION", actor_id, now, ""))
                transition_id = cursor.lastrowid
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
    except (EditTaskNotFound, ValidationError):
        raise
    except Exception as exc:
        raise TaskStorageError("No se pudo iniciar la gestión de la Tarea.") from exc
    return TaskLifecycleResult(task_id, empresa_id, Tarea.Estado.ACTIVA, Tarea.Estado.GESTION, correlativo, transition_id=transition_id)


MySQLTaskStorage.publish_task = _mysql_publish_task
MySQLTaskStorage.enter_management = _mysql_enter_management


def resolve_edit_storage():
    try:
        context = resolve_operational_backend("BASE_TAREAS")
        if context.backend_type == "DJANGO":
            return DjangoTaskStorage(context.django_alias)
        if context.backend_type == "MYSQL_CONFIG":
            return MySQLTaskStorage(
                context.mysql_connection,
                context.database_name,
            )
        raise TaskStorageError("tareas.assignment.errors.backend")
    except Exception as exc:
        logger.error("BASE_TAREAS edit storage resolution failed.")
        raise TaskStorageError("tareas.assignment.errors.backend") from exc


def resolve_create_storage() -> DjangoTaskStorage | MySQLTaskStorage:
    try:
        context = resolve_operational_backend("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise TaskStorageError(
            "No se pudo resolver el backend de BASE_TAREAS."
        ) from exc
    if context.backend_type == "MYSQL_CONFIG":
        return MySQLTaskStorage(context.mysql_connection, context.database_name)
    if context.backend_type != "DJANGO":
        raise TaskStorageError("El backend de BASE_TAREAS no es válido.")
    return DjangoTaskStorage(context.django_alias)


def resolve_list_storage() -> DjangoTaskListStorage | MySQLTaskListStorage:
    try:
        context = resolve_operational_backend("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise TaskStorageError(
            "No se pudo resolver el backend de BASE_TAREAS."
        ) from exc
    if context.backend_type == "MYSQL_CONFIG":
        return MySQLTaskListStorage(context.mysql_connection, context.database_name)
    if context.backend_type != "DJANGO":
        raise TaskStorageError("El backend de BASE_TAREAS no es válido.")
    return DjangoTaskListStorage(context.django_alias)


def create_task_draft(
    data: CreateTaskDraftInput,
    *,
    active_company,
    actor,
) -> CreatedTaskResult:
    if data.responsable_id is not None:
        valid_responsible = get_valid_users_for_empresa(
            active_company,
            active_only=True,
        ).filter(pk=data.responsable_id).exists()
        if not valid_responsible:
            raise ValidationError(
                "El responsable debe estar activo y pertenecer a la Empresa activa."
            )

    storage = resolve_create_storage()
    result = storage.create_draft(
        data,
        empresa_id=active_company.pk,
        creador_id=actor.pk,
    )
    if result.responsable_id is not None:
        notification_task = result.task
        if notification_task is None:
            responsible = get_valid_users_for_empresa(
                active_company,
                active_only=True,
            ).get(pk=result.responsable_id)
            notification_task = SimpleNamespace(
                pk=result.id,
                empresa=active_company,
                responsable=responsible,
                prioridad=result.prioridad,
                participantes=SimpleNamespace(
                    select_related=lambda *args, **kwargs: []
                ),
            )
        emit_task_event(
            tarea=notification_task,
            event="asignacion",
            recipients=task_recipients(
                notification_task,
                actor=actor,
                include_responsible=True,
            ),
            title="Tarea asignada",
            body="Se te asignó una nueva tarea.",
            actor=actor,
        )
    return result
