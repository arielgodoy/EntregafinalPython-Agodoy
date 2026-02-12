from django.test import TestCase, Client
from django.contrib.auth.models import User
from access_control.models import Empresa, PerfilAcceso, UsuarioPerfilEmpresa, Vista, Permiso
from notificaciones.models import Notification


class ForzarNotificacionesNoUsersTests(TestCase):
    """Tests para vista forzar_notificaciones con empresa_objetivo y Permiso"""
    
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(username='staff', password='pass123', is_staff=True)
        self.normal_user = User.objects.create_user(username='normal', password='pass123', is_staff=False)
        self.empresa1 = Empresa.objects.create(codigo='01', descripcion='Empresa 1')
        self.empresa2 = Empresa.objects.create(codigo='02', descripcion='Empresa 2')
        self.perfil = PerfilAcceso.objects.create(nombre='Basico', descripcion='Perfil basico')
        self.vista = Vista.objects.create(nombre='Test Vista', descripcion='Vista de prueba')
        
    def test_sin_empresa_objetivo_muestra_warning(self):
        """Staff sin empresa_objetivo en GET -> vista 200, warning select_company, boton disabled"""
        # Login sin setear empresa activa
        self.client.login(username='staff', password='pass123')
        
        # Request a vista sin empresa_objetivo_id
        response = self.client.get('/notificaciones/forzar/')
        
        # Validaciones
        self.assertEqual(response.status_code, 200)
        self.assertIn('tiene_empresa_objetivo', response.context)
        self.assertFalse(response.context['tiene_empresa_objetivo'])
        self.assertEqual(response.context['warning_key'], 'notifications.force.warning.select_company')
        self.assertIsNone(response.context['empresa_objetivo'])
        
        # HTML contiene warning
        content = response.content.decode('utf-8')
        self.assertIn('notifications.force.warning.select_company', content)
        
    def test_con_empresa_objetivo_y_permisos_lista_usuarios(self):
        """Staff con empresa_objetivo elegida y usuario con Permiso -> lista usuarios"""
        # Crear Permiso (pertenencia real) en empresa1
        Permiso.objects.create(
            usuario=self.normal_user,
            empresa=self.empresa1,
            vista=self.vista,
            ingresar=True
        )
        
        # Login
        self.client.login(username='staff', password='pass123')
        
        # Request con empresa_objetivo_id
        response = self.client.get(f'/notificaciones/forzar/?empresa_objetivo_id={self.empresa1.id}')
        
        # Validaciones
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['tiene_empresa_objetivo'])
        self.assertTrue(response.context['tiene_destinatarios'])
        self.assertEqual(response.context['empresa_objetivo'].id, self.empresa1.id)
        # Debe incluir normal_user + staff_user (fallback)
        self.assertGreaterEqual(len(response.context['destinatarios']), 1)
        usernames = [u.username for u in response.context['destinatarios']]
        self.assertIn('normal', usernames)
        self.assertEqual(response.context['warning_key'], '')
        
    def test_con_empresa_objetivo_sin_permisos_muestra_placeholder(self):
        """Staff con empresa_objetivo sin permisos -> placeholder no_users"""
        # NO crear Permiso en empresa2
        
        # Login
        self.client.login(username='staff', password='pass123')
        
        # Request con empresa_objetivo_id
        response = self.client.get(f'/notificaciones/forzar/?empresa_objetivo_id={self.empresa2.id}')
        
        # Validaciones
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['tiene_empresa_objetivo'])
        # Staff user debe aparecer como fallback
        self.assertTrue(response.context['tiene_destinatarios'])
        self.assertEqual(response.context['empresa_objetivo'].id, self.empresa2.id)
        self.assertEqual(len(response.context['destinatarios']), 1)
        self.assertEqual(response.context['destinatarios'][0].username, 'staff')
        self.assertEqual(response.context['warning_key'], '')
        
    def test_post_genera_notificaciones_con_empresa_objetivo(self):
        """POST genera notificaciones usando empresa_objetivo, no empresa activa"""
        # Crear Permiso
        Permiso.objects.create(
            usuario=self.normal_user,
            empresa=self.empresa1,
            vista=self.vista,
            ingresar=True
        )
        
        # Login con empresa2 en session (diferente a empresa_objetivo)
        self.client.login(username='staff', password='pass123')
        session = self.client.session
        session['empresa_id'] = self.empresa2.id
        session.save()
        
        # POST con empresa_objetivo_id=empresa1
        response = self.client.post('/notificaciones/forzar/', {
            'empresa_objetivo_id': self.empresa1.id,
            'destinatario_id': self.normal_user.id,
            'cantidad': 2,
            'force_membership': 'on',
        })
        
        # Validar redirect
        self.assertEqual(response.status_code, 302)
        
        # Validar notificaciones creadas con empresa_objetivo (empresa1), NO empresa activa (empresa2)
        notifications = Notification.objects.filter(destinatario=self.normal_user)
        self.assertGreater(notifications.count(), 0)
        
        for notif in notifications:
            self.assertEqual(notif.empresa_id, self.empresa1.id, "Notification debe usar empresa_objetivo, no empresa activa")
        
    def test_usuario_no_staff_retorna_403(self):
        """Usuario no staff -> 403"""
        # Login como usuario normal (no staff)
        self.client.login(username='normal', password='pass123')
        
        # Request a vista
        response = self.client.get('/notificaciones/forzar/')
        
        # Validacion
        self.assertEqual(response.status_code, 403)
        
    def test_staff_como_fallback_en_destinatarios(self):
        """Staff user aparece en destinatarios aunque no tenga Permiso explícito"""
        # NO crear Permiso para staff en empresa1
        
        # Login
        self.client.login(username='staff', password='pass123')
        
        # Request con empresa_objetivo_id
        response = self.client.get(f'/notificaciones/forzar/?empresa_objetivo_id={self.empresa1.id}')
        
        # Validaciones: staff debe aparecer como fallback
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['tiene_destinatarios'])
        self.assertIn(self.staff_user, response.context['destinatarios'])
        
    def test_solo_usuarios_activos_en_destinatarios(self):
        """Usuarios inactivos NO aparecen en destinatarios"""
        # Crear usuario inactivo con Permiso
        inactive_user = User.objects.create_user(username='inactive', password='pass123', is_active=False)
        Permiso.objects.create(
            usuario=inactive_user,
            empresa=self.empresa1,
            vista=self.vista,
            ingresar=True
        )
        
        # Login
        self.client.login(username='staff', password='pass123')
        
        # Request
        response = self.client.get(f'/notificaciones/forzar/?empresa_objetivo_id={self.empresa1.id}')
        
        # Validacion: inactive_user NO debe aparecer, solo staff (fallback)
        self.assertEqual(response.status_code, 200)
        user_ids = [u.id for u in response.context['destinatarios']]
        self.assertNotIn(inactive_user.id, user_ids)
        self.assertIn(self.staff_user.id, user_ids)
    
    def test_post_sin_permisos_sin_force_membership_error(self):
        """POST con destinatario sin Permiso y force_membership=False -> error"""
        # NO crear Permiso para normal_user en empresa1
        
        # Login
        self.client.login(username='staff', password='pass123')
        
        # POST sin force_membership
        response = self.client.post('/notificaciones/forzar/', {
            'empresa_objetivo_id': self.empresa1.id,
            'destinatario_id': self.normal_user.id,
            'cantidad': 2,
        })
        
        # Validacion: debe mostrar error_key correcto
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['error_key'], 'notifications.force.error.no_permissions_in_target_company')
        
        # No debe crear notificaciones
        notifications = Notification.objects.filter(destinatario=self.normal_user)
        self.assertEqual(notifications.count(), 0)
    
    def test_post_sin_permisos_con_force_membership_crea_permiso_y_notificaciones(self):
        """POST con destinatario sin Permiso y force_membership=True -> crea Permiso minimo y genera notificaciones"""
        # NO crear Permiso para normal_user en empresa1
        
        # Login
        self.client.login(username='staff', password='pass123')
        
        # POST con force_membership=True
        response = self.client.post('/notificaciones/forzar/', {
            'empresa_objetivo_id': self.empresa1.id,
            'destinatario_id': self.normal_user.id,
            'cantidad': 2,
            'force_membership': 'on',
        })
        
        # Validacion: debe crear notificaciones (redirect 302)
        self.assertEqual(response.status_code, 302)
        
        # Verificar que se creó Permiso mínimo
        permisos = Permiso.objects.filter(usuario=self.normal_user, empresa=self.empresa1)
        self.assertGreater(permisos.count(), 0)
        
        # Verificar que el Permiso creado es mínimo (solo ingresar=True)
        permiso = permisos.first()
        self.assertTrue(permiso.ingresar)
        self.assertFalse(permiso.crear)
        self.assertFalse(permiso.modificar)
        self.assertFalse(permiso.eliminar)
        
        # Verificar que se generaron notificaciones
        notifications = Notification.objects.filter(destinatario=self.normal_user, empresa=self.empresa1)
        self.assertGreater(notifications.count(), 0)
    
    def test_post_con_usuario_inactivo_error(self):
        """POST con destinatario inactivo -> error user_not_found"""
        # Crear usuario inactivo
        inactive_user = User.objects.create_user(username='inactive', password='pass123', is_active=False)
        
        # Login
        self.client.login(username='staff', password='pass123')
        
        # POST con usuario inactivo
        response = self.client.post('/notificaciones/forzar/', {
            'empresa_objetivo_id': self.empresa1.id,
            'destinatario_id': inactive_user.id,
            'cantidad': 2,
            'force_membership': 'on',
        })
        
        # Validacion: debe mostrar error_key user_not_found
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['error_key'], 'notifications.force.error.user_not_found')
        
        # No debe crear notificaciones
        notifications = Notification.objects.filter(destinatario=inactive_user)
        self.assertEqual(notifications.count(), 0)
