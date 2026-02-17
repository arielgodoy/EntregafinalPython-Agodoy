import time
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from auditoria.helpers import audit_log
from auditoria.models import AuditoriaBibliotecaEvent
from access_control.models import Empresa

User = get_user_model()

class AuditLogHelpersTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='testuser', password='12345')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Test Empresa')

    def test_audit_log_sets_vista_nombre_status_code_duration(self):
        request = self.factory.get('/test/')
        request.user = self.user
        from django.contrib.sessions.backends.db import SessionStore
        request.session = SessionStore()
        request.session['empresa_id'] = self.empresa.id
        request.session.save()
        # Simular tiempos y status
        request._audit_start_time = time.time() - 0.1
        request._audit_response_status_code = 200
        audit_log(
            request=request,
            action='VIEW',
            app_label='biblioteca',
            vista_nombre='VistaTest',
            status_code=None,
            duration_ms=None,
        )
        evento = AuditoriaBibliotecaEvent.objects.filter(action='VIEW').first()
        assert evento.vista_nombre == 'VistaTest'
        assert evento.status_code == 200
        assert evento.duration_ms is not None
