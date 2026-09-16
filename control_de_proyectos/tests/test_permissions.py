import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Vista, Permiso
from access_control.services.permissions import SIDEBAR_VIEW_NAMES
from access_control.services.permissions import ensure_user_view_permissions
from access_control.services.view_catalog import audit_protected_views, discover_protected_views
from control_de_proyectos.models import ClienteEmpresa, Proyecto, Tarea
from control_de_proyectos.views import (
    CrearProyectoView,
    DetalleProyectoView,
    EditarProyectoView,
    EliminarProyectoView,
    ListarProyectosView,
)


class ProjectsMotherViewMetadataTests(TestCase):
    def test_project_endpoints_share_mother_view_and_permissions(self):
        expected = {
            "listar_proyectos": (ListarProyectosView, "ingresar"),
            "detalle_proyecto": (DetalleProyectoView, "ingresar"),
            "crear_proyecto": (CrearProyectoView, "crear"),
            "editar_proyecto": (EditarProyectoView, "modificar"),
            "eliminar_proyecto": (EliminarProyectoView, "eliminar"),
        }

        for view_class, permission in expected.values():
            self.assertEqual(view_class.vista_nombre, "Control de Proyectos - Proyectos")
            self.assertEqual(view_class.permiso_requerido, permission)

        self.assertEqual(
            SIDEBAR_VIEW_NAMES["projects_list"],
            "Control de Proyectos - Proyectos",
        )
        self.assertEqual(
            SIDEBAR_VIEW_NAMES["projects_create"],
            "Control de Proyectos - Proyectos",
        )

    def test_catalog_deduplicates_project_mother_without_issues(self):
        definitions = [
            definition
            for definition in discover_protected_views()
            if definition.vista_nombre == "Control de Proyectos - Proyectos"
        ]
        self.assertEqual(len(definitions), 1)

        _, issues = audit_protected_views()
        project_routes = {
            "control_de_proyectos:listar_proyectos",
            "control_de_proyectos:detalle_proyecto",
            "control_de_proyectos:crear_proyecto",
            "control_de_proyectos:editar_proyecto",
            "control_de_proyectos:eliminar_proyecto",
            "control_de_proyectos:sugerir_tipos",
            "control_de_proyectos:sugerir_especialidades",
        }
        self.assertFalse(any(issue.route_name in project_routes for issue in issues))

    def test_project_mother_permissions_are_deny_by_default(self):
        user = User.objects.create_user(username="project-mother", password="pass")
        empresa = Empresa.objects.create(codigo="02", descripcion="Empresa 02")
        vista = Vista.objects.create(nombre="Control de Proyectos - Proyectos")
        permission = Permiso.objects.create(usuario=user, empresa=empresa, vista=vista)

        self.assertFalse(any(getattr(permission, field) for field in (
            "ver", "ingresar", "crear", "modificar", "eliminar", "autorizar", "supervisor"
        )))

    def test_materialization_does_not_reset_existing_mother_flags(self):
        user = User.objects.create_user(username="project-mother-existing", password="pass")
        empresa = Empresa.objects.create(codigo="03", descripcion="Empresa 03")
        vista = Vista.objects.create(nombre="Control de Proyectos - Proyectos")
        permission = Permiso.objects.create(
            usuario=user,
            empresa=empresa,
            vista=vista,
            crear=True,
            modificar=True,
        )

        ensure_user_view_permissions(user, empresa.id, view_names=[vista.nombre])

        permission.refresh_from_db()
        self.assertTrue(permission.crear)
        self.assertTrue(permission.modificar)


class AvancePermisosTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='user1', password='pass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        self.vista = Vista.objects.create(nombre='Control de Proyectos - Actualizar avance de tarea')
        self.cliente = ClienteEmpresa.objects.create(
            nombre='Cliente Uno',
            rut='12.345.678-5',
            telefono='123',
            email='cliente@example.com',
            direccion='Calle 123',
            ciudad='Santiago'
        )
        self.proyecto = Proyecto.objects.create(
            nombre='Proyecto A',
            descripcion='Desc',
            empresa_interna=self.empresa,
            cliente=self.cliente,
            tipo_texto='Tipo'
        )
        self.tarea = Tarea.objects.create(
            proyecto=self.proyecto,
            nombre='Tarea 1'
        )

    def _login_with_empresa(self):
        self.client.login(username='user1', password='pass')
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def test_post_sin_permiso_devuelve_403(self):
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            modificar=False
        )
        self._login_with_empresa()
        url = reverse('control_de_proyectos:actualizar_avance_tarea', args=[self.tarea.id])
        response = self.client.post(
            url,
            data=json.dumps({'porcentaje_avance': 10}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)

    def test_post_con_permiso_actualiza_avance(self):
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            modificar=True
        )
        self._login_with_empresa()
        url = reverse('control_de_proyectos:actualizar_avance_tarea', args=[self.tarea.id])
        response = self.client.post(
            url,
            data=json.dumps({'porcentaje_avance': 30}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.tarea.refresh_from_db()
        self.assertEqual(self.tarea.porcentaje_avance, 30)
