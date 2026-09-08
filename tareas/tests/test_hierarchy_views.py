"""Pruebas focalizadas de navegación jerárquica en modo lectura."""

from django.test import TestCase
from django.urls import reverse

from tareas.models import Tarea
from tareas.services.hierarchy import add_child
from tareas.services.lifecycle import annul_task, transition_task
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class HierarchyViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="HV1", descripcion="Empresa navegación")
        cls.otra_empresa = create_empresa(codigo="HV2", descripcion="Empresa externa")
        cls.user = create_user(username="hierarchy_view_user")
        assign_permission(cls.user, cls.empresa, "Tareas - Detalle", ingresar=True)

    def setUp(self):
        self.client.login(username="hierarchy_view_user", password="password-prueba")
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def make_task(self, title, empresa=None):
        return create_tarea(
            empresa or self.empresa,
            self.user,
            titulo=title,
            responsable=self.user,
        )

    def get_detail(self, task):
        return self.client.get(reverse("tareas:detalle_tarea", args=[task.pk]))

    def test_detalle_raiz_muestra_hijas_con_correlativo(self):
        parent = self.make_task("Padre raíz")
        child = self.make_task("Hija directa")
        add_child(parent, child)

        response = self.get_detail(parent)

        self.assertContains(response, "Hija directa")
        self.assertContains(response, child.correlativo)

    def test_detalle_hija_muestra_padre(self):
        parent = self.make_task("Padre visible")
        child = self.make_task("Hija visible")
        add_child(parent, child)

        response = self.get_detail(child)

        self.assertContains(response, "Padre visible")
        self.assertContains(response, parent.correlativo)

    def test_detalle_hija_muestra_sus_nietas(self):
        parent = self.make_task("Padre")
        child = self.make_task("Hija")
        grandchild = self.make_task("Nieta")
        add_child(parent, child)
        add_child(child, grandchild)

        response = self.get_detail(child)

        self.assertContains(response, "Nieta")
        self.assertContains(response, grandchild.correlativo)

    def test_enlaces_apuntan_al_detalle_correcto(self):
        parent = self.make_task("Padre enlazado")
        child = self.make_task("Hija enlazada")
        add_child(parent, child)

        response = self.get_detail(child)

        self.assertContains(response, reverse("tareas:detalle_tarea", args=[parent.pk]))

    def test_navegacion_padre_hija_nieta(self):
        parent = self.make_task("Nivel padre")
        child = self.make_task("Nivel hija")
        grandchild = self.make_task("Nivel nieta")
        add_child(parent, child)
        add_child(child, grandchild)

        root_response = self.get_detail(parent)
        child_response = self.client.get(
            reverse("tareas:detalle_tarea", args=[child.pk])
        )
        grandchild_response = self.client.get(
            reverse("tareas:detalle_tarea", args=[grandchild.pk])
        )

        self.assertContains(root_response, reverse("tareas:detalle_tarea", args=[child.pk]))
        self.assertContains(child_response, reverse("tareas:detalle_tarea", args=[grandchild.pk]))
        self.assertContains(grandchild_response, reverse("tareas:detalle_tarea", args=[child.pk]))

    def test_jerarquia_vacia_no_rompe_detalle(self):
        response = self.get_detail(self.make_task("Sin jerarquía"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jerarquía")

    def test_tarea_anulada_directamente_se_representa(self):
        task = self.make_task("Tarea anulada")
        task.publicar(self.user)
        transition_task(task, Tarea.Estado.GESTION, self.user, "INICIAR_GESTION")
        annul_task(task, self.user)

        response = self.get_detail(task)

        self.assertContains(response, "Anulada")

    def test_hija_anulada_efectivamente_por_padre_se_representa(self):
        parent = self.make_task("Padre anulado")
        child = self.make_task("Hija afectada")
        parent.publicar(self.user)
        child.publicar(self.user)
        transition_task(parent, Tarea.Estado.GESTION, self.user, "INICIAR_GESTION")
        transition_task(child, Tarea.Estado.GESTION, self.user, "INICIAR_GESTION")
        add_child(parent, child)
        annul_task(parent, self.user)

        response = self.get_detail(child)

        self.assertContains(response, "Anulada por tarea superior")

    def test_aislamiento_multiempresa_en_navegacion(self):
        task = self.make_task("Tarea de empresa activa")
        external = self.make_task("Tarea de otra empresa", empresa=self.otra_empresa)

        response = self.get_detail(task)
        external_response = self.client.get(
            reverse("tareas:detalle_tarea", args=[external.pk])
        )

        self.assertNotContains(response, "Tarea de otra empresa")
        self.assertEqual(external_response.status_code, 404)

    def test_no_aparecen_acciones_de_reparenting(self):
        response = self.get_detail(self.make_task("Solo lectura"))

        self.assertNotContains(response, "reparent")
        self.assertNotContains(response, "crear relación")
