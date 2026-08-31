from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


class CopyPermisosViewTests(TestCase):
    vista_nombre = "Control de Acceso - Maestro Permisos"

    def setUp(self):
        self.operator = User.objects.create_user(username="operator", password="pass123")
        self.origen_usuario = User.objects.create_user(username="origen", password="pass123")
        self.destino_usuario = User.objects.create_user(username="destino", password="pass123")
        self.empresa_origen = Empresa.objects.create(codigo="01", descripcion="Origen")
        self.empresa_destino = Empresa.objects.create(codigo="02", descripcion="Destino")
        self.vista_control = Vista.objects.create(nombre=self.vista_nombre)
        self.vista_copiada = Vista.objects.create(nombre="Modulo - Vista Copiada")
        Permiso.objects.create(
            usuario=self.operator,
            empresa=self.empresa_origen,
            vista=self.vista_control,
            supervisor=True,
        )
        Permiso.objects.create(
            usuario=self.origen_usuario,
            empresa=self.empresa_origen,
            vista=self.vista_copiada,
            ingresar=True,
            crear=True,
            modificar=True,
            eliminar=False,
            autorizar=True,
            supervisor=False,
        )
        self.client.force_login(self.operator)
        session = self.client.session
        session["empresa_id"] = self.empresa_origen.id
        session.save()

    def _copy(self, **overrides):
        data = {
            "origen_usuario": self.origen_usuario.id,
            "origen_empresa": self.empresa_origen.id,
            "destino_usuario": self.destino_usuario.id,
            "destino_empresa": self.empresa_destino.id,
        }
        data.update(overrides)
        return self.client.post(
            reverse("access_control:copy_permissions"),
            data,
            HTTP_ACCEPT="application/json",
        )

    def test_copia_permisos_con_flags_icmeas_sin_modificarlos(self):
        response = self._copy()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["message"], "Permisos copiados correctamente.")
        permiso = Permiso.objects.get(
            usuario=self.destino_usuario,
            empresa=self.empresa_destino,
            vista=self.vista_copiada,
        )
        self.assertTrue(permiso.ingresar)
        self.assertTrue(permiso.crear)
        self.assertTrue(permiso.modificar)
        self.assertFalse(permiso.eliminar)
        self.assertTrue(permiso.autorizar)
        self.assertFalse(permiso.supervisor)

    def test_usuario_destino_invalido_retorna_404_sin_alterar_copia(self):
        response = self._copy(destino_usuario=999999)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["success"])
        self.assertFalse(
            Permiso.objects.filter(
                usuario=self.destino_usuario,
                empresa=self.empresa_destino,
                vista=self.vista_copiada,
            ).exists()
        )