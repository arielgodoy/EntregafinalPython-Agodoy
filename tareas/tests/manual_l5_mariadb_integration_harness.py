"""Explicit, manually invoked L5 integration campaign against BASE_TAREAS.

Run with ``python -m tareas.tests.manual_l5_mariadb_integration_harness --execute``.
This module is not discovered by Django's automatic test runner.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
import hashlib
import json
import os
import re
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AppDocs.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, connections
from django.db.backends.signals import connection_created
from django.utils import timezone

from access_control.models import Empresa
from access_control.services.permissions import (
    get_valid_users_for_empresa,
    user_has_permission_for_empresa,
)
from auditoria.services import AuditIdempotencyStorageError, AuditoriaService
from settings.services import mysql_connections
from tareas.models import (
    LOGICAL_RESTORATION_RESULT_CODE,
    TareaEliminacionOperacion,
)
from tareas.services.assignment_storage import resolve_assignment_storage
from tareas.services.connection_roles import resolve_operational_backend
from tareas.services.deletion_ledger import (
    MySQLDeletionLedgerUnitOfWork,
    DeletionLedgerStateError,
)
from tareas.services.hierarchy_creation import create_child_task_atomic
from tareas.services.logical_deletion import logically_delete_task_tree
from tareas.services.logical_restoration import (
    LogicalRestorationError,
    _MySQLRestorationAdapter,
    build_logical_restoration_preview,
    reconcile_logical_restoration_audit,
    restore_logical_task_tree,
)
from tareas.services.task_storage import CreateTaskDraftInput


CAMPAIGN = "L5_INTEGRATION_20261020"
DATABASE_NAME = "tareas"
CONNECTION_NAME = "django_tareas"
COMPANY_CODE = "00"
SQL_USER = "admin_proyectos"
_DDL_OR_SCHEMA_STATEMENT = re.compile(
    r"^\s*(?:USE|CREATE|ALTER|DROP|TRUNCATE|RENAME|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
_QUALIFIED_TABLE = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO|DELETE\s+FROM)\s+"
    r"`?(?P<schema>[A-Za-z0-9_]+)`?\s*\.\s*`?[A-Za-z0-9_]+`?",
    re.IGNORECASE,
)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CampaignError(RuntimeError):
    pass


class DefaultDatabaseWriteBlocked(CampaignError):
    pass


@dataclass
class CampaignState:
    task_ids: list[int] = field(default_factory=list)
    document_ids: list[int] = field(default_factory=list)
    source_operation_ids: set[str] = field(default_factory=set)
    restoration_operation_ids: set[str] = field(default_factory=set)
    initial_correlativo: int | None = None
    results: dict[str, dict[str, object]] = field(default_factory=dict)
    connection_identities: list[tuple[str, str, str]] = field(default_factory=list)
    audit_event_count: int = 0
    default_write_attempts: int = 0


def _normalize_uuid(value) -> str:
    return value.hex if isinstance(value, UUID) else UUID(str(value)).hex


def _sql_guard(execute, sql, params, many, context):
    if _DDL_OR_SCHEMA_STATEMENT.match(sql):
        raise CampaignError("SQL DDL, USE y cambios de permisos están bloqueados.")
    for match in _QUALIFIED_TABLE.finditer(sql):
        if match.group("schema").casefold() not in {
            DATABASE_NAME,
            "information_schema",
        }:
            raise CampaignError("La sentencia SQL referencia otro esquema.")
    return execute(sql, params, many, context)


def _default_read_only_guard(execute, sql, params, many, context):
    if re.match(
        r"^\s*(?:INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|TRUNCATE|"
        r"RENAME|GRANT|REVOKE|VACUUM|ATTACH|DETACH)\b",
        sql,
        re.IGNORECASE,
    ):
        raise DefaultDatabaseWriteBlocked(
            "Las escrituras Django fuera de tareas están bloqueadas en esta campaña."
        )
    return execute(sql, params, many, context)


class InMemoryAudit:
    def __init__(self):
        self.events: dict[str, SimpleNamespace] = {}
        self.fail_once_for: set[str] = set()
        self.next_id = 990000
        self.next_deletion_id = 980000
        self.lock = threading.Lock()

    def log_deletion(self, **event_data):
        self.next_deletion_id += 1
        return SimpleNamespace(pk=self.next_deletion_id)

    def log_restoration(self, app_label, *, idempotency_key, **event_data):
        if app_label != "tareas":
            raise CampaignError("El mock solo admite auditoría de Tareas.")
        key = _normalize_uuid(idempotency_key)
        with self.lock:
            if key in self.fail_once_for:
                self.fail_once_for.remove(key)
                raise AuditIdempotencyStorageError("simulated post-commit audit outage")
            canonical = json.dumps(
                event_data,
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
            payload_hash = hashlib.sha256(canonical).hexdigest()
            existing = self.events.get(key)
            if existing is not None:
                if existing.idempotency_payload_hash != payload_hash:
                    raise CampaignError("Audit replay payload changed.")
                return SimpleNamespace(event=existing, created=False)
            self.next_id += 1
            user = event_data.get("user")
            event = SimpleNamespace(
                pk=self.next_id,
                id=self.next_id,
                idempotency_key=key,
                idempotency_payload_hash=payload_hash,
                user_id=getattr(user, "pk", None),
                before=None,
                after=None,
                **{
                    key_name: value
                    for key_name, value in event_data.items()
                    if key_name != "user"
                },
            )
            self.events[key] = event
            return SimpleNamespace(event=event, created=True)

    def get_restoration(self, app_label, idempotency_key):
        if app_label != "tareas":
            raise CampaignError("El mock solo admite auditoría de Tareas.")
        return self.events.get(_normalize_uuid(idempotency_key))


class L5MariaDBCampaign:
    def __init__(self):
        self.context = resolve_operational_backend("BASE_TAREAS")
        connection_config = self.context.mysql_connection
        if (
            self.context.logical_role != "BASE_TAREAS"
            or self.context.backend_type != "MYSQL_CONFIG"
            or connection_config is None
            or connection_config.nombre_logico != CONNECTION_NAME
            or connection_config.empresa.codigo != COMPANY_CODE
            or self.context.database_name != DATABASE_NAME
        ):
            raise CampaignError("BASE_TAREAS no coincide con el destino autorizado.")

        self.state = CampaignState()
        self.audit = InMemoryAudit()
        self.original_open = mysql_connections.open_mysql_connection
        self.guarded_open = self._make_guarded_open()
        self._original_system_ensure = None
        self._system_connection = None
        self._patch_connection_factories()
        self._install_connection_guards()
        self.company = Empresa.objects.get(codigo=COMPANY_CODE)
        self.actor, self.non_supervisor, self.e_only_user = self._select_actors()
        if self.company.pk < 1:
            raise CampaignError("Empresa Base 00 inválida.")
        self.assignment_storage = resolve_assignment_storage()

    def _make_guarded_open(self):
        original_open = self.original_open
        expected_connection = self.context.mysql_connection

        @contextmanager
        def guarded_open(connection_config, database_name=None):
            if (
                connection_config.pk != expected_connection.pk
                or connection_config.nombre_logico != CONNECTION_NAME
                or connection_config.empresa.codigo != COMPANY_CODE
                or database_name != DATABASE_NAME
            ):
                raise CampaignError("Una operación intentó usar otra conexión o base.")
            with original_open(
                connection_config,
                database_name=database_name,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT DATABASE(), VERSION(), CURRENT_USER()")
                    identity = cursor.fetchone()
                if (
                    not identity
                    or identity[0] != DATABASE_NAME
                    or not str(identity[1]).startswith("10.11.")
                    or "mariadb" not in str(identity[1]).casefold()
                    or str(identity[2]).split("@", 1)[0].casefold() != SQL_USER
                ):
                    raise CampaignError(
                        "Una conexión operacional no cumplió identidad/base/version."
                    )
                execute_wrappers = getattr(connection, "execute_wrappers", None)
                if execute_wrappers is None:
                    raise CampaignError(
                        "No se pudo instalar el guard SQL en la conexión operacional."
                    )
                if _sql_guard not in execute_wrappers:
                    execute_wrappers.append(_sql_guard)
                self.state.connection_identities.append(
                    (str(identity[0]), str(identity[1]), str(identity[2]))
                )
                try:
                    yield connection
                finally:
                    if _sql_guard in execute_wrappers:
                        execute_wrappers.remove(_sql_guard)

        return guarded_open

    def _patch_connection_factories(self):
        import importlib
        import sys

        mysql_connections.open_mysql_connection = self.guarded_open
        importlib.import_module("tareas.services.base_tareas_schema")
        importlib.import_module("tareas.services.assignment_storage")
        importlib.import_module("tareas.services.deletion_ledger")
        importlib.import_module("tareas.services.hierarchy_creation")
        for module in tuple(sys.modules.values()):
            if (
                module is not None
                and getattr(module, "open_mysql_connection", None)
                is self.original_open
            ):
                module.open_mysql_connection = self.guarded_open

    def _install_connection_guards(self):
        self._connection_created_receiver = self._on_connection_created
        connection_created.connect(
            self._connection_created_receiver,
            weak=False,
            dispatch_uid=f"l5-mariadb-campaign-{id(self)}",
        )
        default_connection = connections["default"]
        if _default_read_only_guard not in default_connection.execute_wrappers:
            default_connection.execute_wrappers.append(_default_read_only_guard)
        self._default_connection = default_connection
        if "DB_sistema" in connections:
            self._system_connection = connections["DB_sistema"]
            self._original_system_ensure = self._system_connection.ensure_connection

            def deny_system_connection():
                raise CampaignError("DB_sistema está bloqueada durante la campaña.")

            self._system_connection.ensure_connection = deny_system_connection

    def _restore_runtime_guards(self):
        connection_created.disconnect(
            self._connection_created_receiver,
            dispatch_uid=f"l5-mariadb-campaign-{id(self)}",
        )
        if _default_read_only_guard in self._default_connection.execute_wrappers:
            self._default_connection.execute_wrappers.remove(
                _default_read_only_guard
            )
        if self._system_connection is not None:
            self._system_connection.ensure_connection = self._original_system_ensure
        mysql_connections.open_mysql_connection = self.original_open
        import sys

        for module in tuple(sys.modules.values()):
            if (
                module is not None
                and getattr(module, "open_mysql_connection", None)
                is self.guarded_open
            ):
                module.open_mysql_connection = self.original_open

    def _on_connection_created(self, sender, connection, **kwargs):
        if connection.alias == "default":
            if _default_read_only_guard not in connection.execute_wrappers:
                connection.execute_wrappers.append(_default_read_only_guard)
            return
        if not connection.alias.startswith("mysql_runtime_"):
            raise CampaignError(
                f"Conexión Django inesperada durante la campaña: {connection.alias}."
            )
        config = connection.settings_dict
        if (
            config.get("NAME") != DATABASE_NAME
            or config.get("USER") != SQL_USER
            or config.get("ENGINE") != "django.db.backends.mysql"
        ):
            raise CampaignError("Alias MySQL dinámico fuera del destino autorizado.")
        if _sql_guard not in connection.execute_wrappers:
            connection.execute_wrappers.append(_sql_guard)

    def _select_actors(self):
        valid_users = get_valid_users_for_empresa(
            self.company,
            active_only=True,
        )
        supervisor = None
        non_supervisor = None
        e_only_user = None
        for candidate in valid_users.order_by("pk"):
            has_supervisor = user_has_permission_for_empresa(
                user=candidate,
                empresa=self.company,
                vista_nombre="Tareas",
                accion="supervisor",
            )
            has_delete = user_has_permission_for_empresa(
                user=candidate,
                empresa=self.company,
                vista_nombre="Tareas",
                accion="eliminar",
            )
            if has_supervisor and supervisor is None:
                supervisor = candidate
            elif not has_supervisor and non_supervisor is None:
                non_supervisor = candidate
            if has_delete and not has_supervisor:
                e_only_user = candidate
        if supervisor is None:
            raise CampaignError("No hay un actor activo con S explícito en Base 00.")
        return supervisor, non_supervisor, e_only_user

    def _identity_preflight(self):
        with self.guarded_open(
            self.context.mysql_connection,
            database_name=DATABASE_NAME,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM tareas_tarea WHERE titulo LIKE %s",
                    (f"{CAMPAIGN}%",),
                )
                campaign_tasks = int(cursor.fetchone()[0])
                if campaign_tasks:
                    raise CampaignError(
                        "Ya existen tareas con el prefijo de esta campaña."
                    )
                cursor.execute(
                    "SELECT siguiente_numero FROM tareas_correlativoempresa "
                    "WHERE empresa_id = %s",
                    (self.company.pk,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise CampaignError("Falta el correlativo de Empresa 00.")
                self.state.initial_correlativo = int(row[0])
                cursor.execute(
                    "SELECT engine FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_name IN (%s,%s,%s,%s,%s,%s)",
                    (
                        DATABASE_NAME,
                        "tareas_tarea",
                        "tareas_tarearelacion",
                        "tareas_tareareasignacion",
                        "tareas_documentotarea",
                        "tareas_eliminacion_operacion",
                        "tareas_eliminacion_elemento",
                    ),
                )
                engines = {str(row[0]).casefold() for row in cursor.fetchall()}
                if engines != {"innodb"}:
                    raise CampaignError("Hay tablas requeridas que no usan InnoDB.")

    def _create_task(self, label: str) -> int:
        created = self.assignment_storage.create(
            empresa_id=self.company.pk,
            creador_id=self.actor.pk,
            assignments=[
                {
                    "titulo": f"{CAMPAIGN}_{label}",
                    "descripcion": f"Synthetic L5 campaign {label}",
                    "prioridad": "MEDIA",
                    "responsable_id": self.actor.pk,
                    "fecha_comun": timezone.now(),
                    "motivo": CAMPAIGN,
                }
            ],
        )
        task_id = int(created[0].id)
        self.state.task_ids.append(task_id)
        return task_id

    def _create_child(self, label: str, parent_id: int) -> int:
        result = create_child_task_atomic(
            CreateTaskDraftInput(
                titulo=f"{CAMPAIGN}_{label}",
                descripcion=f"Synthetic L5 campaign {label}",
                prioridad="MEDIA",
                responsable_id=self.actor.pk,
                fecha_tope=timezone.localdate() + timedelta(days=30),
            ),
            active_company=self.company,
            actor=self.actor,
            parent_id=parent_id,
        )
        task_id = int(result.task.id)
        self.state.task_ids.append(task_id)
        return task_id

    def _insert_document(self, task_id: int, label: str) -> int:
        with self.guarded_open(
            self.context.mysql_connection,
            database_name=DATABASE_NAME,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "INSERT INTO tareas_documentotarea "
                    "(tarea_id,tipo,formato_archivo,archivo,url,fecha_documento,"
                    "fecha_vencimiento,usuario_id,estado) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        task_id,
                        "INFORME",
                        "PDF",
                        "",
                        f"https://example.invalid/{CAMPAIGN}_{label}.pdf",
                        timezone.localdate(),
                        None,
                        self.actor.pk,
                        "",
                    ),
                )
                document_id = int(cursor.lastrowid)
            finally:
                cursor.close()
        self.state.document_ids.append(document_id)
        return document_id

    def _delete_logically(self, root_id: int, label: str) -> UUID:
        operation_id = uuid4()
        self.state.source_operation_ids.add(operation_id.hex)
        from tareas.services.logical_deletion import logically_delete_task_tree

        result = logically_delete_task_tree(
            actor=self.actor,
            empresa_id=self.company.pk,
            root_task_id=root_id,
            motivo=f"{CAMPAIGN} deletion {label}",
            operation_id=operation_id,
        )
        if result.operation_id != operation_id:
            raise CampaignError("La eliminación no conservó su UUID de campaña.")
        return operation_id

    def _preview(self, operation_id: UUID, actor=None):
        return build_logical_restoration_preview(
            actor=actor or self.actor,
            empresa_id=self.company.pk,
            deletion_operation_id=operation_id,
        )

    def _restore(
        self,
        source_id: UUID,
        preview,
        *,
        restoration_id: UUID | None = None,
        reason: str | None = None,
        actor=None,
    ):
        restoration_id = restoration_id or uuid4()
        self.state.restoration_operation_ids.add(restoration_id.hex)
        return restore_logical_task_tree(
            actor=actor or self.actor,
            empresa_id=self.company.pk,
            deletion_operation_id=source_id,
            restoration_operation_id=restoration_id,
            motivo=reason or f"{CAMPAIGN} restoration",
            expected_fingerprint=preview.fingerprint,
        )

    def _read(self, sql: str, params=()):
        with self.guarded_open(
            self.context.mysql_connection,
            database_name=DATABASE_NAME,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(sql, params)
                return cursor.fetchall()
            finally:
                cursor.close()

    def _run_case(self, name: str, callback):
        try:
            detail = callback()
            pending_subcheck = isinstance(detail, dict) and any(
                isinstance(value, str) and value.startswith("PENDIENTE:")
                for value in detail.values()
            )
            self.state.results[name] = {
                "status": "PARCIAL" if pending_subcheck else "PASS",
                "evidence": detail if isinstance(detail, dict) else {},
            }
        except Exception as exc:
            self.state.results[name] = {
                "status": "FAIL",
                "error_type": type(exc).__name__,
                "error_code": getattr(exc, "code", None),
            }

    def _test_t01_individual(self):
        task_id = self._create_task("T01_SINGLE")
        original = self._read(
            "SELECT id,empresa_id,correlativo,titulo,descripcion,prioridad,"
            "estado,responsable_id,fecha_creacion,fecha_tope,fecha_cumplimiento "
            "FROM tareas_tarea WHERE id=%s",
            (task_id,),
        )[0]
        source_id = self._delete_logically(task_id, "T01")
        preview = self._preview(source_id)
        if preview.task_ids != (task_id,):
            raise CampaignError("El preview individual no contiene el ID exacto.")
        original_operation = self._read(
            "SELECT * FROM tareas_eliminacion_operacion WHERE operation_id=%s",
            (source_id.hex,),
        )[0]
        result = self._restore(source_id, preview, reason=f"{CAMPAIGN} T01")
        current = self._read(
            "SELECT id,empresa_id,correlativo,titulo,descripcion,prioridad,"
            "estado,responsable_id,fecha_creacion,fecha_tope,fecha_cumplimiento,"
            "eliminada,eliminada_en,eliminada_por_id,eliminacion_operacion_id "
            "FROM tareas_tarea WHERE id=%s",
            (task_id,),
        )[0]
        original_after = self._read(
            "SELECT * FROM tareas_eliminacion_operacion WHERE operation_id=%s",
            (source_id.hex,),
        )[0]
        restoration = self._read(
            "SELECT status,result_code,reverses_operation_id "
            "FROM tareas_eliminacion_operacion WHERE operation_id=%s",
            (result.operation_id.hex,),
        )[0]
        if (
            result.task_ids != (task_id,)
            or current[:11] != original
            or current[11:] != (0, None, None, None)
            or original_operation != original_after
            or restoration != ("COMMITTED", LOGICAL_RESTORATION_RESULT_CODE, source_id.hex)
        ):
            raise CampaignError("La restauración individual no conservó el contrato.")
        self.artifacts = getattr(self, "artifacts", {})
        self.artifacts["T01"] = (source_id, result.operation_id, preview)
        return {"task_id": task_id, "source_immutable": True, "restoration": restoration}

    def _test_t02_tree_and_document(self):
        root_id = self._create_task("T02_PARENT")
        child_id = self._create_child("T02_CHILD", root_id)
        grandchild_id = self._create_child("T02_GRANDCHILD", child_id)
        document_id = self._insert_document(child_id, "T02_DOCUMENT")
        source_id = self._delete_logically(root_id, "T02")
        preview = self._preview(source_id)
        expected_ids = tuple(sorted((root_id, child_id, grandchild_id)))
        if preview.task_ids != expected_ids or len(preview.documents) != 1:
            raise CampaignError("El preview no contiene el árbol/documento exactos.")
        doc_before = self._read(
            "SELECT id,tarea_id,tipo,formato_archivo,archivo,url,fecha_documento,"
            "fecha_vencimiento,usuario_id,estado "
            "FROM tareas_documentotarea WHERE id=%s",
            (document_id,),
        )[0]
        original_edges = tuple(
            self._read(
                "SELECT padre_id,hija_id FROM tareas_tarearelacion "
                "WHERE padre_id IN (%s,%s,%s) ORDER BY padre_id,hija_id",
                (root_id, child_id, grandchild_id),
            )
        )
        result = self._restore(source_id, preview, reason=f"{CAMPAIGN} T02")
        restored_ids = tuple(
            row[0]
            for row in self._read(
                "SELECT id FROM tareas_tarea WHERE id IN (%s,%s,%s) "
                "AND eliminada=0 ORDER BY id",
                (root_id, child_id, grandchild_id),
            )
        )
        edges_after = tuple(
            self._read(
                "SELECT padre_id,hija_id FROM tareas_tarearelacion "
                "WHERE padre_id IN (%s,%s,%s) ORDER BY padre_id,hija_id",
                (root_id, child_id, grandchild_id),
            )
        )
        doc_after = self._read(
            "SELECT id,tarea_id,tipo,formato_archivo,archivo,url,fecha_documento,"
            "fecha_vencimiento,usuario_id,estado "
            "FROM tareas_documentotarea WHERE id=%s",
            (document_id,),
        )[0]
        if (
            result.task_ids != expected_ids
            or restored_ids != expected_ids
            or edges_after != original_edges
            or doc_after != doc_before
        ):
            raise CampaignError("El árbol o los metadatos documentales cambiaron.")
        self.artifacts = getattr(self, "artifacts", {})
        self.artifacts["T02"] = (source_id, result.operation_id, preview)
        return {
            "task_ids": list(expected_ids),
            "edges": [list(row) for row in edges_after],
            "document_id_preserved": document_id,
        }

    def _test_t03_manifest_stale(self):
        task_id = self._create_task("T03_MANIFEST")
        source_id = self._delete_logically(task_id, "T03")
        preview = self._preview(source_id)
        rows = self._read(
            "SELECT id,object_id FROM tareas_eliminacion_elemento "
            "WHERE operacion_id=%s AND tipo='tareas.tarea'",
            (source_id.hex,),
        )
        if len(rows) != 1:
            raise CampaignError("No se encontró el manifiesto T03 esperado.")
        item_id, original_object_id = rows[0]
        replacement_id = int(original_object_id) + 100000000
        with self.guarded_open(
            self.context.mysql_connection,
            database_name=DATABASE_NAME,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "UPDATE tareas_eliminacion_elemento SET object_id=%s WHERE id=%s",
                    (replacement_id, item_id),
                )
                connection.commit()
            finally:
                cursor.close()
        try:
            try:
                self._restore(source_id, preview, reason=f"{CAMPAIGN} T03")
            except LogicalRestorationError:
                pass
            else:
                raise CampaignError("Se aceptó un manifiesto alterado.")
        finally:
            with self.guarded_open(
                self.context.mysql_connection,
                database_name=DATABASE_NAME,
            ) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        "UPDATE tareas_eliminacion_elemento SET object_id=%s WHERE id=%s",
                        (original_object_id, item_id),
                    )
                    connection.commit()
                finally:
                    cursor.close()
        marker = self._read(
            "SELECT eliminada,eliminacion_operacion_id FROM tareas_tarea WHERE id=%s",
            (task_id,),
        )[0]
        if marker != (1, source_id.hex):
            raise CampaignError("El rechazo del manifiesto dejó cambios parciales.")
        return {"tampered_manifest_rejected": True, "task_marker_unchanged": True}

    def _test_t04_atomicity(self):
        task_id = self._create_task("T04_ATOMICITY")
        source_id = self._delete_logically(task_id, "T04")
        preview = self._preview(source_id)
        restoration_id = uuid4()
        self.state.restoration_operation_ids.add(restoration_id.hex)
        from tareas.services.deletion_ledger import MySQLDeletionLedgerUnitOfWork

        with patch.object(
            MySQLDeletionLedgerUnitOfWork,
            "mark_logically_restored",
            side_effect=DeletionLedgerStateError("controlled failure before commit"),
        ):
            try:
                self._restore(
                    source_id,
                    preview,
                    restoration_id=restoration_id,
                    reason=f"{CAMPAIGN} T04",
                )
            except LogicalRestorationError:
                pass
            else:
                raise CampaignError("El fallo inyectado no abortó la restauración.")
        task_state = self._read(
            "SELECT eliminada,eliminada_en,eliminada_por_id,eliminacion_operacion_id "
            "FROM tareas_tarea WHERE id=%s",
            (task_id,),
        )[0]
        restoration_rows = self._read(
            "SELECT operation_id FROM tareas_eliminacion_operacion WHERE operation_id=%s",
            (restoration_id.hex,),
        )
        if task_state[0] != 1 or task_state[3] != source_id.hex or restoration_rows:
            raise CampaignError("El rollback de atomicidad dejó estado parcial.")
        return {"task_still_deleted": True, "pending_restore_rows": 0}

    def _test_t05_real_rollback(self):
        task_id = self._create_task("T05_ROLLBACK")
        before = self._read(
            "SELECT titulo FROM tareas_tarea WHERE id=%s",
            (task_id,),
        )[0][0]
        with self.guarded_open(
            self.context.mysql_connection,
            database_name=DATABASE_NAME,
        ) as first:
            first_cursor = first.cursor()
            try:
                first_cursor.execute("START TRANSACTION")
                first_cursor.execute(
                    "UPDATE tareas_tarea SET titulo=%s WHERE id=%s",
                    (f"{CAMPAIGN}_ROLLBACK_TEMP", task_id),
                )
                second_rows = self._read(
                    "SELECT titulo FROM tareas_tarea WHERE id=%s",
                    (task_id,),
                )
                if not second_rows or second_rows[0][0] != before:
                    raise CampaignError("Otra conexión observó una escritura sin commit.")
                first.rollback()
            except Exception:
                first.rollback()
                raise
            finally:
                first_cursor.close()
        after = self._read(
            "SELECT titulo FROM tareas_tarea WHERE id=%s",
            (task_id,),
        )[0][0]
        if after != before:
            raise CampaignError("El rollback real no revirtió el UPDATE.")
        return {"second_connection_saw_uncommitted_change": False, "value_after_rollback": after}

    def _test_t06_concurrency(self):
        task_id = self._create_task("T06_CONCURRENCY")
        source_id = self._delete_logically(task_id, "T06")
        preview = self._preview(source_id)
        restoration_ids = (uuid4(), uuid4())
        self.state.restoration_operation_ids.update(item.hex for item in restoration_ids)
        barrier = threading.Barrier(2)
        outcomes = []
        outcome_lock = threading.Lock()
        from tareas.services import logical_restoration

        original_preview_reader = logical_restoration._read_preview

        def synchronized_preview(**kwargs):
            value = original_preview_reader(**kwargs)
            barrier.wait(timeout=12)
            return value

        def attempt(operation_id):
            try:
                result = restore_logical_task_tree(
                    actor=self.actor,
                    empresa_id=self.company.pk,
                    deletion_operation_id=source_id,
                    restoration_operation_id=operation_id,
                    motivo=f"{CAMPAIGN} T06",
                    expected_fingerprint=preview.fingerprint,
                )
                value = ("committed", result.operation_id.hex)
            except LogicalRestorationError as exc:
                value = ("rejected", exc.code)
            except Exception as exc:
                value = ("unexpected", type(exc).__name__)
            with outcome_lock:
                outcomes.append(value)

        with patch.object(
            logical_restoration,
            "_read_preview",
            side_effect=synchronized_preview,
        ):
            threads = [
                threading.Thread(target=attempt, args=(operation_id,))
                for operation_id in restoration_ids
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=25)
        if any(thread.is_alive() for thread in threads):
            raise CampaignError("La carrera T06 excedió el timeout acotado.")
        committed = [item for item in outcomes if item[0] == "committed"]
        rejected = [item for item in outcomes if item[0] == "rejected"]
        if (
            len(committed) != 1
            or len(rejected) != 1
            or rejected[0][1]
            not in {
                "RESTORATION_ALREADY_COMPLETED",
                "RESTORATION_STATE_CONFLICT",
                "RESTORATION_PREVIEW_STALE",
            }
        ):
            raise CampaignError("La concurrencia no produjo un único ganador.")
        stored = self._read(
            "SELECT COUNT(*) FROM tareas_eliminacion_operacion "
            "WHERE reverses_operation_id=%s AND status='COMMITTED' "
            "AND result_code=%s",
            (source_id.hex, LOGICAL_RESTORATION_RESULT_CODE),
        )[0][0]
        if int(stored) != 1:
            raise CampaignError("El ledger no conserva exactamente un ganador.")
        self.artifacts = getattr(self, "artifacts", {})
        self.artifacts["T06"] = (source_id, preview)
        return {"outcomes": outcomes, "committed_restorations_for_source": int(stored)}

    def _test_t07_unique_index(self):
        source_id, restoration_id, _preview = self.artifacts["T01"]
        with self.guarded_open(
            self.context.mysql_connection,
            database_name=DATABASE_NAME,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT * FROM tareas_eliminacion_operacion WHERE operation_id=%s",
                    (restoration_id.hex,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise CampaignError("Falta la restauración confirmada T01.")
                column_names = [item[0] for item in cursor.description]
                values = list(row)
                values[column_names.index("operation_id")] = uuid4().hex
                columns_sql = ",".join(f"`{name}`" for name in column_names)
                placeholders = ",".join(["%s"] * len(column_names))
                try:
                    cursor.execute(
                        f"INSERT INTO tareas_eliminacion_operacion ({columns_sql}) "
                        f"VALUES ({placeholders})",
                        tuple(values),
                    )
                except IntegrityError as exc:
                    if not exc.args or int(exc.args[0]) != 1062:
                        raise
                    connection.rollback()
                else:
                    connection.rollback()
                    raise CampaignError("El índice permitió duplicar reverses_operation_id.")
            finally:
                cursor.close()
        duplicate_count = self._read(
            "SELECT COUNT(*) FROM tareas_eliminacion_operacion "
            "WHERE reverses_operation_id=%s",
            (source_id.hex,),
        )[0][0]
        if int(duplicate_count) != 1:
            raise CampaignError("El intento UNIQUE dejó una fila duplicada.")
        return {"duplicate_reverses_rejected": True, "rows_for_source": int(duplicate_count)}

    def _test_t08_idempotency(self):
        source_id, restoration_id, preview = self.artifacts["T01"]
        result = self._restore(
            source_id,
            preview,
            restoration_id=restoration_id,
            reason=f"{CAMPAIGN} T01",
        )
        if not result.replayed or result.operation_id != restoration_id:
            raise CampaignError("El replay idéntico no fue idempotente.")
        count = self._read(
            "SELECT COUNT(*) FROM tareas_eliminacion_operacion "
            "WHERE reverses_operation_id=%s",
            (source_id.hex,),
        )[0][0]
        if int(count) != 1:
            raise CampaignError("El replay duplicó el ledger de restauración.")
        return {"replayed": result.replayed, "restore_rows": int(count)}

    def _test_t09_uuid_reuse(self):
        source_id, restoration_id, preview = self.artifacts["T01"]
        try:
            self._restore(
                source_id,
                preview,
                restoration_id=restoration_id,
                reason=f"{CAMPAIGN} different payload",
            )
        except LogicalRestorationError:
            return {"different_payload_rejected": True}
        raise CampaignError("Se aceptó reutilizar un UUID con payload distinto.")

    def _lock_task(self, task_id: int, wait_seconds: float, release_holder: bool):
        holder_open = threading.Event()
        release = threading.Event()
        worker_started = threading.Event()
        worker_result = {}

        def holder():
            with self.guarded_open(
                self.context.mysql_connection,
                database_name=DATABASE_NAME,
            ) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute("START TRANSACTION")
                    cursor.execute(
                        "SELECT id FROM tareas_tarea WHERE id=%s FOR UPDATE",
                        (task_id,),
                    )
                    holder_open.set()
                    release.wait(timeout=12)
                    if release_holder:
                        connection.commit()
                    else:
                        connection.rollback()
                finally:
                    cursor.close()

        def worker():
            try:
                with self.guarded_open(
                    self.context.mysql_connection,
                    database_name=DATABASE_NAME,
                ) as connection:
                    cursor = connection.cursor()
                    try:
                        cursor.execute(
                            "SET SESSION innodb_lock_wait_timeout=%s",
                            (5 if release_holder else 1,),
                        )
                        cursor.execute("START TRANSACTION")
                        worker_started.set()
                        cursor.execute(
                            "SELECT id FROM tareas_tarea WHERE id=%s FOR UPDATE",
                            (task_id,),
                        )
                        worker_result["status"] = "acquired"
                        connection.rollback()
                    except Exception as exc:
                        worker_result["status"] = "error"
                        worker_result["error_code"] = (
                            int(exc.args[0])
                            if getattr(exc, "args", None)
                            and str(exc.args[0]).isdigit()
                            else None
                        )
                        connection.rollback()
                    finally:
                        cursor.close()
            except Exception as exc:
                worker_result["status"] = "unexpected"
                worker_result["error_type"] = type(exc).__name__

        holder_thread = threading.Thread(target=holder, daemon=True)
        holder_thread.start()
        if not holder_open.wait(timeout=8):
            release.set()
            raise CampaignError("La conexión A no obtuvo FOR UPDATE.")
        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()
        if not worker_started.wait(timeout=8):
            release.set()
            raise CampaignError("La conexión B no inició la consulta FOR UPDATE.")
        time.sleep(min(wait_seconds, 0.3) if not release_holder else wait_seconds)
        blocked = worker_thread.is_alive()
        if not release_holder:
            worker_thread.join(timeout=5)
        release.set()
        holder_thread.join(timeout=10)
        worker_thread.join(timeout=10)
        if holder_thread.is_alive() or worker_thread.is_alive():
            raise CampaignError("El escenario de locks excedió el timeout.")
        return blocked, worker_result

    def _test_t10_for_update(self):
        task_id = self._create_task("T10_LOCK")
        blocked, result = self._lock_task(task_id, 0.5, True)
        if not blocked or result.get("status") != "acquired":
            raise CampaignError("Las conexiones independientes no observaron el lock.")
        return {"blocked_until_release": blocked, "second_connection": result["status"]}

    def _test_t11_timeout(self):
        task_id = self._create_task("T11_TIMEOUT")
        blocked, result = self._lock_task(task_id, 1.5, False)
        if not blocked or result.get("status") != "error" or result.get("error_code") != 1205:
            raise CampaignError("No se reprodujo el timeout acotado de InnoDB.")
        return {"blocked_then_timed_out": blocked, "mysql_error_code": result["error_code"]}

    def _test_t12_company_isolation(self):
        task_id = self._create_task("T12_COMPANY")
        document_id = self._insert_document(task_id, "T12_FOREIGN_COMPANY_DOCUMENT")
        source_id = self._delete_logically(task_id, "T12")
        with self.guarded_open(
            self.context.mysql_connection,
            database_name=DATABASE_NAME,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "UPDATE tareas_tarea SET empresa_id=%s WHERE id=%s",
                    (self.company.pk + 9999, task_id),
                )
                connection.commit()
            finally:
                cursor.close()
        document_reads = []
        from tareas.services import logical_restoration

        original_documents = logical_restoration._MySQLRestorationAdapter.documents

        def tracked_documents(adapter, task_ids, *, lock):
            document_reads.append(tuple(task_ids))
            return original_documents(adapter, task_ids, lock=lock)

        try:
            with patch.object(
                logical_restoration._MySQLRestorationAdapter,
                "documents",
                tracked_documents,
            ):
                preview = self._preview(source_id)
            if preview.documents:
                raise CampaignError("El preview reveló documentos de otra empresa.")
        finally:
            with self.guarded_open(
                self.context.mysql_connection,
                database_name=DATABASE_NAME,
            ) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        "UPDATE tareas_tarea SET empresa_id=%s WHERE id=%s",
                        (self.company.pk, task_id),
                    )
                    connection.commit()
                finally:
                    cursor.close()
        if document_reads:
            raise CampaignError("Se consultaron documentos antes de validar empresa.")
        if not self._read(
            "SELECT id FROM tareas_documentotarea WHERE id=%s AND tarea_id=%s",
            (document_id, task_id),
        ):
            raise CampaignError("No se encontró el documento sintético de aislamiento.")
        return {"foreign_company_document_reads": 0, "metadata_exposed": False}

    def _test_t13_permissions(self):
        source_id, _restore_id, _preview = self.artifacts["T01"]
        results = {}
        if self.non_supervisor is None:
            raise CampaignError("No hay actor válido sin S para la prueba negativa.")
        opened_before = len(self.state.connection_identities)
        try:
            self._preview(source_id, actor=self.non_supervisor)
        except LogicalRestorationError as exc:
            results["without_supervisor"] = exc.code == "RESTORATION_UNAUTHORIZED"
        else:
            raise CampaignError("Un actor sin S obtuvo preview de restauración.")
        if len(self.state.connection_identities) != opened_before:
            raise CampaignError("La autorización negativa abrió conexión operacional.")

        elevated_copy = get_user_model().objects.get(pk=self.non_supervisor.pk)
        elevated_copy.is_staff = True
        elevated_copy.is_superuser = True
        try:
            self._preview(source_id, actor=elevated_copy)
        except LogicalRestorationError as exc:
            results["staff_superuser_no_bypass"] = exc.code == "RESTORATION_UNAUTHORIZED"
        else:
            raise CampaignError("Staff/superuser obtuvo bypass de S.")

        if self.e_only_user is None:
            results["delete_without_supervisor"] = "PENDIENTE: no existe actor E-solo en Base 00."
        else:
            try:
                self._preview(source_id, actor=self.e_only_user)
            except LogicalRestorationError as exc:
                results["delete_without_supervisor"] = exc.code == "RESTORATION_UNAUTHORIZED"
            else:
                raise CampaignError("El permiso E sustituyó a S.")
        if not all(
            value is True
            for key, value in results.items()
            if key != "delete_without_supervisor"
        ):
            raise CampaignError("Falló una comprobación de autorización ICMEAS.")
        return results

    def _test_t14_document_integrity(self):
        source_id, restoration_id, preview = self.artifacts["T02"]
        task_ids = preview.task_ids
        document_ids = tuple(
            item.document_id for item in preview.documents
        )
        before = [
            self._read(
                "SELECT id,tarea_id,tipo,formato_archivo,archivo,url,"
                "fecha_documento,fecha_vencimiento,usuario_id,estado "
                "FROM tareas_documentotarea WHERE id=%s",
                (document_id,),
            )[0]
            for document_id in document_ids
        ]
        result = self._restore(
            source_id,
            preview,
            restoration_id=restoration_id,
            reason=f"{CAMPAIGN} T02",
        )
        after = [
            self._read(
                "SELECT id,tarea_id,tipo,formato_archivo,archivo,url,"
                "fecha_documento,fecha_vencimiento,usuario_id,estado "
                "FROM tareas_documentotarea WHERE id=%s",
                (document_id,),
            )[0]
            for document_id in document_ids
        ]
        if result.task_ids != task_ids or before != after:
            raise CampaignError("La restauración modificó metadatos documentales.")
        return {"document_ids_unchanged": list(document_ids), "physical_files_touched": False}

    def _test_t15_audit(self):
        task_id = self._create_task("T15_AUDIT")
        source_id = self._delete_logically(task_id, "T15")
        preview = self._preview(source_id)
        restoration_id = uuid4()
        self.state.restoration_operation_ids.add(restoration_id.hex)
        self.audit.fail_once_for.add(restoration_id.hex)
        try:
            self._restore(
                source_id,
                preview,
                restoration_id=restoration_id,
                reason=f"{CAMPAIGN} T15",
            )
        except LogicalRestorationError as exc:
            if exc.code != "RESTORATION_AUDIT_PENDING":
                raise CampaignError("El error post-commit no fue audit-pending.")
        else:
            raise CampaignError("La falla simulada de auditoría no fue detectada.")
        committed = self._read(
            "SELECT status,result_code,audit_status FROM tareas_eliminacion_operacion "
            "WHERE operation_id=%s",
            (restoration_id.hex,),
        )
        if not committed or committed[0][0:2] != ("COMMITTED", LOGICAL_RESTORATION_RESULT_CODE):
            raise CampaignError("La falla central revirtió o alteró el commit operacional.")
        reconciled = reconcile_logical_restoration_audit(
            actor=self.actor,
            empresa_id=self.company.pk,
            restoration_operation_id=restoration_id,
        )
        final = self._read(
            "SELECT audit_status FROM tareas_eliminacion_operacion WHERE operation_id=%s",
            (restoration_id.hex,),
        )[0][0]
        if final != TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA:
            raise CampaignError("La auditoría simulada no se reconcilió.")
        return {
            "operational_commit_survived_audit_error": True,
            "reconciled_audit_status": final,
            "central_audit_mode": "in-memory double; no SQLite writes",
            "result_status": reconciled.status,
        }

    def _cleanup(self):
        if not self.state.task_ids and not self.state.source_operation_ids:
            return {"status": "nothing_to_clean", "deleted_tasks": 0}
        task_ids = tuple(sorted(set(self.state.task_ids)))
        source_ids = tuple(sorted(self.state.source_operation_ids))
        restore_ids = tuple(sorted(self.state.restoration_operation_ids))
        if not task_ids:
            task_marks = ""
            task_params = ()
        else:
            task_marks = ",".join(["%s"] * len(task_ids))
            task_params = task_ids
        operation_ids = tuple(sorted(set(source_ids + restore_ids)))
        operation_marks = ",".join(["%s"] * len(operation_ids)) if operation_ids else ""
        allowed_task_references = {
            ("tareas_documentotarea", "tarea_id"),
            ("tareas_tarealectura", "tarea_id"),
            ("tareas_tareaparticipante", "tarea_id"),
            ("tareas_tareareasignacion", "tarea_id"),
            ("tareas_tarearelacion", "padre_id"),
            ("tareas_tarearelacion", "hija_id"),
        }
        with self.guarded_open(
            self.context.mysql_connection,
            database_name=DATABASE_NAME,
        ) as connection:
            connection.set_autocommit(False)
            cursor = connection.cursor()
            try:
                cursor.execute(
                    f"SELECT id FROM tareas_tarea WHERE id IN ({task_marks}) "
                    "AND titulo LIKE %s",
                    (*task_params, f"{CAMPAIGN}%"),
                )
                found = {int(row[0]) for row in cursor.fetchall()}
                if found != set(task_ids):
                    raise CampaignError("Cleanup rechazado: IDs no pertenecen a la campaña.")

                if task_ids:
                    cursor.execute(
                        "SELECT TABLE_NAME,COLUMN_NAME "
                        "FROM information_schema.KEY_COLUMN_USAGE "
                        "WHERE TABLE_SCHEMA=%s AND REFERENCED_TABLE_SCHEMA=%s "
                        "AND REFERENCED_TABLE_NAME='tareas_tarea' "
                        "AND REFERENCED_COLUMN_NAME='id'",
                        (DATABASE_NAME, DATABASE_NAME),
                    )
                    references = cursor.fetchall()
                    unknown = []
                    for table_name, column_name in references:
                        if not _SAFE_IDENTIFIER.fullmatch(str(table_name)) or not _SAFE_IDENTIFIER.fullmatch(str(column_name)):
                            raise CampaignError("Metadata FK no segura para cleanup.")
                        cursor.execute(
                            f"SELECT COUNT(*) FROM `{table_name}` "
                            f"WHERE `{column_name}` IN ({task_marks})",
                            task_params,
                        )
                        count = int(cursor.fetchone()[0])
                        if count and (str(table_name), str(column_name)) not in allowed_task_references:
                            unknown.append((str(table_name), str(column_name), count))
                    if unknown:
                        raise CampaignError(
                            f"Cleanup detenido por dependencias no inventariadas: {unknown!r}"
                        )

                if self.state.document_ids:
                    document_marks = ",".join(["%s"] * len(self.state.document_ids))
                    cursor.execute(
                        f"DELETE FROM tareas_documentohistorial "
                        f"WHERE documento_id IN ({document_marks})",
                        tuple(self.state.document_ids),
                    )
                    cursor.execute(
                        f"DELETE FROM tareas_documentotarea WHERE id IN ({document_marks})",
                        tuple(self.state.document_ids),
                    )
                if task_ids:
                    cursor.execute(
                        f"DELETE FROM tareas_tarearelacion "
                        f"WHERE padre_id IN ({task_marks}) OR hija_id IN ({task_marks})",
                        task_params + task_params,
                    )
                    cursor.execute(
                        f"DELETE FROM tareas_tarealectura WHERE tarea_id IN ({task_marks})",
                        task_params,
                    )
                    cursor.execute(
                        f"DELETE FROM tareas_tareaparticipante WHERE tarea_id IN ({task_marks})",
                        task_params,
                    )
                    cursor.execute(
                        f"DELETE FROM tareas_tareareasignacion WHERE tarea_id IN ({task_marks})",
                        task_params,
                    )
                if operation_ids:
                    cursor.execute(
                        f"DELETE FROM tareas_eliminacion_archivo "
                        f"WHERE operacion_id IN ({operation_marks})",
                        operation_ids,
                    )
                    cursor.execute(
                        f"DELETE FROM tareas_eliminacion_elemento "
                        f"WHERE operacion_id IN ({operation_marks})",
                        operation_ids,
                    )
                if restore_ids:
                    marks = ",".join(["%s"] * len(restore_ids))
                    cursor.execute(
                        f"DELETE FROM tareas_eliminacion_operacion "
                        f"WHERE operation_id IN ({marks})",
                        restore_ids,
                    )
                if source_ids:
                    marks = ",".join(["%s"] * len(source_ids))
                    cursor.execute(
                        f"DELETE FROM tareas_eliminacion_operacion "
                        f"WHERE operation_id IN ({marks})",
                        source_ids,
                    )
                if task_ids:
                    cursor.execute(
                        f"DELETE FROM tareas_tarea WHERE id IN ({task_marks})",
                        task_params,
                    )

                counter_reset = False
                if self.state.initial_correlativo is not None:
                    cursor.execute(
                        "SELECT siguiente_numero FROM tareas_correlativoempresa "
                        "WHERE empresa_id=%s FOR UPDATE",
                        (self.company.pk,),
                    )
                    current = cursor.fetchone()
                    expected = self.state.initial_correlativo + len(task_ids)
                    if current is not None and int(current[0]) == expected:
                        cursor.execute(
                            "UPDATE tareas_correlativoempresa SET siguiente_numero=%s "
                            "WHERE empresa_id=%s",
                            (self.state.initial_correlativo, self.company.pk),
                        )
                        counter_reset = True
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
                connection.set_autocommit(True)

        remaining_tasks = self._read(
            "SELECT COUNT(*) FROM tareas_tarea WHERE titulo LIKE %s",
            (f"{CAMPAIGN}%",),
        )[0][0]
        if int(remaining_tasks) != 0:
            raise CampaignError("Quedaron tareas de campaña tras cleanup.")
        if operation_ids:
            remaining_operations = self._read(
                f"SELECT COUNT(*) FROM tareas_eliminacion_operacion "
                f"WHERE operation_id IN ({operation_marks})",
                operation_ids,
            )[0][0]
            if int(remaining_operations) != 0:
                raise CampaignError("Quedaron operaciones de campaña tras cleanup.")
        return {
            "status": "completed",
            "deleted_tasks": len(task_ids),
            "deleted_documents": len(self.state.document_ids),
            "deleted_operations": len(operation_ids),
            "correlativo_reset": counter_reset,
        }

    def run(self):
        cleanup = {"status": "not_started"}
        try:
            self._identity_preflight()
            from tareas.services.base_tareas_schema import preview_logical_restoration_schema

            schema = preview_logical_restoration_schema()
            if schema["status"] != "CURRENT" or schema["missing"]:
                raise CampaignError("El preflight L5 dejó de estar CURRENT.")
            from tareas.services import logical_deletion

            with ExitStack() as stack:
                stack.enter_context(
                    patch.object(
                        logical_deletion,
                        "log_logical_deletion_operation",
                        side_effect=self.audit.log_deletion,
                    )
                )
                stack.enter_context(
                    patch.object(
                        AuditoriaService,
                        "log_event_idempotent",
                        side_effect=self.audit.log_restoration,
                    )
                )
                stack.enter_context(
                    patch.object(
                        AuditoriaService,
                        "get_event_by_idempotency_key",
                        side_effect=self.audit.get_restoration,
                    )
                )
                self._run_case("T01", self._test_t01_individual)
                self._run_case("T02", self._test_t02_tree_and_document)
                self._run_case("T03", self._test_t03_manifest_stale)
                self._run_case("T04", self._test_t04_atomicity)
                self._run_case("T05", self._test_t05_real_rollback)
                self._run_case("T06", self._test_t06_concurrency)
                self._run_case("T07", self._test_t07_unique_index)
                self._run_case("T08", self._test_t08_idempotency)
                self._run_case("T09", self._test_t09_uuid_reuse)
                self._run_case("T10", self._test_t10_for_update)
                self._run_case("T11", self._test_t11_timeout)
                self._run_case("T12", self._test_t12_company_isolation)
                self._run_case("T13", self._test_t13_permissions)
                self._run_case("T14", self._test_t14_document_integrity)
                self._run_case("T15", self._test_t15_audit)
                self.state.results["T16"] = {
                    "status": "PENDIENTE",
                    "evidence": "No se interrumpieron conexiones; requiere un fault injector controlado de commit.",
                }
        finally:
            try:
                cleanup = self._cleanup()
                self.state.results["CLEANUP"] = cleanup
            finally:
                self._restore_runtime_guards()

        return {
            "connection": CONNECTION_NAME,
            "database": DATABASE_NAME,
            "company": COMPANY_CODE,
            "server": "MariaDB 10.11.x",
            "sql_user": SQL_USER,
            "campaign": CAMPAIGN,
            "connections_verified": len(self.state.connection_identities),
            "connection_identities": sorted(set(self.state.connection_identities)),
            "actor_id": self.actor.pk,
            "non_supervisor_actor_id": (
                self.non_supervisor.pk if self.non_supervisor is not None else None
            ),
            "e_only_actor_available": self.e_only_user is not None,
            "central_audit": "in-memory double; SQLite real database is read-only",
            "tests": self.state.results,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run the explicitly authorized real-data campaign against tareas.",
    )
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("Pass --execute to start the MariaDB test-data campaign.")

    campaign = L5MariaDBCampaign()
    results = campaign.run()
    print(json.dumps(results, sort_keys=True, ensure_ascii=True, default=str))
    if any(
        item.get("status") == "FAIL"
        for name, item in results["tests"].items()
        if name != "CLEANUP"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
