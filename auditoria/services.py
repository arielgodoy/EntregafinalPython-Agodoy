from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, date
import hashlib
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import DatabaseError, models, router

from .models import (
    AuditoriaBibliotecaEvent,
    AuditoriaGestionDTEEvent,
    AuditoriaTareasEvent,
    UserPresence,
    AuditArchiveBatch,
)
from access_control.models import Vista

logger = logging.getLogger(__name__)


class AuditIdempotencyError(RuntimeError):
    """Base error for idempotent audit writes and lookups."""


class AuditIdempotencyInputError(AuditIdempotencyError):
    pass


class AuditIdempotencyConflict(AuditIdempotencyError):
    pass


class AuditIdempotencyStorageError(AuditIdempotencyError):
    pass


@dataclass(frozen=True)
class IdempotentAuditResult:
    event: AuditoriaTareasEvent
    created: bool


def _normalize_audit_idempotency_key(value):
    if isinstance(value, UUID):
        return value.hex
    try:
        return UUID(str(value)).hex
    except (ValueError, TypeError, AttributeError) as exc:
        raise AuditIdempotencyInputError(
            "La clave idempotente debe ser un UUID válido."
        ) from exc


def _canonical_audit_value(value):
    if isinstance(value, models.Model):
        if value.pk is None:
            raise AuditIdempotencyInputError(
                "El payload idempotente contiene un modelo sin persistir."
            )
        return {
            "__model__": value._meta.label_lower,
            "pk": str(value.pk),
        }
    if isinstance(value, dict):
        canonical = {}
        for key, item in value.items():
            normalized_key = str(key)
            if normalized_key in canonical:
                raise AuditIdempotencyInputError(
                    "El payload idempotente contiene claves JSON ambiguas."
                )
            canonical[normalized_key] = _canonical_audit_value(item)
        return canonical
    if isinstance(value, (list, tuple)):
        return [_canonical_audit_value(item) for item in value]
    if isinstance(value, set):
        raise AuditIdempotencyInputError(
            "El payload idempotente no admite conjuntos."
        )
    return value


