import sqlite3
from datetime import timedelta
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from auditoria.archive_service import AuditArchiveService
from auditoria.models import AuditArchiveBatch, AuditoriaBibliotecaEvent, AuditoriaGestionDTEEvent, UserPresence

User = get_user_model()


class AuditArchiveUITests(TestCase):
    def setUp(self):
        self.archive_root = TemporaryDirectory()
        self.addCleanup(self.archive_root.cleanup)
        self.override = override_settings(AUDIT_ARCHIVE_ROOT=self.archive_root.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = User.objects.create_user(username='archive-ui', password='pass')
        self.empresa_a = Empresa.objects.create(codigo='00', descripcion='Empresa A')
        self.empresa_b = Empresa.objects.create(codigo='03', descripcion='Empresa B')
        self.empresa_c = Empresa.objects.create(codigo='05', descripcion='Empresa C')
        self.vista = Vista.objects.create(nombre='Auditoría - Biblioteca')
        self.grant(self.empresa_a, ingresar=True, autorizar=True)
        self.grant(self.empresa_b, ingresar=True, autorizar=True)
        self.grant(self.empresa_c, ingresar=True, autorizar=False)
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa_a.id
        session.save()

    def grant(self, empresa, **flags):
        return Permiso.objects.create(
            usuario=self.user,
            empresa=empresa,
            vista=self.vista,
            **flags,
        )

    def event(self, empresa=None, suffix=None):
        suffix = suffix or uuid4().hex
        return AuditoriaBibliotecaEvent.objects.create(
            user=self.user,
            empresa_id=(empresa or self.empresa_a).id,
            action='VIEW',
            path=f'/archive-ui/{suffix}/',
            vista_nombre=self.vista.nombre,
            meta={'ui': True},
        )

    def archive_snapshot(self, events, companies=None, batch_id=None):
        return AuditArchiveService.run_batch(
            'biblioteca',
            timezone.now() + timedelta(days=1),
            max_source_id=max(event.id for event in events),
            requested_company_ids=companies or [self.empresa_a.id],
            batch_id=batch_id or f'ui-{uuid4().hex}',
            user=self.user,
            vista_nombre=self.vista.nombre,
        )

    def test_audit_list_with_ingresar_without_autorizar_hides_archive_admin(self):
        Permiso.objects.filter(
            usuario=self.user,
            vista=self.vista,
        ).update(autorizar=False)
        response = self.client.get(reverse('auditoria:auditoria_biblioteca_list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Administrar archivado')

    def test_archive_ui_shows_only_authorized_companies(self):
        response = self.client.get(reverse('auditoria:auditoria_biblioteca_archive'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Limpieza real aún no habilitada')
        self.assertContains(response, 'Limpieza disponible después de validar el dry-run.')
        self.assertContains(response, 'id="archive-company-%s"' % self.empresa_a.id)
        self.assertContains(response, 'id="archive-company-%s"' % self.empresa_b.id)
        self.assertNotContains(response, 'id="archive-company-%s"' % self.empresa_c.id)

    def test_manipulated_company_post_is_forbidden(self):
        response = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'),
            {
                'action': 'preview_snapshot',
                'company_ids': [str(self.empresa_a.id), str(self.empresa_c.id)],
                'cutoff_datetime': '2030-01-01T00:00',
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_snapshot_preview_and_create_are_post_only(self):
        event = self.event()
        preview = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'),
            {
                'action': 'preview_snapshot',
                'company_ids': [str(self.empresa_a.id)],
                'cutoff_datetime': '2030-01-01T00:00',
            },
        )
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, 'Vista previa del snapshot')
        self.assertContains(preview, str(event.id))
        self.assertEqual(AuditArchiveService._model_for_app('biblioteca').objects.filter(pk=event.pk).count(), 1)

        created = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'),
            {
                'action': 'create_snapshot',
                'company_ids': [str(self.empresa_a.id)],
                'cutoff_datetime': '2030-01-01T00:00',
            },
        )
        self.assertEqual(created.status_code, 200)
        self.assertContains(created, 'Snapshot creado y validado')
        self.assertEqual(AuditoriaBibliotecaEvent.objects.filter(pk=event.pk).count(), 1)
        snapshot_events = AuditoriaBibliotecaEvent.objects.filter(action='EXECUTE')
        self.assertEqual(snapshot_events.count(), 1)
        snapshot_event = snapshot_events.get()
        self.assertEqual(snapshot_event.message_key, 'auditoria.snapshot.creado')
        self.assertTrue(AuditArchiveBatch.objects.filter(batch_id=snapshot_event.meta['batch_id']).exists())
        self.assertGreater(snapshot_event.id, event.id)

    def test_snapshot_for_gestiondte_uses_gestiondte_audit_table(self):
        vista = Vista.objects.create(nombre='Auditoría - Gestión DTE')
        Permiso.objects.create(usuario=self.user, empresa=self.empresa_a, vista=vista, ingresar=True, autorizar=True)
        event = AuditoriaGestionDTEEvent.objects.create(
            user=self.user,
            empresa_id=self.empresa_a.id,
            action='VIEW',
            path='/archive-ui/dte/',
            vista_nombre=vista.nombre,
        )
        response = self.client.post(
            reverse('auditoria:auditoria_gestiondte_archive'),
            {
                'action': 'create_snapshot',
                'company_ids': [str(self.empresa_a.id)],
                'cutoff_datetime': '2030-01-01T00:00',
            },
        )
        self.assertEqual(response.status_code, 200)
        snapshot_events = AuditoriaGestionDTEEvent.objects.filter(action='EXECUTE')
        self.assertEqual(snapshot_events.count(), 1)
        self.assertEqual(snapshot_events.get().message_key, 'auditoria.snapshot.creado')
        self.assertGreater(snapshot_events.get().id, event.id)

    def test_purge_preview_and_dry_run_do_not_delete(self):
        event = self.event()
        batch = self.archive_snapshot([event])
        preview = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'),
            {'action': 'preview_purge', 'batch_id': batch.batch_id},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, 'Eventos archivados: 1')

        dry_run = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'),
            {'action': 'dry_run', 'batch_id': batch.batch_id},
        )
        self.assertEqual(dry_run.status_code, 200)
        self.assertContains(dry_run, 'Listo para limpiar')
        self.assertTrue(AuditoriaBibliotecaEvent.objects.filter(pk=event.pk).exists())

    def test_purge_requires_explicit_confirmation(self):
        event = self.event()
        batch = self.archive_snapshot([event])

        response = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'),
            {'action': 'purge', 'batch_id': batch.batch_id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Debes confirmar la eliminación')
        self.assertTrue(AuditoriaBibliotecaEvent.objects.filter(pk=event.pk).exists())
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'COMPLETED')

    def test_purge_requires_authorization_for_every_batch_company(self):
        first = self.event(empresa=self.empresa_a, suffix='company-a')
        second = self.event(empresa=self.empresa_b, suffix='company-b')
        batch = self.archive_snapshot(
            [first, second],
            companies=[self.empresa_a.id, self.empresa_b.id],
        )
        Permiso.objects.filter(usuario=self.user, empresa=self.empresa_b, vista=self.vista).update(autorizar=False)

        response = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'),
            {'action': 'preview_purge', 'batch_id': batch.batch_id},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(AuditoriaBibliotecaEvent.objects.filter(pk=first.pk).exists())
        self.assertTrue(AuditoriaBibliotecaEvent.objects.filter(pk=second.pk).exists())

    def test_ingresar_without_autorizar_cannot_post_purge(self):
        Permiso.objects.filter(usuario=self.user, vista=self.vista).update(autorizar=False)
        response = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'),
            {'action': 'preview_purge', 'batch_id': 'missing'},
        )
        self.assertEqual(response.status_code, 403)

    def test_execute_button_requires_completed_and_dry_run(self):
        completed = self.archive_snapshot([self.event(suffix='completed')])
        for status in ('PENDING', 'COPYING', 'VALIDATING', 'FAILED', 'PURGING', 'PURGE_FAILED', 'PURGED'):
            batch = AuditArchiveBatch.objects.create(
                batch_id=f'status-{status.lower()}',
                app_label='biblioteca',
                cutoff_datetime=self.cutoff if hasattr(self, 'cutoff') else timezone.now(),
                company_ids=[self.empresa_a.id],
                source_count=1,
                archive_count=1,
                source_checksum='checksum',
                archive_checksum='checksum',
                status=status,
            )
            response = self.client.get(reverse('auditoria:auditoria_biblioteca_archive'))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'Ejecutar limpieza')
            batch.delete()

        validated = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'),
            {'action': 'dry_run', 'batch_id': completed.batch_id},
        )
        self.assertEqual(validated.status_code, 200)
        self.assertContains(validated, 'Ejecutar limpieza')

    def test_real_purge_is_post_only_and_logs_event_after_purge(self):
        presence = UserPresence.objects.create(
            user=self.user,
            empresa_id=self.empresa_a.id,
            app_label='biblioteca',
            vista_nombre=self.vista.nombre,
            path='/archive-ui/',
        )
        archived = self.event(suffix='archived')
        batch = self.archive_snapshot([archived])
        outside = self.event(suffix='outside')

        preview = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'),
            {'action': 'preview_purge', 'batch_id': batch.batch_id},
        )
        self.assertContains(preview, 'Cantidad que será eliminada')
        validated = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'),
            {'action': 'dry_run', 'batch_id': batch.batch_id},
        )
        self.assertContains(validated, 'Ejecutar limpieza')

        response = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'),
            {
                'action': 'purge',
                'batch_id': batch.batch_id,
                'confirm_purge': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Limpieza completada correctamente. Se eliminaron 1 eventos')
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'PURGED')
        self.assertEqual(batch.purged_count, 1)
        self.assertFalse(AuditoriaBibliotecaEvent.objects.filter(pk=archived.pk).exists())
        self.assertTrue(AuditoriaBibliotecaEvent.objects.filter(pk=outside.pk).exists())
        self.assertEqual(len(AuditArchiveService.read_archived_rows(batch)), 1)
        presence.refresh_from_db()
        self.assertEqual(presence.path, '/archive-ui/')

        purge_events = AuditoriaBibliotecaEvent.objects.filter(
            action='EXECUTE',
            message_key='auditoria.snapshot.purgado',
        )
        self.assertEqual(purge_events.count(), 1)
        purge_event = purge_events.get()
        self.assertEqual(
            set(purge_event.meta),
            {'batch_id', 'purged_count', 'company_ids'},
        )
        self.assertEqual(purge_event.meta['batch_id'], batch.batch_id)
        self.assertEqual(purge_event.meta['purged_count'], 1)

    def test_repeated_purge_does_not_delete_or_log_success_again(self):
        event = self.event(suffix='double')
        batch = self.archive_snapshot([event])
        payload = {
            'action': 'purge',
            'batch_id': batch.batch_id,
            'confirm_purge': 'on',
        }
        first = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'), payload,
        )
        self.assertEqual(first.status_code, 302)
        second = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'), payload,
        )
        self.assertEqual(second.status_code, 200)
        self.assertContains(second, 'El batch ya fue purgado')
        self.assertEqual(
            AuditoriaBibliotecaEvent.objects.filter(
                action='EXECUTE', message_key='auditoria.snapshot.purgado',
            ).count(),
            1,
        )

    def test_corrupted_history_rejects_purge_without_delete(self):
        event = self.event(suffix='corrupted')
        batch = self.archive_snapshot([event])
        connection = sqlite3.connect(batch.archive_path)
        try:
            connection.execute(
                "UPDATE audit_event_history SET action='CREATE' WHERE source_event_id=?",
                (event.id,),
            )
            connection.commit()
        finally:
            connection.close()

        response = self.client.post(
            reverse('auditoria:auditoria_biblioteca_archive'),
            {
                'action': 'purge',
                'batch_id': batch.batch_id,
                'confirm_purge': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No fue posible completar la limpieza')
        self.assertTrue(AuditoriaBibliotecaEvent.objects.filter(pk=event.pk).exists())
        self.assertEqual(
            AuditoriaBibliotecaEvent.objects.filter(
                action='EXECUTE', message_key='auditoria.snapshot.purgado',
            ).count(),
            0,
        )
