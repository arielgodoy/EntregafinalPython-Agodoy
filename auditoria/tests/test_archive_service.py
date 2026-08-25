from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from datetime import timedelta

from auditoria.models import AuditoriaBibliotecaEvent, UserPresence
from auditoria.services import AuditArchiveService
from access_control.models import Empresa, Permiso, Vista

User = get_user_model()


class AuditArchiveServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='archive-user', password='12345')
        self.empresa = Empresa.objects.create(codigo='99', descripcion='Archive Test')
        self.vista = Vista.objects.create(nombre='Auditoría - Biblioteca')
        Permiso.objects.create(usuario=self.user, empresa=self.empresa, vista=self.vista, autorizar=True)
        self.cutoff = timezone.now() + timedelta(days=1)
        self.archive_root = TemporaryDirectory()
        self.addCleanup(self.archive_root.cleanup)
        self.settings_override = override_settings(AUDIT_ARCHIVE_ROOT=self.archive_root.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def test_archive_root_and_history_path_are_configured(self):
        from django.conf import settings

        self.assertTrue(hasattr(settings, 'AUDIT_ARCHIVE_ROOT'))
        history_path = str(AuditArchiveService.get_history_db_path('biblioteca'))
        self.assertIn('biblioteca_history.sqlite3', history_path)

    def test_run_batch_copies_events_without_deleting_source(self):
        for index in range(3):
            AuditoriaBibliotecaEvent.objects.create(
                user=self.user,
                empresa_id=self.empresa.id,
                action='VIEW',
                object_type='Documento',
                object_id=str(index + 1),
                path=f'/biblioteca/{index + 1}/',
                status_code=200,
                vista_nombre='Auditoría - Biblioteca',
                meta={'event': index},
                before={'status': 'old'},
                after={'status': 'new'},
            )

        UserPresence.objects.create(
            user=self.user,
            empresa_id=self.empresa.id,
            app_label='biblioteca',
            vista_nombre='Auditoría - Biblioteca',
            path='/biblioteca/'
        )

        batch = AuditArchiveService.run_batch(
            app_label='biblioteca',
            cutoff_datetime=self.cutoff,
            max_source_id=AuditoriaBibliotecaEvent.objects.order_by('-id').first().id,
            requested_company_ids=[self.empresa.id],
            batch_id='batch-copy-test',
            user=self.user,
            vista_nombre=self.vista.nombre,
        )

        self.assertEqual(batch.status, 'COMPLETED')
        self.assertEqual(AuditoriaBibliotecaEvent.objects.count(), 3)
        self.assertTrue(batch.archive_path)
        self.assertTrue(batch.archive_count >= 3)
        self.assertTrue(batch.source_checksum)
        self.assertTrue(batch.archive_checksum)

        archived_rows = AuditArchiveService.read_archived_rows(batch)
        self.assertEqual(len(archived_rows), 3)
        self.assertNotIn('auditoria_user_presence', str(batch.archive_path))

    def test_run_batch_is_idempotent_for_same_window(self):
        first = AuditoriaBibliotecaEvent.objects.create(
            user=self.user,
            empresa_id=self.empresa.id,
            action='VIEW',
            object_type='Documento',
            object_id='42',
            path='/biblioteca/42/',
            status_code=200,
            vista_nombre='Auditoría - Biblioteca',
            meta={'event': 'once'},
        )

        first_batch = AuditArchiveService.run_batch(
            app_label='biblioteca',
            cutoff_datetime=self.cutoff,
            max_source_id=first.id,
            requested_company_ids=[self.empresa.id],
            batch_id='batch-idempotent',
            user=self.user,
            vista_nombre=self.vista.nombre,
        )

        second_batch = AuditArchiveService.run_batch(
            app_label='biblioteca',
            cutoff_datetime=self.cutoff,
            max_source_id=first.id,
            requested_company_ids=[self.empresa.id],
            batch_id='batch-idempotent',
            user=self.user,
            vista_nombre=self.vista.nombre,
        )

        self.assertEqual(first_batch.id, second_batch.id)
        self.assertEqual(first_batch.status, 'COMPLETED')
        self.assertEqual(AuditoriaBibliotecaEvent.objects.count(), 1)
