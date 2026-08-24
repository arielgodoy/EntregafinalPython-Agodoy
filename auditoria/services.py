from django.db import models
from decimal import Decimal
from datetime import datetime, date
import hashlib
import json
import logging
import os
import sqlite3
from pathlib import Path

from django.conf import settings

from .models import AuditoriaBibliotecaEvent, AuditoriaGestionDTEEvent, UserPresence, AuditArchiveBatch
from access_control.models import Vista

logger = logging.getLogger(__name__)


class AuditArchiveService:
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
