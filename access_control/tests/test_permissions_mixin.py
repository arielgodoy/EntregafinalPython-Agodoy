from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.http import JsonResponse
from access_control.models import Empresa, Vista, Permiso
from access_control.views import UsuariosListaView


class TestVerificarPermisoMixinHTML(TestCase):
    """Tests para VerificarPermisoMixin con requests HTML normales"""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.empresa = Empresa.objects.create(codigo='TEST', descripcion='Empresa Test')
        self.vista = Vista.objects.create(nombre='Maestro Usuarios', descripcion='Usuarios')
        
    def test_sin_permiso_retorna_403_html(self):
        """Cuando falta permiso en request HTML, debe retornar 403 con template custom"""
        # Crear permiso con ingresar=False
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=False,
            crear=False,
            modificar=False,
            eliminar=False
        )
        
        # Request HTTP normal
        request = self.factory.get('/access-control/usuarios/')
        request.user = self.user
        request.session = {'empresa_id': self.empresa.id, 'empresa_nombre': f'{self.empresa.codigo} - {self.empresa.descripcion}'}
        
        # Ejecutar vista
        view = UsuariosListaView.as_view()
        response = view(request)
        
        # Validaciones
        self.assertEqual(response.status_code, 403, "Status code debe ser 403, NO 500")
        self.assertNotEqual(response.status_code, 500, "NO debe retornar error 500")
        
        # Verificar que se renderiza template o contiene texto del 403_forbidden.html
        content = response.content.decode('utf-8')
        # El template 403_forbidden.html contiene estos textos distintivos
        tiene_error_403 = (
            'No tienes permiso' in content or
            'Acceso Denegado' in content or
            'error_403' in content or
            'Maestro Usuarios' in content
        )
        self.assertTrue(tiene_error_403, "Debe renderizar contenido del template 403_forbidden.html")


class TestVerificarPermisoMixinAJAX(TestCase):
    """Tests para VerificarPermisoMixin con requests AJAX"""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='testajax', password='testpass123')
        self.empresa = Empresa.objects.create(codigo='AJAX', descripcion='Test AJAX')
        self.vista = Vista.objects.create(nombre='Maestro Usuarios', descripcion='Usuarios')
        
    def test_sin_permiso_retorna_403_json(self):
        """Cuando falta permiso en request AJAX, debe retornar 403 JSON"""
        # Crear permiso con ingresar=False
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=False,
            crear=False,
            modificar=False,
            eliminar=False
        )
        
        # Request AJAX con header X-Requested-With
        request = self.factory.get('/access-control/usuarios/')
        request.user = self.user
        request.session = {'empresa_id': self.empresa.id, 'empresa_nombre': f'{self.empresa.codigo}'}
        request.META['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'
        
        # Ejecutar vista
        view = UsuariosListaView.as_view()
        response = view(request)
        
        # Validaciones
        self.assertEqual(response.status_code, 403, "Status code debe ser 403 para AJAX")
        self.assertIsInstance(response, JsonResponse, "Response debe ser JsonResponse")
        
        # Verificar contenido JSON
        import json
        data = json.loads(response.content)
        self.assertFalse(data.get('success'), "success debe ser False")
        self.assertIn('error', data, "Debe incluir campo error")
        self.assertIn('permiso', data['error'].lower(), "Mensaje debe mencionar permiso")


class TestVerificarPermisoMixinConPermiso(TestCase):
    """Tests para verificar que con permiso correcto funciona normal"""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='authorized', password='testpass123')
        self.empresa = Empresa.objects.create(codigo='AUTH', descripcion='Autorizado')
        self.vista = Vista.objects.create(nombre='Maestro Usuarios', descripcion='Usuarios')
        
    def test_con_permiso_funciona_normal(self):
        """Cuando tiene permiso, la vista debe ejecutar normalmente sin 403"""
        # Crear permiso con ingresar=True
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,  # TIENE PERMISO
            crear=False,
            modificar=False,
            eliminar=False
        )
        
        # Request HTTP normal
        request = self.factory.get('/access-control/usuarios/')
        request.user = self.user
        request.session = {'empresa_id': self.empresa.id, 'empresa_nombre': self.empresa.codigo}
        
        # Ejecutar vista
        view = UsuariosListaView.as_view()
        response = view(request)
        
        # Validaciones - debe funcionar normalmente
        self.assertEqual(response.status_code, 200, "Con permiso debe retornar 200")
        self.assertNotEqual(response.status_code, 403, "NO debe retornar 403 cuando tiene permiso")
        self.assertNotEqual(response.status_code, 500, "NO debe retornar error 500")
