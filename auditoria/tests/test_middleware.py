from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from auditoria.middleware import AuditMiddleware
from auditoria.models import AuditoriaBibliotecaEvent
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
