from datetime import date, datetime
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model

from .models import AuditArchiveBatch


class HistoricalAuditQueryService:
    VALID_BATCH_STATUSES = {'COMPLETED', 'PURGED', 'PURGE_FAILED'}
    ALLOWED_APPS = {'biblioteca', 'gestiondte'}

    @classmethod
    def _history_path(cls, app_label):
        if app_label not in cls.ALLOWED_APPS:
            raise ValueError('app_label no permitido')
        root = Path(getattr(settings, 'AUDIT_ARCHIVE_ROOT', Path(settings.BASE_DIR) / 'audit_archive'))
        return root / f'{app_label}_history.sqlite3'

    @classmethod
    def _valid_batches(cls, app_label):
        return [batch for batch in AuditArchiveBatch.objects.filter(
            app_label=app_label,
            status__in=cls.VALID_BATCH_STATUSES,
        ).exclude(archive_path='') if batch.manifest and batch.source_checksum == batch.archive_checksum]

    @staticmethod
    def _parse_datetime(value, end=False):
        if not value:
            return None
        parsed = date.fromisoformat(value)
        return datetime.combine(parsed, datetime.max.time() if end else datetime.min.time()).isoformat()

    @classmethod
    def _query_batch(cls, path, batch, company_ids, filters):
        if not path.is_file():
            return []
        conditions = ['batch_id = ?', 'app_label = ?']
        params = [batch.batch_id, batch.app_label]
        placeholders = ','.join('?' for _ in company_ids)
        conditions.append(f'empresa_id IN ({placeholders})')
        params.extend(company_ids)
        if filters.get('action'):
            conditions.append('action = ?')
            params.append(filters['action'])
        if filters.get('object_type'):
            conditions.append('object_type LIKE ?')
            params.append(f"%{filters['object_type']}%")
        if filters.get('object_id'):
            conditions.append('object_id = ?')
            params.append(str(filters['object_id']))
        if filters.get('vista_nombre'):
            conditions.append('vista_nombre LIKE ?')
            params.append(f"%{filters['vista_nombre']}%")
        if filters.get('path'):
            conditions.append('path LIKE ?')
            params.append(f"%{filters['path']}%")
        date_from = cls._parse_datetime(filters.get('date_from'))
        date_to = cls._parse_datetime(filters.get('date_to'), end=True)
        if date_from:
            conditions.append('created_at >= ?')
            params.append(date_from)
        if date_to:
            conditions.append('created_at <= ?')
            params.append(date_to)
        if filters.get('user_ids') is not None:
            if not filters['user_ids']:
                return []
            user_placeholders = ','.join('?' for _ in filters['user_ids'])
            conditions.append(f'user_id IN ({user_placeholders})')
            params.extend(filters['user_ids'])
        sql = (
            'SELECT source_event_id, app_label, empresa_id, user_id, action, object_type, '
            'object_id, method, path, querystring, status_code, duration_ms, vista_nombre, '
            'message_key, meta, before, after, created_at '
            'FROM audit_event_history WHERE ' + ' AND '.join(conditions) + ' '
            'ORDER BY created_at DESC, source_event_id DESC'
        )
        connection = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(sql, params).fetchall()
        finally:
            connection.close()
        usernames = dict(get_user_model().objects.filter(
            id__in={row['user_id'] for row in rows if row['user_id'] is not None}
        ).values_list('id', 'username'))
        return [SimpleNamespace(
            pk=row['source_event_id'],
            source_event_id=row['source_event_id'],
            source='historical',
            batch_id=batch.batch_id,
            created_at=datetime.fromisoformat(row['created_at']),
            user=usernames.get(row['user_id'], row['user_id'] or ''),
            user_id=row['user_id'],
            empresa_id=row['empresa_id'],
            action=row['action'],
            object_type=row['object_type'],
            object_id=row['object_id'],
            method=row['method'],
            path=row['path'],
            querystring=row['querystring'],
            status_code=row['status_code'],
            duration_ms=row['duration_ms'],
            vista_nombre=row['vista_nombre'],
            message_key=row['message_key'],
            meta=row['meta'],
            before=row['before'],
            after=row['after'],
        ) for row in rows]

    @classmethod
    def query(cls, app_label, company_ids, filters=None):
        filters = dict(filters or {})
        user_filter = filters.get('user')
        if user_filter:
            user_model = get_user_model()
            if str(user_filter).isdigit():
                filters['user_ids'] = [int(user_filter)]
            else:
                filters['user_ids'] = list(user_model.objects.filter(
                    username__icontains=user_filter,
                ).values_list('id', flat=True))
        results = []
        for batch in cls._valid_batches(app_label):
            path = Path(batch.archive_path)
            results.extend(cls._query_batch(path, batch, company_ids, filters))
        return results

    @classmethod
    def get_event(cls, app_label, source_event_id, company_ids):
        matches = cls.query(app_label, company_ids)
        for event in matches:
            if event.source_event_id == source_event_id:
                return event
        return None
