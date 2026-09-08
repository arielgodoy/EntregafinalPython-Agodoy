from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


class CopyPermisosViewTests(TestCase):
    vista_nombre = "Control de Acceso - Copiar permisos"
    vista_maestro = "Control de Acceso - Maestro Permisos"

    def setUp(self):
        self.operator = User.objects.create_user(username="operator", password="pass123")
        self.origen_usuario = User.objects.create_user(username="origen", password="pass123")
        self.destino_usuario = User.objects.create_user(username="destino", password="pass123")
        self.empresa_origen = Empresa.objects.create(codigo="01", descripcion="Origen")
        self.empresa_destino = Empresa.objects.create(codigo="02", descripcion="Destino")
        self.vista_control = Vista.objects.create(nombre=self.vista_nombre)
        self.vista_maestro_obj = Vista.objects.create(nombre=self.vista_maestro)
        self.vista_copiada = Vista.objects.create(nombre="Modulo - Vista Copiada")
        # Ejecutor autorizado en origen con la vista granular de copia
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

    def _flags(self, permiso):
        return {
            "ingresar": permiso.ingresar,
            "crear": permiso.crear,
            "modificar": permiso.modificar,
            "eliminar": permiso.eliminar,
            "autorizar": permiso.autorizar,
            "supervisor": permiso.supervisor,
        }

    def test_bootstrap_destino_vacio_permitido(self):
        """CASO A: empresa destino sin ningun Permiso se inicializa sin supervisor previo alli."""
        self.assertFalse(Permiso.objects.filter(empresa=self.empresa_destino).exists())

        response = self._copy()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        permiso = Permiso.objects.get(
            usuario=self.destino_usuario,
            empresa=self.empresa_destino,
            vista=self.vista_copiada,
        )
        self.assertEqual(
            self._flags(permiso),
            {"ingresar": True, "crear": True, "modificar": True,
             "eliminar": False, "autorizar": True, "supervisor": False},
        )

    def test_destino_inicializado_con_autorizacion_permitido(self):
        """CASO B autorizado: ejecutor con supervisor en origen y destino."""
        Permiso.objects.create(
            usuario=self.operator,
            empresa=self.empresa_destino,
            vista=self.vista_control,
            supervisor=True,
        )

        response = self._copy()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    def test_destino_inicializado_sin_autorizacion_es_denegado(self):
        """CASO B no autorizado: destino ya inicializada y ejecutor sin supervisor alli -> 403."""
        Permiso.objects.create(
            usuario=self.origen_usuario,
            empresa=self.empresa_destino,
            vista=self.vista_copiada,
            ingresar=True,
        )

        response = self._copy()

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Permiso.objects.filter(
                usuario=self.destino_usuario,
                empresa=self.empresa_destino,
                vista=self.vista_copiada,
            ).exists()
        )

    def test_sin_supervisor_en_origen_es_denegado(self):
        """El ejecutor sin supervisor en origen no puede copiar (CASO origen)."""
        Permiso.objects.filter(
            usuario=self.operator,
            empresa=self.empresa_origen,
            vista=self.vista_control,
        ).update(supervisor=False)

        response = self._copy()

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Permiso.objects.filter(
                usuario=self.destino_usuario,
                empresa=self.empresa_destino,
            ).exists()
        )

    def test_copia_en_misma_empresa_requiere_un_solo_supervisor(self):
        """CASO C: origen == destino exige una unica autorizacion en esa empresa."""
        response = self._copy(destino_empresa=self.empresa_origen.id)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Permiso.objects.filter(
                usuario=self.destino_usuario,
                empresa=self.empresa_origen,
                vista=self.vista_copiada,
            ).exists()
        )

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

    def test_autorizacion_usa_vista_copiar_permisos_no_maestro(self):
        """La autorizacion debe venir de la vista granular, no de Maestro Permisos."""
        # Eliminar la autorizacion granular y otorgar supervisor solo en Maestro Permisos
        Permiso.objects.filter(
            usuario=self.operator,
            empresa=self.empresa_origen,
            vista=self.vista_control,
        ).delete()
        Permiso.objects.create(
            usuario=self.operator,
            empresa=self.empresa_origen,
            vista=self.vista_maestro_obj,
            supervisor=True,
        )

        response = self._copy()

        self.assertEqual(response.status_code, 403)
