from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, Max, OuterRef, Q
from django.utils import timezone

from access_control.models import Empresa
from tareas.models import (
    Comentario,
    ComentarioAdjunto,
    ComentarioPausaLectura,
    ComentarioVersion,
    ComentarioVersionDocumento,
    DocumentoTarea,
    Tarea,
    TareaLectura,
)
from tareas.services.connection_roles import get_tarea_connection, get_tarea_mysql_connection
from tareas.services.task_storage import EditTaskNotFound, TaskStorageError
from settings.services.mysql_connections import open_mysql_connection


@dataclass(frozen=True)
class CommentCreateCommand:
    task_id: int
    empresa_id: int
    author_id: int
    content: str
    document_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class CommentEditCommand:
    comment_id: int
    task_id: int
    empresa_id: int
    actor_id: int
    content: str
    document_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class CommentVisibilityCommand:
    comment_id: int
    task_id: int
    empresa_id: int
    actor_id: int
    motivo: str
    oculto: bool


@dataclass(frozen=True)
class CommentPageCommand:
    task_id: int
    empresa_id: int
    user_id: int
    after_id: int | None = None
    before_id: int | None = None
    page_size: int = 20
    updated_after: object | None = None
    updated_after_id: int = 0


@dataclass(frozen=True)
class RecognizeCommentsCommand:
    task_id: int
    empresa_id: int
    user_id: int
    comment_ids: tuple[int, ...]


@dataclass(frozen=True)
class ReadingCommand:
    task_id: int
    empresa_id: int
    user_id: int
    at: object | None = None


@dataclass(frozen=True)
class CommentDTO:
    id: int
    task_id: int
    author_id: int
    content: str
    created_at: object
    updated_at: object
    oculto: bool
    versions: tuple = ()
    attachments: tuple = ()

    @property
    def pk(self):
        return self.id

    @property
    def autor_id(self):
        return self.author_id

    @property
    def autor(self):
        return User.objects.using("default").filter(pk=self.author_id).first()

    @property
    def autor(self):
        return User.objects.using("default").filter(pk=self.author_id).first()

    @property
    def tarea_id(self):
        return self.task_id

    @property
    def contenido(self):
        return self.content

    @property
    def adjuntos(self):
        return self.attachments

    @property
    def versiones(self):
        return _CommentRelation(self.versions)


class _CommentRelation(tuple):
    def all(self):
        return self


@dataclass(frozen=True)
class ReadingDTO:
    id: int
    task_id: int
    user_id: int
    leido: bool
    fecha_lectura: object
    comentario_leido_hasta_id: int | None
    pausas: tuple = field(default_factory=tuple)

    @property
    def pk(self):
        return self.id


@dataclass(frozen=True)
class DocumentDTO:
    id: int
    tipo: str
    formato_archivo: str
    url: str
    archivo_url: str = ""
    nombre_archivo: str = ""

    @property
    def pk(self):
        return self.id

    @property
    def archivo(self):
        return SimpleNamespace(name=self.nombre_archivo, url=self.archivo_url)


@dataclass(frozen=True)
class CommentVersionDTO:
    id: int
    evento: str
    numero_version: int | None
    contenido: str
    actor: object
    fecha: object
    motivo: str
    documentos: tuple = ()

    @property
    def actor_id(self):
        return self.actor.pk


@dataclass(frozen=True)
class TaskDTO:
    id: int
    empresa_id: int
    estado: str
    prioridad: str
    anulada: bool
    creador_id: int | None
    responsable_id: int | None
    empresa: object

    @property
    def pk(self):
        return self.id

    @property
    def _tareas_effective_user_ids(self):
        return {
            user_id for user_id in (self.creador_id, self.responsable_id)
            if user_id is not None
        }


def _task_dto(row):
    task_id, empresa_id, state, priority, annulled, creator_id, responsible_id = row
    empresa = Empresa.objects.using("default").filter(pk=empresa_id).first()
    return TaskDTO(task_id, empresa_id, state, priority, bool(annulled), creator_id, responsible_id, empresa)


