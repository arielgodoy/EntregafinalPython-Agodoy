import sqlite3
from datetime import timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from auditoria.models import (
    AuditArchivePurgeChunk,
    AuditoriaBibliotecaEvent,
    AuditoriaGestionDTEEvent,
    UserPresence,
)
from auditoria.archive_service import AuditArchiveService
from auditoria.purge_service import AuditArchivePurgeService

User = get_user_model()


class AuditArchivePurgeServiceTests(TestCase):
    def setUp(self):
        self.archive_root = TemporaryDirectory()
        self.addCleanup(self.archive_root.cleanup)
        self.settings_override = override_settings(
            AUDIT_ARCHIVE_ROOT=self.archive_root.name,
            AUDIT_ARCHIVE_DELETE_CHUNK_SIZE=2,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.user = User.objects.create_user(username='purge-user', password='pass')
        self.other_user = User.objects.create_user(username='other-purge-user', password='pass')
        self.empresa_a = Empresa.objects.create(codigo='00', descripcion='Empresa A')
        self.empresa_b = Empresa.objects.create(codigo='03', descripcion='Empresa B')
        self.vista_biblioteca = Vista.objects.create(nombre='Auditoría - Biblioteca')
        self.vista_dte = Vista.objects.create(nombre='Auditoría - Gestión DTE')
        for empresa in (self.empresa_a, self.empresa_b):
            Permiso.objects.create(usuario=self.user, empresa=empresa, vista=self.vista_biblioteca, autorizar=True)
            Permiso.objects.create(usuario=self.user, empresa=empresa, vista=self.vista_dte, autorizar=True)
        self.cutoff = timezone.now() + timedelta(days=1)

    def event(self, model=AuditoriaBibliotecaEvent, empresa=None, suffix='1'):
        return model.objects.create(
            user=self.user,
            empresa_id=(empresa or self.empresa_a).id,
            action='VIEW',
            object_type='AuditEvent',
            object_id=suffix,
            path=f'/audit/{suffix}/',
            status_code=200,
            vista_nombre=(self.vista_biblioteca if model is AuditoriaBibliotecaEvent else self.vista_dte).nombre,
            meta={'suffix': suffix},
        )

    def snapshot(self, app='biblioteca', events=None, batch_id='purge-batch', companies=None):
        events = events or []
        max_id = max(event.id for event in events)
        vista = self.vista_biblioteca if app == 'biblioteca' else self.vista_dte
        return AuditArchiveService.run_batch(
            app,
            self.cutoff,
            max_source_id=max_id,
            requested_company_ids=companies or [self.empresa_a.id],
            batch_id=batch_id,
            user=self.user,
            vista_nombre=vista.nombre,
        )

    def test_preview_and_dry_run_validate_without_deleting(self):
        events = [self.event(suffix=str(index)) for index in range(1, 4)]
        batch = self.snapshot(events=events)
        preview = AuditArchivePurgeService.preview(batch.batch_id, self.user)
        self.assertEqual(preview['source_count'], 3)
        self.assertEqual(preview['remaining_in_source'], 3)
        result = AuditArchivePurgeService.purge(batch.batch_id, self.user, dry_run=True)
        self.assertTrue(result['dry_run'])
        self.assertEqual(result['source_ids'], [event.id for event in events])
        self.assertEqual(AuditoriaBibliotecaEvent.objects.count(), 3)

    def test_purge_requires_completed_snapshot(self):
        batch = self.snapshot(events=[self.event()])
        for status in ('PENDING', 'COPYING', 'VALIDATING', 'FAILED'):
            batch.status = status
            batch.save(update_fields=['status'])
            with self.subTest(status=status), self.assertRaises(ValueError):
                AuditArchivePurgeService.purge(batch.batch_id, self.user)
        self.assertEqual(AuditoriaBibliotecaEvent.objects.count(), 1)

    def test_purge_uses_historical_ids_and_preserves_new_events(self):
        first = self.event(suffix='first')
        batch = self.snapshot(events=[first])
        new_event = self.event(suffix='new')
        result = AuditArchivePurgeService.purge(batch.batch_id, self.user)
        self.assertEqual(result.status, 'PURGED')
        self.assertEqual(result.purged_count, 1)
        self.assertFalse(AuditoriaBibliotecaEvent.objects.filter(pk=first.pk).exists())
        self.assertTrue(AuditoriaBibliotecaEvent.objects.filter(pk=new_event.pk).exists())
        self.assertEqual(len(AuditArchiveService.read_archived_rows(batch)), 1)

    def test_archive_checksum_or_source_change_aborts_without_delete(self):
        event = self.event()
        batch = self.snapshot(events=[event])
        connection = sqlite3.connect(batch.archive_path)
        try:
            connection.execute("UPDATE audit_event_history SET action='CREATE' WHERE source_event_id=?", (event.id,))
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ValueError):
            AuditArchivePurgeService.purge(batch.batch_id, self.user)
        self.assertTrue(AuditoriaBibliotecaEvent.objects.filter(pk=event.pk).exists())

        with TemporaryDirectory() as other_root, override_settings(AUDIT_ARCHIVE_ROOT=other_root):
            event2 = self.event(suffix='source-change')
            batch2 = self.snapshot(events=[event2], batch_id='source-change')
            event2.action = 'UPDATE'
            event2.save(update_fields=['action'])
            with self.assertRaises(ValueError):
                AuditArchivePurgeService.purge(batch2.batch_id, self.user)
            self.assertTrue(AuditoriaBibliotecaEvent.objects.filter(pk=event2.id).exists())

    def test_missing_source_before_first_purge_aborts(self):
        event = self.event()
        batch = self.snapshot(events=[event])
        AuditoriaBibliotecaEvent.objects.filter(pk=event.pk).delete()
        with self.assertRaises(ValueError):
            AuditArchivePurgeService.purge(batch.batch_id, self.user)
        self.assertEqual(batch.refresh_from_db() or batch.status, 'PURGE_FAILED')

    def test_chunk_failure_marks_failed_and_retry_completes(self):
        events = [self.event(suffix=str(index)) for index in range(1, 6)]
        batch = self.snapshot(events=events)
        original = AuditArchivePurgeService._delete_chunk
        calls = {'count': 0}

        def fail_second(model, source_ids):
            calls['count'] += 1
            if calls['count'] == 2:
                raise RuntimeError('forced purge failure')
            return original(model, source_ids)

        with patch.object(AuditArchivePurgeService, '_delete_chunk', side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                AuditArchivePurgeService.purge(batch.batch_id, self.user, chunk_size=2)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'PURGE_FAILED')
        self.assertEqual(batch.purged_count, 2)
        result = AuditArchivePurgeService.purge(batch.batch_id, self.user, chunk_size=2)
        self.assertEqual(result.status, 'PURGED')
        self.assertEqual(result.purged_count, 5)
        self.assertEqual(AuditoriaBibliotecaEvent.objects.count(), 0)
        self.assertEqual(len(AuditArchiveService.read_archived_rows(batch)), 5)

    def test_userpresence_and_history_remain_intact(self):
        presence = UserPresence.objects.create(
            user=self.user,
            empresa_id=self.empresa_a.id,
            app_label='biblioteca',
            vista_nombre=self.vista_biblioteca.nombre,
            path='/audit/',
        )
        event = self.event()
        batch = self.snapshot(events=[event])
        history_before = AuditArchiveService.read_archived_rows(batch)
        AuditArchivePurgeService.purge(batch.batch_id, self.user)
        presence.refresh_from_db()
        self.assertEqual(presence.path, '/audit/')
        self.assertEqual(AuditArchiveService.read_archived_rows(batch), history_before)

    def test_app_isolation(self):
        biblioteca_event = self.event()
        dte_event = self.event(model=AuditoriaGestionDTEEvent)
        biblioteca_batch = self.snapshot(events=[biblioteca_event], batch_id='biblioteca-purge')
        dte_batch = self.snapshot(app='gestiondte', events=[dte_event], batch_id='dte-purge')
        AuditArchivePurgeService.purge(biblioteca_batch.batch_id, self.user)
        self.assertFalse(AuditoriaBibliotecaEvent.objects.filter(pk=biblioteca_event.pk).exists())
        self.assertTrue(AuditoriaGestionDTEEvent.objects.filter(pk=dte_event.pk).exists())
        AuditArchivePurgeService.purge(dte_batch.batch_id, self.user)
        self.assertFalse(AuditoriaGestionDTEEvent.objects.filter(pk=dte_event.pk).exists())

    def test_current_purge_user_must_authorize_all_batch_companies(self):
        events = [self.event(empresa=self.empresa_a, suffix='a'), self.event(empresa=self.empresa_b, suffix='b')]
        batch = self.snapshot(events=events, companies=[self.empresa_a.id, self.empresa_b.id])
        Permiso.objects.filter(usuario=self.user, empresa=self.empresa_b, vista=self.vista_biblioteca).update(autorizar=False)
        with self.assertRaises(PermissionError):
            AuditArchivePurgeService.purge(batch.batch_id, self.user)
        self.assertEqual(AuditoriaBibliotecaEvent.objects.count(), 2)

    def test_chunks_are_deterministic_and_unique_per_batch(self):
        events = [self.event(suffix=str(index)) for index in range(1, 6)]
        batch = self.snapshot(events=events)
        with patch.object(AuditArchivePurgeService, '_delete_chunk', side_effect=RuntimeError('stop before delete')):
            with self.assertRaises(RuntimeError):
                AuditArchivePurgeService.purge(batch.batch_id, self.user, chunk_size=2)
        chunks = list(AuditArchivePurgeChunk.objects.filter(batch=batch).order_by('sequence'))
        self.assertEqual([(chunk.sequence, chunk.expected_count) for chunk in chunks], [(1, 2), (2, 2), (3, 1)])
        for chunk, ids in zip(chunks, ([event.id for event in events[:2]], [event.id for event in events[2:4]], [events[4].id])):
            self.assertEqual(chunk.source_ids_checksum, AuditArchivePurgeService._chunk_ids_checksum(ids))
        with self.assertRaises(Exception):
            AuditArchivePurgeChunk.objects.create(
                batch=batch,
                sequence=1,
                expected_count=2,
                source_ids_checksum=chunks[0].source_ids_checksum,
            )

    def test_purged_count_uses_source_count_not_cascade_total(self):
        events = [self.event(suffix=str(index)) for index in range(1, 4)]
        batch = self.snapshot(events=events)
        original = AuditArchivePurgeService._delete_chunk

        def delete_with_cascade_count(model, source_ids):
            original(model, source_ids)
            return 999

        with patch.object(AuditArchivePurgeService, '_delete_chunk', side_effect=delete_with_cascade_count):
            result = AuditArchivePurgeService.purge(batch.batch_id, self.user)
        self.assertEqual(result.purged_count, 3)
        self.assertEqual(
            sum(chunk.deleted_count for chunk in AuditArchivePurgeChunk.objects.filter(batch=batch, status='COMPLETED')),
            3,
        )

    def test_chunk_transaction_rolls_back_delete_before_completed_evidence(self):
        events = [self.event(suffix=str(index)) for index in range(1, 3)]
        batch = self.snapshot(events=events)
        original = AuditArchivePurgeService._delete_chunk

        def delete_then_fail(model, source_ids):
            original(model, source_ids)
            raise RuntimeError('fail after delete')

        with patch.object(AuditArchivePurgeService, '_delete_chunk', side_effect=delete_then_fail):
            with self.assertRaises(RuntimeError):
                AuditArchivePurgeService.purge(batch.batch_id, self.user, chunk_size=2)
        self.assertEqual(AuditoriaBibliotecaEvent.objects.count(), 2)
        chunk = AuditArchivePurgeChunk.objects.get(batch=batch, sequence=1)
        self.assertNotEqual(chunk.status, 'COMPLETED')
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'PURGE_FAILED')

    def test_external_absence_without_completed_chunk_evidence_is_rejected_on_retry(self):
        events = [self.event(suffix=str(index)) for index in range(1, 3)]
        batch = self.snapshot(events=events)
        with patch.object(AuditArchivePurgeService, '_delete_chunk', side_effect=RuntimeError('before delete')):
            with self.assertRaises(RuntimeError):
                AuditArchivePurgeService.purge(batch.batch_id, self.user, chunk_size=2)
        AuditoriaBibliotecaEvent.objects.filter(pk=events[0].pk).delete()
        with self.assertRaises(ValueError):
            AuditArchivePurgeService.purge(batch.batch_id, self.user, chunk_size=2)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'PURGE_FAILED')
        self.assertTrue(AuditoriaBibliotecaEvent.objects.filter(pk=events[1].pk).exists())

    def test_completed_chunk_evidence_allows_legitimate_retry(self):
        events = [self.event(suffix=str(index)) for index in range(1, 5)]
        batch = self.snapshot(events=events)
        original = AuditArchivePurgeService._delete_chunk
        calls = {'count': 0}

        def fail_second(model, source_ids):
            calls['count'] += 1
            if calls['count'] == 2:
                raise RuntimeError('second chunk failure')
            return original(model, source_ids)

        with patch.object(AuditArchivePurgeService, '_delete_chunk', side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                AuditArchivePurgeService.purge(batch.batch_id, self.user, chunk_size=2)
        self.assertEqual(AuditArchivePurgeChunk.objects.filter(batch=batch, status='COMPLETED').count(), 1)
        result = AuditArchivePurgeService.purge(batch.batch_id, self.user, chunk_size=2)
        self.assertEqual(result.status, 'PURGED')
        self.assertEqual(result.purged_count, 4)

    def test_model_manifest_corruption_is_rejected(self):
        event = self.event()
        batch = self.snapshot(events=[event])
        batch.manifest['source_count'] = 999
        batch.save(update_fields=['manifest'])
        with self.assertRaises(ValueError):
            AuditArchivePurgeService.preview(batch.batch_id, self.user)
        self.assertTrue(AuditoriaBibliotecaEvent.objects.filter(pk=event.pk).exists())

    def test_historical_manifest_json_corruption_is_rejected(self):
        event = self.event()
        batch = self.snapshot(events=[event])
        connection = sqlite3.connect(batch.archive_path)
        try:
            connection.execute("UPDATE archive_batches SET manifest_json=? WHERE batch_id=?", ('{}', batch.batch_id))
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ValueError):
            AuditArchivePurgeService.preview(batch.batch_id, self.user)
        self.assertTrue(AuditoriaBibliotecaEvent.objects.filter(pk=event.pk).exists())

    def test_historical_manifest_column_corruption_is_rejected(self):
        event = self.event()
        batch = self.snapshot(events=[event])
        connection = sqlite3.connect(batch.archive_path)
        try:
            connection.execute("UPDATE archive_batches SET source_count=999 WHERE batch_id=?", (batch.batch_id,))
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ValueError):
            AuditArchivePurgeService.preview(batch.batch_id, self.user)
        self.assertTrue(AuditoriaBibliotecaEvent.objects.filter(pk=event.pk).exists())
