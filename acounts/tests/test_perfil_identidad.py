import base64

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from acounts.models import Avatar


def _set_permission(user, empresa, vista_name, **flags):
    vista, _ = Vista.objects.get_or_create(nombre=vista_name)
    permiso, _ = Permiso.objects.get_or_create(
        usuario=user,
        empresa=empresa,
        vista=vista,
    )
    permiso.ingresar = flags.get('ingresar', False)
    permiso.crear = flags.get('crear', False)
    permiso.modificar = flags.get('modificar', False)
    permiso.eliminar = flags.get('eliminar', False)
    permiso.autorizar = flags.get('autorizar', False)
    permiso.supervisor = flags.get('supervisor', False)
    permiso.save()
    return permiso


class PerfilIdentidadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="perfil-user",
            password="pass1234",
            first_name="Nombre original",
            last_name="Apellido original",
            email="original@example.com",
        )
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        perfil_vista = Vista.objects.create(nombre="Accounts - Editar Perfil")
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=perfil_vista,
            modificar=True,
        )
        password_vista = Vista.objects.create(nombre="Accounts - Cambiar Password")
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=password_vista,
            modificar=True,
        )
        self.avatar = Avatar.objects.get(user=self.user)
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def _post_profile(self, **data):
        payload = {
            "username": self.user.username,
            "first_name": "Nombre nuevo",
            "last_name": "Apellido nuevo",
            "email": "nuevo@example.com",
            "profesion": "Ingeniera",
            "dni": "12.345.678-5",
        }
        payload.update(data)
        return self.client.post(reverse("editar_perfil"), payload)

    def test_profile_updates_user_first_name(self):
        response = self._post_profile()

        self.assertRedirects(response, reverse("editar_perfil"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Nombre nuevo")

    def test_profile_updates_user_last_name(self):
        self._post_profile()

        self.user.refresh_from_db()
        self.assertEqual(self.user.last_name, "Apellido nuevo")

    def test_profile_updates_user_email(self):
        self._post_profile()

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "nuevo@example.com")

    def test_avatar_has_no_duplicate_identity_fields(self):
        avatar_fields = {field.name for field in Avatar._meta.get_fields()}

        self.assertNotIn("username", avatar_fields)
        self.assertNotIn("first_name", avatar_fields)
        self.assertNotIn("last_name", avatar_fields)
        self.assertNotIn("email", avatar_fields)

    def test_profile_keeps_avatar_complementary_fields(self):
        self._post_profile()

        self.avatar.refresh_from_db()
        self.assertEqual(self.avatar.profesion, "Ingeniera")
        self.assertEqual(self.avatar.dni, "12.345.678-5")

    def test_profile_updates_avatar_image(self):
        previous_image_name = self.avatar.imagen.name
        image = SimpleUploadedFile(
            "avatar.png",
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ),
            content_type="image/png",
        )

        response = self._post_profile(imagen=image)

        self.assertRedirects(response, reverse("editar_perfil"), fetch_redirect_response=False)
        self.avatar.refresh_from_db()
        self.assertNotEqual(self.avatar.imagen.name, previous_image_name)

    def test_profile_does_not_change_username(self):
        self._post_profile(username="otro-usuario")

        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "perfil-user")

    def test_profile_template_renders_identity_fields_from_user_form(self):
        response = self.client.get(reverse("editar_perfil"))
        content = response.content.decode("utf-8")

        self.assertContains(response, 'name="first_name"')
        self.assertContains(response, 'name="last_name"')
        self.assertContains(response, 'name="email"')
        self.assertIn('value="Nombre original"', content)
        self.assertIn('value="Apellido original"', content)
        self.assertIn('value="original@example.com"', content)

    def test_profile_template_has_both_tabs_and_password_fields(self):
        response = self.client.get(reverse("editar_perfil"))
        content = response.content.decode("utf-8")

        self.assertContains(response, 'href="#personalDetails"')
        self.assertContains(response, 'href="#passwordChange"')
        self.assertContains(response, 'Datos personales')
        self.assertContains(response, 'Cambiar contraseña')
        self.assertContains(response, 'name="old_password"')
        self.assertContains(response, 'name="new_password1"')
        self.assertContains(response, 'name="new_password2"')
        self.assertIn('id="passwordChange"', content)

    def test_password_change_with_incorrect_old_password_keeps_user_and_does_not_change_password(self):
        old_password = "pass1234"
        response = self.client.post(
            reverse("editar_perfil"),
            {
                "form_action": "password",
                "old_password": "wrong-password",
                "new_password1": "NewPass123!",
                "new_password2": "NewPass123!",
            },
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(old_password))
        self.assertContains(response, 'Por favor corrige los errores abajo.')
        self.assertContains(response, 'id="passwordChange"')

    def test_password_change_with_valid_old_password_updates_password_and_keeps_session(self):
        response = self.client.post(
            reverse("editar_perfil"),
            {
                "form_action": "password",
                "old_password": "pass1234",
                "new_password1": "NewPass123!",
                "new_password2": "NewPass123!",
            },
            follow=True,
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPass123!"))
        self.assertTrue(self.client.session.session_key is not None)
        self.assertContains(response, "Tu contraseña ha sido cambiada con éxito.")

    def test_profile_error_keeps_personal_tab_active(self):
        response = self.client.post(
            reverse("editar_perfil"),
            {
                "form_action": "profile",
                "username": self.user.username,
                "first_name": "",
                "last_name": "Apellido nuevo",
                "email": "invalid-email",
                "profesion": "Ingeniera",
                "dni": "12.345.678-5",
            },
        )

        self.assertContains(response, 'id="personalDetails"')
        self.assertContains(response, 'class="tab-pane fade show active"', count=1)
        self.assertContains(response, 'Revisa los datos ingresados.')

    def test_password_change_does_not_update_profile_fields(self):
        self.client.post(
            reverse("editar_perfil"),
            {
                "form_action": "password",
                "old_password": "pass1234",
                "new_password1": "NewPass123!",
                "new_password2": "NewPass123!",
            },
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Nombre original")
        self.assertEqual(self.user.last_name, "Apellido original")
        self.assertEqual(self.user.email, "original@example.com")

    def test_legacy_change_password_url_still_renders_password_form(self):
        response = self.client.get(reverse("cambiar_password"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="old_password"')
        self.assertContains(response, 'name="new_password1"')
        self.assertContains(response, 'name="new_password2"')

    def test_user_with_profile_permission_only_cannot_submit_password_change(self):
        Permiso.objects.filter(usuario=self.user, empresa=self.empresa).delete()
        _set_permission(self.user, self.empresa, "Accounts - Editar Perfil", modificar=True)

        response = self.client.post(
            reverse("editar_perfil"),
            {
                "form_action": "password",
                "old_password": "pass1234",
                "new_password1": "NewPass123!",
                "new_password2": "NewPass123!",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("pass1234"))

    def test_user_with_profile_and_password_permission_can_change_password_from_profile_tab(self):
        Permiso.objects.filter(usuario=self.user, empresa=self.empresa).delete()
        _set_permission(self.user, self.empresa, "Accounts - Editar Perfil", modificar=True)
        _set_permission(self.user, self.empresa, "Accounts - Cambiar Password", modificar=True)

        response = self.client.post(
            reverse("editar_perfil"),
            {
                "form_action": "password",
                "old_password": "pass1234",
                "new_password1": "NewPass123!",
                "new_password2": "NewPass123!",
            },
            follow=True,
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPass123!"))
        self.assertContains(response, "Tu contraseña ha sido cambiada con éxito.")

    def test_avatar_upload_template_reads_identity_from_user(self):
        response = self.client.get(reverse("subeavatar"))

        self.assertContains(response, "Nombre original")
        self.assertContains(response, "Apellido original")
        self.assertContains(response, "original@example.com")