def _comment_dto(row, versions=(), attachments=()):
    return CommentDTO(*row, tuple(versions), tuple(attachments))


class DjangoCommentStorage:
    def __init__(self, alias):
        self.alias = alias

    def task(self, task_id, empresa_id):
        try:
            query = Tarea.objects.using(self.alias).select_related("empresa")
            if empresa_id is not None:
                query = query.filter(empresa_id=empresa_id)
            return query.get(pk=task_id)
        except Tarea.DoesNotExist as exc:
            raise EditTaskNotFound from exc

    def create(self, command, *, documents=()):
        task = self.task(command.task_id, command.empresa_id)
        with transaction.atomic(using=self.alias):
            comment = Comentario.objects.using(self.alias).create(
                tarea_id=task.pk, autor_id=command.author_id, contenido=command.content,
            )
            self._replace_attachments(comment.pk, command.task_id, command.document_ids)
            version = ComentarioVersion.objects.using(self.alias).create(
                comentario_id=comment.pk, evento=ComentarioVersion.Evento.CREADO,
                numero_version=1, contenido=command.content, actor_id=command.author_id,
                motivo="",
            )
            self._replace_version_documents(version.pk, command.document_ids)
        return comment

    def get(self, comment_id, task_id, empresa_id):
        return Comentario.objects.using(self.alias).select_related("autor", "tarea").get(
            pk=comment_id, tarea_id=task_id, tarea__empresa_id=empresa_id,
        )

    def list(self, command):
        queryset = Comentario.objects.using(self.alias).filter(
            tarea_id=command.task_id, tarea__empresa_id=command.empresa_id,
        )
        if command.updated_after is not None:
            queryset = queryset.filter(
                Q(pk__gt=command.after_id or 0)
                | Q(updated_at__gt=command.updated_after)
                | Q(updated_at=command.updated_after, pk__gt=command.updated_after_id)
            )
        elif command.after_id is not None:
            queryset = queryset.filter(pk__gt=command.after_id)
        if command.before_id is not None:
            anchor = self.get(command.before_id, command.task_id, command.empresa_id)
            queryset = queryset.filter(
                Q(created_at__lt=anchor.created_at)
                | Q(created_at=anchor.created_at, pk__lt=anchor.pk)
            )
        return list(queryset.order_by("created_at", "pk")[:command.page_size])

    def edit(self, command, *, documents=()):
        with transaction.atomic(using=self.alias):
            comment = self.get(command.comment_id, command.task_id, command.empresa_id)
            comment.contenido = command.content
            comment.save(using=self.alias, update_fields=["contenido", "updated_at"])
            self._replace_attachments(comment.pk, command.task_id, command.document_ids)
            number = ComentarioVersion.objects.using(self.alias).filter(
                comentario_id=comment.pk,
            ).aggregate(value=Max("numero_version"))["value"] or 0
            version = ComentarioVersion.objects.using(self.alias).create(
                comentario_id=comment.pk, evento=ComentarioVersion.Evento.EDITADO,
                numero_version=number + 1, contenido=command.content,
                actor_id=command.actor_id, motivo="",
            )
            self._replace_version_documents(version.pk, command.document_ids)
        return comment

    def set_visibility(self, command):
        with transaction.atomic(using=self.alias):
            comment = self.get(command.comment_id, command.task_id, command.empresa_id)
            documents = list(DocumentoTarea.objects.using(self.alias).filter(
                adjuntos_comentarios__comentario_id=comment.pk, tarea_id=command.task_id,
            ))
            comment.oculto = command.oculto
            comment.save(using=self.alias, update_fields=["oculto", "updated_at"])
            version = ComentarioVersion.objects.using(self.alias).create(
                comentario_id=comment.pk,
                evento=(ComentarioVersion.Evento.OCULTADO if command.oculto else ComentarioVersion.Evento.RESTAURADO),
                numero_version=None, contenido=comment.contenido,
                actor_id=command.actor_id, motivo=command.motivo,
            )
            self._replace_version_documents(version.pk, tuple(doc.pk for doc in documents))
        return comment

    def _replace_attachments(self, comment_id, task_id, document_ids):
        ComentarioAdjunto.objects.using(self.alias).filter(comentario_id=comment_id).delete()
        valid = set(DocumentoTarea.objects.using(self.alias).filter(
            pk__in=document_ids, tarea_id=task_id,
        ).values_list("pk", flat=True))
        if valid != set(document_ids):
            raise ValidationError("El documento no pertenece a la tarea.")
        ComentarioAdjunto.objects.using(self.alias).bulk_create([
            ComentarioAdjunto(comentario_id=comment_id, documento_id=document_id)
            for document_id in document_ids
        ])

    def _replace_version_documents(self, version_id, document_ids):
        ComentarioVersionDocumento.objects.using(self.alias).bulk_create([
            ComentarioVersionDocumento(version_id=version_id, documento_id=document_id)
            for document_id in document_ids
        ])

    def document_ids_for_comment(self, comment_id):
        return tuple(ComentarioAdjunto.objects.using(self.alias).filter(
            comentario_id=comment_id,
        ).values_list("documento_id", flat=True))

    def documents(self, task_id, document_ids):
        return list(DocumentoTarea.objects.using(self.alias).filter(
            tarea_id=task_id, pk__in=document_ids,
        ))

    def reading(self, command):
        reading, _ = TareaLectura.objects.using(self.alias).get_or_create(
            tarea_id=command.task_id, usuario_id=command.user_id,
        )
        return reading

    def pending(self, command):
        reading = self.reading(command)
        queryset = Comentario.objects.using(self.alias).filter(tarea_id=command.task_id)
        if reading.comentario_leido_hasta_id:
            cursor = Comentario.objects.using(self.alias).get(pk=reading.comentario_leido_hasta_id)
            queryset = queryset.filter(
                Q(created_at__gt=cursor.created_at)
                | Q(created_at=cursor.created_at, pk__gt=cursor.pk)
            )
        pauses = ComentarioPausaLectura.objects.using(self.alias).filter(
            lectura_id=reading.pk,
            desde__lte=OuterRef("created_at"),
        ).filter(Q(hasta__isnull=True) | Q(hasta__gt=OuterRef("created_at")))
        return list(queryset.exclude(autor_id=command.user_id).annotate(
            _during_pause=Exists(pauses),
        ).filter(_during_pause=False).order_by("created_at", "pk"))

    def page(self, command):
        reading = self.reading(command)
        pending = self.pending(command)
        if pending:
            queryset = Comentario.objects.using(self.alias).filter(
                tarea_id=command.task_id,
            )
            if reading.comentario_leido_hasta_id:
                cursor = Comentario.objects.using(self.alias).get(
                    pk=reading.comentario_leido_hasta_id,
                )
                queryset = queryset.filter(
                    Q(created_at__gt=cursor.created_at)
                    | Q(created_at=cursor.created_at, pk__gt=cursor.pk)
                )
            return list(queryset.order_by("created_at", "pk")[:command.page_size])
        return list(Comentario.objects.using(self.alias).filter(
            tarea_id=command.task_id,
        ).order_by("-created_at", "-pk")[:command.page_size])[::-1]

    def previous_page(self, command, before_comment):
        queryset = Comentario.objects.using(self.alias).filter(tarea_id=command.task_id).filter(
            Q(created_at__lt=before_comment.created_at)
            | Q(created_at=before_comment.created_at, pk__lt=before_comment.pk)
        )
        return list(queryset.order_by("-created_at", "-pk")[:command.page_size])[::-1]

    def recognize(self, command):
        with transaction.atomic(using=self.alias):
            reading = TareaLectura.objects.using(self.alias).select_for_update().get(
                tarea_id=command.task_id, usuario_id=command.user_id,
            )
            expected_queryset = Comentario.objects.using(self.alias).filter(
                tarea_id=command.task_id,
            )
            if reading.comentario_leido_hasta_id:
                cursor = Comentario.objects.using(self.alias).get(
                    pk=reading.comentario_leido_hasta_id,
                )
                expected_queryset = expected_queryset.filter(
                    Q(created_at__gt=cursor.created_at)
                    | Q(created_at=cursor.created_at, pk__gt=cursor.pk)
                )
            expected = list(expected_queryset.order_by("created_at", "pk")[:20])
            if [item.pk for item in expected] != list(command.comment_ids):
                raise ValidationError("Solo se puede reconocer la siguiente página contigua.")
            reading.comentario_leido_hasta_id = expected[-1].pk
            reading.save(using=self.alias, update_fields=["comentario_leido_hasta"])
        return reading

    def open_pause(self, command):
        reading = self.reading(command)
        current = ComentarioPausaLectura.objects.using(self.alias).filter(
            lectura_id=reading.pk, hasta__isnull=True,
        ).order_by("desde", "pk").first()
        if current is not None:
            return current
        return ComentarioPausaLectura.objects.using(self.alias).create(
            lectura_id=reading.pk, desde=command.at or timezone.now(),
        )

    def close_pause(self, command):
        reading = self.reading(command)
        current = ComentarioPausaLectura.objects.using(self.alias).filter(
            lectura_id=reading.pk, hasta__isnull=True,
        ).order_by("desde", "pk").first()
        if current is None:
            return None
        current.hasta = max(command.at or timezone.now(), current.desde)
        current.save(using=self.alias, update_fields=["hasta"])
        return current

    def ensure_readings(self, task_id, comment_id, user_ids, created_at):
        with transaction.atomic(using=self.alias):
            predecessor = Comentario.objects.using(self.alias).filter(
                tarea_id=task_id,
            ).filter(
                Q(created_at__lt=created_at)
                | Q(created_at=created_at, pk__lt=comment_id)
            ).order_by("-created_at", "-pk").first()
            for user_id in user_ids:
                TareaLectura.objects.using(self.alias).get_or_create(
                    tarea_id=task_id,
                    usuario_id=user_id,
                    defaults={"comentario_leido_hasta": predecessor},
                )

    def handle_user_activity(self, user_id, active, at):
        readings = TareaLectura.objects.using(self.alias).filter(usuario_id=user_id)
        for reading in readings:
            command = ReadingCommand(
                reading.tarea_id, reading.tarea.empresa_id, reading.usuario_id, at,
            )
            if active:
                self.close_pause(command)
            else:
                self.open_pause(command)


