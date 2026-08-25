from datetime import timedelta
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from auditoria.archive_service import AuditArchiveService
from auditoria.models import AuditArchiveBatch, AuditoriaBibliotecaEvent, AuditoriaGestionDTEEvent

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
