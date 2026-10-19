from __future__ import annotations

from contextlib import contextmanager
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
from tareas.services.task_mutation_locks import (
    bounded_django_lock_wait,
    bounded_mysql_lock_wait,
    lock_mysql_task_rows,
    lock_orm_task_rows,
    mysql_mutation_transaction,
    TaskMutationConflict,
    TaskMutationLockError,
    TaskMutationScopeError,
)


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
        with transaction.atomic(using=self.alias):
            with bounded_django_lock_wait(self.alias):
                try:
                    lock_orm_task_rows(
                        self.alias,
                        command.empresa_id,
                        (command.task_id,),
                    )
                    task = Tarea.objects.using(self.alias).select_related(
                        "empresa"
                    ).get(
                        pk=command.task_id,
                        empresa_id=command.empresa_id,
                    )
                except (TaskMutationScopeError, Tarea.DoesNotExist) as exc:
                    raise EditTaskNotFound from exc
                link = EnlaceTarea.objects.using(self.alias).create(
                    tarea_id=task.pk,
                    destinatario_id=command.destinatario_id,
                    creado_por_id=command.creado_por_id,
                    token_hash=command.token_hash,
                    fecha_expiracion=command.fecha_expiracion,
                )
        return SharedLinkResult(link.pk, task.pk, task.empresa_id, link.token_hash, command.token, link.fecha_expiracion, link.destinatario_id, link.creado_por_id, task, link)

    def resolve(self, token, usuario_id, empresa_id):
        initial = (
            EnlaceTarea.objects.using(self.alias)
            .filter(
                token_hash=hash_link_token(token),
                tarea__eliminada=False,
            )
            .values("pk", "tarea_id", "tarea__empresa_id")
            .first()
        )
        if initial is None:
            raise ValidationError("RECHAZADO_TOKEN_INVALIDO")
        rejection = None
        access = None
        with transaction.atomic(using=self.alias):
            with bounded_django_lock_wait(self.alias):
                task_company_id = initial["tarea__empresa_id"]
                if task_company_id == empresa_id:
                    try:
                        lock_orm_task_rows(
                            self.alias,
                            empresa_id,
                            (initial["tarea_id"],),
                        )
                    except TaskMutationScopeError as exc:
                        raise EditTaskNotFound from exc
                try:
                    link = (
                        EnlaceTarea.objects.using(self.alias)
                        .select_for_update()
                        .get(pk=initial["pk"])
                    )
                except EnlaceTarea.DoesNotExist as exc:
                    raise ValidationError("RECHAZADO_TOKEN_INVALIDO") from exc
                if link.tarea_id != initial["tarea_id"]:
                    raise TaskMutationConflict(
                        "El enlace cambió durante la operación."
                    )
                current_company_id = (
                    Tarea.objects.using(self.alias)
                    .filter(pk=link.tarea_id)
                    .values_list("empresa_id", flat=True)
                    .first()
                )
                if current_company_id is None:
                    raise EditTaskNotFound
                task = None
                if current_company_id == empresa_id:
                    task = Tarea.objects.using(self.alias).select_related(
                        "empresa"
                    ).get(pk=link.tarea_id, empresa_id=empresa_id)

                if current_company_id != empresa_id:
                    rejection = EventoAccesoEnlace.Resultado.RECHAZADO_EMPRESA
                elif (
                    link.destinatario_id != usuario_id
                    or not _is_valid_external_user(task.empresa, usuario_id)
                ):
                    rejection = EventoAccesoEnlace.Resultado.RECHAZADO_USUARIO
                elif link.fecha_expiracion <= timezone.now():
                    rejection = EventoAccesoEnlace.Resultado.RECHAZADO_EXPIRADO
                elif link.revocado_at is not None:
                    rejection = EventoAccesoEnlace.Resultado.RECHAZADO_REVOCADO
                else:
                    rejection = EventoAccesoEnlace.Resultado.ACCESO_OK
                    access = SharedLinkAccessResult(task, link.pk)
                EventoAccesoEnlace.objects.using(self.alias).create(
                    enlace_id=link.pk,
                    usuario_id=usuario_id,
                    resultado=rejection,
                )
        if rejection != EventoAccesoEnlace.Resultado.ACCESO_OK:
            raise ValidationError(rejection)
        return access

    def revoke(self, command):
        initial = (
            EnlaceTarea.objects.using(self.alias)
            .filter(
                pk=command.link_id,
                tarea__empresa_id=command.empresa_id,
                tarea__eliminada=False,
            )
            .values("tarea_id", "tarea__empresa_id")
            .first()
        )
        if initial is None:
            raise EditTaskNotFound
        with transaction.atomic(using=self.alias):
            with bounded_django_lock_wait(self.alias):
                try:
                    lock_orm_task_rows(
                        self.alias,
                        command.empresa_id,
                        (initial["tarea_id"],),
                    )
                    link = (
                        EnlaceTarea.objects.using(self.alias)
                        .select_for_update()
                        .get(
                            pk=command.link_id,
                            tarea_id=initial["tarea_id"],
                            tarea__empresa_id=command.empresa_id,
                        )
                    )
                except (TaskMutationScopeError, EnlaceTarea.DoesNotExist) as exc:
                    raise EditTaskNotFound from exc
                if link.revocado_at is None:
                    link.revocado_at = timezone.now()
                    link.revocado_por_id = command.actor_id
                    link.save(
                        using=self.alias,
                        update_fields=["revocado_at", "revocado_por"],
                    )
        return link


class MySQLSharedLinkStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    @contextmanager
    def _mutation(self, connection, *, company_id=None, task_ids=None):
        with bounded_mysql_lock_wait(connection):
            with mysql_mutation_transaction(connection):
                if company_id is not None:
                    try:
                        lock_mysql_task_rows(connection, company_id, task_ids)
                    except TaskMutationScopeError as exc:
                        raise EditTaskNotFound from exc
                cursor = connection.cursor()
                try:
                    yield cursor
                finally:
                    cursor.close()

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
                with self._mutation(
                    connection,
                    company_id=command.empresa_id,
                    task_ids=(command.task_id,),
                ) as cursor:
                    cursor.execute(
                        "SELECT id,titulo,descripcion,correlativo,estado,prioridad,"
                        "responsable_id,empresa_id FROM tareas_tarea "
                        "WHERE id=%s AND empresa_id=%s AND eliminada=0 FOR UPDATE",
                        (command.task_id, command.empresa_id),
                    )
                    task_row = cursor.fetchone()
                    if task_row is None:
                        raise EditTaskNotFound
                    cursor.execute("INSERT INTO tareas_enlacetarea (tarea_id,destinatario_id,creado_por_id,token_hash,fecha_creacion,fecha_expiracion) VALUES (%s,%s,%s,%s,%s,%s)", (command.task_id,command.destinatario_id,command.creado_por_id,command.token_hash,timezone.now(),command.fecha_expiracion))
                    link_id=cursor.lastrowid
        except (EditTaskNotFound,ValidationError): raise
        except TaskMutationLockError as exc:
            raise TaskStorageError("No se pudo crear el enlace.") from exc
        except Exception as exc: raise TaskStorageError("No se pudo crear el enlace.") from exc
        task_id,title,description,correlativo,state,priority,responsible_id,task_company = task_row
        empresa = Empresa.objects.using("default").get(pk=task_company)
        responsible = User.objects.using("default").filter(pk=responsible_id).first() if responsible_id else None
        task = SharedLinkTaskData(task_id, task_company, title, description, correlativo, state, priority, responsible, empresa)
        return SharedLinkResult(link_id,task_id,task_company,command.token_hash,command.token,command.fecha_expiracion,command.destinatario_id,command.creado_por_id,task)

    def resolve(self, token, usuario_id, empresa_id):
        rejection = None
        task_values = None
        link_id = None
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                with bounded_mysql_lock_wait(connection):
                    with mysql_mutation_transaction(connection):
                        cursor = connection.cursor()
                        try:
                            cursor.execute(
                                "SELECT link.id,link.tarea_id,link.destinatario_id,"
                                "link.fecha_expiracion,link.revocado_at,task.empresa_id "
                                "FROM tareas_enlacetarea AS link "
                                "INNER JOIN tareas_tarea AS task ON task.id=link.tarea_id "
                                "WHERE link.token_hash=%s AND task.eliminada=0",
                                (hash_link_token(token),),
                            )
                            initial = cursor.fetchone()
                            if initial is None:
                                raise ValidationError("RECHAZADO_TOKEN_INVALIDO")
                            (
                                link_id,
                                task_id,
                                _initial_recipient,
                                _initial_expires,
                                _initial_revoked,
                                task_company,
                            ) = initial
                            if task_company == empresa_id:
                                try:
                                    lock_mysql_task_rows(
                                        connection,
                                        task_company,
                                        (task_id,),
                                    )
                                except TaskMutationScopeError as exc:
                                    raise EditTaskNotFound from exc
                            cursor.execute(
                                "SELECT id,tarea_id,destinatario_id,fecha_expiracion,revocado_at "
                                "FROM tareas_enlacetarea WHERE id=%s FOR UPDATE",
                                (link_id,),
                            )
                            link = cursor.fetchone()
                            if link is None or link[1] != task_id:
                                raise ValidationError("RECHAZADO_TOKEN_INVALIDO")
                            _, task_id, destinatario, expires, revoked = link
                            if timezone.is_naive(expires):
                                expires = timezone.make_aware(expires)
                            if task_company != empresa_id:
                                rejection = EventoAccesoEnlace.Resultado.RECHAZADO_EMPRESA
                            elif (
                                destinatario != usuario_id
                                or not _is_valid_external_user_id(task_company, usuario_id)
                            ):
                                rejection = EventoAccesoEnlace.Resultado.RECHAZADO_USUARIO
                            elif expires <= timezone.now():
                                rejection = EventoAccesoEnlace.Resultado.RECHAZADO_EXPIRADO
                            elif revoked is not None:
                                rejection = EventoAccesoEnlace.Resultado.RECHAZADO_REVOCADO
                            else:
                                rejection = EventoAccesoEnlace.Resultado.ACCESO_OK
                                cursor.execute(
                                    "SELECT titulo,descripcion,correlativo,estado,prioridad,"
                                    "responsable_id,empresa_id FROM tareas_tarea "
                                    "WHERE id=%s AND empresa_id=%s AND eliminada=0",
                                    (task_id, task_company),
                                )
                                task_values = cursor.fetchone()
                                if task_values is None:
                                    raise EditTaskNotFound
                            cursor.execute(
                                "INSERT INTO tareas_eventoaccesoenlace "
                                "(enlace_id,usuario_id,fecha,resultado) "
                                "VALUES (%s,%s,%s,%s)",
                                (link_id, usuario_id, timezone.now(), rejection),
                            )
                        finally:
                            cursor.close()
        except ValidationError: raise
        except (EditTaskNotFound, TaskMutationLockError): raise
        except Exception as exc: raise TaskStorageError("No se pudo resolver el enlace.") from exc
        if rejection != EventoAccesoEnlace.Resultado.ACCESO_OK:
            raise ValidationError(rejection)
        title, description, correlativo, state, priority, responsible, task_company = task_values
        empresa = Empresa.objects.using("default").get(pk=task_company)
        responsible_user = User.objects.using("default").filter(pk=responsible).first() if responsible else None
        task = SharedLinkTaskData(
            task_id, task_company, title, description, correlativo, state,
            priority, responsible_user, empresa,
        )
        return SharedLinkAccessResult(task, link_id)

    def revoke(self, command):
        try:
            with open_mysql_connection(self.connection_config,database_name=self.database_name) as connection:
                with bounded_mysql_lock_wait(connection):
                    with mysql_mutation_transaction(connection):
                        cursor = connection.cursor()
                        try:
                            cursor.execute(
                                "SELECT tarea_id FROM tareas_enlacetarea WHERE id=%s",
                                (command.link_id,),
                            )
                            initial = cursor.fetchone()
                            if initial is None:
                                raise EditTaskNotFound
                            task_id = initial[0]
                            try:
                                lock_mysql_task_rows(
                                    connection,
                                    command.empresa_id,
                                    (task_id,),
                                )
                            except TaskMutationScopeError as exc:
                                raise EditTaskNotFound from exc
                            cursor.execute(
                                "SELECT link.revocado_at FROM tareas_enlacetarea AS link "
                                "INNER JOIN tareas_tarea AS task ON task.id=link.tarea_id "
                                "WHERE link.id=%s AND link.tarea_id=%s "
                                "AND task.empresa_id=%s AND task.eliminada=0 FOR UPDATE",
                                (command.link_id, task_id, command.empresa_id),
                            )
                            row = cursor.fetchone()
                            if row is None:
                                raise EditTaskNotFound
                            if row[0] is None:
                                cursor.execute(
                                    "UPDATE tareas_enlacetarea SET revocado_at=%s, "
                                    "revocado_por_id=%s WHERE id=%s AND tarea_id=%s",
                                    (
                                        timezone.now(),
                                        command.actor_id,
                                        command.link_id,
                                        task_id,
                                    ),
                                )
                        finally:
                            cursor.close()
        except (EditTaskNotFound,ValidationError): raise
        except TaskMutationLockError as exc:
            raise TaskStorageError("No se pudo revocar el enlace.") from exc
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
