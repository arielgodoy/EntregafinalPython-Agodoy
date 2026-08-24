from unittest.mock import patch

from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.urls import resolve
from auditoria.middleware import AuditMiddleware
from auditoria.models import AuditoriaBibliotecaEvent, AuditoriaGestionDTEEvent, UserPresence
from auditoria.helpers import audit_log
from auditoria.services import AuditoriaService
from access_control.models import Empresa

User = get_user_model()


@override_settings(MIDDLEWARE=[
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'auditoria.middleware.AuditMiddleware',
])
class AuditMiddlewareTests(TestCase):
    
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = AuditMiddleware(get_response=lambda r: HttpResponse())
        self.user = User.objects.create_user(username='testuser', password='12345')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Test Empresa')
    
    def _create_request(self, path='/', method='GET', user=None, empresa_id=None):
        """Helper para crear request con sesión."""
        request = getattr(self.factory, method.lower())(path)
        request.user = user or self.user
        
        # Simular sesión
        from django.contrib.sessions.backends.db import SessionStore
        request.session = SessionStore()
        if empresa_id:
            request.session['empresa_id'] = empresa_id
        request.session.save()
        
        return request
    
    def test_middleware_logs_403_biblioteca(self):
        """Test: middleware registra evento 403 en biblioteca."""
        
        # Crear request a biblioteca
        request = self._create_request(
            path='/biblioteca/documentos/', 
            user=self.user,
            empresa_id=self.empresa.id
        )
        
        # Simular respuesta 403
        self.middleware.process_request(request)
        response = HttpResponse(status=403)
        self.middleware.process_response(request, response)
        
        # Verificar evento creado
        eventos = AuditoriaBibliotecaEvent.objects.filter(action='ERROR_403')
        self.assertEqual(eventos.count(), 1)
        
        evento = eventos.first()
        self.assertEqual(evento.user, self.user)
        self.assertEqual(evento.empresa_id, self.empresa.id)
        self.assertEqual(evento.status_code, 403)
        self.assertEqual(evento.path, '/biblioteca/documentos/')
    
    def test_middleware_logs_500_biblioteca(self):
        """Test: middleware registra evento 500 en biblioteca."""
        
        request = self._create_request(
            path='/biblioteca/propiedades/1/',
            user=self.user,
            empresa_id=self.empresa.id
        )
        
        self.middleware.process_request(request)
        response = HttpResponse(status=500)
        self.middleware.process_response(request, response)
        
        eventos = AuditoriaBibliotecaEvent.objects.filter(action='ERROR_500')
        self.assertEqual(eventos.count(), 1)
        self.assertEqual(eventos.first().status_code, 500)
    
    def test_middleware_respects_audit_logged_flag(self):
        """
        FIX C: Test que middleware NO sobrescribe _audit_logged si ya existe.
        La vista puede marcar _audit_logged ANTES de process_request.
        """
        
        request = self._create_request(path='/biblioteca/documentos/')
        
        # FIX C: Marcar como auditado ANTES de process_request
        request._audit_logged = True
        
        # Middleware NO debe sobrescribir
        self.middleware.process_request(request)
        self.assertTrue(request._audit_logged)  # Debe seguir siendo True
        
        # Procesar respuesta exitosa
        response = HttpResponse(status=200)
        self.middleware.process_response(request, response)
        
        # No debe haber creado evento genérico porque ya estaba marcado
        eventos = AuditoriaBibliotecaEvent.objects.filter(action='VIEW')
        self.assertEqual(eventos.count(), 0)
    
    def test_middleware_excludes_static_paths(self):
        """Test: middleware no audita /static/ ni /media/."""
        
        for path in ['/static/css/styles.css', '/media/uploads/doc.pdf']:
            request = self._create_request(path=path)
            self.middleware.process_request(request)
            response = HttpResponse(status=200)
            self.middleware.process_response(request, response)
        
        # No debe haber eventos
        self.assertEqual(AuditoriaBibliotecaEvent.objects.count(), 0)
    
    def test_middleware_initializes_audit_logged_if_not_exists(self):
        """Test: middleware inicializa _audit_logged=False si no existe."""
        
        request = self._create_request(path='/biblioteca/test/')
        
        # Verificar que no existe
        self.assertFalse(hasattr(request, '_audit_logged'))
        
        # Middleware debe inicializarlo
        self.middleware.process_request(request)
        
        # Ahora debe existir y ser False
        self.assertTrue(hasattr(request, '_audit_logged'))
        self.assertFalse(request._audit_logged)

    def test_valid_biblioteca_get_logs_exactly_one_view(self):
        request = self._create_request(path='/biblioteca/', empresa_id=self.empresa.id)

        self.middleware.process_request(request)
        self.middleware.process_response(request, HttpResponse(status=200))

        self.assertEqual(AuditoriaBibliotecaEvent.objects.filter(action='VIEW').count(), 1)
        presence = UserPresence.objects.get(user=self.user)
        self.assertEqual(presence.app_label, 'biblioteca')
        self.assertEqual(presence.empresa_id, self.empresa.id)

    def test_second_navigation_updates_same_presence_row(self):
        first = self._create_request(path='/biblioteca/', empresa_id=self.empresa.id)
        self.middleware.process_request(first)
        self.middleware.process_response(first, HttpResponse(status=200))

        second = self._create_request(path='/gestiondte/cesiones/', empresa_id=self.empresa.id)
        second.resolver_match = resolve(second.path)
        self.middleware.process_request(second)
        self.middleware.process_response(second, HttpResponse(status=200))

        self.assertEqual(UserPresence.objects.filter(user=self.user).count(), 1)
        presence = UserPresence.objects.get(user=self.user)
        self.assertEqual(presence.app_label, 'gestiondte')
        self.assertEqual(presence.path, '/gestiondte/cesiones/')

    def test_ten_navigations_keep_one_presence_row(self):
        for _ in range(10):
            request = self._create_request(path='/biblioteca/', empresa_id=self.empresa.id)
            self.middleware.process_request(request)
            self.middleware.process_response(request, HttpResponse(status=200))

        self.assertEqual(UserPresence.objects.filter(user=self.user).count(), 1)

    def test_non_navigable_requests_do_not_create_presence(self):
        for path, headers in [
            ('/gestiondte/cesiones/', {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}),
            ('/gestiondte/cesiones/', {'HTTP_HX_REQUEST': 'true'}),
            ('/gestiondte/cesiones/', {'HTTP_ACCEPT': 'application/json'}),
            ('/api/v1/', {}),
            ('/static/app.js', {}),
        ]:
            request = self._create_request(path=path, empresa_id=self.empresa.id)
            request.META.update(headers)
            if path.startswith('/gestiondte/'):
                request.resolver_match = resolve(request.path)
            self.middleware.process_request(request)
            self.middleware.process_response(request, HttpResponse(status=200))

        self.assertEqual(UserPresence.objects.count(), 0)

    def test_presence_activity_status_is_calculated(self):
        from datetime import timedelta
        from django.utils import timezone

        presence = UserPresence.objects.create(
            user=self.user,
            empresa_id=self.empresa.id,
            app_label='biblioteca',
            path='/biblioteca/',
            last_seen=timezone.now(),
        )
        self.assertEqual(presence.activity_status, 'Activo')
        presence.last_seen = timezone.now() - timedelta(minutes=10)
        self.assertEqual(presence.activity_status, 'Reciente')
        presence.last_seen = timezone.now() - timedelta(minutes=20)
        self.assertEqual(presence.activity_status, 'Inactivo')

    def test_two_separate_valid_gets_log_two_views(self):
        for _ in range(2):
            request = self._create_request(path='/biblioteca/', empresa_id=self.empresa.id)
            self.middleware.process_request(request)
            self.middleware.process_response(request, HttpResponse(status=200))

        self.assertEqual(AuditoriaBibliotecaEvent.objects.filter(action='VIEW').count(), 2)

    def test_ajax_biblioteca_get_does_not_log_view(self):
        request = self._create_request(path='/biblioteca/', empresa_id=self.empresa.id)
        request.META['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'

        self.middleware.process_request(request)
        self.middleware.process_response(request, HttpResponse(status=200))

        self.assertEqual(AuditoriaBibliotecaEvent.objects.filter(action='VIEW').count(), 0)

    def test_api_request_does_not_log_view(self):
        request = self._create_request(path='/api/v1/', empresa_id=self.empresa.id)

        self.middleware.process_request(request)
        self.middleware.process_response(request, HttpResponse(status=200))

        self.assertEqual(AuditoriaBibliotecaEvent.objects.filter(action='VIEW').count(), 0)

    def test_technical_path_does_not_log_view(self):
        request = self._create_request(path='/static/app.js', empresa_id=self.empresa.id)

        self.middleware.process_request(request)
        self.middleware.process_response(request, HttpResponse(status=200))

        self.assertEqual(AuditoriaBibliotecaEvent.objects.filter(action='VIEW').count(), 0)

    def test_audit_failure_does_not_break_original_response(self):
        request = self._create_request(path='/biblioteca/', empresa_id=self.empresa.id)
        response = HttpResponse(status=200)

        with self.assertLogs('auditoria.helpers', level='ERROR') as logs:
            with patch('auditoria.helpers.AuditoriaService.log_event', side_effect=RuntimeError('db unavailable')):
                audit_log(request, action='VIEW', app_label='biblioteca')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any('Falló el registro de auditoría' in message for message in logs.output))

    def test_middleware_audit_failure_preserves_original_response(self):
        request = self._create_request(path='/biblioteca/', empresa_id=self.empresa.id)
        response = HttpResponse(status=200)
        self.middleware.process_request(request)

        with self.assertLogs('auditoria.middleware', level='ERROR') as logs:
            with patch('auditoria.middleware.AuditoriaService.log_event', side_effect=RuntimeError('db unavailable')):
                returned_response = self.middleware.process_response(request, response)

        self.assertIs(returned_response, response)
        self.assertEqual(returned_response.status_code, 200)
        self.assertTrue(any('Falló el middleware de auditoría' in message for message in logs.output))

    def test_audit_mixin_event_is_not_duplicated_by_middleware(self):
        request = self._create_request(path='/biblioteca/', empresa_id=self.empresa.id)
        self.middleware.process_request(request)
        audit_log(request, action='VIEW', app_label='biblioteca', status_code=200)

        self.middleware.process_response(request, HttpResponse(status=200))

        self.assertEqual(AuditoriaBibliotecaEvent.objects.filter(action='VIEW').count(), 1)

    def test_gestiondte_get_logs_only_gestiondte_event(self):
        request = self._create_request(path='/gestiondte/cesiones/', empresa_id=self.empresa.id)
        request.resolver_match = resolve(request.path)
        self.middleware.process_request(request)

        self.middleware.process_response(request, HttpResponse(status=200))

        self.assertEqual(AuditoriaGestionDTEEvent.objects.filter(action='VIEW').count(), 1)
        self.assertEqual(AuditoriaBibliotecaEvent.objects.filter(action='VIEW').count(), 0)

    def test_two_gestiondte_gets_log_two_views(self):
        for _ in range(2):
            request = self._create_request(path='/gestiondte/cesiones/', empresa_id=self.empresa.id)
            request.resolver_match = resolve(request.path)
            self.middleware.process_request(request)
            self.middleware.process_response(request, HttpResponse(status=200))

        self.assertEqual(AuditoriaGestionDTEEvent.objects.filter(action='VIEW').count(), 2)

    def test_gestiondte_ajax_does_not_log_view(self):
        request = self._create_request(path='/gestiondte/cesiones/', empresa_id=self.empresa.id)
        request.resolver_match = resolve(request.path)
        request.META['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'
        self.middleware.process_request(request)

        self.middleware.process_response(request, HttpResponse(status=200))

        self.assertEqual(AuditoriaGestionDTEEvent.objects.filter(action='VIEW').count(), 0)

    def test_gestiondte_htmx_does_not_log_view(self):
        request = self._create_request(path='/gestiondte/cesiones/', empresa_id=self.empresa.id)
        request.resolver_match = resolve(request.path)
        request.META['HTTP_HX_REQUEST'] = 'true'
        self.middleware.process_request(request)

        self.middleware.process_response(request, HttpResponse(status=200))

        self.assertEqual(AuditoriaGestionDTEEvent.objects.filter(action='VIEW').count(), 0)

    def test_gestiondte_json_does_not_log_view(self):
        request = self._create_request(path='/gestiondte/cesiones/', empresa_id=self.empresa.id)
        request.resolver_match = resolve(request.path)
        request.META['HTTP_ACCEPT'] = 'application/json'
        self.middleware.process_request(request)

        self.middleware.process_response(request, HttpResponse(status=200))

        self.assertEqual(AuditoriaGestionDTEEvent.objects.filter(action='VIEW').count(), 0)

    def test_router_separates_gestiondte_and_biblioteca_events(self):
        request = self._create_request(path='/gestiondte/cesiones/', empresa_id=self.empresa.id)
        gestion_event = AuditoriaService.log_event(
            app_label='gestiondte',
            action='VIEW',
            user=self.user,
            empresa_id=self.empresa.id,
            method='GET',
            path=request.path,
            status_code=200,
        )
        biblioteca_event = AuditoriaService.log_event(
            app_label='biblioteca',
            action='VIEW',
            user=self.user,
            empresa_id=self.empresa.id,
            method='GET',
            path='/biblioteca/',
            status_code=200,
        )

        self.assertIsInstance(gestion_event, AuditoriaGestionDTEEvent)
        self.assertIsInstance(biblioteca_event, AuditoriaBibliotecaEvent)
        self.assertEqual(AuditoriaGestionDTEEvent.objects.count(), 1)
        self.assertEqual(AuditoriaBibliotecaEvent.objects.count(), 1)

    def test_router_ignores_unknown_app(self):
        event = AuditoriaService.log_event(
            app_label='unknown',
            action='VIEW',
            user=self.user,
            empresa_id=self.empresa.id,
            method='GET',
            path='/unknown/',
            status_code=200,
        )

        self.assertIsNone(event)
        self.assertEqual(AuditoriaGestionDTEEvent.objects.count(), 0)
        self.assertEqual(AuditoriaBibliotecaEvent.objects.count(), 0)
