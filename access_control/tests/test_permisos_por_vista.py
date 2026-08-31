from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.forms import PermisoPorVistaFiltroForm
from access_control.models import Empresa, Permiso, PerfilAcceso, UsuarioPerfilEmpresa, Vista


class PermisosPorVistaTests(TestCase):
    vista_admin_nombre = "Control de Acceso - Permisos por Vista"

    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="pass")
        self.empresa_a = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        self.vista_admin = Vista.objects.create(nombre=self.vista_admin_nombre)
        self.vista_x = Vista.objects.create(nombre="Vista X")
        self.vista_y = Vista.objects.create(nombre="Vista Y")
        Permiso.objects.create(usuario=self.admin, empresa=self.empresa_a, vista=self.vista_admin, modificar=True)
        self.perfil = PerfilAcceso.objects.create(nombre="Perfil prueba")
        self.client.force_login(self.admin)
        session = self.client.session
        session["empresa_id"] = self.empresa_a.id
        session.save()

    def _url(self):
        return reverse("access_control:permisos_por_vista")

    def _toggle(self, **overrides):
        data = {
            "usuario_id": self.usuario_perfil.id,
            "empresa_id": self.empresa_a.id,
            "vista_id": self.vista_x.id,
            "permiso_field": "modificar",
            "value": "true",
        }
        data.update(overrides)
        return self.client.post(reverse("access_control:toggle_permiso_por_vista"), data, HTTP_ACCEPT="application/json")

    def _create_valid_profile_user(self):
        self.usuario_perfil = User.objects.create_user(username="perfil", password="pass")
        UsuarioPerfilEmpresa.objects.create(usuario=self.usuario_perfil, empresa=self.empresa_a, perfil=self.perfil)

    def test_filtro_vistas_esta_ordenado_por_nombre(self):
        zulu = Vista.objects.create(nombre="Zulu")
        alpha = Vista.objects.create(nombre="Alpha")
        beta = Vista.objects.create(nombre="Beta")

        vistas = list(PermisoPorVistaFiltroForm().fields["vista"].queryset)

        self.assertLess(vistas.index(alpha), vistas.index(beta))
        self.assertLess(vistas.index(beta), vistas.index(zulu))

    def test_listado_une_fuentes_y_no_crea_permisos_al_renderizar(self):
        self._create_valid_profile_user()
        usuario_permiso = User.objects.create_user(username="permiso", password="pass")
        usuario_ambos = User.objects.create_user(username="ambos", password="pass")
        otro_usuario = User.objects.create_user(username="otra_empresa", password="pass")
        UsuarioPerfilEmpresa.objects.create(usuario=usuario_ambos, empresa=self.empresa_a, perfil=self.perfil)
        Permiso.objects.create(usuario=usuario_permiso, empresa=self.empresa_a, vista=self.vista_y, ingresar=True)
        Permiso.objects.create(usuario=usuario_ambos, empresa=self.empresa_a, vista=self.vista_y, ingresar=True)
        Permiso.objects.create(usuario=otro_usuario, empresa=self.empresa_b, vista=self.vista_x, ingresar=True)
        before = Permiso.objects.count()

        response = self.client.get(self._url(), {"empresa": self.empresa_a.id, "vista": self.vista_x.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "perfil")
        self.assertContains(response, "permiso")
        self.assertContains(response, "ambos", count=1)
        self.assertNotContains(response, "otra_empresa")
        self.assertEqual(Permiso.objects.count(), before)
        self.assertFalse(Permiso.objects.filter(usuario=self.usuario_perfil, empresa=self.empresa_a, vista=self.vista_x).exists())

    def test_toggle_crea_solo_flag_solicitado_y_false_ausente_no_crea(self):
        self._create_valid_profile_user()

        response = self._toggle(value="false")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Permiso.objects.filter(usuario=self.usuario_perfil, empresa=self.empresa_a, vista=self.vista_x).exists())

        response = self._toggle()
        self.assertEqual(response.status_code, 200)
        permiso = Permiso.objects.get(usuario=self.usuario_perfil, empresa=self.empresa_a, vista=self.vista_x)
        self.assertFalse(permiso.ingresar)
        self.assertFalse(permiso.crear)
        self.assertTrue(permiso.modificar)
        self.assertFalse(permiso.eliminar)
        self.assertFalse(permiso.autorizar)
        self.assertFalse(permiso.supervisor)

    def test_toggle_preserva_flags_y_aislamiento_empresa_y_vista(self):
        self._create_valid_profile_user()
        Permiso.objects.create(usuario=self.usuario_perfil, empresa=self.empresa_a, vista=self.vista_x, ingresar=True, crear=True, modificar=True, autorizar=True)
        permiso_otro_vista = Permiso.objects.create(usuario=self.usuario_perfil, empresa=self.empresa_a, vista=self.vista_y, ingresar=True)
        permiso_otra_empresa = Permiso.objects.create(usuario=self.usuario_perfil, empresa=self.empresa_b, vista=self.vista_x, supervisor=True)

        response = self._toggle(value="false")

        self.assertEqual(response.status_code, 200)
        permiso = Permiso.objects.get(usuario=self.usuario_perfil, empresa=self.empresa_a, vista=self.vista_x)
        self.assertTrue(permiso.ingresar)
        self.assertTrue(permiso.crear)
        self.assertFalse(permiso.modificar)
        self.assertTrue(permiso.autorizar)
        permiso_otro_vista.refresh_from_db()
        permiso_otra_empresa.refresh_from_db()
        self.assertTrue(permiso_otro_vista.ingresar)
        self.assertTrue(permiso_otra_empresa.supervisor)

    def test_toggle_mantiene_permiso_cuando_todos_los_flags_quedan_false(self):
        self._create_valid_profile_user()
        permiso = Permiso.objects.create(usuario=self.usuario_perfil, empresa=self.empresa_a, vista=self.vista_x, modificar=True)

        response = self._toggle(value="false")

        self.assertEqual(response.status_code, 200)
        permiso.refresh_from_db()
        self.assertFalse(permiso.modificar)

    def test_get_otra_empresa_es_permitido_con_autorizacion_en_empresa_activa(self):
        self._create_valid_profile_user()
        UsuarioPerfilEmpresa.objects.create(usuario=self.usuario_perfil, empresa=self.empresa_b, perfil=self.perfil)

        response = self.client.get(self._url(), {"empresa": self.empresa_b.id, "vista": self.vista_x.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.usuario_perfil.username)

    def test_toggle_otra_empresa_es_permitido_con_autorizacion_en_empresa_activa(self):
        self._create_valid_profile_user()
        UsuarioPerfilEmpresa.objects.create(usuario=self.usuario_perfil, empresa=self.empresa_b, perfil=self.perfil)

        response = self._toggle(empresa_id=self.empresa_b.id)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Permiso.objects.get(usuario=self.usuario_perfil, empresa=self.empresa_b, vista=self.vista_x).modificar)

    def test_toggle_rechaza_datos_manipulados_y_sin_permiso_administrativo(self):
        self._create_valid_profile_user()

        invalid_field = self._toggle(permiso_field="admin")
        self.assertEqual(invalid_field.status_code, 400)
        invalid_user = self._toggle(usuario_id=999999)
        self.assertEqual(invalid_user.status_code, 404)
        invalid_empresa = self._toggle(empresa_id=999999)
        self.assertEqual(invalid_empresa.status_code, 404)
        invalid_vista = self._toggle(vista_id=999999)
        self.assertEqual(invalid_vista.status_code, 404)
        foreign_user = User.objects.create_user(username="externo", password="pass")
        invalid_company_user = self._toggle(usuario_id=foreign_user.id)
        self.assertEqual(invalid_company_user.status_code, 400)

        denied = User.objects.create_user(username="denied", password="pass")
        Permiso.objects.create(usuario=denied, empresa=self.empresa_a, vista=self.vista_admin, ingresar=True)
        self.client.force_login(denied)
        session = self.client.session
        session["empresa_id"] = self.empresa_a.id
        session.save()
        denied_response = self._toggle()
        self.assertEqual(denied_response.status_code, 403)

    def test_sin_modificar_en_empresa_activa_es_denegado_aun_con_permiso_en_objetivo(self):
        self._create_valid_profile_user()
        UsuarioPerfilEmpresa.objects.create(usuario=self.usuario_perfil, empresa=self.empresa_b, perfil=self.perfil)
        denied = User.objects.create_user(username="denied", password="pass")
        Permiso.objects.create(usuario=denied, empresa=self.empresa_b, vista=self.vista_admin, modificar=True)
        self.client.force_login(denied)
        session = self.client.session
        session["empresa_id"] = self.empresa_a.id
        session.save()

        response = self.client.get(self._url(), {"empresa": self.empresa_b.id, "vista": self.vista_x.id})

        self.assertEqual(response.status_code, 403)
