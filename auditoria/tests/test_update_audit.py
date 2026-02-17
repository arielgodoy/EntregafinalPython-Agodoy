from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.urls import reverse
from auditoria.models import AuditoriaBibliotecaEvent
from auditoria.services import AuditoriaService
from access_control.models import Empresa, Vista, Permiso
from biblioteca.models import Propiedad, Propietario, TipoDocumento, Documento
from biblioteca.forms import PropiedadForm, PropietarioForm, TipoDocumentoForm
from settings.models import UserPreferences
from unittest.mock import patch, MagicMock
from django.core.files.uploadedfile import SimpleUploadedFile
import json
import tempfile
import os

User = get_user_model()


class UpdateAuditTests(TestCase):
    """Tests de auditoría para operaciones UPDATE y SHARE en biblioteca."""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='testuser', password='12345', email='test@example.com')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Test Empresa')
        
        # Crear datos de prueba
        self.propietario = Propietario.objects.create(
            nombre='Test Propietario',
            rut='12.345.678-9',  # Formato correcto XX.XXX.XXX-X
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
        self.tipo_doc = TipoDocumento.objects.create(nombre='Test Tipo', descricion='Descripción Test')
        
        # Crear archivo temporal para el documento
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        self.temp_file.write(b'PDF test content')
        self.temp_file.close()
        
        # Crear documento con archivo
        with open(self.temp_file.name, 'rb') as f:
            self.documento = Documento.objects.create(
                tipo_documento=self.tipo_doc,
                nombre_documento='Doc Test',
                propiedad=self.propiedad,
                archivo=SimpleUploadedFile('test.pdf', f.read(), content_type='application/pdf')
            )
        
        # Crear vistas y permisos
        self._create_permissions()
        
        # Crear preferencias SMTP para test de SHARE (mockeado)
        UserPreferences.objects.get_or_create(
            user=self.user,
            defaults={
                'smtp_host': 'smtp.test.com',
                'smtp_port': 587,
                'smtp_username': 'test@test.com',
                'smtp_password': 'testpass',
                'smtp_encryption': 'STARTTLS'
            }
        )
    
    def tearDown(self):
        """Limpiar archivos temporales."""
        if hasattr(self, 'temp_file') and os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)
        # Eliminar archivo del documento si existe
        if hasattr(self, 'documento') and self.documento.archivo:
            if os.path.exists(self.documento.archivo.path):
                os.unlink(self.documento.archivo.path)
    
    def _create_permissions(self):
        """Crear vistas y permisos necesarios para tests."""
        vista_mod_propiedad = Vista.objects.create(nombre='Biblioteca - Modificar Propiedad')
        vista_mod_propietario = Vista.objects.create(nombre='Biblioteca - Modificar Propietario')
        vista_mod_tipo = Vista.objects.create(nombre='Biblioteca - Modificar Tipo Documento')
        vista_enviar = Vista.objects.create(nombre='Biblioteca - Enviar Enlace Documento')
        
        for vista in [vista_mod_propiedad, vista_mod_propietario, vista_mod_tipo]:
            Permiso.objects.create(
                usuario=self.user,
                empresa=self.empresa,
                vista=vista,
                modificar=True,
                ingresar=True
            )
        
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista_enviar,
            ingresar=True
        )
    
    def _create_request_with_session(self, method='POST', path='/', data=None):
        """Helper para crear request con sesión."""
        if method == 'POST':
            request = self.factory.post(path, data=data or {})
        else:
            request = self.factory.get(path)
        
        request.user = self.user
        
        from django.contrib.sessions.backends.db import SessionStore
        request.session = SessionStore()
        request.session['empresa_id'] = self.empresa.id
        request.session.save()
        
        return request
    
    def test_update_propiedad_logs_before_after(self):
        """Test: ModificarPropiedadView registra UPDATE con before/after."""
        from biblioteca.views import ModificarPropiedadView
        
        # Limpiar eventos previos
        AuditoriaBibliotecaEvent.objects.all().delete()
        
        # Datos originales
        original_descripcion = self.propiedad.descripcion
        
        # Crear request GET para capturar before
        request_get = self._create_request_with_session('GET', f'/biblioteca/propiedad/{self.propiedad.pk}/modificar/')
        view = ModificarPropiedadView()
        view.request = request_get
        view.kwargs = {'pk': self.propiedad.pk}
        
        # Simular GET para capturar before
        view.dispatch(request_get, pk=self.propiedad.pk)
        
        # Datos modificados
        new_data = {
            'rol': self.propiedad.rol,
            'descripcion': 'Descripción Modificada',
            'direccion': 'Nueva Dirección 456',
            'ciudad': self.propiedad.ciudad,
            'telefono': self.propiedad.telefono,
            'propietario': self.propietario.pk
        }
        
        # Crear request POST
        request_post = self._create_request_with_session('POST', f'/biblioteca/propiedad/{self.propiedad.pk}/modificar/', data=new_data)
        view_post = ModificarPropiedadView()
        view_post.request = request_post
        view_post.kwargs = {'pk': self.propiedad.pk}
        view_post.object = self.propiedad
        view_post._audit_before = view._audit_before  # Transferir snapshot del GET
        
        # Crear form y validar
        form = PropiedadForm(new_data, instance=self.propiedad)
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")
        
        # Ejecutar form_valid
        view_post.form_valid(form)
        
        # Verificar evento de auditoría
        events = AuditoriaBibliotecaEvent.objects.filter(action='UPDATE')
        self.assertEqual(events.count(), 1, "Debe registrarse 1 evento UPDATE")
        
        event = events.first()
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.empresa_id, self.empresa.id)
        self.assertEqual(event.object_type, 'Propiedad')
        self.assertEqual(event.object_id, str(self.propiedad.pk))
        
        # Verificar before/after y changes
        self.assertIsNotNone(event.before, "before debe existir")
        self.assertIsNotNone(event.after, "after debe existir")
        self.assertEqual(event.before['descripcion'], original_descripcion)
        self.assertEqual(event.after['descripcion'], 'Descripción Modificada')
        self.assertEqual(event.meta.get('entity'), 'Propiedad')
        changes = event.meta.get('changes', {})
        self.assertIn('descripcion', changes)
        self.assertEqual(changes['descripcion']['from'], original_descripcion)
        self.assertEqual(changes['descripcion']['to'], 'Descripción Modificada')
    
    def test_update_propietario_logs_before_after(self):
        """Test: ModificarPropietarioView registra UPDATE con before/after."""
        from biblioteca.views import ModificarPropietarioView
        
        # Limpiar eventos previos
        AuditoriaBibliotecaEvent.objects.all().delete()
        
        # Datos originales
        original_nombre = self.propietario.nombre
        
        # Crear request GET para capturar before
        request_get = self._create_request_with_session('GET', f'/biblioteca/propietario/{self.propietario.pk}/modificar/')
        view = ModificarPropietarioView()
        view.request = request_get
        view.kwargs = {'pk': self.propietario.pk}
        view.dispatch(request_get, pk=self.propietario.pk)
        
        # Datos modificados
        new_data = {
            'nombre': 'Propietario Modificado',
            'rut': '12.345.678-5',  # RUT válido con dígito verificador correcto
            'telefono': '987654321',
            'rol': self.propietario.rol
        }
        
        # Crear request POST
        request_post = self._create_request_with_session('POST', f'/biblioteca/propietario/{self.propietario.pk}/modificar/', data=new_data)
        view_post = ModificarPropietarioView()
        view_post.request = request_post
        view_post.kwargs = {'pk': self.propietario.pk}
        view_post.object = self.propietario
        view_post._audit_before = view._audit_before
        
        # Crear form y validar
        form = PropietarioForm(new_data, instance=self.propietario)
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")
        
        # Ejecutar form_valid
        view_post.form_valid(form)
        
        # Verificar evento
        events = AuditoriaBibliotecaEvent.objects.filter(action='UPDATE')
        self.assertEqual(events.count(), 1)
        
        event = events.first()
        self.assertEqual(event.object_type, 'Propietario')
        self.assertIsNotNone(event.before)
        self.assertIsNotNone(event.after)
        self.assertEqual(event.before['nombre'], original_nombre)
        self.assertEqual(event.after['nombre'], 'Propietario Modificado')
        self.assertEqual(event.after['telefono'], '987654321')
        changes = event.meta.get('changes', {})
        self.assertIn('nombre', changes)
        self.assertEqual(changes['nombre']['from'], original_nombre)
        self.assertEqual(changes['nombre']['to'], 'Propietario Modificado')
    
    def test_update_tipo_documento_logs_before_after(self):
        """Test: ModificarTipoDocumentoView.post() registra UPDATE con before/after."""
        from biblioteca.views import ModificarTipoDocumentoView
        
        # Limpiar eventos previos
        AuditoriaBibliotecaEvent.objects.all().delete()
        
        # Datos originales
        original_nombre = self.tipo_doc.nombre
        
        # Datos modificados
        new_data = {
            'nombre': 'Tipo Modificado',
            'descricion': 'Descripción modificada'
        }
        
        # Crear request POST
        request = self._create_request_with_session('POST', f'/biblioteca/tipo/{self.tipo_doc.pk}/modificar/', data=new_data)
        
        # Ejecutar vista
        view = ModificarTipoDocumentoView()
        response = view.post(request, pk=self.tipo_doc.pk)
        
        # Verificar evento
        events = AuditoriaBibliotecaEvent.objects.filter(action='UPDATE')
        self.assertEqual(events.count(), 1)
        
        event = events.first()
        self.assertEqual(event.object_type, 'TipoDocumento')
        self.assertIsNotNone(event.before)
        self.assertIsNotNone(event.after)
        self.assertEqual(event.before['nombre'], original_nombre)
        self.assertEqual(event.after['nombre'], 'Tipo Modificado')
        self.assertEqual(event.meta.get('entity'), 'TipoDocumento')
    
    @patch('biblioteca.views.EmailMultiAlternatives')
    @patch('biblioteca.views.get_connection')
    def test_share_email_link_logs_event(self, mock_connection, mock_email_class):
        """Test: enviar_enlace_documento registra SHARE con metadata."""
        from biblioteca.views import enviar_enlace_documento
        
        # Limpiar eventos previos
        AuditoriaBibliotecaEvent.objects.all().delete()
        
        # Mockear envío de email
        mock_email_instance = MagicMock()
        mock_email_class.return_value = mock_email_instance
        mock_email_instance.send.return_value = 1
        
        # Crear request POST
        email_destino = 'destino@example.com'
        request = self.factory.post(
            f'/biblioteca/documento/{self.documento.pk}/enviar/',
            data={'correo': email_destino}
        )
        request.user = self.user
        
        from django.contrib.sessions.backends.db import SessionStore
        request.session = SessionStore()
        request.session['empresa_id'] = self.empresa.id
        request.session.save()
        
        # Ejecutar vista
        response = enviar_enlace_documento(request, self.documento.pk)
        
        # Verificar response exitoso
        response_data = json.loads(response.content)
        self.assertTrue(response_data.get('success'), f"Expected success, got: {response_data}")
        
        # Verificar evento de auditoría
        events = AuditoriaBibliotecaEvent.objects.filter(action='SHARE')
        self.assertEqual(events.count(), 1, "Debe registrarse 1 evento SHARE")
        
        event = events.first()
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.empresa_id, self.empresa.id)
        self.assertEqual(event.object_type, 'Documento')
        self.assertEqual(event.object_id, str(self.documento.pk))
        
        # Verificar metadata
        self.assertIsNotNone(event.meta)
        self.assertEqual(event.meta.get('share_type'), 'email_link')
        self.assertIn('***@example.com', event.meta.get('to_email_masked', ''))
        self.assertEqual(event.meta.get('rol'), self.propiedad.rol)
        self.assertEqual(event.meta.get('document_name'), self.documento.nombre_documento)
    
    def test_model_to_snapshot_sanitizes_correctly(self):
        """Test: AuditoriaService.model_to_snapshot serializa correctamente."""
        
        # Serializar propiedad
        snapshot = AuditoriaService.model_to_snapshot(self.propiedad)
        
        # Verificar campos esperados
        self.assertEqual(snapshot['rol'], 'ROL-123')
        self.assertEqual(snapshot['descripcion'], 'Test Propiedad')
        self.assertEqual(snapshot['direccion'], 'Calle Test 123')
        self.assertEqual(snapshot['ciudad'], 'Test City')
        self.assertEqual(snapshot['propietario_id'], self.propietario.pk)
        
        # Verificar que ForeignKey se convierte a ID
        self.assertIn('propietario_id', snapshot)
        self.assertNotIn('propietario', snapshot)
    
    def test_model_to_snapshot_handles_none(self):
        """Test: model_to_snapshot retorna None para obj None."""
        snapshot = AuditoriaService.model_to_snapshot(None)
        self.assertIsNone(snapshot)
