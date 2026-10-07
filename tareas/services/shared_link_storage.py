from __future__ import annotations

from dataclasses import dataclass
import hashlib

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from access_control.models import Empresa
from access_control.services.permissions import get_valid_users_for_empresa
from django.contrib.auth.models import User
from tareas.models import EnlaceTarea, EventoAccesoEnlace, Tarea
from tareas.services.task_storage import EditTaskNotFound, TaskStorageError
from tareas.services.connection_roles import resolve_operational_backend
from settings.services.mysql_connections import open_mysql_connection


def hash_link_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SharedLinkCreateCommand:
    task_id: int
    empresa_id: int
    destinatario_id: int
    creado_por_id: int
    fecha_expiracion: object
    token: str
    token_hash: str


@dataclass(frozen=True)
class SharedLinkTaskData:
    pk: int
    empresa_id: int
    titulo: str
    descripcion: str
    correlativo: str
    estado: str
    prioridad: str
    responsable: object
    empresa: object


@dataclass(frozen=True)
class SharedLinkResult:
    id: int
    task_id: int
    empresa_id: int
    token_hash: str
    token: str | None
    fecha_expiracion: object
    destinatario_id: int
    creado_por_id: int
    tarea: object | None = None
    record: object | None = None


@dataclass(frozen=True)
class SharedLinkAccessResult:
    task: object
    link_id: int


@dataclass(frozen=True)
class SharedLinkRevokeCommand:
    link_id: int
    empresa_id: int
    actor_id: int


class DjangoSharedLinkStorage:
    def __init__(self, alias: str):
        self.alias = alias

    def create(self, command: SharedLinkCreateCommand):
        try:
            task = Tarea.objects.using(self.alias).select_related("empresa").get(pk=command.task_id, empresa_id=command.empresa_id)
        except Tarea.DoesNotExist as exc:
            raise EditTaskNotFound from exc
        with transaction.atomic(using=self.alias):
            link = EnlaceTarea.objects.using(self.alias).create(
                tarea_id=task.pk,
                destinatario_id=command.destinatario_id,
                creado_por_id=command.creado_por_id,
                token_hash=command.token_hash,
                fecha_expiracion=command.fecha_expiracion,
            )
        return SharedLinkResult(link.pk, task.pk, task.empresa_id, link.token_hash, command.token, link.fecha_expiracion, link.destinatario_id, link.creado_por_id, task, link)

    def resolve(self, token, usuario_id, empresa_id):
        try:
            link = EnlaceTarea.objects.using(self.alias).select_related("tarea", "tarea__empresa").get(token_hash=hash_link_token(token))
        except EnlaceTarea.DoesNotExist:
            raise ValidationError("RECHAZADO_TOKEN_INVALIDO")
        if link.tarea.empresa_id != empresa_id:
            resultado = EventoAccesoEnlace.Resultado.RECHAZADO_EMPRESA
            EventoAccesoEnlace.objects.using(self.alias).create(enlace_id=link.pk, usuario_id=usuario_id, resultado=resultado)
            raise ValidationError(resultado)
        if link.destinatario_id != usuario_id or not _is_valid_external_user(link.tarea.empresa, usuario_id):
            resultado = EventoAccesoEnlace.Resultado.RECHAZADO_USUARIO
            EventoAccesoEnlace.objects.using(self.alias).create(enlace_id=link.pk, usuario_id=usuario_id, resultado=resultado)
            raise ValidationError(resultado)
        if link.fecha_expiracion <= timezone.now():
            EventoAccesoEnlace.objects.using(self.alias).create(enlace_id=link.pk, usuario_id=usuario_id, resultado=EventoAccesoEnlace.Resultado.RECHAZADO_EXPIRADO)
            raise ValidationError(EventoAccesoEnlace.Resultado.RECHAZADO_EXPIRADO)
        if link.revocado_at is not None:
            EventoAccesoEnlace.objects.using(self.alias).create(enlace_id=link.pk, usuario_id=usuario_id, resultado=EventoAccesoEnlace.Resultado.RECHAZADO_REVOCADO)
            raise ValidationError(EventoAccesoEnlace.Resultado.RECHAZADO_REVOCADO)
        EventoAccesoEnlace.objects.using(self.alias).create(enlace_id=link.pk, usuario_id=usuario_id, resultado=EventoAccesoEnlace.Resultado.ACCESO_OK)
        return SharedLinkAccessResult(link.tarea, link.pk)

    def revoke(self, command):
        try:
            link = EnlaceTarea.objects.using(self.alias).get(pk=command.link_id, tarea__empresa_id=command.empresa_id)
        except EnlaceTarea.DoesNotExist as exc:
            raise EditTaskNotFound from exc
        if link.revocado_at is None:
            link.revocado_at = timezone.now()
            link.revocado_por_id = command.actor_id
            link.save(using=self.alias, update_fields=["revocado_at", "revocado_por"])
        return link


class MySQLSharedLinkStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    def _validate_users(self, empresa_id, *user_ids):
        empresa = Empresa.objects.using("default").get(pk=empresa_id)
        users = list(User.objects.using("default").filter(pk__in=user_ids, is_active=True))
        valid = get_valid_users_for_empresa(empresa, active_only=True).filter(pk__in=user_ids).count()
        if valid != len(set(user_ids)):
            raise ValidationError("El usuario no pertenece a la Empresa.")
        return users

    def create(self, command):
        self._validate_users(command.empresa_id, command.destinatario_id, command.creado_por_id)
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor=connection.cursor()
                try:
                    cursor.execute("SELECT id,titulo,descripcion,correlativo,estado,prioridad,responsable_id,empresa_id FROM tareas_tarea WHERE id=%s AND empresa_id=%s", (command.task_id,command.empresa_id))
                    task_row = cursor.fetchone()
                    if task_row is None: raise EditTaskNotFound
                    cursor.execute("INSERT INTO tareas_enlacetarea (tarea_id,destinatario_id,creado_por_id,token_hash,fecha_creacion,fecha_expiracion) VALUES (%s,%s,%s,%s,%s,%s)", (command.task_id,command.destinatario_id,command.creado_por_id,command.token_hash,timezone.now(),command.fecha_expiracion))
                    link_id=cursor.lastrowid; connection.commit()
                except Exception:
                    connection.rollback(); raise
                finally: cursor.close()
        except (EditTaskNotFound,ValidationError): raise
        except Exception as exc: raise TaskStorageError("No se pudo crear el enlace.") from exc
        task_id,title,description,correlativo,state,priority,responsible_id,task_company = task_row
        empresa = Empresa.objects.using("default").get(pk=task_company)
        responsible = User.objects.using("default").filter(pk=responsible_id).first() if responsible_id else None
        task = SharedLinkTaskData(task_id, task_company, title, description, correlativo, state, priority, responsible, empresa)
        return SharedLinkResult(link_id,task_id,task_company,command.token_hash,command.token,command.fecha_expiracion,command.destinatario_id,command.creado_por_id,task)

    def resolve(self, token, usuario_id, empresa_id):
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor=connection.cursor()
                try:
                    cursor.execute("SELECT l.id,l.tarea_id,l.destinatario_id,l.fecha_expiracion,l.revocado_at,t.titulo,t.descripcion,t.correlativo,t.estado,t.prioridad,t.responsable_id,t.empresa_id FROM tareas_enlacetarea l JOIN tareas_tarea t ON t.id=l.tarea_id WHERE l.token_hash=%s", (hash_link_token(token),))
                    row=cursor.fetchone()
                    if row is None: raise ValidationError("RECHAZADO_TOKEN_INVALIDO")
                    link_id,task_id,destinatario,expires,revoked,title,description,correlativo,state,priority,responsible,task_company=row
                    if timezone.is_naive(expires): expires=timezone.make_aware(expires)
                    if task_company != empresa_id: result=EventoAccesoEnlace.Resultado.RECHAZADO_EMPRESA
                    elif destinatario != usuario_id or not _is_valid_external_user_id(task_company, usuario_id): result=EventoAccesoEnlace.Resultado.RECHAZADO_USUARIO
                    elif expires <= timezone.now(): result=EventoAccesoEnlace.Resultado.RECHAZADO_EXPIRADO
                    elif revoked is not None: result=EventoAccesoEnlace.Resultado.RECHAZADO_REVOCADO
                    else: result=EventoAccesoEnlace.Resultado.ACCESO_OK
                    cursor.execute("INSERT INTO tareas_eventoaccesoenlace (enlace_id,usuario_id,fecha,resultado) VALUES (%s,%s,%s,%s)",(link_id,usuario_id,timezone.now(),result))
                    if result != EventoAccesoEnlace.Resultado.ACCESO_OK: connection.commit(); raise ValidationError(result)
                    connection.commit()
                except Exception:
                    if cursor: connection.rollback()
                    raise
                finally: cursor.close()
        except ValidationError: raise
        except Exception as exc: raise TaskStorageError("No se pudo resolver el enlace.") from exc
        empresa = Empresa.objects.using("default").get(pk=task_company)
        responsible_user = User.objects.using("default").filter(pk=responsible).first() if responsible else None
        task=SharedLinkTaskData(task_id, task_company, title, description, correlativo, state, priority, responsible_user, empresa)
        return SharedLinkAccessResult(task,link_id)

    def revoke(self, command):
        try:
            with open_mysql_connection(self.connection_config,database_name=self.database_name) as connection:
                cursor=connection.cursor()
                try:
                    cursor.execute("SELECT l.id,l.revocado_at FROM tareas_enlacetarea l JOIN tareas_tarea t ON t.id=l.tarea_id WHERE l.id=%s AND t.empresa_id=%s FOR UPDATE",(command.link_id,command.empresa_id))
                    row=cursor.fetchone()
                    if row is None: raise EditTaskNotFound
                    if row[1] is None:
                        cursor.execute("UPDATE tareas_enlacetarea SET revocado_at=%s, revocado_por_id=%s WHERE id=%s",(timezone.now(),command.actor_id,command.link_id))
                    connection.commit()
                except Exception:
                    connection.rollback(); raise
                finally: cursor.close()
        except (EditTaskNotFound,ValidationError): raise
        except Exception as exc: raise TaskStorageError("No se pudo revocar el enlace.") from exc
        return command.link_id


def resolve_shared_link_storage():
    context=resolve_operational_backend("BASE_TAREAS")
    if context.backend_type=="DJANGO": return DjangoSharedLinkStorage(context.django_alias)
    if context.backend_type=="MYSQL_CONFIG": return MySQLSharedLinkStorage(context.mysql_connection,context.database_name)
    raise TaskStorageError("El backend de BASE_TAREAS no es válido.")


def _is_valid_external_user(empresa, user_id):
    return _is_valid_external_user_id(empresa.pk, user_id, empresa=empresa)


def _is_valid_external_user_id(empresa_id, user_id, empresa=None):
    empresa = empresa or Empresa.objects.using("default").filter(pk=empresa_id).first()
    if empresa is None or not User.objects.using("default").filter(pk=user_id, is_active=True).exists():
        return False
    return get_valid_users_for_empresa(empresa, active_only=True).filter(pk=user_id).exists()
