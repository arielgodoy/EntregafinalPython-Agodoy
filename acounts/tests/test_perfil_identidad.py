import base64

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from acounts.models import Avatar


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
        self.avatar = Avatar.objects.get(user=self.user)
        self.avatar.first_name = "Avatar original"
        self.avatar.last_name = "Avatar original"
        self.avatar.email = "avatar@example.com"
        self.avatar.save()
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

    def test_profile_does_not_write_duplicate_avatar_identity_fields(self):
        self._post_profile()

        self.avatar.refresh_from_db()
        self.assertEqual(self.avatar.first_name, "Avatar original")
        self.assertEqual(self.avatar.last_name, "Avatar original")
        self.assertEqual(self.avatar.email, "avatar@example.com")

    def test_profile_keeps_avatar_complementary_fields(self):
        self._post_profile()

        self.avatar.refresh_from_db()
        self.assertEqual(self.avatar.profesion, "Ingeniera")
        self.assertEqual(self.avatar.dni, "12.345.678-5")

    def test_profile_updates_avatar_image(self):
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
        self.assertTrue(self.avatar.imagen.name.endswith("avatar.png"))

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
