from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.http import HttpResponse, HttpResponseRedirect
from django.views.generic import CreateView, DetailView
from auditoria.mixins import AuditMixin
from auditoria.models import AuditoriaBibliotecaEvent
from access_control.models import Empresa
from biblioteca.models import Documento, Propiedad, Propietario, TipoDocumento

User = get_user_model()


class TestDocumentoCreateView(AuditMixin, CreateView):
    """Vista de prueba para testing del mixin."""
    model = Documento
    fields = ['tipo_documento', 'nombre_documento', 'propiedad']
    audit_action = 'CREATE'
    audit_app_label = 'biblioteca'
    template_name = 'test.html'
    vista_nombre = 'DocumentoCreateTest'

    def form_valid(self, form):
        self.object = form.save()
        return HttpResponseRedirect('/success/')


class TestPropiedadDetailView(AuditMixin, DetailView):
    """Vista de prueba para testing VIEW."""
    model = Propiedad
    audit_action = 'VIEW'
    audit_app_label = 'biblioteca'
    template_name = 'test.html'


class AuditMixinTests(TestCase):
    
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='testuser', password='12345')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Test Empresa')
        
        # Crear datos de prueba para biblioteca
        self.propietario = Propietario.objects.create(
            nombre='Test Propietario',
            rut='12345678-9',
            telefono='123456789',
            rol='persona'
        )
        self.propiedad = Propiedad.objects.create(
            rol='ROL-123',
            descripcion='Test Propiedad',
            direccion='Calle Test 123',
            ciudad='Test City',
            propietario=self.propietario
        )
        self.tipo_doc = TipoDocumento.objects.create(nombre='Test Tipo')
    
    def _create_request_with_session(self, method='POST', path='/test/'):
        """Helper para crear request con sesión."""
        request = getattr(self.factory, method.lower())(path)
        request.user = self.user
        
        from django.contrib.sessions.backends.db import SessionStore
        request.session = SessionStore()
        request.session['empresa_id'] = self.empresa.id
        request.session.save()
        
        return request
    
    def test_mixin_logs_create_on_successful_post_with_redirect(self):
        """AuditMixin registra CREATE con vista_nombre y after snapshot."""
        request = self._create_request_with_session(method='POST')
        view = TestDocumentoCreateView()
        view.request = request
        view.object = Documento.objects.create(
            tipo_documento=self.tipo_doc,
            nombre_documento='Doc Test',
            propiedad=self.propiedad
        )
        response = HttpResponseRedirect('/success/')
        self.assertTrue(view._should_audit(request, response))
        view._audit_dispatch(request, response)
        eventos = AuditoriaBibliotecaEvent.objects.filter(action='CREATE')
        self.assertEqual(eventos.count(), 1)
        evento = eventos.first()
        self.assertEqual(evento.user, self.user)
        self.assertEqual(evento.empresa_id, self.empresa.id)
        self.assertEqual(evento.object_type, 'Documento')
        self.assertTrue(request._audit_logged)
        self.assertEqual(evento.vista_nombre, 'DocumentoCreateTest')
        self.assertIsNotNone(evento.after)
        self.assertIsNone(evento.before)
    
    def test_mixin_does_not_log_create_on_get(self):
        """FIX A: AuditMixin NO registra CREATE en GET (formulario vacío)."""
        
        request = self._create_request_with_session(method='GET')
        
        view = TestDocumentoCreateView()
        view.request = request
        
        # GET retorna 200 (formulario vacío)
        response = HttpResponse(status=200)
        
        # Validar que NO debe auditar (GET con action=CREATE)
        self.assertFalse(view._should_audit(request, response))
        
        # No debe haber eventos
        eventos = AuditoriaBibliotecaEvent.objects.filter(action='CREATE')
        self.assertEqual(eventos.count(), 0)
    
    def test_mixin_logs_view_only_on_get_200(self):
        """FIX A: AuditMixin registra VIEW solo en GET exitoso (200)."""
        
        request = self._create_request_with_session(method='GET', path='/biblioteca/propiedad/1/')
        
        view = TestPropiedadDetailView()
        view.request = request
        view.object = self.propiedad
        
        # GET exitoso retorna 200
        response = HttpResponse(status=200)
        
        # Validar que SÍ debe auditar (GET + 200 + action=VIEW)
        self.assertTrue(view._should_audit(request, response))
        
        # Ejecutar auditoría
        view._audit_dispatch(request, response)
        
        # Verificar evento creado
        eventos = AuditoriaBibliotecaEvent.objects.filter(action='VIEW')
        self.assertEqual(eventos.count(), 1)
        
        evento = eventos.first()
        self.assertEqual(evento.action, 'VIEW')
        self.assertEqual(evento.object_type, 'Propiedad')
        self.assertEqual(evento.object_id, str(self.propiedad.pk))
    
    def test_mixin_does_not_log_view_on_post(self):
        """FIX A: AuditMixin NO registra VIEW en POST."""
        
        request = self._create_request_with_session(method='POST')
        
        view = TestPropiedadDetailView()
        view.request = request
        view.object = self.propiedad
        
        response = HttpResponse(status=200)
        
        # Validar que NO debe auditar (POST con action=VIEW)
        self.assertFalse(view._should_audit(request, response))
        
        # No debe haber eventos
        eventos = AuditoriaBibliotecaEvent.objects.filter(action='VIEW')
        self.assertEqual(eventos.count(), 0)
