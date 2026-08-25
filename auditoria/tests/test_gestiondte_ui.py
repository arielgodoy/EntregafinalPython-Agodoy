from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from auditoria.models import AuditoriaBibliotecaEvent, AuditoriaGestionDTEEvent, UserPresence
from auditoria.permissions import get_auditable_company_ids


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
        Permiso.objects.create(usuario=self.user, empresa=self.empresa1, vista=self.gestion_vista, ingresar=True)
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