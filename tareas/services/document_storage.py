from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from access_control.services.permissions import get_valid_users_for_empresa
from django.contrib.auth.models import User

from .connection_roles import TareaConnectionError, resolve_operational_backend
from .image_processing import optimize_uploaded_image
from .task_storage import EditTaskNotFound, TaskStorageError
from settings.services.mysql_connections import open_mysql_connection
from ..models import DocumentoHistorial, DocumentoTarea, EvidenciaCierre, Tarea


@dataclass(frozen=True)
class DocumentCreateCommand:
    tarea_id: int
    empresa_id: int
    usuario_id: int
    tipo: str
    formato_archivo: str
    archivo: object = None
    url: str = ""
    fecha_documento: object = None
    fecha_vencimiento: object = None
    estado: str = ""


@dataclass(frozen=True)
class EvidenceCreateCommand:
    tarea_id: int
    empresa_id: int
    usuario_id: int
    formato_archivo: str
    archivo: object = None
    url: str = ""
    documento_id: int | None = None


@dataclass(frozen=True)
class DocumentUpdateCommand:
    documento_id: int
    tarea_id: int
    empresa_id: int
    usuario_id: int
    changes: dict


class DjangoDocumentStorage:
    def __init__(self, alias: str):
        self.alias = alias

    def _task(self, task_id, empresa_id):
        try:
            return Tarea.objects.using(self.alias).get(pk=task_id, empresa_id=empresa_id)
        except Tarea.DoesNotExist as exc:
            raise EditTaskNotFound from exc

    def _actor(self, usuario_id, empresa):
        actor = User.objects.using("default").get(pk=usuario_id)
        if not get_valid_users_for_empresa(empresa, active_only=True).filter(pk=actor.pk).exists():
            raise ValidationError("El usuario no pertenece a la Empresa activa.")
        return actor

    def create_document(self, command: DocumentCreateCommand):
        tarea = self._task(command.tarea_id, command.empresa_id)
        actor = self._actor(command.usuario_id, tarea.empresa)
        archivo = optimize_uploaded_image(command.archivo, command.formato_archivo)
        with transaction.atomic(using=self.alias):
            documento = DocumentoTarea(
                tarea_id=tarea.pk,
                tipo=command.tipo,
                formato_archivo=command.formato_archivo,
                url=command.url or "",
                fecha_vencimiento=command.fecha_vencimiento,
                usuario_id=actor.pk,
                estado=command.estado,
            )
            if command.fecha_documento is not None:
                documento.fecha_documento = command.fecha_documento
            if archivo:
                if hasattr(archivo, "read"):
                    documento.archivo.save(getattr(archivo, "name", "archivo"), archivo, save=False)
                else:
                    documento.archivo = archivo
            documento.full_clean()
            documento.save(using=self.alias)
            DocumentoHistorial.objects.using(self.alias).create(
                documento_id=documento.pk,
                accion="CREADO",
                usuario_id=actor.pk,
            )
        return documento

    def register_evidence(self, command: EvidenceCreateCommand):
        tarea = self._task(command.tarea_id, command.empresa_id)
        actor = self._actor(command.usuario_id, tarea.empresa)
        documento = None
        if command.documento_id is not None:
            try:
                documento = DocumentoTarea.objects.using(self.alias).get(
                    pk=command.documento_id,
                    tarea_id=tarea.pk,
                )
            except DocumentoTarea.DoesNotExist as exc:
                raise ValidationError("El documento no pertenece a la tarea.") from exc
        archivo = optimize_uploaded_image(command.archivo, command.formato_archivo)
        if documento is not None and not archivo and not command.url:
            archivo = documento.archivo
            url = documento.url
        else:
            url = command.url or ""
        with transaction.atomic(using=self.alias):
            evidencia = EvidenciaCierre(
                tarea_id=tarea.pk,
                documento_id=documento.pk if documento else None,
                formato_archivo=command.formato_archivo,
                url=url,
                usuario_id=actor.pk,
            )
            if archivo:
                if hasattr(archivo, "read"):
                    evidencia.archivo.save(getattr(archivo, "name", "archivo"), archivo, save=False)
                else:
                    evidencia.archivo = archivo
            evidencia.full_clean()
            evidencia.save(using=self.alias)
        return evidencia

    def configure_evidence(self, *, task_id, empresa_id, usuario_id, required):
        tarea = self._task(task_id, empresa_id)
        self._actor(usuario_id, tarea.empresa)
        tarea.requiere_evidencia_cierre = bool(required)
        tarea.save(using=self.alias, update_fields=["requiere_evidencia_cierre"])
        return tarea

    def update_document(self, command: DocumentUpdateCommand):
        task = self._task(command.tarea_id, command.empresa_id)
        actor = self._actor(command.usuario_id, task.empresa)
        documento = DocumentoTarea.objects.using(self.alias).get(
            pk=command.documento_id,
            tarea_id=task.pk,
        )
        allowed = {"tipo", "formato_archivo", "archivo", "url", "fecha_documento", "fecha_vencimiento", "estado"}
        unknown = set(command.changes) - allowed
        if unknown:
            raise ValidationError("El documento contiene campos no editables.")
        for field, value in command.changes.items():
            setattr(documento, field, value or "" if field in {"archivo", "url"} else value)
        documento.full_clean()
        with transaction.atomic(using=self.alias):
            documento.save(using=self.alias)
            DocumentoHistorial.objects.using(self.alias).create(
                documento_id=documento.pk, accion="ACTUALIZADO", usuario_id=actor.pk
            )
        return documento

    def has_valid_closure_evidence(self, *, task_id, empresa_id):
        try:
            task = Tarea.objects.using(self.alias).get(pk=task_id, empresa_id=empresa_id)
        except Tarea.DoesNotExist:
            raise EditTaskNotFound
        return any(
            bool(item.archivo or item.url)
            and not _document_validation_error(item)
            for item in EvidenciaCierre.objects.using(self.alias).filter(tarea_id=task.pk)
        )


class MySQLDocumentStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    def _task(self, cursor, task_id, empresa_id):
        cursor.execute(
            "SELECT id, empresa_id, requiere_evidencia_cierre FROM tareas_tarea "
            "WHERE id=%s AND empresa_id=%s",
            (task_id, empresa_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise EditTaskNotFound
        return row

    def _validate_actor(self, usuario_id, empresa_id):
        from access_control.models import Empresa
        empresa = Empresa.objects.using("default").get(pk=empresa_id)
        if not get_valid_users_for_empresa(empresa, active_only=True).filter(pk=usuario_id).exists():
            raise ValidationError("El usuario no pertenece a la Empresa activa.")

    @staticmethod
    def _path(uploaded):
        return getattr(uploaded, "name", uploaded or "")

    def create_document(self, command: DocumentCreateCommand):
        self._validate_actor(command.usuario_id, command.empresa_id)
        archivo = optimize_uploaded_image(command.archivo, command.formato_archivo)
        archivo_path = ""
        if archivo:
            archivo_path = default_storage.save(
                f"tareas/documentos/{getattr(archivo, 'name', 'archivo')}",
                archivo,
            )
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor = connection.cursor()
                try:
                    self._task(cursor, command.tarea_id, command.empresa_id)
                    cursor.execute(
                        "INSERT INTO tareas_documentotarea "
                        "(tarea_id,tipo,formato_archivo,archivo,url,fecha_documento,fecha_vencimiento,usuario_id,estado) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (command.tarea_id, command.tipo, command.formato_archivo, archivo_path, command.url or "", command.fecha_documento or timezone.localdate(), command.fecha_vencimiento, command.usuario_id, command.estado),
                    )
                    document_id = cursor.lastrowid
                    cursor.execute(
                        "INSERT INTO tareas_documentohistorial (documento_id,accion,usuario_id,fecha) VALUES (%s,%s,%s,%s)",
                        (document_id, "CREADO", command.usuario_id, timezone.now()),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except EditTaskNotFound:
            if archivo_path:
                default_storage.delete(archivo_path)
            raise
        except Exception as exc:
            if archivo_path:
                default_storage.delete(archivo_path)
            raise TaskStorageError("No se pudo crear el documento.") from exc
        return document_id

    def register_evidence(self, command: EvidenceCreateCommand):
        self._validate_actor(command.usuario_id, command.empresa_id)
        archivo = optimize_uploaded_image(command.archivo, command.formato_archivo)
        archivo_path = ""
        if archivo:
            archivo_path = default_storage.save(
                f"tareas/evidencias/{getattr(archivo, 'name', 'archivo')}",
                archivo,
            )
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor = connection.cursor()
                try:
                    self._task(cursor, command.tarea_id, command.empresa_id)
                    inherited_archivo = ""
                    inherited_url = ""
                    if command.documento_id is not None:
                        cursor.execute(
                            "SELECT archivo, url FROM tareas_documentotarea WHERE id=%s AND tarea_id=%s",
                            (command.documento_id, command.tarea_id),
                        )
                        document_row = cursor.fetchone()
                        if document_row is None:
                            raise ValidationError("El documento no pertenece a la tarea.")
                        inherited_archivo, inherited_url = document_row
                    if command.documento_id is not None and not archivo_path and not command.url:
                        archivo_path = inherited_archivo
                        evidence_url = inherited_url
                    else:
                        evidence_url = command.url or ""
                    cursor.execute(
                        "INSERT INTO tareas_evidenciacierre "
                        "(tarea_id,documento_id,formato_archivo,archivo,url,usuario_id,fecha) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (command.tarea_id, command.documento_id, command.formato_archivo, archivo_path, evidence_url, command.usuario_id, timezone.now()),
                    )
                    evidence_id = cursor.lastrowid
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except EditTaskNotFound:
            if archivo_path:
                default_storage.delete(archivo_path)
            raise
        except Exception as exc:
            if archivo_path:
                default_storage.delete(archivo_path)
            raise TaskStorageError("No se pudo registrar la evidencia de cierre.") from exc
        return evidence_id

    def configure_evidence(self, *, task_id, empresa_id, usuario_id, required):
        self._validate_actor(usuario_id, empresa_id)
        with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
            cursor = connection.cursor()
            try:
                self._task(cursor, task_id, empresa_id)
                # This column is already part of the frozen tasks table.
                cursor.execute(
                    "UPDATE tareas_tarea SET requiere_evidencia_cierre=%s WHERE id=%s AND empresa_id=%s",
                    (bool(required), task_id, empresa_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
        return task_id

    def update_document(self, command: DocumentUpdateCommand):
        self._validate_actor(command.usuario_id, command.empresa_id)
        allowed = {"tipo", "formato_archivo", "archivo", "url", "fecha_documento", "fecha_vencimiento", "estado"}
        unknown = set(command.changes) - allowed
        if unknown:
            raise ValidationError("El documento contiene campos no editables.")
        fields = []
        values = []
        for field, value in command.changes.items():
            fields.append(f"{field}=%s")
            values.append(value or "" if field in {"archivo", "url"} else value)
        try:
            with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        "SELECT id FROM tareas_documentotarea WHERE id=%s AND tarea_id=%s "
                        "AND tarea_id IN (SELECT id FROM tareas_tarea WHERE empresa_id=%s) FOR UPDATE",
                        (command.documento_id, command.tarea_id, command.empresa_id),
                    )
                    if cursor.fetchone() is None:
                        raise EditTaskNotFound
                    cursor.execute(
                        "UPDATE tareas_documentotarea SET " + ",".join(fields) + " WHERE id=%s AND tarea_id=%s",
                        tuple(values) + (command.documento_id, command.tarea_id),
                    )
                    cursor.execute(
                        "INSERT INTO tareas_documentohistorial (documento_id,accion,usuario_id,fecha) VALUES (%s,%s,%s,%s)",
                        (command.documento_id, "ACTUALIZADO", command.usuario_id, timezone.now()),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
        except (EditTaskNotFound, ValidationError):
            raise
        except Exception as exc:
            raise TaskStorageError("No se pudo actualizar el documento.") from exc
        return command.documento_id

    def has_valid_closure_evidence(self, *, task_id, empresa_id):
        with open_mysql_connection(self.connection_config, database_name=self.database_name) as connection:
            cursor = connection.cursor()
            try:
                self._task(cursor, task_id, empresa_id)
                cursor.execute(
                    "SELECT formato_archivo, archivo, url FROM tareas_evidenciacierre WHERE tarea_id=%s",
                    (task_id,),
                )
                return any(bool(row[1] or row[2]) and bool(row[0]) for row in cursor.fetchall())
            finally:
                cursor.close()


def resolve_document_storage():
    try:
        context = resolve_operational_backend("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise TaskStorageError("No se pudo resolver BASE_TAREAS para Documentos/Evidencia.") from exc
    if context.backend_type == "DJANGO":
        return DjangoDocumentStorage(context.django_alias)
    if context.backend_type == "MYSQL_CONFIG":
        return MySQLDocumentStorage(
            context.mysql_connection,
            context.database_name,
        )
    raise TaskStorageError("El backend de BASE_TAREAS no es válido.")


def _document_validation_error(evidence):
    try:
        evidence.full_clean()
    except ValidationError:
        return True
    return False
