from django.test import TestCase, RequestFactory, Client
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from auditoria.models import AuditoriaBibliotecaEvent
from access_control.models import Empresa, Vista, Permiso
from biblioteca.models import Documento, Propiedad, Propietario, TipoDocumento
from biblioteca.views import respaldo_biblioteca_zip, descargar_documentos_propiedad_zip
import os
import tempfile
from django.conf import settings

User = get_user_model()


class BibliotecaAuditTests(TestCase):
    """Tests de auditoría para endpoints de biblioteca."""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.client = Client()
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
        self.documento = Documento.objects.create(
            tipo_documento=self.tipo_doc,
            nombre_documento='Doc Test',
            propiedad=self.propiedad
        )
        
        # Crear vistas y permisos
        self._create_permissions()
    
    def _create_permissions(self):
        """Crear vistas y permisos necesarios para tests."""
        vista_respaldo = Vista.objects.create(nombre='Biblioteca - Respaldo Biblioteca')
        vista_descargar = Vista.objects.create(nombre='Biblioteca - Descargar Propiedad')
        vista_eliminar = Vista.objects.create(nombre='Biblioteca - Eliminar Documento')
        
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista_respaldo,
            ingresar=True
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista_descargar,
            ingresar=True
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista_eliminar,
            eliminar=True,
            ingresar=True
        )
    
    def _create_request_with_session(self, method='GET', path='/', user=None):
        """Helper para crear request con sesión."""
        request = getattr(self.factory, method.lower())(path)
        request.user = user or self.user
        
        from django.contrib.sessions.backends.db import SessionStore
        request.session = SessionStore()
        request.session['empresa_id'] = self.empresa.id
        request.session.save()
        
        return request
    
    def test_download_backup_zip_logs_event(self):
        """Test: descarga de backup completo registra evento DOWNLOAD."""
        
        # Crear directorio temporal para archivos
        with tempfile.TemporaryDirectory() as tmpdir:
            # Simular carpeta de archivos
            original_media_root = settings.MEDIA_ROOT
            settings.MEDIA_ROOT = tmpdir
            
            archivos_dir = os.path.join(tmpdir, 'archivos_documentos')
            os.makedirs(archivos_dir, exist_ok=True)
            
            # Crear archivo de prueba
            test_file = os.path.join(archivos_dir, 'test.txt')
            with open(test_file, 'w') as f:
                f.write('test content')
            
            try:
                request = self._create_request_with_session(path='/biblioteca/respaldo/')
                
                # Llamar a la función
                response = respaldo_biblioteca_zip(request)
                
                # Verificar respuesta exitosa
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], 'application/zip')
                
                # Verificar evento creado
                eventos = AuditoriaBibliotecaEvent.objects.filter(action='DOWNLOAD')
                self.assertEqual(eventos.count(), 1)
                
                evento = eventos.first()
                self.assertEqual(evento.user, self.user)
                self.assertEqual(evento.empresa_id, self.empresa.id)
                self.assertEqual(evento.action, 'DOWNLOAD')
                self.assertIsNotNone(evento.meta)
                self.assertEqual(evento.meta.get('download_type'), 'backup_zip')
                self.assertIn('filename', evento.meta)
                self.assertIn('file_count', evento.meta)
                self.assertEqual(evento.meta['file_count'], 1)
                
            finally:
                # Restaurar MEDIA_ROOT
                settings.MEDIA_ROOT = original_media_root
    
    def test_download_propiedad_zip_logs_event(self):
        """Test: descarga de ZIP por propiedad registra evento con object_id."""
        
        with tempfile.TemporaryDirectory() as tmpdir:
            original_media_root = settings.MEDIA_ROOT
            settings.MEDIA_ROOT = tmpdir
            
            archivos_dir = os.path.join(tmpdir, 'archivos_documentos')
            os.makedirs(archivos_dir, exist_ok=True)
            
            # Crear archivo de prueba (simular archivo del documento)
            test_file = os.path.join(archivos_dir, 'doc_test.txt')
            with open(test_file, 'w') as f:
                f.write('test document')
            
            # Asignar archivo al documento
            self.documento.archivo.name = 'archivos_documentos/doc_test.txt'
            self.documento.save()
            
            try:
                request = self._create_request_with_session(
                    path=f'/biblioteca/propiedad/{self.propiedad.id}/descargar/'
                )
                
                # Llamar a la función
                response = descargar_documentos_propiedad_zip(request, self.propiedad.id)
                
                # Verificar respuesta exitosa
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], 'application/zip')
                
                # Verificar evento creado
                eventos = AuditoriaBibliotecaEvent.objects.filter(
                    action='DOWNLOAD',
                    object_type='Propiedad'
                )
                self.assertEqual(eventos.count(), 1)
                
                evento = eventos.first()
                self.assertEqual(evento.user, self.user)
                self.assertEqual(evento.empresa_id, self.empresa.id)
                self.assertEqual(evento.object_type, 'Propiedad')
                self.assertEqual(evento.object_id, str(self.propiedad.id))
                self.assertIsNotNone(evento.meta)
                self.assertEqual(evento.meta.get('download_type'), 'propiedad_zip')
                self.assertIn('filename', evento.meta)
                self.assertIn('file_count', evento.meta)
                
            finally:
                settings.MEDIA_ROOT = original_media_root
    
    def test_delete_documento_logs_event(self):
        """Test: eliminación de documento registra evento DELETE."""
        
        from biblioteca.views import EliminarDocumentoView
        from django.http import HttpResponseRedirect
        
        # Crear request con POST (DeleteView requiere POST para confirmar)
        request = self._create_request_with_session(
            method='POST',
            path=f'/biblioteca/documento/{self.documento.id}/eliminar/'
        )
        
        # Crear instancia de la vista
        view = EliminarDocumentoView()
        view.request = request
        view.object = self.documento
        
        # Obtener ID antes de simular delete
        doc_id = self.documento.id
        
        # Simular respuesta exitosa (redirect 302)
        response = HttpResponseRedirect('/success/')
        
        # Validar que debería auditar (POST + redirect)
        self.assertTrue(view._should_audit(request, response))
        
        # Ejecutar auditoría manualmente (en el flujo real lo hace dispatch)
        view._audit_dispatch(request, response)
        
        # Verificar evento creado
        eventos = AuditoriaBibliotecaEvent.objects.filter(
            action='DELETE',
            object_type='Documento'
        )
        self.assertEqual(eventos.count(), 1)
        
        evento = eventos.first()
        self.assertEqual(evento.user, self.user)
        self.assertEqual(evento.empresa_id, self.empresa.id)
        self.assertEqual(evento.object_type, 'Documento')
        self.assertEqual(evento.object_id, str(doc_id))
        self.assertTrue(request._audit_logged)