def _audit_payload_hash(app_label, event_data):
    try:
        canonical_payload = json.dumps(
            {
                "app_label": app_label,
                "event_data": _canonical_audit_value(event_data),
                "format_version": 1,
            },
            cls=DjangoJSONEncoder,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AuditIdempotencyInputError(
            "El payload idempotente no se puede normalizar."
        ) from exc
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def _is_retryable_idempotency_lock_error(error):
    seen = set()
    current = error
    retryable_codes = {5, 6, 1205, 1213, "40001", "40P01", "55P03"}
    retryable_messages = (
        "database is locked",
        "database table is locked",
        "database schema is locked",
    )
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = (
            getattr(current, "sqlstate", None)
            or getattr(current, "pgcode", None)
            or getattr(current, "errno", None)
        )
        args = getattr(current, "args", ())
        if code in retryable_codes or (args and args[0] in retryable_codes):
            return True
        message = str(current).casefold()
        if any(text in message for text in retryable_messages):
            return True
        current = current.__cause__ or current.__context__
    return False


class _LegacyAuditArchiveService:
    """Copia segura de auditoría a SQLite histórico sin borrar el origen."""

    @staticmethod
    def get_history_db_path(app_label):
        root = Path(getattr(settings, 'AUDIT_ARCHIVE_ROOT', Path(settings.BASE_DIR) / 'audit_archive'))
        root.mkdir(parents=True, exist_ok=True)
        return str(root / f'{app_label}_history.sqlite3')

    @staticmethod
    def _sha256_text(value):
        return hashlib.sha256((value or '').encode('utf-8')).hexdigest()

    @staticmethod
    def _iter_source_rows(app_label, cutoff_datetime, max_source_id=None, company_ids=None):
        model = AuditoriaService.APP_MODEL_MAP.get(app_label)
        if model is None:
            return []

        queryset = model.objects.all().order_by('id')
        if cutoff_datetime is not None:
            queryset = queryset.filter(created_at__lte=cutoff_datetime)
        if max_source_id is not None:
            queryset = queryset.filter(id__lte=max_source_id)
        if company_ids:
            queryset = queryset.filter(empresa_id__in=company_ids)
        return list(queryset)

    @staticmethod
    def _ensure_history_schema(path):
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_event_history (
                    id INTEGER PRIMARY KEY,
                    source_event_id INTEGER NOT NULL,
                    batch_id TEXT NOT NULL,
                    app_label TEXT NOT NULL,
                    empresa_id INTEGER,
                    user_id INTEGER,
                    action TEXT,
                    object_type TEXT,
                    object_id TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    method TEXT,
                    path TEXT,
                    querystring TEXT,
                    status_code INTEGER,
                    duration_ms INTEGER,
                    vista_nombre TEXT,
                    message_key TEXT,
                    meta TEXT,
                    before TEXT,
                    after TEXT,
                    created_at TEXT,
                    source_checksum TEXT,
                    archive_checksum TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def run_batch(app_label, cutoff_datetime, max_source_id=None, company_ids=None, batch_id=None):
        if not app_label:
            raise ValueError('app_label is required')

        normalized_ids = list(company_ids or [])
        resolved_batch_id = batch_id or f"{app_label}-{cutoff_datetime.isoformat()}-{max_source_id or 0}-{','.join(map(str, normalized_ids))}"

        existing = AuditArchiveBatch.objects.filter(batch_id=resolved_batch_id).first()
        if existing:
            return existing

        existing_window = AuditArchiveBatch.objects.filter(
            app_label=app_label,
            cutoff_datetime=cutoff_datetime,
            source_max_id=max_source_id,
            company_ids=normalized_ids,
            status='completed',
        ).order_by('-created_at').first()
        if existing_window:
            return existing_window

        source_rows = AuditArchiveService._iter_source_rows(app_label, cutoff_datetime, max_source_id, normalized_ids)
        archive_path = AuditArchiveService.get_history_db_path(app_label)
        batch = AuditArchiveBatch.objects.create(
            batch_id=resolved_batch_id,
            app_label=app_label,
            cutoff_datetime=cutoff_datetime,
            source_min_id=min((row.id for row in source_rows), default=None),
            source_max_id=max_source_id,
            company_ids=normalized_ids,
            status='pending',
            archive_path=archive_path,
        )

        try:
            AuditArchiveService._ensure_history_schema(archive_path)
            conn = sqlite3.connect(archive_path)
            try:
                source_payload = []
                for row in source_rows:
                    payload = {
                        'source_event_id': row.id,
                        'batch_id': resolved_batch_id,
                        'app_label': app_label,
                        'empresa_id': row.empresa_id,
                        'user_id': row.user_id,
                        'action': row.action,
                        'object_type': row.object_type,
                        'object_id': row.object_id,
                        'ip_address': row.ip_address,
                        'user_agent': row.user_agent,
                        'method': row.method,
                        'path': row.path,
                        'querystring': row.querystring,
                        'status_code': row.status_code,
                        'duration_ms': row.duration_ms,
                        'vista_nombre': row.vista_nombre,
                        'message_key': row.message_key,
                        'meta': json.dumps(row.meta, default=str) if row.meta is not None else None,
                        'before': json.dumps(row.before, default=str) if row.before is not None else None,
                        'after': json.dumps(row.after, default=str) if row.after is not None else None,
                        'created_at': row.created_at.isoformat() if row.created_at else None,
                    }
                    source_payload.append(payload)

                rows_to_insert = [
                    (
                        item['source_event_id'], item['batch_id'], item['app_label'], item['empresa_id'], item['user_id'],
                        item['action'], item['object_type'], item['object_id'], item['ip_address'], item['user_agent'],
                        item['method'], item['path'], item['querystring'], item['status_code'], item['duration_ms'],
                        item['vista_nombre'], item['message_key'], item['meta'], item['before'], item['after'], item['created_at']
                    )
                    for item in source_payload
                ]
                if rows_to_insert:
                    conn.executemany(
                        """
                        INSERT INTO audit_event_history (
                            source_event_id, batch_id, app_label, empresa_id, user_id, action, object_type, object_id,
                            ip_address, user_agent, method, path, querystring, status_code, duration_ms, vista_nombre,
                            message_key, meta, before, after, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows_to_insert,
                    )
                conn.commit()
                source_checksum = AuditArchiveService._sha256_text(json.dumps([{
                    'source_event_id': row.id,
                    'created_at': row.created_at.isoformat() if row.created_at else None,
                    'empresa_id': row.empresa_id,
                    'action': row.action,
                } for row in source_rows], default=str, sort_keys=True))
                archive_checksum = hashlib.sha256(Path(archive_path).read_bytes()).hexdigest() if os.path.exists(archive_path) else ''

                conn.execute(
                    "UPDATE audit_event_history SET source_checksum = ?, archive_checksum = ? WHERE batch_id = ?",
                    (source_checksum, archive_checksum, resolved_batch_id),
                )
                conn.commit()

                manifest = {
                    'app_label': app_label,
                    'cutoff_datetime': cutoff_datetime.isoformat() if cutoff_datetime else None,
                    'max_source_id': max_source_id,
                    'company_ids': normalized_ids,
                    'file': archive_path,
                    'row_count': len(source_rows),
                    'schema': 'audit_event_history_v1',
                    'source_checksum': source_checksum,
                    'archive_checksum': archive_checksum,
                }
                manifest_path = f'{archive_path}.manifest.json'
                with open(manifest_path, 'w', encoding='utf-8') as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)

                batch.status = 'completed'
                batch.archive_count = len(source_rows)
                batch.source_checksum = source_checksum
                batch.archive_checksum = archive_checksum
                batch.manifest = manifest
                batch.save(update_fields=['status', 'archive_count', 'source_checksum', 'archive_checksum', 'manifest', 'updated_at'])
                return batch
            finally:
                conn.close()
        except Exception as exc:
            batch.status = 'failed'
            batch.error_message = str(exc)
            batch.save(update_fields=['status', 'error_message', 'updated_at'])
            raise

    @staticmethod
    def read_archived_rows(batch):
        archive_path = batch.archive_path or AuditArchiveService.get_history_db_path(batch.app_label)
        if not os.path.exists(archive_path):
            return []
        conn = sqlite3.connect(archive_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM audit_event_history WHERE batch_id = ? ORDER BY source_event_id ASC",
                (batch.batch_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


class AuditoriaService:
    """
    Servicio centralizado para logging de auditoría.
    Decide en qué tabla escribir según app_label.
    """

    APP_MODEL_MAP = {
        'biblioteca': AuditoriaBibliotecaEvent,
        'gestiondte': AuditoriaGestionDTEEvent,
        'tareas': AuditoriaTareasEvent,
    }

    @classmethod
    def update_user_presence(cls, request, app_label, vista_nombre=None):
        if not getattr(request.user, 'is_authenticated', False):
            return None
        try:
            if not vista_nombre:
                resolver_match = getattr(request, 'resolver_match', None)
                route_name = getattr(resolver_match, 'view_name', None)
                if route_name:
                    vista_nombre = Vista.objects.filter(route_name=route_name).values_list('nombre', flat=True).first()
                if not vista_nombre:
                    vista_nombre = getattr(resolver_match, 'url_name', None)
            return UserPresence.objects.update_or_create(
                user=request.user,
                defaults={
                    'empresa_id': request.session.get('empresa_id'),
                    'app_label': app_label,
                    'vista_nombre': vista_nombre,
                    'path': request.path,
                },
            )[0]
        except Exception:
            logger.exception('No se pudo actualizar UserPresence user=%s app=%s', request.user.pk, app_label)
            return None

    @classmethod
    def diff_snapshots(cls, before, after):
        """
        Calcula diferencias entre snapshots dict.
        Retorna dict: {campo: {'from': old, 'to': new}}

        - before None + after dict => todos los campos son nuevos (from=None)
        - after None + before dict => todos los campos eliminados (to=None)
        - ambos dict => comparar normal
        - ambos None => {}
        """
        if before is None and after is None:
            return {}

        before = before or {}
        after = after or {}

        changes = {}
        keys = set(before.keys()) | set(after.keys())

        for k in keys:
            old = before.get(k, None)
            new = after.get(k, None)
            if old != new:
                changes[k] = {'from': old, 'to': new}

        return changes

    @classmethod
    def log_event(cls, app_label, **event_data):
        """
        Registra un evento de auditoría en la tabla correspondiente.
        """
        model_class = cls.APP_MODEL_MAP.get(app_label)
        if not model_class:
            return None
        try:
            event_data = cls._sanitize_data(event_data)
            return model_class.objects.create(**event_data)
        except Exception:
            logger.exception("No se pudo persistir el evento de auditoría app=%s", app_label)
            return None

    @classmethod
    def log_event_idempotent(
        cls,
        app_label,
        *,
        idempotency_key,
        **event_data,
    ):
        """Create or replay one Tareas audit event using a unique operation UUID."""
        model_class = cls.APP_MODEL_MAP.get(app_label)
        if app_label != "tareas" or model_class is not AuditoriaTareasEvent:
            raise AuditIdempotencyInputError(
                "La escritura idempotente solo está habilitada para auditoría de Tareas."
            )
        if {"idempotency_key", "idempotency_payload_hash"}.intersection(event_data):
            raise AuditIdempotencyInputError(
                "Los campos idempotentes son reservados por el servicio."
            )

        normalized_key = _normalize_audit_idempotency_key(idempotency_key)
        sanitized_data = cls._sanitize_data(dict(event_data))
        payload_hash = _audit_payload_hash(app_label, sanitized_data)
        manager = model_class._default_manager.db_manager(
            router.db_for_write(model_class)
        )
        for attempt in range(3):
            try:
                event, created = manager.get_or_create(
                    idempotency_key=normalized_key,
                    defaults={
                        **sanitized_data,
                        "idempotency_payload_hash": payload_hash,
                    },
                )
                break
            except DatabaseError as exc:
                if attempt < 2 and _is_retryable_idempotency_lock_error(exc):
                    time.sleep(0.02 * (attempt + 1))
                    continue
                raise AuditIdempotencyStorageError(
                    "No se pudo confirmar la escritura idempotente; el resultado "
                    "puede ser ambiguo. Reintente únicamente con la misma clave."
                ) from exc

        if event.idempotency_payload_hash != payload_hash:
            raise AuditIdempotencyConflict(
                "La clave idempotente ya está asociada a un payload diferente."
            )
        return IdempotentAuditResult(event=event, created=created)

    @classmethod
    def get_event_by_idempotency_key(cls, app_label, idempotency_key):
        """Read one Tareas audit event by its stable UUID key from the write DB."""
        model_class = cls.APP_MODEL_MAP.get(app_label)
        if app_label != "tareas" or model_class is not AuditoriaTareasEvent:
            raise AuditIdempotencyInputError(
                "La consulta idempotente solo está habilitada para auditoría de Tareas."
            )

        normalized_key = _normalize_audit_idempotency_key(idempotency_key)
        manager = model_class._default_manager.db_manager(
            router.db_for_write(model_class)
        )
        try:
            return manager.filter(idempotency_key=normalized_key).first()
        except DatabaseError as exc:
            raise AuditIdempotencyStorageError(
                "No se pudo consultar la auditoría central por clave idempotente."
            ) from exc

    @classmethod
    def _sanitize_data(cls, data):
        """
        Elimina datos sensibles de meta, before, after.
        """
        sensitive_keys = ['password', 'token', 'secret', 'api_key', 'csrfmiddlewaretoken']

        for field in ['meta', 'before', 'after']:
            if field in data and isinstance(data[field], dict):
                data[field] = {
                    k: v for k, v in data[field].items()
                    if k.lower() not in sensitive_keys
                }

        return data

    @classmethod
    def model_to_snapshot(cls, obj, max_string_length=1000):
        """
        Serializa un objeto Django Model a dict sanitizado para auditoría.
        """
        if obj is None:
            return None

        snapshot = {}
        sensitive_keys = ['password', 'token', 'secret', 'api_key', 'csrf']

        for field in obj._meta.get_fields():
            field_name = getattr(field, 'name', None)
            if not field_name:
                continue

            if any(sensitive in field_name.lower() for sensitive in sensitive_keys):
                continue

            if getattr(field, 'auto_created', False) or getattr(field, 'many_to_many', False):
                continue

            try:
                value = getattr(obj, field_name, None)

                if isinstance(field, models.FileField):
                    snapshot[field_name] = value.name if value else None

                elif isinstance(field, models.ForeignKey):
                    snapshot[field_name + '_id'] = value.pk if value else None

                elif isinstance(value, (datetime, date)):
                    snapshot[field_name] = value.isoformat()

                elif isinstance(value, Decimal):
                    snapshot[field_name] = str(value)

                elif isinstance(value, str) and len(value) > max_string_length:
                    snapshot[field_name] = value[:max_string_length] + '...[truncado]'

                else:
                    snapshot[field_name] = value

            except Exception:
                continue

        return snapshot


from .archive_service import AuditArchiveService
