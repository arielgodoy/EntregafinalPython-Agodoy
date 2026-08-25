from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from auditoria.models import AuditoriaBibliotecaEvent, AuditoriaGestionDTEEvent, UserPresence
from auditoria.permissions import get_auditable_company_ids
from auditoria.archive_service import AuditArchiveService
from auditoria.historical_query_service import HistoricalAuditQueryService
from tempfile import TemporaryDirectory
from django.test import override_settings
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone as dt_timezone


User = get_user_model()


class GestionDTEAuditUITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='gestion-auditor', password='secret')
        self.empresa1 = Empresa.objects.create(codigo='01', descripcion='Empresa 1')
        self.empresa2 = Empresa.objects.create(codigo='02', descripcion='Empresa 2')
        self.gestion_vista = Vista.objects.get_or_create(
            nombre='Auditoría - Gestión DTE',
            defaults={'route_name': 'auditoria:auditoria_gestiondte_list'},
        )[0]
        self.biblioteca_vista = Vista.objects.get_or_create(nombre='Auditoría - Biblioteca')[0]
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa1,
            vista=self.gestion_vista,
            ingresar=True,
            autorizar=True,
        )
        self.event1 = AuditoriaGestionDTEEvent.objects.create(
            user=self.user, empresa_id=self.empresa1.id, action='VIEW', path='/gestiondte/cesiones/', status_code=200,
        )
        self.event2 = AuditoriaGestionDTEEvent.objects.create(
            user=self.user, empresa_id=self.empresa2.id, action='VIEW', path='/gestiondte/cesiones/', status_code=200,
        )

    def _activate(self, empresa):
        session = self.client.session
        session['empresa_id'] = empresa.id
        session.save()

    def test_gestiondte_permission_allows_list_and_detail(self):
        self.client.force_login(self.user)
        self._activate(self.empresa1)

        list_response = self.client.get(reverse('auditoria:auditoria_gestiondte_list'))
        detail_response = self.client.get(reverse('auditoria:auditoria_gestiondte_detail', args=[self.event1.pk]))

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        listed_ids = {event.pk for event in list_response.context['eventos']}
        self.assertEqual(listed_ids, {self.event1.pk})

    def test_gestiondte_detail_isolated_by_company(self):
        self.client.force_login(self.user)
        self._activate(self.empresa1)

        response = self.client.get(reverse('auditoria:auditoria_gestiondte_detail', args=[self.event2.pk]))

        self.assertEqual(response.status_code, 404)

    def test_authorized_companies_are_independent_from_active_company(self):
        empresa3 = Empresa.objects.create(codigo='03', descripcion='Empresa 3')
        Permiso.objects.create(usuario=self.user, empresa=empresa3, vista=self.gestion_vista, ingresar=True)
        event3 = AuditoriaGestionDTEEvent.objects.create(
            user=self.user, empresa_id=empresa3.id, action='VIEW', path='/gestiondte/cesiones/', status_code=200,
        )
        self.client.force_login(self.user)
        self._activate(self.empresa2)

        response = self.client.get(reverse('auditoria:auditoria_gestiondte_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual({event.pk for event in response.context['eventos']}, {self.event1.pk, event3.pk})
        self.assertContains(response, '01 - Empresa 1')
        self.assertContains(response, '03 - Empresa 3')
        self.assertContains(response, '/auditoria/gestiondte/')
        self.assertContains(response, '/auditoria/biblioteca/')

    def test_unauthorized_company_filter_returns_404(self):
        self.client.force_login(self.user)
        self._activate(self.empresa1)

        response = self.client.get(
            reverse('auditoria:auditoria_gestiondte_list'),
            {'empresa': self.empresa2.id},
        )

        self.assertEqual(response.status_code, 404)

    def test_authorized_company_detail_ignores_active_company(self):
        empresa3 = Empresa.objects.create(codigo='03', descripcion='Empresa 3')
        Permiso.objects.create(usuario=self.user, empresa=empresa3, vista=self.gestion_vista, ingresar=True)
        event3 = AuditoriaGestionDTEEvent.objects.create(
            user=self.user, empresa_id=empresa3.id, action='VIEW', path='/gestiondte/cesiones/', status_code=200,
        )
        self.client.force_login(self.user)
        self._activate(self.empresa2)

        response = self.client.get(reverse('auditoria:auditoria_gestiondte_detail', args=[event3.pk]))

        self.assertEqual(response.status_code, 200)

    def test_gestiondte_permission_is_independent_from_biblioteca(self):
        self.client.force_login(self.user)
        self._activate(self.empresa1)

        gestion_response = self.client.get(reverse('auditoria:auditoria_gestiondte_list'))
        biblioteca_response = self.client.get(reverse('auditoria:auditoria_biblioteca_list'))

        self.assertEqual(gestion_response.status_code, 200)
        self.assertEqual(biblioteca_response.status_code, 403)
        self.assertContains(gestion_response, '/auditoria/gestiondte/')
        self.assertContains(gestion_response, '/auditoria/biblioteca/')

    def test_gestiondte_without_permission_is_forbidden(self):
        user = User.objects.create_user(username='without-gestion-audit', password='secret')
        self.client.force_login(user)
        self._activate(self.empresa1)

        response = self.client.get(reverse('auditoria:auditoria_gestiondte_list'))

        self.assertEqual(response.status_code, 403)

    def test_authorization_helper_returns_only_true_flags(self):
        empresa3 = Empresa.objects.create(codigo='03', descripcion='Empresa 3')
        Permiso.objects.create(usuario=self.user, empresa=empresa3, vista=self.gestion_vista, ingresar=True)
        empresa5 = Empresa.objects.create(codigo='05', descripcion='Empresa 5')
        Permiso.objects.create(usuario=self.user, empresa=empresa5, vista=self.gestion_vista, ingresar=False)

        self.assertEqual(
            get_auditable_company_ids(self.user, 'Auditoría - Gestión DTE'),
            {self.empresa1.id, empresa3.id},
        )

    def test_authorization_helper_does_not_cross_apps(self):
        biblioteca = Vista.objects.get_or_create(nombre='Auditoría - Biblioteca')[0]
        Permiso.objects.create(usuario=self.user, empresa=self.empresa1, vista=biblioteca, ingresar=True)

        self.assertEqual(
            get_auditable_company_ids(self.user, 'Auditoría - Gestión DTE'),
            {self.empresa1.id},
        )

    def test_biblioteca_event_does_not_appear_in_gestiondte_list(self):
        AuditoriaBibliotecaEvent.objects.create(
            user=self.user, empresa_id=self.empresa1.id, action='VIEW', path='/biblioteca/', status_code=200,
        )
        self.client.force_login(self.user)
        self._activate(self.empresa1)

        response = self.client.get(reverse('auditoria:auditoria_gestiondte_list'))

        self.assertEqual(response.status_code, 200)
        listed_ids = {event.pk for event in response.context['eventos']}
        self.assertEqual(listed_ids, {self.event1.pk})

    def test_latest_views_endpoint_returns_ten_views_only_for_authorized_companies(self):
        empresa3 = Empresa.objects.create(codigo='03', descripcion='Empresa 3')
        Permiso.objects.create(usuario=self.user, empresa=empresa3, vista=self.gestion_vista, ingresar=True)
        empresa5 = Empresa.objects.create(codigo='05', descripcion='Empresa 5')
        Permiso.objects.create(usuario=self.user, empresa=empresa5, vista=self.gestion_vista, ingresar=False)
        for index in range(12):
            AuditoriaGestionDTEEvent.objects.create(
                user=self.user,
                empresa_id=self.empresa1.id if index % 2 == 0 else empresa3.id,
                action='VIEW',
                path=f'/gestiondte/{index}/',
                status_code=200,
            )
        AuditoriaGestionDTEEvent.objects.create(
            user=self.user, empresa_id=empresa5.id, action='VIEW', path='/gestiondte/hidden/', status_code=200,
        )
        AuditoriaGestionDTEEvent.objects.create(
            user=self.user, empresa_id=self.empresa1.id, action='UPDATE', path='/gestiondte/update/', status_code=200,
        )
        self.client.force_login(self.user)
        self._activate(self.empresa2)

        response = self.client.get(
            reverse('auditoria:auditoria_gestiondte_latest_views', args=[self.user.id]),
        )

        self.assertEqual(response.status_code, 200)
        results = list(response.context['eventos'])
        self.assertEqual(len(results), 10)
        self.assertTrue(all(item.empresa_id in {self.empresa1.id, empresa3.id} for item in results))
        self.assertTrue(all(item.path != '/gestiondte/hidden/' for item in results))
        self.assertTrue(all(item.path != '/gestiondte/update/' for item in results))

    def test_latest_views_endpoint_requires_app_specific_permission(self):
        self.client.force_login(self.user)
        self._activate(self.empresa1)

        response = self.client.get(
            reverse('auditoria:auditoria_biblioteca_latest_views', args=[self.user.id]),
        )

        self.assertEqual(response.status_code, 403)

    def test_presence_list_excludes_unauthorized_companies(self):
        UserPresence.objects.create(
            user=User.objects.create_user(username='other-user', password='secret'),
            empresa_id=self.empresa2.id,
            app_label='gestiondte',
            vista_nombre='cesiones',
            path='/gestiondte/cesiones/',
        )
        self.client.force_login(self.user)
        self._activate(self.empresa1)

        response = self.client.get(reverse('auditoria:auditoria_gestiondte_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['presencias'].count(), 0)

    def test_historical_query_sources_are_filtered_and_deduplicated(self):
        with TemporaryDirectory() as archive_root, override_settings(AUDIT_ARCHIVE_ROOT=archive_root):
            old_event = AuditoriaGestionDTEEvent.objects.create(
                user=self.user, empresa_id=self.empresa1.id, action='CREATE',
                path='/historico/old/', object_type='Documento', object_id='old',
                vista_nombre='Gestión DTE', status_code=200,
            )
            batch = AuditArchiveService.run_batch(
                'gestiondte', timezone.now() + timedelta(days=1),
                max_source_id=old_event.id, requested_company_ids=[self.empresa1.id],
                batch_id='historical-ui', user=self.user,
                vista_nombre=self.gestion_vista.nombre,
            )
            self.client.force_login(self.user)
            self._activate(self.empresa1)

            all_response = self.client.get(reverse('auditoria:auditoria_gestiondte_list'))
            self.assertEqual(all_response.status_code, 200)
            all_events = list(all_response.context['eventos'])
            self.assertEqual(sum(event.pk == old_event.pk for event in all_events), 1)
            self.assertTrue(all(event.source == 'active' for event in all_events))
            self.assertContains(all_response, 'Todos los orígenes')

            historical_response = self.client.get(
                reverse('auditoria:auditoria_gestiondte_list'), {'source': 'historical'},
            )
            self.assertEqual(historical_response.status_code, 200)
            self.assertTrue(all(event.source == 'historical' for event in historical_response.context['eventos']))
            self.assertEqual(
                {event.pk for event in historical_response.context['eventos']},
                {self.event1.pk, old_event.pk},
            )
            self.assertContains(historical_response, batch.batch_id)

            active_response = self.client.get(
                reverse('auditoria:auditoria_gestiondte_list'), {'source': 'active'},
            )
            self.assertEqual(active_response.status_code, 200)
            self.assertTrue(all(event.source == 'active' for event in active_response.context['eventos']))

    def test_historical_detail_and_date_filter(self):
        with TemporaryDirectory() as archive_root, override_settings(AUDIT_ARCHIVE_ROOT=archive_root):
            Permiso.objects.filter(
                usuario=self.user, empresa=self.empresa1, vista=self.gestion_vista,
            ).update(autorizar=True)
            event = AuditoriaGestionDTEEvent.objects.create(
                user=self.user, empresa_id=self.empresa1.id, action='VIEW',
                path='/historico/detail/', vista_nombre='Gestión DTE',
            )
            event.created_at = datetime(2026, 1, 15, tzinfo=dt_timezone.utc)
            event.save(update_fields=['created_at'])
            AuditArchiveService.run_batch(
                'gestiondte', datetime(2026, 3, 1, tzinfo=dt_timezone.utc),
                max_source_id=event.id, requested_company_ids=[self.empresa1.id],
                batch_id='historical-detail', user=self.user,
                vista_nombre=self.gestion_vista.nombre,
            )
            self.client.force_login(self.user)
            self._activate(self.empresa1)
            response = self.client.get(
                reverse('auditoria:auditoria_gestiondte_list'),
                {'source': 'historical', 'date_from': '2026-01-01', 'date_to': '2026-03-31'},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual([item.pk for item in response.context['eventos']], [event.id])
            detail = self.client.get(
                reverse('auditoria:auditoria_gestiondte_historical_detail', args=[event.id]),
            )
            self.assertEqual(detail.status_code, 200)
            self.assertContains(detail, 'Histórico (historical-detail)')

    def test_historical_query_ignores_unauthorized_company_and_preserves_file(self):
        with TemporaryDirectory() as archive_root, override_settings(AUDIT_ARCHIVE_ROOT=archive_root):
            archive_user = User.objects.create_user(username='archive-owner', password='secret')
            Permiso.objects.create(
                usuario=archive_user, empresa=self.empresa2,
                vista=self.gestion_vista, ingresar=True, autorizar=True,
            )
            event = AuditoriaGestionDTEEvent.objects.create(
                user=self.user, empresa_id=self.empresa2.id, action='VIEW', path='/hidden/',
            )
            batch = AuditArchiveService.run_batch(
                'gestiondte', timezone.now() + timedelta(days=1), max_source_id=event.id,
                requested_company_ids=[self.empresa2.id], batch_id='hidden-history',
                user=archive_user, vista_nombre=self.gestion_vista.nombre,
            )
            history_path = Path(batch.archive_path)
            before = hashlib.sha256(history_path.read_bytes()).hexdigest()
            result = HistoricalAuditQueryService.query('gestiondte', {self.empresa1.id})
            after = hashlib.sha256(history_path.read_bytes()).hexdigest()
            self.assertEqual(result, [])
            self.assertEqual(before, after)

    def test_multiple_batches_and_purged_event_are_searchable_in_order(self):
        with TemporaryDirectory() as archive_root, override_settings(AUDIT_ARCHIVE_ROOT=archive_root):
            first = AuditoriaGestionDTEEvent.objects.create(
                user=self.user, empresa_id=self.empresa1.id, action='DELETE',
                path='/historico/first/', object_type='Documento', object_id='1',
            )
            first.created_at = datetime(2026, 1, 10, tzinfo=dt_timezone.utc)
            first.save(update_fields=['created_at'])
            first_batch = AuditArchiveService.run_batch(
                'gestiondte', datetime(2026, 1, 11, tzinfo=dt_timezone.utc),
                max_source_id=first.id, requested_company_ids=[self.empresa1.id],
                batch_id='historical-first', user=self.user,
                vista_nombre=self.gestion_vista.nombre,
            )
            first_id = first.id
            first.delete()

            second = AuditoriaGestionDTEEvent.objects.create(
                user=self.user, empresa_id=self.empresa1.id, action='CREATE',
                path='/active/second/', object_type='Documento', object_id='2',
            )
            second.created_at = datetime(2026, 2, 10, tzinfo=dt_timezone.utc)
            second.save(update_fields=['created_at'])
            second_batch = AuditArchiveService.run_batch(
                'gestiondte', datetime(2026, 2, 11, tzinfo=dt_timezone.utc),
                max_source_id=second.id, requested_company_ids=[self.empresa1.id],
                batch_id='historical-second', user=self.user,
                vista_nombre=self.gestion_vista.nombre,
            )
            historical_events = HistoricalAuditQueryService.query(
                'gestiondte', {self.empresa1.id},
            )
            self.assertIn(first_id, {event.pk for event in historical_events})
            self.client.force_login(self.user)
            self._activate(self.empresa1)

            response = self.client.get(reverse('auditoria:auditoria_gestiondte_list'))
            self.assertEqual(response.status_code, 200)
            events = list(response.context['eventos'])
            first_match = next(event for event in events if event.pk == first_id)
            self.assertEqual(first_match.source, 'historical')
            self.assertEqual(first_match.batch_id, first_batch.batch_id)
            self.assertEqual(
                [event.pk for event in events if event.pk in {first_id, second.id}],
                [second.id, first_id],
            )
            self.assertEqual(second_batch.status, 'COMPLETED')

    def test_historical_reuses_action_object_and_user_filters(self):
        with TemporaryDirectory() as archive_root, override_settings(AUDIT_ARCHIVE_ROOT=archive_root):
            event = AuditoriaGestionDTEEvent.objects.create(
                user=self.user, empresa_id=self.empresa1.id, action='EXECUTE',
                path='/historico/filter/', object_type='Certificado', object_id='42',
                vista_nombre='Gestión DTE - Certificados',
            )
            AuditArchiveService.run_batch(
                'gestiondte', timezone.now() + timedelta(days=1),
                max_source_id=event.id, requested_company_ids=[self.empresa1.id],
                batch_id='historical-filters', user=self.user,
                vista_nombre=self.gestion_vista.nombre,
            )
            self.client.force_login(self.user)
            self._activate(self.empresa1)
            response = self.client.get(
                reverse('auditoria:auditoria_gestiondte_list'),
                {
                    'source': 'historical', 'action': 'EXECUTE',
                    'object_type': 'Cert', 'object_id': '42', 'user': self.user.username,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual([item.pk for item in response.context['eventos']], [event.id])