class MySQLCommentStorage:
    def __init__(self, connection_config, database_name):
        self.connection_config = connection_config
        self.database_name = database_name

    def _connection(self):
        return open_mysql_connection(self.connection_config, database_name=self.database_name)

    def task(self, task_id, empresa_id):
        try:
            with self._connection() as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        "SELECT id, empresa_id, estado, prioridad, anulada, creada_por_id, responsable_id "
                        "FROM tareas_tarea WHERE id=%s AND empresa_id=%s",
                        (task_id, empresa_id),
                    )
                    row = cursor.fetchone()
                finally:
                    cursor.close()
        except Exception as exc:
            raise TaskStorageError("No se pudo resolver la Tarea en BASE_TAREAS.") from exc
        if row is None:
            raise EditTaskNotFound
        return _task_dto(row)

    def _execute(self, operation):
        try:
            with self._connection() as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute("START TRANSACTION")
                    result = operation(cursor)
                    connection.commit()
                    return result
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except (ValidationError, EditTaskNotFound):
            raise
        except Exception as exc:
            raise TaskStorageError("No se pudo persistir el comentario.") from exc

    def _task(self, cursor, task_id, empresa_id):
        cursor.execute(
            "SELECT id, empresa_id, estado, prioridad, anulada, creada_por_id, responsable_id "
            "FROM tareas_tarea WHERE id=%s AND empresa_id=%s",
            (task_id, empresa_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise EditTaskNotFound
        return _task_dto(row)

    def document_ids_for_comment(self, comment_id):
        def operation(cursor):
            cursor.execute(
                "SELECT documento_id FROM tareas_comentarioadjunto WHERE comentario_id=%s",
                (comment_id,),
            )
            return tuple(row[0] for row in cursor.fetchall())
        return self._execute(operation)

    def pending(self, command):
        def operation(cursor):
            cursor.execute(
                "SELECT comentario_leido_hasta_id FROM tareas_tarealectura "
                "WHERE tarea_id=%s AND usuario_id=%s",
                (command.task_id, command.user_id),
            )
            row = cursor.fetchone()
            cursor_id = row[0] if row else None
            if cursor_id is None:
                cursor.execute(
                    "SELECT id, tarea_id, autor_id, contenido, created_at, updated_at, oculto "
                    "FROM tareas_comentario WHERE tarea_id=%s AND autor_id<>%s "
                    "ORDER BY created_at, id",
                    (command.task_id, command.user_id),
                )
            else:
                cursor.execute(
                    "SELECT id, tarea_id, autor_id, contenido, created_at, updated_at, oculto "
                    "FROM tareas_comentario WHERE tarea_id=%s AND id>%s AND autor_id<>%s "
                    "ORDER BY created_at, id",
                    (command.task_id, cursor_id, command.user_id),
                )
            return [_comment_dto(item) for item in cursor.fetchall()]
        return self._execute(operation)

    def page(self, command):
        def operation(cursor):
            cursor.execute(
                "SELECT id, tarea_id, autor_id, contenido, created_at, updated_at, oculto "
                "FROM tareas_comentario WHERE tarea_id=%s ORDER BY created_at, id LIMIT %s",
                (command.task_id, command.page_size),
            )
            return [_comment_dto(item) for item in cursor.fetchall()]
        return self._execute(operation)

    def previous_page(self, command, before_comment):
        def operation(cursor):
            cursor.execute(
                "SELECT id, tarea_id, autor_id, contenido, created_at, updated_at, oculto "
                "FROM tareas_comentario WHERE tarea_id=%s AND id<%s "
                "ORDER BY created_at DESC, id DESC LIMIT %s",
                (command.task_id, before_comment.pk, command.page_size),
            )
            return [_comment_dto(item) for item in cursor.fetchall()][::-1]
        return self._execute(operation)

    def open_pause(self, command):
        def operation(cursor):
            reading = self._reading_row(cursor, command)
            cursor.execute(
                "SELECT id, desde, hasta FROM tareas_comentariopausalectura "
                "WHERE lectura_id=%s AND hasta IS NULL ORDER BY desde, id LIMIT 1",
                (reading[0],),
            )
            row = cursor.fetchone()
            if row:
                return SimpleNamespace(pk=row[0], lectura_id=reading[0], desde=row[1], hasta=row[2])
            started = command.at or timezone.now()
            cursor.execute(
                "INSERT INTO tareas_comentariopausalectura (lectura_id, desde, hasta) VALUES (%s,%s,%s)",
                (reading[0], started, None),
            )
            return SimpleNamespace(pk=cursor.lastrowid, lectura_id=reading[0], desde=started, hasta=None)
        return self._execute(operation)

    def close_pause(self, command):
        def operation(cursor):
            reading = self._reading_row(cursor, command)
            cursor.execute(
                "SELECT id, desde FROM tareas_comentariopausalectura "
                "WHERE lectura_id=%s AND hasta IS NULL ORDER BY desde, id LIMIT 1 FOR UPDATE",
                (reading[0],),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            started = row[1]
            if timezone.is_naive(started):
                started = timezone.make_aware(started)
            ended = max(command.at or timezone.now(), started)
            cursor.execute(
                "UPDATE tareas_comentariopausalectura SET hasta=%s WHERE id=%s",
                (ended, row[0]),
            )
            return SimpleNamespace(pk=row[0], lectura_id=reading[0], desde=started, hasta=ended)
        return self._execute(operation)

    def _reading_row(self, cursor, command):
        cursor.execute(
            "SELECT id, tarea_id, usuario_id, leido, fecha_lectura, comentario_leido_hasta_id "
            "FROM tareas_tarealectura WHERE tarea_id=%s AND usuario_id=%s FOR UPDATE",
            (command.task_id, command.user_id),
        )
        row = cursor.fetchone()
        if row is None:
            cursor.execute(
                "INSERT INTO tareas_tarealectura (tarea_id, usuario_id, leido, fecha_lectura) VALUES (%s,%s,%s,%s)",
                (command.task_id, command.user_id, False, None),
            )
            return (cursor.lastrowid, command.task_id, command.user_id, False, None, None)
        return row

    def handle_user_activity(self, user_id, active, at):
        def operation(cursor):
            cursor.execute(
                "SELECT id FROM tareas_tarealectura WHERE usuario_id=%s",
                (user_id,),
            )
            reading_ids = [row[0] for row in cursor.fetchall()]
            for reading_id in reading_ids:
                cursor.execute(
                    "SELECT id FROM tareas_comentariopausalectura "
                    "WHERE lectura_id=%s AND hasta IS NULL ORDER BY desde, id LIMIT 1",
                    (reading_id,),
                )
                current = cursor.fetchone()
                if active and current:
                    cursor.execute(
                        "UPDATE tareas_comentariopausalectura SET hasta=%s WHERE id=%s",
                        (at or timezone.now(), current[0]),
                    )
                elif not active and not current:
                    cursor.execute(
                        "INSERT INTO tareas_comentariopausalectura (lectura_id, desde, hasta) VALUES (%s,%s,%s)",
                        (reading_id, at or timezone.now(), None),
                    )
        return self._execute(operation)

    def documents(self, task_id, document_ids):
        return ()

    def create(self, command, *, documents=()):
        def operation(cursor):
            self._task(cursor, command.task_id, command.empresa_id)
            cursor.execute(
                "INSERT INTO tareas_comentario "
                "(tarea_id, autor_id, contenido, created_at, updated_at, oculto) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (command.task_id, command.author_id, command.content, timezone.now(), timezone.now(), False),
            )
            comment_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO tareas_comentarioversion "
                "(comentario_id, evento, numero_version, contenido, actor_id, fecha, motivo) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (comment_id, "CREADO", 1, command.content, command.author_id, timezone.now(), ""),
            )
            version_id = cursor.lastrowid
            self._insert_document_links(cursor, comment_id, version_id, command.document_ids)
            cursor.execute("SELECT id, tarea_id, autor_id, contenido, created_at, updated_at, oculto FROM tareas_comentario WHERE id=%s", (comment_id,))
            return self._materialize_comment(cursor, cursor.fetchone())
        return self._execute(operation)

    def _insert_document_links(self, cursor, comment_id, version_id, document_ids):
        for document_id in document_ids:
            cursor.execute(
                "INSERT INTO tareas_comentarioadjunto (comentario_id, documento_id) VALUES (%s,%s)",
                (comment_id, document_id),
            )
            cursor.execute(
                "INSERT INTO tareas_comentarioversiondocumento (version_id, documento_id) VALUES (%s,%s)",
                (version_id, document_id),
            )

    def _materialize_comment(self, cursor, row):
        comment_id = row[0]
        cursor.execute("SELECT d.id,d.tipo,d.formato_archivo,d.url,d.archivo FROM tareas_comentarioadjunto a JOIN tareas_documentotarea d ON d.id=a.documento_id WHERE a.comentario_id=%s ORDER BY a.id", (comment_id,))
        attachments = []
        for document_id, tipo, formato, url, archivo in cursor.fetchall():
            name = str(archivo or "").replace("\\", "/").rsplit("/", 1)[-1]
            attachments.append(DocumentDTO(document_id, tipo, formato, url or "", archivo or "", name))
        cursor.execute("SELECT v.id,v.evento,v.numero_version,v.contenido,v.actor_id,v.fecha,v.motivo FROM tareas_comentarioversion v WHERE v.comentario_id=%s ORDER BY v.fecha,v.id", (comment_id,))
        versions = []
        for version_id, event, number, content, actor_id, fecha, reason in cursor.fetchall():
            cursor.execute("SELECT d.id,d.tipo,d.formato_archivo,d.url,d.archivo FROM tareas_comentarioversiondocumento x JOIN tareas_documentotarea d ON d.id=x.documento_id WHERE x.version_id=%s ORDER BY x.id", (version_id,))
            documents = []
            for document_id, tipo, formato, url, archivo in cursor.fetchall():
                name = str(archivo or "").replace("\\", "/").rsplit("/", 1)[-1]
                documents.append(DocumentDTO(document_id, tipo, formato, url or "", archivo or "", name))
            actor = User.objects.using("default").filter(pk=actor_id).first()
            versions.append(CommentVersionDTO(version_id, event, number, content, actor, fecha, reason, tuple(documents)))
        return _comment_dto(row, versions, attachments)

    def get(self, comment_id, task_id, empresa_id):
        def operation(cursor):
            self._task(cursor, task_id, empresa_id)
            cursor.execute(
                "SELECT id, tarea_id, autor_id, contenido, created_at, updated_at, oculto "
                "FROM tareas_comentario WHERE id=%s AND tarea_id=%s",
                (comment_id, task_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise EditTaskNotFound
            return self._materialize_comment(cursor, row)
        return self._execute(operation)

    def list(self, command):
        def operation(cursor):
            self._task(cursor, command.task_id, command.empresa_id)
            cursor.execute(
                "SELECT id, tarea_id, autor_id, contenido, created_at, updated_at, oculto "
                "FROM tareas_comentario WHERE tarea_id=%s ORDER BY created_at, id",
                (command.task_id,),
            )
            rows = cursor.fetchall()
            return [self._materialize_comment(cursor, row) for row in rows]
        return self._execute(operation)

    def edit(self, command, *, documents=()):
        def operation(cursor):
            cursor.execute(
                "SELECT id, tarea_id, autor_id, contenido, created_at, updated_at, oculto "
                "FROM tareas_comentario WHERE id=%s AND tarea_id=%s",
                (command.comment_id, command.task_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise EditTaskNotFound
            comment = _comment_dto(row)
            cursor.execute(
                "UPDATE tareas_comentario SET contenido=%s, updated_at=%s WHERE id=%s AND tarea_id=%s",
                (command.content, timezone.now(), command.comment_id, command.task_id),
            )
            cursor.execute(
                "SELECT COALESCE(MAX(numero_version), 0) + 1 FROM tareas_comentarioversion WHERE comentario_id=%s",
                (command.comment_id,),
            )
            number = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO tareas_comentarioversion "
                "(comentario_id, evento, numero_version, contenido, actor_id, fecha, motivo) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (command.comment_id, "EDITADO", number, command.content, command.actor_id, timezone.now(), ""),
            )
            cursor.execute("SELECT id,tarea_id,autor_id,contenido,created_at,updated_at,oculto FROM tareas_comentario WHERE id=%s", (comment.id,))
            return self._materialize_comment(cursor, cursor.fetchone())
        return self._execute(operation)

    def set_visibility(self, command):
        def operation(cursor):
            cursor.execute(
                "SELECT id, tarea_id, autor_id, contenido, created_at, updated_at, oculto "
                "FROM tareas_comentario WHERE id=%s AND tarea_id=%s",
                (command.comment_id, command.task_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise EditTaskNotFound
            comment = _comment_dto(row)
            event = "OCULTADO" if command.oculto else "RESTAURADO"
            cursor.execute(
                "UPDATE tareas_comentario SET oculto=%s, updated_at=%s WHERE id=%s AND tarea_id=%s",
                (command.oculto, timezone.now(), command.comment_id, command.task_id),
            )
            cursor.execute(
                "INSERT INTO tareas_comentarioversion "
                "(comentario_id, evento, numero_version, contenido, actor_id, fecha, motivo) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (command.comment_id, event, None, comment.content, command.actor_id, timezone.now(), command.motivo),
            )
            cursor.execute("SELECT id,tarea_id,autor_id,contenido,created_at,updated_at,oculto FROM tareas_comentario WHERE id=%s", (comment.id,))
            return self._materialize_comment(cursor, cursor.fetchone())
        return self._execute(operation)

    def reading(self, command):
        def operation(cursor):
            cursor.execute(
                "SELECT id, tarea_id, usuario_id, leido, fecha_lectura, comentario_leido_hasta_id "
                "FROM tareas_tarealectura WHERE tarea_id=%s AND usuario_id=%s FOR UPDATE",
                (command.task_id, command.user_id),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "INSERT INTO tareas_tarealectura (tarea_id, usuario_id, leido, fecha_lectura) VALUES (%s,%s,%s,%s)",
                    (command.task_id, command.user_id, False, None),
                )
                return ReadingDTO(cursor.lastrowid, command.task_id, command.user_id, False, None, None)
            return ReadingDTO(*row)
        return self._execute(operation)

    def recognize(self, command):
        def operation(cursor):
            cursor.execute(
                "SELECT id, tarea_id, usuario_id, leido, fecha_lectura, comentario_leido_hasta_id "
                "FROM tareas_tarealectura WHERE tarea_id=%s AND usuario_id=%s FOR UPDATE",
                (command.task_id, command.user_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise EditTaskNotFound
            reading = ReadingDTO(*row)
            cursor.execute(
                "UPDATE tareas_tarealectura SET comentario_leido_hasta_id=%s WHERE id=%s",
                (command.comment_ids[-1], reading.id),
            )
            return ReadingDTO(reading.id, reading.task_id, reading.user_id, reading.leido, reading.fecha_lectura, command.comment_ids[-1])
        return self._execute(operation)

    def ensure_readings(self, task_id, comment_id, user_ids, created_at):
        def operation(cursor):
            cursor.execute(
                "SELECT id FROM tareas_comentario WHERE tarea_id=%s AND "
                "(created_at < %s OR (created_at=%s AND id < %s)) "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (task_id, created_at, created_at, comment_id),
            )
            predecessor = cursor.fetchone()
            predecessor_id = predecessor[0] if predecessor else None
            for user_id in user_ids:
                cursor.execute(
                    "SELECT id FROM tareas_tarealectura WHERE tarea_id=%s AND usuario_id=%s",
                    (task_id, user_id),
                )
                if cursor.fetchone() is None:
                    cursor.execute(
                        "INSERT INTO tareas_tarealectura "
                        "(tarea_id, usuario_id, leido, fecha_lectura, comentario_leido_hasta_id) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (task_id, user_id, False, None, predecessor_id),
                    )
        return self._execute(operation)


def resolve_comment_storage():
    source = get_tarea_connection("BASE_TAREAS")
    if source["type"] == "DJANGO":
        return DjangoCommentStorage(source["alias"])
    if source["type"] == "MYSQL_CONFIG":
        return MySQLCommentStorage(
            get_tarea_mysql_connection("BASE_TAREAS"), source["database_name"],
        )
    raise TaskStorageError("El backend de BASE_TAREAS no es válido.")
