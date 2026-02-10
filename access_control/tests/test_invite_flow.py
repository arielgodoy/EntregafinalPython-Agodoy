import re
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.mail import send_mail
from django.test import TestCase
from django.urls import reverse

from acounts.models import SystemConfig, UserEmailToken
from access_control.models import Empresa, Permiso, Vista


class InviteUserFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='testpass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        self.empresa_sec = Empresa.objects.create(codigo='02', descripcion='Empresa 02')
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def _grant_invite_perm(self, allow_create=True):
        vista_auth = Vista.objects.create(nombre='auth_invite')
        Vista.objects.create(nombre='Maestro Usuarios')
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista_auth,
            ingresar=True,
            crear=allow_create,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

    def test_permiso_denegado_retorna_403(self):
        self._grant_invite_perm(allow_create=False)
        response = self.client.post(reverse('access_control:usuario_crear'), data={
            'email': 'invite@test.local',
            'first_name': 'Inv',
            'last_name': 'User',
            'tipo_usuario': 'PROFESIONAL',
        })
        self.assertEqual(response.status_code, 403)

    def test_config_sin_public_base_url_muestra_error(self):
        self._grant_invite_perm(allow_create=True)
        response = self.client.post(reverse('access_control:usuario_crear'), data={
            'email': 'invite@test.local',
            'first_name': 'Inv',
            'last_name': 'User',
            'tipo_usuario': 'PROFESIONAL',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'errors.company_config.public_base_url_required')

    @patch('access_control.services.invite.send_security_email')
    def test_invite_crea_usuario_inactivo_y_token_no_consumido_en_get(self, mock_send):
        self._grant_invite_perm(allow_create=True)
        SystemConfig.objects.create(
            is_active=True,
            public_base_url='http://testserver',
            default_from_email='noreply@test.local',
            default_from_name='Test System',
        )

        def _send_mail_side_effect(**kwargs):
            send_mail(
                kwargs['subject'],
                kwargs['body_text'],
                'noreply@test.local',
                kwargs['to_emails'],
            )
            return {'success': True}

        mock_send.side_effect = _send_mail_side_effect

        response = self.client.post(reverse('access_control:usuario_crear'), data={
            'email': 'invite@test.local',
            'first_name': 'Inv',
            'last_name': 'User',
            'tipo_usuario': 'PROFESIONAL',
        })
        self.assertEqual(response.status_code, 302)

        invited = User.objects.get(username='invite@test.local')
        self.assertFalse(invited.is_active)
        self.assertFalse(invited.has_usable_password())

        token_obj = UserEmailToken.objects.filter(user=invited).first()
        self.assertIsNotNone(token_obj)
        self.assertIsNone(token_obj.used_at)

        self.assertEqual(len(mail.outbox), 1)
        token_match = re.search(r'/auth/activate/([^/]+)/', mail.outbox[0].body)
        self.assertIsNotNone(token_match)

        token_plain = token_match.group(1)
        response = self.client.get(reverse('acounts_activation:activate', args=[token_plain]))
        self.assertEqual(response.status_code, 200)

        token_obj.refresh_from_db()
        self.assertIsNone(token_obj.used_at)

    @patch('access_control.services.invite.send_security_email')
    def test_mail_contiene_link_activacion(self, mock_send):
        self._grant_invite_perm(allow_create=True)
        SystemConfig.objects.create(
            is_active=True,
            public_base_url='http://testserver',
            default_from_email='noreply@test.local',
            default_from_name='Test System',
        )

        def _send_mail_side_effect(**kwargs):
            send_mail(
                kwargs['subject'],
                kwargs['body_text'],
                'noreply@test.local',
                kwargs['to_emails'],
            )
            return {'success': True}

        mock_send.side_effect = _send_mail_side_effect

        response = self.client.post(reverse('access_control:usuario_crear'), data={
            'email': 'link@test.local',
            'first_name': 'Link',
            'last_name': 'User',
            'tipo_usuario': 'PROFESIONAL',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertRegex(mail.outbox[0].body, r'/auth/activate/[^/]+/')

    def test_invitar_usuario_sin_perfil_retiene_error(self):
        self._grant_invite_perm(allow_create=True)
        SystemConfig.objects.create(
            is_active=True,
            public_base_url='http://testserver',
            default_from_email='noreply@test.local',
            default_from_name='Test System',
        )

        response = self.client.post(reverse('access_control:usuario_crear'), data={
            'email': 'user@test.local',
            'first_name': 'User',
            'last_name': 'NoProfile',
            'tipo_usuario': 'USUARIO',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'validation.reference_required')

    @patch('access_control.services.invite.send_security_email')
    def test_invitar_profesional_no_requiere_perfil(self, mock_send):
        self._grant_invite_perm(allow_create=True)
        SystemConfig.objects.create(
            is_active=True,
            public_base_url='http://testserver',
            default_from_email='noreply@test.local',
            default_from_name='Test System',
        )

        def _send_mail_side_effect(**kwargs):
            send_mail(
                kwargs['subject'],
                kwargs['body_text'],
                'noreply@test.local',
                kwargs['to_emails'],
            )
            return {'success': True}

        mock_send.side_effect = _send_mail_side_effect

        response = self.client.post(reverse('access_control:usuario_crear'), data={
            'email': 'pro@test.local',
            'first_name': 'Pro',
            'last_name': 'User',
            'tipo_usuario': 'PROFESIONAL',
        })
        self.assertEqual(response.status_code, 302)

        invited = User.objects.get(username='pro@test.local')
        permisos = Permiso.objects.filter(usuario=invited).count()
        self.assertGreaterEqual(permisos, 1)

    @patch('access_control.services.invite.send_security_email')
    def test_invitar_usuario_con_referencia_clona_permisos(self, mock_send):
        self._grant_invite_perm(allow_create=True)
        SystemConfig.objects.create(
            is_active=True,
            public_base_url='http://testserver',
            default_from_email='noreply@test.local',
            default_from_name='Test System',
        )

        vista = Vista.objects.create(nombre='Vista Referencia')
        usuario_ref = User.objects.create_user(username='referencia', password='pass')
        Permiso.objects.create(
            usuario=usuario_ref,
            empresa=self.empresa,
            vista=vista,
            ingresar=True,
            crear=True,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

        def _send_mail_side_effect(**kwargs):
            send_mail(
                kwargs['subject'],
                kwargs['body_text'],
                'noreply@test.local',
                kwargs['to_emails'],
            )
            return {'success': True}

        mock_send.side_effect = _send_mail_side_effect

        response = self.client.post(reverse('access_control:usuario_crear'), data={
            'email': 'user-profile@test.local',
            'first_name': 'User',
            'last_name': 'Profile',
            'tipo_usuario': 'USUARIO',
            'usuario_referencia': usuario_ref.id,
        })
        self.assertEqual(response.status_code, 302)

        invited = User.objects.get(username='user-profile@test.local')
        permiso = Permiso.objects.filter(
            usuario=invited,
            empresa=self.empresa,
            vista=vista,
        ).first()
        self.assertIsNotNone(permiso)
        self.assertTrue(permiso.ingresar)

    @patch('access_control.services.invite.send_security_email')
    def test_invitar_multiempresa_crea_permisos_y_meta(self, mock_send):
        self._grant_invite_perm(allow_create=True)
        SystemConfig.objects.create(
            is_active=True,
            public_base_url='http://testserver',
            default_from_email='noreply@test.local',
            default_from_name='Test System',
        )

        def _send_mail_side_effect(**kwargs):
            send_mail(
                kwargs['subject'],
                kwargs['body_text'],
                'noreply@test.local',
                kwargs['to_emails'],
            )
            return {'success': True}

        mock_send.side_effect = _send_mail_side_effect

        response = self.client.post(reverse('access_control:usuario_crear'), data={
            'email': 'multi@test.local',
            'first_name': 'Multi',
            'last_name': 'Empresa',
            'tipo_usuario': 'PROFESIONAL',
            'empresas': [self.empresa.id, self.empresa_sec.id],
        })
        self.assertEqual(response.status_code, 302)

        invited = User.objects.get(username='multi@test.local')
        permisos = Permiso.objects.filter(
            usuario=invited,
            vista__nombre='Maestro Usuarios',
        )
        self.assertEqual(permisos.count(), 2)

        token_obj = UserEmailToken.objects.filter(user=invited).first()
        self.assertIsNotNone(token_obj)
        self.assertIn('empresa_ids', token_obj.meta)
        self.assertEqual(
            sorted(token_obj.meta.get('empresa_ids')),
            sorted([self.empresa.id, self.empresa_sec.id]),
        )

    def test_endpoint_usuarios_por_empresas_filtra_por_permiso(self):
        vista_auth = Vista.objects.create(nombre='auth_invite')
        vista_base = Vista.objects.create(nombre='Maestro Usuarios')
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista_auth,
            ingresar=True,
            crear=True,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista_base,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

        usuario_ref = User.objects.create_user(username='ref', password='pass')
        Permiso.objects.create(
            usuario=usuario_ref,
            empresa=self.empresa,
            vista=vista_base,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

        response = self.client.get(
            reverse('access_control:usuarios_por_empresas_json'),
            {'empresa_ids': str(self.empresa.id)},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ref')
