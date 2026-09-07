"""Tests de vistas de tareas (T019, T024, T027).

Cubre: creación/edición de borradores (US1), publicación (US2) y aislamiento
multiempresa + permisos ICMEAS (US3).
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from tareas.models import Tarea


class TareasViewsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        cls.otra_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        cls.user = User.objects.create_user(username="user1", password="pass")
        cls.responsable = User.objects.create_user(username="resp", password="pass")
        cls.vista_listado = Vista.objects.create(nombre="Tareas - Listado")
        cls.vista_detalle = Vista.objects.create(nombre="Tareas - Detalle")
        cls.vista_crear = Vista.objects.create(nombre="Tareas - Crear tarea")
        cls.vista_editar = Vista.objects.create(nombre="Tareas - Editar tarea")
        cls.vista_publicar = Vista.objects.create(nombre="Tareas - Publicar tarea")

    def _login(self, empresa=None):
        self.client.login(username="user1", password="pass")
        session = self.client.session
        session["empresa_id"] = (empresa or self.empresa).id
        session.save()

    def _permiso(self, vista, **flags):
        base = dict(
            ingresar=False, crear=False, modificar=False,
            eliminar=False, autorizar=False, supervisor=False,
        )
        base.update(flags)
        Permiso.objects.update_or_create(
            usuario=self.user, empresa=self.empresa, vista=vista, defaults=base
        )

    def _crear_tarea(self, empresa=None, **kwargs):
        datos = {
            "titulo": "Tarea X",
            "empresa": empresa or self.empresa,
            "creada_por": self.user,
        }
        datos.update(kwargs)
        return Tarea.objects.create(**datos)


class CrearEditarBorradoresTests(TareasViewsBase):
    def test_crear_solo_titulo_guarda_borrador_con_empresa_de_sesion(self):
        # Permisos completos para que el redirect al detalle sea exitoso.
        self._permiso(self.vista_crear, crear=True, ingresar=True)
        self._permiso(self.vista_detalle, ingresar=True)
        self._login()
        response = self.client.post(
            reverse("tareas:crear_tarea"),
            {"titulo": "Nueva tarea"},  # solo título
            follow=True,
        )
        tarea = Tarea.objects.get(titulo="Nueva tarea")
        self.assertEqual(tarea.estado, Tarea.Estado.BORRADOR)
        self.assertEqual(tarea.empresa, self.empresa)
        self.assertEqual(tarea.creada_por, self.user)
        # prioridad queda NORMAL por default
        self.assertEqual(tarea.prioridad, Tarea.Prioridad.NORMAL)
        # redirect al detalle exitoso
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(
            response,
            reverse("tareas:detalle_tarea", args=[tarea.pk]),
        )

    def test_editar_borrador_persiste_sin_fecha_publicacion(self):
        self._permiso(self.vista_editar, modificar=True, ingresar=True)
        tarea = self._crear_tarea()
        self._login()
        self.client.post(
            reverse("tareas:editar_tarea", args=[tarea.pk]),
            {"titulo": "Editada", "prioridad": Tarea.Prioridad.URGENTE},
        )
        tarea.refresh_from_db()
        self.assertEqual(tarea.titulo, "Editada")
        self.assertEqual(tarea.estado, Tarea.Estado.BORRADOR)

    def test_crear_sin_permiso_devuelve_403(self):
        self._permiso(self.vista_crear, crear=False, ingresar=False)
        self._login()
        response = self.client.get(reverse("tareas:crear_tarea"))
        self.assertEqual(response.status_code, 403)

    def test_crear_sin_empresa_activa_redirige_a_seleccionar_empresa(self):
        # Comportamiento vigente verificado: el decorador ICMEAS redirige al
        # selector de empresa cuando no hay empresa activa en sesión.
        self._permiso(self.vista_crear, crear=True, ingresar=True)
        self.client.login(username="user1", password="pass")
        # No se fija empresa_id en la sesión.
        response = self.client.post(
            reverse("tareas:crear_tarea"), {"titulo": "Sin empresa"}
        )
        self.assertRedirects(
            response,
            reverse("access_control:seleccionar_empresa"),
            fetch_redirect_response=False,
        )
        self.assertFalse(Tarea.objects.filter(titulo="Sin empresa").exists())

    def test_editar_publicada_quitando_responsable_rechazado(self):
        self._permiso(self.vista_editar, modificar=True, ingresar=True)
        tarea = self._crear_tarea(responsable=self.responsable)
        tarea.publicar()
        self._login()
        self.client.post(
            reverse("tareas:editar_tarea", args=[tarea.pk]),
            {
                "titulo": tarea.titulo,
                "prioridad": tarea.prioridad,
                "responsable": "",
            },
        )
        tarea.refresh_from_db()
        # La edición es rechazada: permanece publicada con responsable válido.
        self.assertEqual(tarea.estado, Tarea.Estado.PUBLICADA)
        self.assertEqual(tarea.responsable, self.responsable)

    def test_editar_tarea_de_otra_empresa_devuelve_404(self):
        self._permiso(self.vista_editar, modificar=True, ingresar=True)
        tarea = self._crear_tarea(empresa=self.otra_empresa)
        self._login(empresa=self.empresa)
        response = self.client.post(
            reverse("tareas:editar_tarea", args=[tarea.pk]),
            {"titulo": "X", "prioridad": Tarea.Prioridad.NORMAL},
        )
        self.assertEqual(response.status_code, 404)


class PublicarTests(TareasViewsBase):
    def test_publicar_sin_responsable_rechazado_y_permanece_borrador(self):
        self._permiso(self.vista_publicar, modificar=True, ingresar=True)
        tarea = self._crear_tarea()
        self._login()
        self.client.post(reverse("tareas:publicar_tarea", args=[tarea.pk]))
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, Tarea.Estado.BORRADOR)
        self.assertIsNone(tarea.fecha_publicacion)

    def test_publicar_con_responsable_inactivo_rechazado(self):
        self._permiso(self.vista_publicar, modificar=True, ingresar=True)
        self.responsable.is_active = False
        self.responsable.save()
        tarea = self._crear_tarea(responsable=self.responsable)
        self._login()
        self.client.post(reverse("tareas:publicar_tarea", args=[tarea.pk]))
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, Tarea.Estado.BORRADOR)

    def test_publicar_con_responsable_activo_ok(self):
        self._permiso(self.vista_publicar, modificar=True, ingresar=True)
        tarea = self._crear_tarea(responsable=self.responsable)
        self._login()
        self.client.post(reverse("tareas:publicar_tarea", args=[tarea.pk]))
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, Tarea.Estado.PUBLICADA)
        self.assertIsNotNone(tarea.fecha_publicacion)

    def test_publicar_tarea_de_otra_empresa_devuelve_404(self):
        self._permiso(self.vista_publicar, modificar=True, ingresar=True)
        tarea = self._crear_tarea(empresa=self.otra_empresa, responsable=self.responsable)
        self._login(empresa=self.empresa)
        response = self.client.post(reverse("tareas:publicar_tarea", args=[tarea.pk]))
        self.assertEqual(response.status_code, 404)

    def test_publicar_sin_permiso_devuelve_403(self):
        self._permiso(self.vista_publicar, modificar=False)
        tarea = self._crear_tarea(responsable=self.responsable)
        self._login()
        response = self.client.post(reverse("tareas:publicar_tarea", args=[tarea.pk]))
        self.assertEqual(response.status_code, 403)


class AislamientoPermisosTests(TareasViewsBase):
    def test_listado_muestra_solo_empresa_activa(self):
        self._permiso(self.vista_listado, ingresar=True)
        self._crear_tarea(titulo="De A", empresa=self.empresa)
        self._crear_tarea(titulo="De B", empresa=self.otra_empresa)
        self._login(empresa=self.empresa)
        response = self.client.get(reverse("tareas:listar_tareas"))
        self.assertContains(response, "De A")
        self.assertNotContains(response, "De B")

    def test_cambio_de_empresa_activa_cambia_listado(self):
        self._permiso(self.vista_listado, ingresar=True)
        Permiso.objects.update_or_create(
            usuario=self.user,
            empresa=self.otra_empresa,
            vista=self.vista_listado,
            defaults={"ingresar": True},
        )
        self._crear_tarea(titulo="De A", empresa=self.empresa)
        self._crear_tarea(titulo="De B", empresa=self.otra_empresa)
        self._login(empresa=self.otra_empresa)
        response = self.client.get(reverse("tareas:listar_tareas"))
        self.assertContains(response, "De B")
        self.assertNotContains(response, "De A")

    def test_detalle_tarea_de_otra_empresa_devuelve_404(self):
        self._permiso(self.vista_detalle, ingresar=True)
        tarea = self._crear_tarea(empresa=self.otra_empresa)
        self._login(empresa=self.empresa)
        response = self.client.get(reverse("tareas:detalle_tarea", args=[tarea.pk]))
        self.assertEqual(response.status_code, 404)

    def test_listado_sin_permiso_ingresar_devuelve_403(self):
        self._permiso(self.vista_listado, ingresar=False)
        self._login()
        response = self.client.get(reverse("tareas:listar_tareas"))
        self.assertEqual(response.status_code, 403)
