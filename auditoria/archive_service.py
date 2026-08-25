from datetime import date, datetime
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import AuditArchiveBatch, AuditoriaBibliotecaEvent, AuditoriaGestionDTEEvent
from .permissions import get_archivable_company_ids


class AuditArchiveService:
    ALLOWED_APPS = {
        'biblioteca': AuditoriaBibliotecaEvent,
        'gestiondte': AuditoriaGestionDTEEvent,
    }
    ARCHIVE_SCHEMA_VERSION = 'audit_event_history_v2'
    CHECKSUM_ALGORITHM = 'SHA-256'
    EVENT_COLUMNS = (
        'source_event_id', 'app_label', 'empresa_id', 'user_id', 'action',
        'object_type', 'object_id', 'ip_address', 'user_agent', 'method',
        'path', 'querystring', 'status_code', 'duration_ms', 'vista_nombre',
        'message_key', 'meta', 'before', 'after', 'created_at',
    )

    @classmethod
    def _model_for_app(cls, app_label):
        try:
            return cls.ALLOWED_APPS[app_label]
        except KeyError:
            raise ValueError('app_label no permitido') from None

    @staticmethod
    def get_history_db_path(app_label):
        if app_label not in AuditArchiveService.ALLOWED_APPS:
            raise ValueError('app_label no permitido')
        root = Path(getattr(settings, 'AUDIT_ARCHIVE_ROOT', Path(settings.BASE_DIR) / 'audit_archive'))
        root.mkdir(parents=True, exist_ok=True)
        return str(root / f'{app_label}_history.sqlite3')

    @staticmethod
    def canonicalize(value):
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            return value
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): AuditArchiveService.canonicalize(value[key]) for key in sorted(value, key=str)}
        if isinstance(value, (list, tuple)):
            return [AuditArchiveService.canonicalize(item) for item in value]
        return str(value)

    @classmethod
    def canonical_json(cls, value):
        return json.dumps(cls.canonicalize(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False)

    @classmethod
    def checksum(cls, events):
        payload = [cls.canonicalize(event) for event in events]
        return hashlib.sha256(cls.canonical_json(payload).encode('utf-8')).hexdigest()

    @classmethod
    def _event_payload(cls, row, app_label):
        return {
            'source_event_id': row.id,
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
            'meta': row.meta,
            'before': row.before,
            'after': row.after,
            'created_at': row.created_at,
        }

    @classmethod
    def _archive_payload(cls, row):
        payload = dict(row)
        for field in ('meta', 'before', 'after'):
            if payload[field] is not None:
                payload[field] = json.loads(payload[field])
        return {field: payload.get(field) for field in cls.EVENT_COLUMNS}

    @classmethod
    def _selected_rows(cls, app_label, cutoff_datetime, max_source_id, company_ids):
        queryset = cls._model_for_app(app_label).objects.filter(
            created_at__lte=cutoff_datetime,
            id__lte=max_source_id,
            empresa_id__in=company_ids,
        ).order_by('id')
        return list(queryset)

    @classmethod
    def preview_snapshot(cls, app_label, cutoff_datetime, requested_company_ids, user, vista_nombre):
        cls._model_for_app(app_label)
        company_ids = cls._validate_request(user, vista_nombre, requested_company_ids)
        max_source_id = cls._model_for_app(app_label).objects.order_by('-id').values_list('id', flat=True).first() or 0
        rows = cls._selected_rows(app_label, cutoff_datetime, max_source_id, company_ids)
        return {
            'app_label': app_label,
            'company_ids': company_ids,
            'cutoff_datetime': cutoff_datetime,
            'max_source_id': max_source_id,
            'source_count': len(rows),
            'first_source_id': rows[0].id if rows else None,
            'last_source_id': rows[-1].id if rows else None,
            'first_event_at': rows[0].created_at if rows else None,
            'last_event_at': rows[-1].created_at if rows else None,
        }

    @classmethod
    def _ensure_history_schema(cls, path):
        conn = sqlite3.connect(path)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS archive_batches (
                    batch_id TEXT PRIMARY KEY,
                    source_app TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    cutoff_datetime TEXT NOT NULL,
                    max_source_id INTEGER NOT NULL,
                    company_ids_json TEXT NOT NULL,
                    source_count INTEGER NOT NULL,
                    archive_count INTEGER NOT NULL,
                    checksum_algorithm TEXT NOT NULL,
                    source_checksum TEXT NOT NULL,
                    archive_checksum TEXT NOT NULL,
                    validated_at TEXT,
                    status TEXT NOT NULL,
                    manifest_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_event_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_event_id INTEGER NOT NULL UNIQUE,
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
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_history_batch_idx
                    ON audit_event_history(batch_id, source_event_id);
                """
            )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def _write_archive_batch(cls, batch):
        path = cls.get_history_db_path(batch.app_label)
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                """
                INSERT INTO archive_batches (
                    batch_id, source_app, created_at, cutoff_datetime, max_source_id,
                    company_ids_json, source_count, archive_count, checksum_algorithm,
                    source_checksum, archive_checksum, validated_at, status, manifest_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(batch_id) DO UPDATE SET
                    source_count=excluded.source_count,
                    archive_count=excluded.archive_count,
                    checksum_algorithm=excluded.checksum_algorithm,
                    source_checksum=excluded.source_checksum,
                    archive_checksum=excluded.archive_checksum,
                    validated_at=excluded.validated_at,
                    status=excluded.status,
                    manifest_json=excluded.manifest_json
                """,
                (
                    batch.batch_id,
                    batch.app_label,
                    batch.created_at.isoformat(),
                    batch.cutoff_datetime.isoformat(),
                    batch.source_max_id,
                    cls.canonical_json(batch.company_ids),
                    batch.source_count,
                    batch.archive_count,
                    batch.checksum_algorithm,
                    batch.source_checksum,
                    batch.archive_checksum,
                    batch.validated_at.isoformat() if batch.validated_at else None,
                    batch.status,
                    cls.canonical_json(batch.manifest),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def _insert_event(cls, conn, payload, batch_id):
        conn.execute(
            """
            INSERT INTO audit_event_history (
                source_event_id, batch_id, app_label, empresa_id, user_id, action,
                object_type, object_id, ip_address, user_agent, method, path,
                querystring, status_code, duration_ms, vista_nombre, message_key,
                meta, before, after, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload['source_event_id'], batch_id, payload['app_label'], payload['empresa_id'],
                payload['user_id'], payload['action'], payload['object_type'], payload['object_id'],
                payload['ip_address'], payload['user_agent'], payload['method'], payload['path'],
                payload['querystring'], payload['status_code'], payload['duration_ms'],
                payload['vista_nombre'], payload['message_key'],
                *(json.dumps(payload[field], sort_keys=True, separators=(',', ':'), ensure_ascii=False) if payload[field] is not None else None for field in ('meta', 'before', 'after')),
                payload['created_at'].isoformat() if payload['created_at'] else None,
            ),
        )

    @classmethod
    def _validate_request(cls, user, vista_nombre, requested_company_ids):
        requested = {int(company_id) for company_id in (requested_company_ids or [])}
        if not requested:
            raise ValueError('requested_company_ids no puede estar vacío')
        if user is None or not vista_nombre:
            raise ValueError('user y vista_nombre son obligatorios')
        authorized = set(get_archivable_company_ids(user, vista_nombre))
        if not requested.issubset(authorized):
            raise PermissionError('requested_company_ids contiene empresas no autorizadas')
        return sorted(requested)

    @classmethod
    def run_batch(cls, app_label, cutoff_datetime, max_source_id=None, company_ids=None, batch_id=None, *, user=None, vista_nombre=None, requested_company_ids=None):
        cls._model_for_app(app_label)
        requested = requested_company_ids if requested_company_ids is not None else company_ids
        normalized_ids = cls._validate_request(user, vista_nombre, requested)
        cutoff = cutoff_datetime
        if max_source_id is None:
            max_source_id = cls._model_for_app(app_label).objects.order_by('-id').values_list('id', flat=True).first() or 0
        resolved_batch_id = batch_id or f'{app_label}-{cutoff.isoformat()}-{max_source_id}-{"-".join(map(str, normalized_ids))}'
        with transaction.atomic():
            batch, created = AuditArchiveBatch.objects.get_or_create(
                batch_id=resolved_batch_id,
                defaults={
                    'app_label': app_label,
                    'cutoff_datetime': cutoff,
                    'source_max_id': max_source_id,
                    'company_ids': normalized_ids,
                    'status': 'PENDING',
                    'archive_path': str(cls.get_history_db_path(app_label)),
                },
            )
        if not created:
            if (batch.app_label, batch.cutoff_datetime, batch.source_max_id, batch.company_ids) != (app_label, cutoff, max_source_id, normalized_ids):
                raise ValueError('batch_id ya existe con una frontera diferente')
            if batch.status == 'COMPLETED':
                cls.validate_batch(batch)
                return batch

        source_rows = cls._selected_rows(app_label, cutoff, max_source_id, normalized_ids)
        if not source_rows:
            batch.status = 'FAILED'
            batch.error_message = 'No hay eventos elegibles para archivar'
            batch.save(update_fields=['status', 'error_message', 'updated_at'])
            raise ValueError('batch vacío')

        batch.status = 'COPYING'
        batch.source_count = len(source_rows)
        batch.source_min_id = source_rows[0].id
        batch.first_source_id = source_rows[0].id
        batch.last_source_id = source_rows[-1].id
        batch.first_event_at = source_rows[0].created_at
        batch.last_event_at = source_rows[-1].created_at
        batch.save(update_fields=['status', 'source_count', 'source_min_id', 'first_source_id', 'last_source_id', 'first_event_at', 'last_event_at', 'updated_at'])
        path = cls.get_history_db_path(app_label)
        cls._ensure_history_schema(path)
        cls._write_archive_batch(batch)
        try:
            conn = sqlite3.connect(path)
            try:
                for source in source_rows:
                    payload = cls._event_payload(source, app_label)
                    existing = conn.execute('SELECT * FROM audit_event_history WHERE source_event_id = ?', (source.id,)).fetchone()
                    if existing:
                        columns = [item[1] for item in conn.execute('PRAGMA table_info(audit_event_history)')]
                        existing_batch_id = dict(zip(columns, existing)).get('batch_id')
                        if existing_batch_id != resolved_batch_id:
                            raise ValueError(f'evento ya pertenece al batch {existing_batch_id}')
                        existing_payload = cls._archive_payload(dict(zip(columns, existing)))
                        if cls.canonical_json(existing_payload) != cls.canonical_json(payload):
                            raise ValueError(f'evento histórico divergente: {source.id}')
                        continue
                    cls._insert_event(conn, payload, resolved_batch_id)
                    conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            batch.status = 'FAILED'
            batch.error_message = str(exc)
            batch.save(update_fields=['status', 'error_message', 'updated_at'])
            cls._write_archive_batch(batch)
            raise
        batch.status = 'VALIDATING'
        batch.save(update_fields=['status', 'updated_at'])
        return cls.validate_batch(batch)

    @classmethod
    def validate_batch(cls, batch):
        source_rows = cls._selected_rows(batch.app_label, batch.cutoff_datetime, batch.source_max_id, batch.company_ids)
        if not source_rows:
            raise ValueError('batch vacío')
        source_payloads = [cls._event_payload(row, batch.app_label) for row in source_rows]
        source_checksum = cls.checksum(source_payloads)
        path = Path(batch.archive_path)
        uri = f'file:{path.as_posix()}?mode=ro'
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute('SELECT * FROM audit_event_history WHERE batch_id = ? ORDER BY source_event_id ASC', (batch.batch_id,)).fetchall()
            archive_payloads = [cls._archive_payload(row) for row in rows]
            archive_checksum = cls.checksum(archive_payloads)
            if len(rows) != len(source_rows) or source_checksum != archive_checksum:
                raise ValueError('checksum mismatch')
        except Exception as exc:
            batch.status = 'FAILED'
            batch.error_message = str(exc)
            batch.save(update_fields=['status', 'error_message', 'updated_at'])
            cls._write_archive_batch(batch)
            raise
        finally:
            conn.close()
        now = timezone.now()
        batch.status = 'COMPLETED'
        batch.archive_count = len(archive_payloads)
        batch.source_checksum = source_checksum
        batch.archive_checksum = archive_checksum
        batch.checksum_algorithm = cls.CHECKSUM_ALGORITHM
        batch.validated_at = now
        batch.manifest = {
            'batch_id': batch.batch_id,
            'source_app': batch.app_label,
            'cutoff_datetime': batch.cutoff_datetime.isoformat(),
            'max_source_id': batch.source_max_id,
            'company_ids': sorted(batch.company_ids or []),
            'source_count': len(source_rows),
            'archive_count': len(archive_payloads),
            'checksum_algorithm': cls.CHECKSUM_ALGORITHM,
            'source_checksum': source_checksum,
            'archive_checksum': archive_checksum,
        }
        batch.save(update_fields=['status', 'archive_count', 'checksum_algorithm', 'source_checksum', 'archive_checksum', 'validated_at', 'manifest', 'updated_at'])
        cls._write_archive_batch(batch)
        return batch

    @classmethod
    def read_archived_rows(cls, batch):
        path = Path(batch.archive_path)
        uri = f'file:{path.as_posix()}?mode=ro'
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in conn.execute('SELECT * FROM audit_event_history WHERE batch_id = ? ORDER BY source_event_id ASC', (batch.batch_id,)).fetchall()]
        finally:
            conn.close()
