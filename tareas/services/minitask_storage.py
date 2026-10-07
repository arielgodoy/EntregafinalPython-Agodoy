"""Company-scoped MiniTareas commands and their atomic close aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from os.path import splitext
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from access_control.models import Empresa
from access_control.services.permissions import (
    get_valid_users_for_empresa, user_has_permission_for_empresa,
)
from settings.services.mysql_connections import open_mysql_connection
from tareas.models import (
    Comentario, ComentarioAdjunto, ComentarioPausaLectura, ComentarioVersion,
    ComentarioVersionDocumento, DocumentoHistorial, DocumentoTarea, Hito,
    MiniTarea, MiniTareaEvento, Tarea, TareaLectura, TareaParticipante, TareaRelacion,
)
from .connection_roles import resolve_operational_backend
from .image_processing import optimize_uploaded_image
from .notifications import emit_task_event, send_task_email
from .task_storage import TaskStorageError

logger = logging.getLogger(__name__)
ERROR_KEY = "tareas.messages.generic_error"


class MiniTaskNotFound(Exception):
    pass


@dataclass(frozen=True)
class CreateMiniTaskCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    persona_id: int
    descripcion: str


@dataclass(frozen=True)
class CloseMiniTaskCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    mini_task_id: int
    comentario: str
    notification_recipient_ids: tuple[int, ...] = ()
    email_recipient_ids: tuple[int, ...] = ()
    uploaded_files: tuple[UploadedFile, ...] = ()


@dataclass(frozen=True)
class ReopenMiniTaskCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    mini_task_id: int
    comentario: str


@dataclass(frozen=True)
class DeleteMiniTaskCommand:
    task_id: int
    empresa_id: int
    actor_id: int
    mini_task_id: int


@dataclass
class MiniTaskDelivery:
    failed: bool = False


@dataclass(frozen=True)
class MiniTaskResult:
    task_id: int
    mini_task_id: int
    event_id: int | None = None
    comentario_feed_id: int | None = None
    delivery: MiniTaskDelivery = field(default_factory=MiniTaskDelivery)


def _invalid():
    raise ValidationError(ERROR_KEY)


def _identity(empresa_id, actor_id, action):
    try:
        empresa = Empresa.objects.using("default").get(pk=empresa_id)
        actor = User.objects.using("default").get(pk=actor_id, is_active=True)
    except (Empresa.DoesNotExist, User.DoesNotExist):
        raise PermissionDenied from None
    if not (
        get_valid_users_for_empresa(empresa, active_only=True).using("default")
        .filter(pk=actor.pk).exists()
        and user_has_permission_for_empresa(
            user=actor, empresa=empresa, vista_nombre="Tareas", accion=action
        )
    ):
        raise PermissionDenied
    return empresa, actor


def _eligible(empresa, ids, *, email=False):
    try:
        requested = {int(value) for value in ids}
    except (TypeError, ValueError):
        _invalid()
    users = list(
        get_valid_users_for_empresa(empresa, active_only=True).using("default")
        .filter(pk__in=requested, is_active=True).order_by("pk")
    )
    if {user.pk for user in users} != requested:
        _invalid()
    if email and any(not user.email.strip() for user in users):
        _invalid()
    return users


def _documents(files, task_id, actor_id):
    from tareas.forms import _validate_comment_files

    files = _validate_comment_files(files)
    documents = []
    for upload in files:
        formato = splitext(upload.name)[1].lower().lstrip(".").upper()
        upload = optimize_uploaded_image(upload, formato)
        document = DocumentoTarea(
            tarea_id=task_id, usuario_id=actor_id, tipo=DocumentoTarea.Tipo.OTRO,
            formato_archivo=formato, archivo=upload,
        )
        # External identities were validated in SYSTEM; no operational ORM lookup.
        document.full_clean(
            exclude=["tarea", "usuario"], validate_unique=False, validate_constraints=False,
        )
        documents.append(document)
    return documents


def _cleanup(files):
    for storage, name in files:
        try:
            storage.delete(name)
        except Exception:
            logger.error("MiniTask new-file cleanup failed")


def _failed_files(files, *, commit_attempted):
    if not commit_attempted:
        _cleanup(files)
    elif files:
        # A lost commit acknowledgement does not prove that the database rolled back.
        logger.error("MiniTask commit outcome uncertain; retaining new files for reconciliation")


def _dispatch(command, result, task, empresa, actor, mini, notifications, emails):
    task = SimpleNamespace(
        pk=task.pk, empresa=empresa, titulo=task.titulo, prioridad=task.prioridad,
    )
    title = "MiniTarea cerrada"
    body = (
        f"{actor.username} cerró la MiniTarea '{mini.descripcion}' de la tarea "
        f"'{task.titulo}'. Comentario: {command.comentario.strip()}"
    )
    if notifications:
        try:
            emit_task_event(
                tarea=task, event=f"mini_tarea_cierre:{result.event_id}",
                recipients=notifications, title=title, body=body, actor=actor,
                send_email=False, raise_errors=True,
            )
        except Exception:
            result.delivery.failed = True
            logger.error("MiniTask communication failed: event=%s channel=in_app", result.event_id)
    if emails:
        try:
            send_task_email(
                tarea=task, subject=title, body_text=body,
                to_emails=[user.email.strip() for user in emails],
            )
        except Exception:
            result.delivery.failed = True
            logger.error("MiniTask communication failed: event=%s channel=email", result.event_id)


def _mutate(adapter, command, saved_files):
    action = "crear" if isinstance(command, CreateMiniTaskCommand) else "modificar"
    empresa, actor = _identity(command.empresa_id, command.actor_id, action)
    task = adapter.task(command.task_id, command.empresa_id, lock=True)
    if task.estado not in {Tarea.Estado.ACTIVA, Tarea.Estado.GESTION}:
        _invalid()
    if adapter.annulled(task, command.empresa_id):
        _invalid()
    create = isinstance(command, CreateMiniTaskCommand)
    mini = None if create else adapter.mini(command.mini_task_id, task.pk, lock=True)
    allowed = {task.responsable_id}
    if isinstance(command, CloseMiniTaskCommand):
        allowed.add(mini.persona_id)
    if actor.pk not in allowed and not user_has_permission_for_empresa(
        user=actor, empresa=empresa, vista_nombre="Tareas", accion="supervisor"
    ):
        raise PermissionDenied
    now = timezone.now()
    if create:
        description = str(command.descripcion or "").strip()
        if not description or len(description) > 200:
            _invalid()
        _eligible(empresa, [command.persona_id])
        mini_id = adapter.insert(MiniTarea, dict(
            tarea_id=task.pk, descripcion=description, persona_id=command.persona_id,
            hecho=False, fecha_creacion=now, fecha_completado=None,
        ))
        return MiniTaskResult(task.pk, mini_id), None
    if isinstance(command, DeleteMiniTaskCommand):
        if mini.hecho or adapter.has_events(mini.pk):
            _invalid()
        adapter.delete(mini.pk, task.pk)
        return MiniTaskResult(task.pk, mini.pk), None
    comment = str(command.comentario or "").strip()
    if not comment:
        _invalid()
    close = isinstance(command, CloseMiniTaskCommand)
    if bool(mini.hecho) == close:
        _invalid()
    notifications, emails = [], []
    comment_id = None
    if close:
        effective_ids = adapter.effective_ids(task)
        try:
            notification_ids = {int(value) for value in command.notification_recipient_ids} - {actor.pk}
            email_ids = {int(value) for value in command.email_recipient_ids} - {actor.pk}
        except (TypeError, ValueError):
            _invalid()
        if not (notification_ids | email_ids).issubset(effective_ids):
            _invalid()
        notifications = _eligible(empresa, notification_ids)
        emails = _eligible(empresa, email_ids, email=True)
        documents = _documents(command.uploaded_files, task.pk, actor.pk)
        predecessor = adapter.latest_comment(task.pk)
        content = f'Ha completado la MiniTarea "{mini.descripcion}".\n\nComentario: {comment}'
        comment_id = adapter.insert(Comentario, dict(
            tarea_id=task.pk, autor_id=actor.pk, contenido=content,
            created_at=now, updated_at=now, oculto=False,
        ))
        version_id = adapter.insert(ComentarioVersion, dict(
            comentario_id=comment_id, evento="CREADO", numero_version=1,
            contenido=content, actor_id=actor.pk, fecha=now, motivo="",
        ))
        for document in documents:
            document.archivo.save(document.archivo.name, document.archivo.file, save=False)
            saved_files.append((document.archivo.storage, document.archivo.name))
            document_id = adapter.insert(DocumentoTarea, dict(
                tarea_id=task.pk, tipo=document.tipo, formato_archivo=document.formato_archivo,
                archivo=document.archivo.name, url="", fecha_documento=document.fecha_documento,
                fecha_vencimiento=None, usuario_id=actor.pk, estado="",
            ))
            adapter.insert(DocumentoHistorial, dict(
                documento_id=document_id, accion="CREADO", usuario_id=actor.pk, fecha=now,
            ))
            adapter.insert(ComentarioAdjunto, dict(comentario_id=comment_id, documento_id=document_id))
            adapter.insert(ComentarioVersionDocumento, dict(version_id=version_id, documento_id=document_id))
        users = User.objects.using("default").in_bulk(effective_ids)
        for user_id, user in users.items():
            reading_id, created = adapter.ensure_reading(task.pk, user_id, predecessor)
            if created and not user.is_active:
                adapter.insert(ComentarioPausaLectura, dict(lectura_id=reading_id, desde=now, hasta=None))
    adapter.set_done(mini.pk, task.pk, close, now if close else None)
    event_id = adapter.insert(MiniTareaEvento, dict(
        mini_tarea_id=mini.pk, comentario_feed_id=comment_id,
        tipo="CIERRE" if close else "REAPERTURA", actor_id=actor.pk, fecha=now,
        comentario=comment, destinatarios_notificacion=[user.pk for user in notifications],
        destinatarios_email=[user.pk for user in emails],
    ))
    result = MiniTaskResult(task.pk, mini.pk, event_id, comment_id)
    callback = (
        lambda: _dispatch(command, result, task, empresa, actor, mini, notifications, emails)
    ) if close else None
    return result, callback


class _Queries:
    def create(self, command):
        return self._execute(command)

    def close(self, command):
        return self._execute(command)

    def reopen(self, command):
        return self._execute(command)

    def delete(self, command):
        return self._execute(command)

    def detail(self, *, task_id, empresa_id):
        from .detail_storage import DetailTaskNotFound, TaskDetailSections

        try:
            return self._detail_storage().get_task_detail(
                task_id=task_id, empresa_id=empresa_id,
                sections=TaskDetailSections(milestones=False, documents=False, links=False),
            )
        except DetailTaskNotFound:
            raise MiniTaskNotFound from None

    def has_pending(self, *, task_id, empresa_id):
        return any(not item.hecho for item in self.detail(
            task_id=task_id, empresa_id=empresa_id,
        ).mini_tasks)

    def history(self, *, task_id, empresa_id, mini_task_id, actor_id):
        try:
            _identity(empresa_id, actor_id, "ingresar")
            detail = self.detail(task_id=task_id, empresa_id=empresa_id)
            mini = next((item for item in detail.mini_tasks if item.id == mini_task_id), None)
            if mini is None:
                raise MiniTaskNotFound
            return detail, mini
        except (PermissionDenied, MiniTaskNotFound, TaskStorageError):
            raise
        except Exception:
            logger.error("MiniTask history failed: task=%s company=%s", task_id, empresa_id)
            raise TaskStorageError(ERROR_KEY) from None


class DjangoMiniTaskStorage(_Queries):
    def __init__(self, alias):
        self.alias = alias

    def _detail_storage(self):
        from .detail_storage import DjangoTaskDetailStorage
        return DjangoTaskDetailStorage(self.alias)

    def create_unattributed(self, *, task_id, persona_id, descripcion):
        now = timezone.now()
        with transaction.atomic(using=self.alias):
            mini = MiniTarea.objects.using(self.alias).create(
                tarea_id=task_id,
                descripcion=descripcion,
                persona_id=persona_id,
                hecho=False,
                fecha_creacion=now,
                fecha_completado=None,
            )
        return MiniTaskResult(task_id, mini.pk)

    def _execute(self, command):
        files = []
        commit_attempted = False
        try:
            with transaction.atomic(using=self.alias):
                result, callback = _mutate(_DjangoMutation(self.alias), command, files)
                if callback:
                    transaction.on_commit(callback, using=self.alias)
                commit_attempted = True
            return result
        except (MiniTaskNotFound, PermissionDenied, ValidationError):
            _failed_files(files, commit_attempted=commit_attempted)
            raise
        except Exception:
            _failed_files(files, commit_attempted=commit_attempted)
            logger.error("MiniTask storage failed: task=%s company=%s", command.task_id, command.empresa_id)
            raise TaskStorageError(ERROR_KEY) from None

    def assigned(self, *, empresa_id, actor_id):
        try:
            return _assigned_django(self.alias, empresa_id, actor_id)
        except PermissionDenied:
            raise
        except Exception:
            logger.error("Assigned MiniTask read failed: company=%s", empresa_id)
            raise TaskStorageError(ERROR_KEY) from None


class _DjangoMutation:
    def __init__(self, alias):
        self.alias = alias

    def task(self, task_id, empresa_id, *, lock=False):
        query = Tarea.objects.using(self.alias)
        if lock:
            query = query.select_for_update()
        try:
            return query.get(pk=task_id, empresa_id=empresa_id)
        except Tarea.DoesNotExist:
            raise MiniTaskNotFound from None

    def mini(self, mini_id, task_id, *, lock=False):
        query = MiniTarea.objects.using(self.alias)
        if lock:
            query = query.select_for_update()
        try:
            return query.get(pk=mini_id, tarea_id=task_id)
        except MiniTarea.DoesNotExist:
            raise MiniTaskNotFound from None

    def annulled(self, task, empresa_id):
        from .participant_storage import DjangoParticipantStorage
        return DjangoParticipantStorage(self.alias).annulled(
            task, SimpleNamespace(empresa_id=empresa_id),
        )

    def insert(self, model, values):
        row = model(**values)
        # Explicit aggregate orchestration, including readings; no ORM signals.
        model.objects.using(self.alias).bulk_create([row])
        return row.pk

    def effective_ids(self, task):
        ids = {task.creada_por_id, task.responsable_id}
        for model, field_name, extra in (
            (TareaParticipante, "usuario_id", {}),
            (MiniTarea, "persona_id", {}),
            (Hito, "responsable_id", {"anulado": False}),
        ):
            ids.update(model.objects.using(self.alias).filter(
                tarea_id=task.pk, **extra
            ).values_list(field_name, flat=True))
        return ids - {None}

    def latest_comment(self, task_id):
        return Comentario.objects.using(self.alias).filter(tarea_id=task_id).order_by(
            "-created_at", "-pk"
        ).values_list("pk", flat=True).first()

    def ensure_reading(self, task_id, user_id, predecessor):
        existing = TareaLectura.objects.using(self.alias).filter(
            tarea_id=task_id, usuario_id=user_id,
        ).values_list("pk", flat=True).first()
        if existing is not None:
            return existing, False
        return self.insert(TareaLectura, dict(
            tarea_id=task_id, usuario_id=user_id, comentario_leido_hasta_id=predecessor,
            leido=False, fecha_lectura=None,
        )), True

    def has_events(self, mini_id):
        return MiniTareaEvento.objects.using(self.alias).filter(mini_tarea_id=mini_id).exists()

    def set_done(self, mini_id, task_id, done, completed):
        MiniTarea.objects.using(self.alias).filter(pk=mini_id, tarea_id=task_id).update(
            hecho=done, fecha_completado=completed,
        )

    def delete(self, mini_id, task_id):
        MiniTarea.objects.using(self.alias).filter(pk=mini_id, tarea_id=task_id).delete()


class MySQLMiniTaskStorage(_Queries):
    def __init__(self, config, database_name):
        self.connection_config = config
        self.database_name = database_name

    def _detail_storage(self):
        from .detail_storage import MySQLTaskDetailStorage
        return MySQLTaskDetailStorage(self.connection_config, self.database_name)

    def create_unattributed(self, *, task_id, persona_id, descripcion):
        now = timezone.now()
        with open_mysql_connection(
            self.connection_config, database_name=self.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "INSERT INTO tareas_minitarea ("
                    "tarea_id,descripcion,persona_id,hecho,fecha_creacion,fecha_completado"
                    ") VALUES (%s,%s,%s,%s,%s,%s)",
                    (task_id, descripcion, persona_id, False, now, None),
                )
                mini_id = cursor.lastrowid
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
        return MiniTaskResult(task_id, mini_id)

    def _execute(self, command):
        files = []
        commit_attempted = False
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute("START TRANSACTION")
                    result, callback = _mutate(_MySQLMutation(cursor), command, files)
                    commit_attempted = True
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except (MiniTaskNotFound, PermissionDenied, ValidationError):
            _failed_files(files, commit_attempted=commit_attempted)
            raise
        except Exception:
            _failed_files(files, commit_attempted=commit_attempted)
            logger.error("MiniTask storage failed: task=%s company=%s", command.task_id, command.empresa_id)
            raise TaskStorageError(ERROR_KEY) from None
        if callback:
            callback()
        return result

    def assigned(self, *, empresa_id, actor_id):
        return _assigned_mysql(self, empresa_id, actor_id)


class _MySQLMutation:
    def __init__(self, cursor):
        self.cursor = cursor

    def task(self, task_id, empresa_id, *, lock=False):
        self.cursor.execute(
            "SELECT id, empresa_id, creada_por_id, responsable_id, estado, anulada, "
            "prioridad, titulo FROM tareas_tarea WHERE id=%s AND empresa_id=%s"
            + (" FOR UPDATE" if lock else ""), (task_id, empresa_id),
        )
        row = self.cursor.fetchone()
        if row is None:
            raise MiniTaskNotFound
        return SimpleNamespace(**dict(zip(
            ("pk", "empresa_id", "creada_por_id", "responsable_id", "estado", "anulada",
             "prioridad", "titulo"), row,
        )))

    def mini(self, mini_id, task_id, *, lock=False):
        self.cursor.execute(
            "SELECT id, persona_id, descripcion, hecho FROM tareas_minitarea "
            "WHERE id=%s AND tarea_id=%s" + (" FOR UPDATE" if lock else ""),
            (mini_id, task_id),
        )
        row = self.cursor.fetchone()
        if row is None:
            raise MiniTaskNotFound
        return SimpleNamespace(**dict(zip(("pk", "persona_id", "descripcion", "hecho"), row)))

    def annulled(self, task, empresa_id):
        from .participant_storage import _MySQLMutation as ParticipantMutation
        return ParticipantMutation(self.cursor).annulled(task, SimpleNamespace(empresa_id=empresa_id))

    def insert(self, model, values):
        # Tables/columns originate only from the fixed domain models and dictionaries above.
        columns = ", ".join(values)
        marks = ", ".join("%s" for _ in values)
        params = tuple(json.dumps(value) if isinstance(value, list) else value for value in values.values())
        self.cursor.execute(
            f"INSERT INTO {model._meta.db_table} ({columns}) VALUES ({marks})", params,
        )
        return self.cursor.lastrowid

    def effective_ids(self, task):
        self.cursor.execute(
            "SELECT usuario_id FROM tareas_tareaparticipante WHERE tarea_id=%s "
            "UNION SELECT persona_id FROM tareas_minitarea WHERE tarea_id=%s "
            "UNION SELECT responsable_id FROM tareas_hito WHERE tarea_id=%s AND anulado=0",
            (task.pk, task.pk, task.pk),
        )
        return ({task.creada_por_id, task.responsable_id} | {row[0] for row in self.cursor.fetchall()}) - {None}

    def latest_comment(self, task_id):
        self.cursor.execute(
            "SELECT id FROM tareas_comentario WHERE tarea_id=%s ORDER BY created_at DESC, id DESC LIMIT 1",
            (task_id,),
        )
        row = self.cursor.fetchone()
        return row[0] if row else None

    def ensure_reading(self, task_id, user_id, predecessor):
        self.cursor.execute(
            "SELECT id FROM tareas_tarealectura WHERE tarea_id=%s AND usuario_id=%s FOR UPDATE",
            (task_id, user_id),
        )
        row = self.cursor.fetchone()
        if row:
            return row[0], False
        return self.insert(TareaLectura, dict(
            tarea_id=task_id, usuario_id=user_id, comentario_leido_hasta_id=predecessor,
            leido=False, fecha_lectura=None,
        )), True

    def has_events(self, mini_id):
        self.cursor.execute(
            "SELECT id FROM tareas_minitareaevento WHERE mini_tarea_id=%s LIMIT 1 FOR UPDATE",
            (mini_id,),
        )
        return self.cursor.fetchone() is not None

    def set_done(self, mini_id, task_id, done, completed):
        self.cursor.execute(
            "UPDATE tareas_minitarea SET hecho=%s, fecha_completado=%s WHERE id=%s AND tarea_id=%s",
            (done, completed, mini_id, task_id),
        )

    def delete(self, mini_id, task_id):
        self.cursor.execute("DELETE FROM tareas_minitarea WHERE id=%s AND tarea_id=%s", (mini_id, task_id))


def resolve_minitask_storage():
    try:
        context = resolve_operational_backend("BASE_TAREAS")
        if context.backend_type == "DJANGO":
            return DjangoMiniTaskStorage(context.django_alias)
        if context.backend_type == "MYSQL_CONFIG":
            return MySQLMiniTaskStorage(
                context.mysql_connection, context.database_name,
            )
        raise ValueError("Unsupported source")
    except Exception:
        logger.error("MiniTask BASE_TAREAS resolution failed")
        raise TaskStorageError(ERROR_KEY) from None


def _assigned_django(alias, empresa_id, actor_id):
    user = User.objects.using("default").filter(pk=actor_id, is_active=True).first()
    if user is None:
        raise PermissionDenied
    rows = MiniTarea.objects.using(alias).filter(
        persona_id=actor_id, tarea__empresa_id=empresa_id, tarea__anulada=False,
        tarea__estado__in=["ACTIVA", "GESTION", "PENDIENTE_APROBACION_CIERRE", "CERRADA"],
    ).select_related("tarea").order_by("hecho", "tarea__prioridad", "tarea_id", "pk")
    data = [(row.pk, row.descripcion, row.hecho, row.tarea_id, row.tarea.correlativo,
             row.tarea.titulo, row.tarea.responsable_id) for row in rows]
    return _assigned_present(data)


def _assigned_mysql(storage, empresa_id, actor_id):
    if not User.objects.using("default").filter(pk=actor_id, is_active=True).exists():
        raise PermissionDenied
    try:
        with open_mysql_connection(storage.connection_config, database_name=storage.database_name) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT m.id, m.descripcion, m.hecho, t.id, t.correlativo, t.titulo, t.responsable_id "
                    "FROM tareas_minitarea m JOIN tareas_tarea t ON t.id=m.tarea_id "
                    "WHERE m.persona_id=%s AND t.empresa_id=%s AND t.anulada=0 "
                    "AND t.estado IN (%s,%s,%s,%s) ORDER BY m.hecho, t.prioridad, t.id, m.id",
                    (actor_id, empresa_id, "ACTIVA", "GESTION", "PENDIENTE_APROBACION_CIERRE", "CERRADA"),
                )
                data = cursor.fetchall()
            finally:
                cursor.close()
    except Exception:
        logger.error("Assigned MiniTask read failed: company=%s", empresa_id)
        raise TaskStorageError(ERROR_KEY) from None
    return _assigned_present(data)


def _assigned_present(data):
    users = User.objects.using("default").in_bulk({row[6] for row in data if row[6]})
    return tuple(SimpleNamespace(
        pk=row[0], descripcion=row[1], hecho=bool(row[2]), tarea_id=row[3],
        tarea=SimpleNamespace(
            pk=row[3], correlativo=row[4], titulo=row[5],
            responsable=users.get(row[6], SimpleNamespace(username=str(row[6] or ""))),
        ),
    ) for row in data)
