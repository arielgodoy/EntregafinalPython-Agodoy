from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, PerfilAcceso, PerfilAccesoDetalle, Vista
from access_control.services.perfiles import apply_profile_to_user_empresa


class PerfilAccesoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        self.vista = Vista.objects.create(nombre='Vista A')

    def test_creacion_perfil_y_detalle(self):
        perfil = PerfilAcceso.objects.create(nombre='BASICO', is_active=True)
        PerfilAccesoDetalle.objects.create(
            perfil=perfil,
            vista=self.vista,
            ingresar=True,
        )
        self.assertEqual(perfil.detalles.count(), 1)

    def test_apply_profile_crea_permiso_si_no_existe(self):
        perfil = PerfilAcceso.objects.create(nombre='BASICO', is_active=True)
        PerfilAccesoDetalle.objects.create(
            perfil=perfil,
            vista=self.vista,
            ingresar=True,
            crear=True,
        )

        apply_profile_to_user_empresa(self.user, self.empresa, perfil, overwrite=False)

        permiso = Permiso.objects.filter(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
        ).first()
        self.assertIsNotNone(permiso)
        self.assertTrue(permiso.ingresar)
        self.assertTrue(permiso.crear)

    def test_apply_profile_no_pisa_permiso_existente(self):
        perfil = PerfilAcceso.objects.create(nombre='BASICO', is_active=True)
        PerfilAccesoDetalle.objects.create(
            perfil=perfil,
            vista=self.vista,
            ingresar=True,
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=False,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

        apply_profile_to_user_empresa(self.user, self.empresa, perfil, overwrite=False)

        permiso = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
        )
        self.assertFalse(permiso.ingresar)


class PerfilInvitacionFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

        Vista.objects.create(nombre='auth_invite')
        Vista.objects.create(nombre='Maestro Usuarios')
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=Vista.objects.get(nombre='auth_invite'),
            ingresar=True,
            crear=True,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

    def test_form_renderiza_perfiles_seed(self):
        call_command('seed_access_control')

        response = self.client.get(reverse('access_control:usuario_crear'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'users.invite.reference_user.label')
