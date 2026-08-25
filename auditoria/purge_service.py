import json
import hashlib
import sqlite3
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .archive_service import AuditArchiveService
from .models import AuditArchiveBatch
from .models import AuditArchivePurgeChunk
from .permissions import get_archivable_company_ids


class AuditArchivePurgeService:
    DEFAULT_CHUNK_SIZE = 1000
    APP_VISTA_NAMES = {
        'biblioteca': 'Auditoría - Biblioteca',
        'gestiondte': 'Auditoría - Gestión DTE',
    }
    ALLOWED_STATUSES = {'COMPLETED', 'PURGING', 'PURGED', 'PURGE_FAILED'}
    RETRY_STATUSES = {'PURGING', 'PURGED', 'PURGE_FAILED'}

    @classmethod
    def _chunk_size(cls):
        return int(getattr(settings, 'AUDIT_ARCHIVE_DELETE_CHUNK_SIZE', cls.DEFAULT_CHUNK_SIZE))

    @classmethod
    def _get_batch(cls, batch_id):
        try:
            return AuditArchiveBatch.objects.get(batch_id=batch_id)
        except AuditArchiveBatch.DoesNotExist:
            raise ValueError('Batch de archivado no encontrado') from None

    @classmethod
    def _authorize(cls, user, batch):
        authorized = set(get_archivable_company_ids(user, cls.APP_VISTA_NAMES[batch.app_label]))
        requested = {int(company_id) for company_id in (batch.company_ids or [])}
        if not requested or not requested.issubset(authorized):
            raise PermissionError('El usuario no está autorizado para purgar todas las empresas del batch')

    @classmethod
    def _read_historical_payloads(cls, batch):
        path = Path(batch.archive_path)
        if not path.is_file():
            raise ValueError('Archivo histórico no encontrado')
        connection = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if 'audit_event_history' not in tables or 'archive_batches' not in tables:
                raise ValueError('Esquema histórico incompleto')
            rows = connection.execute(
                'SELECT * FROM audit_event_history WHERE batch_id = ? ORDER BY source_event_id ASC',
                (batch.batch_id,),
            ).fetchall()
            archive_batches = connection.execute(
                'SELECT * FROM archive_batches WHERE batch_id = ?',
                (batch.batch_id,),
            ).fetchall()
            if len(archive_batches) != 1:
                raise ValueError('Manifest histórico ausente')
            return rows, archive_batches[0]
        finally:
            connection.close()

    @classmethod
    def _validate_archive(cls, batch):
        rows, manifest_row = cls._read_historical_payloads(batch)
        if batch.app_label not in AuditArchiveService.ALLOWED_APPS:
            raise ValueError('app_label no permitido')
        if batch.checksum_algorithm != AuditArchiveService.CHECKSUM_ALGORITHM:
            raise ValueError('Algoritmo de checksum no soportado')
        if not batch.manifest:
            raise ValueError('Manifest del batch ausente')
        if batch.source_count != batch.archive_count:
            raise ValueError('Conteos del batch no coinciden')
        if batch.source_count != len(rows):
            raise ValueError('Conteo histórico no coincide con el batch')
        if manifest_row['source_app'] != batch.app_label:
            raise ValueError('Manifest de aplicación incorrecto')
        if manifest_row['max_source_id'] != batch.source_max_id:
            raise ValueError('Manifest de frontera incorrecto')
        if json.loads(manifest_row['company_ids_json']) != batch.company_ids:
            raise ValueError('Manifest de empresas incorrecto')
        expected_manifest = cls.build_expected_manifest(batch)
        if batch.manifest != expected_manifest:
            raise ValueError('Manifest del modelo inconsistente')
        manifest_json = json.loads(manifest_row['manifest_json'])
        if manifest_json != expected_manifest:
            raise ValueError('Manifest histórico inconsistente')
        archive_columns = {
            'batch_id': manifest_row['batch_id'],
            'source_app': manifest_row['source_app'],
            'cutoff_datetime': manifest_row['cutoff_datetime'],
            'max_source_id': manifest_row['max_source_id'],
            'company_ids': json.loads(manifest_row['company_ids_json']),
            'source_count': manifest_row['source_count'],
            'archive_count': manifest_row['archive_count'],
            'checksum_algorithm': manifest_row['checksum_algorithm'],
            'source_checksum': manifest_row['source_checksum'],
            'archive_checksum': manifest_row['archive_checksum'],
        }
        for key, value in expected_manifest.items():
            if archive_columns.get(key) != value:
                raise ValueError('Columnas del manifest histórico inconsistentes')
        payloads = [AuditArchiveService._archive_payload(row) for row in rows]
        archive_checksum = AuditArchiveService.checksum(payloads)
        if archive_checksum != batch.archive_checksum or archive_checksum != batch.source_checksum:
            raise ValueError('checksum mismatch')
        source_ids = [row['source_event_id'] for row in rows]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError('source_event_id duplicado')
        return rows, payloads, source_ids

    @classmethod
    def build_expected_manifest(cls, batch):
        return {
            'batch_id': batch.batch_id,
            'source_app': batch.app_label,
            'cutoff_datetime': batch.cutoff_datetime.isoformat(),
            'max_source_id': batch.source_max_id,
            'company_ids': sorted(batch.company_ids or []),
            'source_count': batch.source_count,
            'archive_count': batch.archive_count,
            'checksum_algorithm': batch.checksum_algorithm,
            'source_checksum': batch.source_checksum,
            'archive_checksum': batch.archive_checksum,
        }

    @classmethod
    def _ensure_chunks(cls, batch, source_ids, chunk_size):
        chunks = [source_ids[index:index + chunk_size] for index in range(0, len(source_ids), chunk_size)]
        existing = {chunk.sequence: chunk for chunk in AuditArchivePurgeChunk.objects.filter(batch=batch)}
        for sequence, ids in enumerate(chunks, start=1):
            checksum = cls._chunk_ids_checksum(ids)
            chunk = existing.get(sequence)
            if chunk is None:
                chunk = AuditArchivePurgeChunk.objects.create(
                    batch=batch,
                    sequence=sequence,
                    expected_count=len(ids),
                    source_ids_checksum=checksum,
                    first_source_id=ids[0],
                    last_source_id=ids[-1],
                )
            elif (chunk.expected_count, chunk.source_ids_checksum, chunk.first_source_id, chunk.last_source_id) != (len(ids), checksum, ids[0], ids[-1]):
                raise ValueError('Progreso de chunks inconsistente')
        if set(existing) - set(range(1, len(chunks) + 1)):
            raise ValueError('Existen chunks fuera de la partición histórica')
        return chunks

    @classmethod
    def _chunk_ids_checksum(cls, source_ids):
        return hashlib.sha256(','.join(str(source_id) for source_id in source_ids).encode('utf-8')).hexdigest()

    @classmethod
    def _validate_source(cls, batch, rows, payloads, source_ids, completed_source_ids):
        model = AuditArchiveService.ALLOWED_APPS[batch.app_label]
        source_rows = {
            row.id: row
            for row in model.objects.filter(id__in=source_ids)
        }
        missing = [source_id for source_id in source_ids if source_id not in source_rows]
        if missing and not set(missing).issubset(completed_source_ids):
            raise ValueError('Evento origen ausente antes del primer purge')
        present_ids = [source_id for source_id in source_ids if source_id in source_rows]
        present_payloads = [
            AuditArchiveService._event_payload(source_rows[source_id], batch.app_label)
            for source_id in present_ids
        ]
        archive_by_id = {
            payload['source_event_id']: payload
            for payload in payloads
        }
        for source_id, payload in zip(present_ids, present_payloads):
            if AuditArchiveService.canonical_json(payload) != AuditArchiveService.canonical_json(archive_by_id[source_id]):
                raise ValueError('Evento origen modificado después del snapshot')
        if not missing and AuditArchiveService.checksum(present_payloads) != batch.source_checksum:
            raise ValueError('checksum origen mismatch')
        return model, source_rows, present_ids

    @classmethod
    def _validated_context(cls, batch, user, chunk_size=None):
        if batch.status not in cls.ALLOWED_STATUSES:
            raise ValueError('El batch no está validado o no puede reanudarse')
        cls._authorize(user, batch)
        rows, payloads, source_ids = cls._validate_archive(batch)
        existing_chunks = list(AuditArchivePurgeChunk.objects.filter(batch=batch).order_by('sequence'))
        if existing_chunks:
            expected_chunks = [
                source_ids[index:index + (chunk_size or cls._chunk_size())]
                for index in range(0, len(source_ids), (chunk_size or cls._chunk_size()))
            ]
            if len(existing_chunks) != len(expected_chunks):
                raise ValueError('Progreso de chunks inconsistente')
            completed_source_ids = set()
            for progress, expected_ids in zip(existing_chunks, expected_chunks):
                if progress.source_ids_checksum != cls._chunk_ids_checksum(expected_ids):
                    raise ValueError('Checksum de IDs del chunk inconsistente')
                if progress.status == 'COMPLETED':
                    completed_source_ids.update(expected_ids)
        else:
            completed_source_ids = set()
        model, source_rows, present_ids = cls._validate_source(
            batch,
            rows,
            payloads,
            source_ids,
            completed_source_ids=completed_source_ids,
        )
        return model, rows, source_ids, source_rows, present_ids

    @classmethod
    def preview(cls, batch_id, user):
        batch = cls._get_batch(batch_id)
        model, rows, source_ids, source_rows, present_ids = cls._validated_context(batch, user)
        return {
            'batch_id': batch.batch_id,
            'app_label': batch.app_label,
            'company_ids': list(batch.company_ids),
            'source_count': batch.source_count,
            'remaining_in_source': len(present_ids),
            'cutoff_datetime': batch.cutoff_datetime,
            'first_source_id': batch.first_source_id,
            'last_source_id': batch.last_source_id,
            'first_event_at': batch.first_event_at,
            'last_event_at': batch.last_event_at,
            'archive_checksum_valid': True,
            'source_ids': source_ids,
        }

    @classmethod
    def purge(cls, batch_id, user, *, dry_run=False, chunk_size=None):
        batch = cls._get_batch(batch_id)
        try:
            chunk_size = int(chunk_size or cls._chunk_size())
            if chunk_size <= 0:
                raise ValueError('chunk_size debe ser positivo')
            context = cls._validated_context(batch, user, chunk_size=chunk_size)
        except Exception as exc:
            if not dry_run and batch.status in cls.ALLOWED_STATUSES and batch.status != 'PURGED':
                batch.status = 'PURGE_FAILED'
                batch.purge_error_message = str(exc)
                batch.save(update_fields=['status', 'purge_error_message', 'updated_at'])
            raise
        model, rows, source_ids, source_rows, present_ids = context
        if dry_run:
            return {
                'dry_run': True,
                'batch_id': batch.batch_id,
                'app_label': batch.app_label,
                'source_count': batch.source_count,
                'remaining_in_source': len(present_ids),
                'source_ids': source_ids,
            }
        if batch.status == 'PURGED':
            return batch
        batch.status = 'PURGING'
        batch.purge_started_at = batch.purge_started_at or timezone.now()
        batch.purge_error_message = ''
        batch.save(update_fields=['status', 'purge_started_at', 'purge_error_message', 'updated_at'])
        try:
            chunks = cls._ensure_chunks(batch, source_ids, chunk_size)
            for sequence, chunk_ids in enumerate(chunks, start=1):
                progress = AuditArchivePurgeChunk.objects.get(batch=batch, sequence=sequence)
                if progress.status == 'COMPLETED':
                    continue
                present_chunk_ids = [source_id for source_id in chunk_ids if source_id in source_rows]
                if len(present_chunk_ids) != len(chunk_ids):
                    raise ValueError('Falta un evento sin evidencia de chunk completado')
                with transaction.atomic():
                    now = timezone.now()
                    progress.status = 'DELETING'
                    progress.started_at = progress.started_at or now
                    progress.save(update_fields=['status', 'started_at'])
                    expected_source_count = model.objects.filter(id__in=chunk_ids).count()
                    cls._delete_chunk(model, chunk_ids)
                    if model.objects.filter(id__in=chunk_ids).exists():
                        raise ValueError('Persisten eventos del chunk en el origen')
                    progress.deleted_count = expected_source_count
                    progress.status = 'COMPLETED'
                    progress.completed_at = timezone.now()
                    progress.save(update_fields=['deleted_count', 'status', 'completed_at'])
                    batch.purged_count = sum(
                        purge_chunk.deleted_count
                        for purge_chunk in AuditArchivePurgeChunk.objects.filter(batch=batch, status='COMPLETED')
                    )
                    batch.save(update_fields=['purged_count', 'updated_at'])
            batch.purged_count = sum(
                chunk.deleted_count
                for chunk in AuditArchivePurgeChunk.objects.filter(batch=batch, status='COMPLETED')
            )
            batch.save(update_fields=['purged_count', 'updated_at'])
            if batch.purged_count != batch.source_count:
                raise ValueError('El contador de purge no coincide con el snapshot')
            if model.objects.filter(id__in=source_ids).exists():
                raise ValueError('Persisten eventos del batch en el origen')
            batch.status = 'PURGED'
            batch.purged_at = timezone.now()
            batch.purged_by = user
            batch.purge_error_message = ''
            batch.save(update_fields=['status', 'purged_at', 'purged_by', 'purge_error_message', 'updated_at'])
            return batch
        except Exception as exc:
            batch.status = 'PURGE_FAILED'
            batch.purge_error_message = str(exc)
            batch.save(update_fields=['status', 'purge_error_message', 'updated_at'])
            raise

    @staticmethod
    def _delete_chunk(model, source_ids):
        deleted, _details = model.objects.filter(id__in=source_ids).delete()
        return deleted
