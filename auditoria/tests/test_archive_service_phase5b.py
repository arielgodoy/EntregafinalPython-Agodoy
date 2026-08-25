import sqlite3
from datetime import timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from auditoria.services import AuditArchiveService
from auditoria.models import AuditoriaBibliotecaEvent, AuditoriaGestionDTEEvent, UserPresence

User = get_user_model()


class Phase5BArchiveTests(TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.override = override_settings(AUDIT_ARCHIVE_ROOT=self.tempdir.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = User.objects.create_user(username='archive-phase5b', password='pass')
        self.empresa_a = Empresa.objects.create(codigo='00', descripcion='Empresa A')
        self.empresa_b = Empresa.objects.create(codigo='03', descripcion='Empresa B')
        self.vista = Vista.objects.create(nombre='Auditoría - Biblioteca')
        Permiso.objects.create(usuario=self.user, empresa=self.empresa_a, vista=self.vista, autorizar=True)
        Permiso.objects.create(usuario=self.user, empresa=self.empresa_b, vista=self.vista, autorizar=True)
        self.cutoff = timezone.now() + timedelta(days=1)

    def create_event(self, model=AuditoriaBibliotecaEvent, empresa_id=None, path='/audit/'):
        event = model.objects.create(
            user=self.user,
            empresa_id=empresa_id or self.empresa_a.id,
            action='VIEW',
            object_type='Documento',
            object_id='1',
            path=path,
            status_code=200,
            vista_nombre=self.vista.nombre,
            meta={'z': 2, 'unicode': 'á', 'nested': {'b': 2, 'a': 1}},
            before={'old': None},
            after={'new': True},
        )
        return event

    def archive(self, app='biblioteca', companies=None, batch_id='phase5b', max_source_id=None):
        return AuditArchiveService.run_batch(
            app,
            self.cutoff,
            max_source_id=max_source_id,
            requested_company_ids=companies or [self.empresa_a.id],
            batch_id=batch_id,
            user=self.user,
            vista_nombre=self.vista.nombre,
        )

    def test_frontier_counts_manifest_and_readonly_file(self):
        first = self.create_event()
        second = self.create_event(path='/audit/2/')
        presence = UserPresence.objects.create(
            user=self.user, empresa_id=self.empresa_a.id, app_label='biblioteca',
            vista_nombre='Auditoría - Biblioteca', path='/audit/',
        )
        presence_snapshot = {
            field: getattr(presence, field)
            for field in ('user_id', 'empresa_id', 'app_label', 'vista_nombre', 'path')
        }
        batch = self.archive(max_source_id=second.id)
        self.assertEqual(batch.status, 'COMPLETED')
        self.assertEqual(batch.source_count, 2)
        self.assertEqual(batch.archive_count, 2)
        self.assertEqual(batch.first_source_id, first.id)
        self.assertEqual(batch.last_source_id, second.id)
        self.assertEqual(batch.source_checksum, batch.archive_checksum)
        self.assertEqual(
            {field: getattr(UserPresence.objects.get(pk=presence.pk), field) for field in presence_snapshot},
            presence_snapshot,
        )
        connection = sqlite3.connect(f'file:{batch.archive_path}?mode=ro', uri=True)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(tables & {'audit_event_history', 'archive_batches'}, {'audit_event_history', 'archive_batches'})
            indexes = connection.execute('PRAGMA index_list(audit_event_history)').fetchall()
            unique_indexes = [row[1] for row in indexes if row[2]]
            self.assertTrue(unique_indexes)
            indexed_columns = {
                row[2]
                for index_name in unique_indexes
                for row in connection.execute(f'PRAGMA index_info("{index_name}")')
            }
            self.assertIn('source_event_id', indexed_columns)
        finally:
            connection.close()

    def test_canonical_checksum_is_deterministic(self):
        first = {'unicode': 'á', 'value': [None, True, 1], 'json': {'b': 2, 'a': 1}}
        second = {'json': {'a': 1, 'b': 2}, 'value': [None, True, 1], 'unicode': 'á'}
        self.assertEqual(AuditArchiveService.checksum([first]), AuditArchiveService.checksum([second]))
        self.assertNotEqual(AuditArchiveService.checksum([first]), AuditArchiveService.checksum([dict(first, value=[None, False, 1])]))

    def test_authorization_uses_autorizar_and_ignores_active_company(self):
        self.create_event(empresa_id=self.empresa_a.id)
        self.create_event(empresa_id=self.empresa_b.id, path='/audit/b/')
        self.assertEqual(self.archive(companies=[self.empresa_a.id, self.empresa_b.id], batch_id='both').archive_count, 2)
        with self.assertRaises(PermissionError):
            self.archive(companies=[self.empresa_a.id, 999], batch_id='denied')

    def test_null_company_is_not_archived(self):
        event = self.create_event()
        event.empresa_id = None
        event.save(update_fields=['empresa_id'])
        with self.assertRaises(ValueError):
            self.archive(max_source_id=event.id, batch_id='null')

    def test_frozen_max_id_excludes_new_event_even_with_old_timestamp(self):
        first = self.create_event()
        later = self.create_event(path='/audit/later/')
        later.created_at = first.created_at
        later.save(update_fields=['created_at'])
        batch = self.archive(max_source_id=first.id, batch_id='frozen')
        self.assertEqual([row['source_event_id'] for row in AuditArchiveService.read_archived_rows(batch)], [first.id])

    def test_empty_batch_fails(self):
        with self.assertRaises(ValueError):
            self.archive(max_source_id=0, batch_id='empty')

    def test_partial_copy_failure_marks_failed_and_retry_is_idempotent(self):
        first = self.create_event()
        second = self.create_event(path='/audit/2/')
        original = AuditArchiveService._insert_event
        calls = {'count': 0}

        def fail_on_second(connection, payload, batch_id):
            calls['count'] += 1
            if calls['count'] == 2:
                raise RuntimeError('forced copy failure')
            return original(connection, payload, batch_id)

        with patch.object(AuditArchiveService, '_insert_event', side_effect=fail_on_second):
            with self.assertRaises(RuntimeError):
                self.archive(max_source_id=second.id, batch_id='retry')
        batch = self.archive(max_source_id=second.id, batch_id='retry')
        self.assertEqual(batch.status, 'COMPLETED')
        self.assertEqual(batch.source_count, batch.archive_count)
        self.assertEqual(batch.source_checksum, batch.archive_checksum)
        self.assertEqual(len(AuditArchiveService.read_archived_rows(batch)), 2)

    def test_corruption_fails_validation_without_touching_source(self):
        event = self.create_event()
        batch = self.archive(max_source_id=event.id)
        source_ids = list(AuditoriaBibliotecaEvent.objects.values_list('id', flat=True))
        source_count = AuditoriaBibliotecaEvent.objects.count()
        connection = sqlite3.connect(batch.archive_path)
        try:
            connection.execute("UPDATE audit_event_history SET action='CREATE' WHERE source_event_id=?", (event.id,))
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ValueError):
            AuditArchiveService.validate_batch(batch)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'FAILED')
        self.assertEqual(list(AuditoriaBibliotecaEvent.objects.values_list('id', flat=True)), source_ids)
        self.assertEqual(AuditoriaBibliotecaEvent.objects.count(), source_count)

    def test_biblioteca_and_gestiondte_archives_are_isolated(self):
        biblioteca_event = self.create_event()
        dte_event = self.create_event(model=AuditoriaGestionDTEEvent)
        biblioteca_batch = self.archive(max_source_id=biblioteca_event.id, batch_id='biblioteca')
        dte_batch = AuditArchiveService.run_batch(
            'gestiondte', self.cutoff, max_source_id=dte_event.id,
            requested_company_ids=[self.empresa_a.id], batch_id='gestiondte',
            user=self.user, vista_nombre=self.vista.nombre,
        )
        self.assertEqual(len(AuditArchiveService.read_archived_rows(biblioteca_batch)), 1)
        self.assertEqual(len(AuditArchiveService.read_archived_rows(dte_batch)), 1)
        self.assertNotEqual(biblioteca_batch.archive_path, dte_batch.archive_path)

    def test_overlapping_snapshot_is_rejected_by_source_event_ownership(self):
        first = self.create_event(path='/overlap/1/')
        second = self.create_event(path='/overlap/2/')
        self.archive(max_source_id=second.id, batch_id='owner-a')
        with self.assertRaises(ValueError):
            self.archive(max_source_id=second.id, batch_id='owner-b')

    def test_archive_source_has_no_destructive_sql(self):
        source = open('auditoria/archive_service.py', encoding='utf-8').read().upper()
        self.assertNotIn('DELETE FROM', source)
        self.assertNotIn('VACUUM', source)
        self.assertNotIn('INSERT OR REPLACE', source)
