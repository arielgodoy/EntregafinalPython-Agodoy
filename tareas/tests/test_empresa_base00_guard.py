from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from tareas import urls
from tareas.models import Tarea, TareaConnectionRole
from tareas.views import (
    AbrirEnlaceTareaView,
    BaseTareasSchemaInstallView,
    TareaConnectionRoleView,
    TareasDashboardDepartamentoView,
    TareasDashboardEmpresaView,
    TareasDashboardGeneralView,
    TareasDashboardUsuarioView,
    TareasVerificarPermisoMixin,
)


class TareasEmpresaBase00GuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa_02 = Empresa.objects.create(
            codigo="02",
            descripcion="Empresa operativa",
        )
        cls.empresa_00 = Empresa.objects.create(
            codigo="00",
            descripcion="Empresa Base",
        )
        cls.empresa_09 = Empresa.objects.create(
            codigo="09",
            descripcion="Otra empresa operativa",
        )
        cls.user = User.objects.create_user(
            username="tareas-base00-user",
            password="test-password",
        )
        cls.vista_tareas = Vista.objects.create(nombre="Tareas")
        cls.vista_conexiones = Vista.objects.create(
            nombre="Tareas - Conexiones SQL",
            route_name="tareas:conexiones_sql",
        )
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="DJANGO",
            django_alias="default",
        )

    def _activate(self, empresa):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = empresa.pk
        session.save()

    def _grant(self, empresa, vista, **flags):
        permissions = {
            "ver": False,
            "ingresar": False,
            "crear": False,
            "modificar": False,
            "eliminar": False,
            "autorizar": False,
            "supervisor": False,
        }
        permissions.update(flags)
        return Permiso.objects.create(
            usuario=self.user,
            empresa=empresa,
            vista=vista,
            **permissions,
        )

    def test_empresa_00_por_codigo_con_permiso_accede_normalmente(self):
        self._grant(self.empresa_00, self.vista_tareas, ingresar=True)
        self._activate(self.empresa_00)

        response = self.client.get(reverse("tareas:listar_tareas"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["empresa_id"], self.empresa_00.pk)

    def test_empresa_02_con_permiso_avisa_y_redirige_sin_cambiar_sesion(self):
        self._grant(self.empresa_02, self.vista_tareas, ingresar=True)
        self._activate(self.empresa_02)

        response = self.client.get(reverse("tareas:listar_tareas"))

        self.assertRedirects(
            response,
            reverse("access_control:seleccionar_empresa"),
            fetch_redirect_response=False,
        )
        selector_response = self.client.get(response.url)
        self.assertContains(
            selector_response,
            "La planificación de tareas solo funciona en la Empresa Base 00. "
            "Seleccione esa empresa para continuar.",
        )
        self.assertContains(selector_response, "02 - Empresa operativa")
        self.assertNotContains(selector_response, "00 - Empresa Base")
        self.assertEqual(self.client.session["empresa_id"], self.empresa_02.pk)

    def test_empresa_02_sin_permiso_conserva_403_y_no_crea_asociacion(self):
        self._activate(self.empresa_02)

        response = self.client.get(reverse("tareas:listar_tareas"))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Permiso.objects.filter(
                usuario=self.user,
                empresa=self.empresa_02,
                vista=self.vista_tareas,
            ).exists()
        )

    def test_post_empresa_02_no_crea_tarea_y_redirige_sin_repetir_post(self):
        self._grant(self.empresa_02, self.vista_tareas, crear=True)
        self._activate(self.empresa_02)

        response = self.client.post(
            reverse("tareas:crear_tarea"),
            {"titulo": "No debe persistirse"},
        )

        self.assertRedirects(
            response,
            reverse("access_control:seleccionar_empresa"),
            fetch_redirect_response=False,
        )
        self.assertFalse(Tarea.objects.filter(titulo="No debe persistirse").exists())
        self.assertEqual(self.client.session["empresa_id"], self.empresa_02.pk)

    def test_ajax_empresa_09_devuelve_respuesta_controlada_sin_escritura(self):
        self._grant(self.empresa_09, self.vista_tareas, crear=True)
        self._activate(self.empresa_09)

        response = self.client.post(
            reverse("tareas:crear_tarea"),
            {"titulo": "No debe persistirse por AJAX"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "message_key": "tareas.empresa_base00.requerida",
            },
        )
        self.assertFalse(
            Tarea.objects.filter(titulo="No debe persistirse por AJAX").exists()
        )

    def test_usuario_anonimo_recibe_autenticacion_habitual(self):
        response = self.client.get(reverse("tareas:listar_tareas"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_empresa_activa_ausente_sigue_bajo_control_del_middleware(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("tareas:crear_tarea"),
            {"titulo": "Sin empresa activa"},
        )

        self.assertRedirects(
            response,
            reverse("access_control:seleccionar_empresa"),
            fetch_redirect_response=False,
        )
        self.assertFalse(Tarea.objects.filter(titulo="Sin empresa activa").exists())

    def test_vistas_con_autorizacion_especial_aplican_guard_despues_de_autorizar(self):
        self._grant(
            self.empresa_02,
            self.vista_conexiones,
            ingresar=True,
            modificar=True,
            supervisor=True,
        )
        self._grant(self.empresa_02, self.vista_tareas, supervisor=True)
        self._activate(self.empresa_02)

        response = self.client.get(reverse("tareas:conexiones_sql"))
        self.assertRedirects(
            response,
            reverse("access_control:seleccionar_empresa"),
            fetch_redirect_response=False,
        )

        response = self.client.post(reverse("tareas:conexiones_sql"), data={})
        self.assertRedirects(
            response,
            reverse("access_control:seleccionar_empresa"),
            fetch_redirect_response=False,
        )

        response = self.client.post(
            reverse("tareas:base_tareas_schema_install"),
            {"schema_action": "preview"},
        )
        self.assertRedirects(
            response,
            reverse("access_control:seleccionar_empresa"),
            fetch_redirect_response=False,
        )

        with patch("tareas.views.get_company_dashboard", return_value={}) as dashboard:
            response = self.client.get(
                reverse(
                    "tareas:dashboard_general_empresa",
                    kwargs={"empresa_id": self.empresa_02.pk},
                )
            )
        self.assertRedirects(
            response,
            reverse("access_control:seleccionar_empresa"),
            fetch_redirect_response=False,
        )
        dashboard.assert_not_called()

        with patch("tareas.views.get_department_dashboard", return_value={}) as dashboard:
            response = self.client.get(
                reverse(
                    "tareas:dashboard_general_departamento",
                    kwargs={
                        "empresa_id": self.empresa_02.pk,
                        "departamento_id": 1,
                    },
                )
            )
        self.assertRedirects(
            response,
            reverse("access_control:seleccionar_empresa"),
            fetch_redirect_response=False,
        )
        dashboard.assert_not_called()

        with patch("tareas.views.get_user_dashboard", return_value={}) as dashboard:
            response = self.client.get(
                reverse(
                    "tareas:dashboard_general_usuario",
                    kwargs={
                        "empresa_id": self.empresa_02.pk,
                        "usuario_id": self.user.pk,
                    },
                )
            )
        self.assertRedirects(
            response,
            reverse("access_control:seleccionar_empresa"),
            fetch_redirect_response=False,
        )
        dashboard.assert_not_called()

        with patch(
            "tareas.views.get_general_dashboard",
            return_value={"rows": [object()]},
        ) as dashboard:
            response = self.client.get(reverse("tareas:dashboard_general"))
        self.assertRedirects(
            response,
            reverse("access_control:seleccionar_empresa"),
            fetch_redirect_response=False,
        )
        dashboard.assert_not_called()

    def test_enlace_no_se_resuelve_antes_de_aplicar_empresa_base(self):
        self._activate(self.empresa_02)
        enlace = SimpleNamespace(tarea=object())

        with patch("tareas.views.resolve_task_link", return_value=enlace) as resolve:
            response = self.client.get(
                reverse("tareas:enlace_tarea", kwargs={"token": "token-valido"})
            )

        resolve.assert_not_called()
        self.assertRedirects(
            response,
            reverse("access_control:seleccionar_empresa"),
            fetch_redirect_response=False,
        )

    def test_todas_las_rutas_tienen_guard_de_dispatch_o_validacion_especifica(self):
        manual_guard_classes = {
            TareaConnectionRoleView,
            BaseTareasSchemaInstallView,
            TareasDashboardGeneralView,
            TareasDashboardEmpresaView,
            TareasDashboardDepartamentoView,
            TareasDashboardUsuarioView,
            AbrirEnlaceTareaView,
        }

        unguarded_routes = [
            pattern.name
            for pattern in urls.urlpatterns
            if not issubclass(pattern.callback.view_class, TareasVerificarPermisoMixin)
            and pattern.callback.view_class not in manual_guard_classes
        ]

        self.assertEqual(unguarded_routes, [])
