from datetime import date
import re

from django.test import TestCase
from django.urls import reverse

from tareas.models import Hito, Tarea
from tareas.services.progress import create_milestone
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class T077DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="77", descripcion="Empresa T077")
        cls.otra_empresa = create_empresa(codigo="78", descripcion="Otra T077")
        cls.usuario = create_user("t077_usuario")
        cls.otro_usuario = create_user("t077_otro")
        assign_permission(cls.usuario, cls.empresa, "Tareas - Dashboard personal", ingresar=True)
        assign_permission(cls.otro_usuario, cls.empresa, "Tareas - Dashboard personal", ingresar=True)
        assign_permission(cls.usuario, cls.otra_empresa, "Tareas - Dashboard personal", ingresar=True)

        cls.tarea_critica = create_tarea(
            cls.empresa,
            cls.usuario,
            titulo="Tarea crítica propia",
            responsable=cls.usuario,
            prioridad=Tarea.Prioridad.CRITICA,
            fecha_tope=date(2026, 10, 1),
        )
        cls.tarea_urgente = create_tarea(
            cls.empresa,
            cls.usuario,
            titulo="Tarea urgente propia",
            responsable=cls.usuario,
            prioridad=Tarea.Prioridad.URGENTE,
        )
        cls.tarea_otro_usuario = create_tarea(
            cls.empresa,
            cls.otro_usuario,
            titulo="Tarea ajena",
            responsable=cls.otro_usuario,
        )
        cls.tarea_otra_empresa = create_tarea(
            cls.otra_empresa,
            cls.usuario,
            titulo="Tarea otra empresa",
            responsable=cls.usuario,
        )
        cls.hito_pendiente = create_milestone(
            cls.tarea_urgente,
            "Hito pendiente propio",
            25,
            2,
            responsable=cls.usuario,
            actor=cls.usuario,
        )
        cls.hito_completado = create_milestone(
            cls.tarea_critica,
            "Hito completado propio",
            100,
            1,
            responsable=cls.usuario,
            actor=cls.usuario,
        )
        cls.hito_completado.completado = True
        cls.hito_completado.save(update_fields=["completado"])
        cls.hito_anulado = create_milestone(
            cls.tarea_critica,
            "Hito anulado propio",
            10,
            1,
            responsable=cls.usuario,
            actor=cls.usuario,
        )
        cls.hito_anulado.anulado = True
        cls.hito_anulado.save(update_fields=["anulado"])
        cls.hito_otro_usuario = create_milestone(
            cls.tarea_critica,
            "Hito ajeno",
            10,
            1,
            responsable=cls.otro_usuario,
            actor=cls.usuario,
        )
        cls.hito_otra_empresa = create_milestone(
            cls.tarea_otra_empresa,
            "Hito otra empresa",
            10,
            1,
            responsable=cls.usuario,
            actor=cls.usuario,
        )

    def setUp(self):
        self.client.force_login(self.usuario)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def test_dashboard_filtra_asignaciones_y_agrupa_prioridad(self):
        response = self.client.get(reverse("tareas:mis_tareas"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Tarea crítica propia", content)
        self.assertIn("Tarea urgente propia", content)
        self.assertNotIn("Tarea ajena", content)
        self.assertNotIn("Tarea otra empresa", content)
        self.assertIn("Hito pendiente propio", content)
        self.assertIn("Hito completado propio", content)
        self.assertNotIn("Hito anulado propio", content)
        self.assertNotIn("Hito ajeno", content)
        self.assertNotIn("Hito otra empresa", content)
        self.assertLess(content.index("CRITICA"), content.index("URGENTE"))

    def test_dashboard_reutiliza_navegacion_y_acciones_canonicas(self):
        response = self.client.get(reverse("tareas:mis_tareas"))
        content = response.content.decode()

        self.assertContains(response, reverse("tareas:detalle_tarea", args=[self.tarea_critica.pk]))
        self.assertContains(response, reverse("tareas:hitos_tarea", args=[self.tarea_urgente.pk]))
        self.assertContains(response, "Gestionar Hito")
        self.assertContains(response, "Ver cumplimiento")
        self.assertNotContains(response, "Reasignar")
        self.assertNotContains(response, "Editar Hito")
        self.assertNotIn("clasificacion", content.lower())

    def test_dashboard_browser_title_is_plain_text_and_heading_keeps_i18n(self):
        response = self.client.get(reverse("tareas:mis_tareas"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        title_match = re.search(r"<title>(.*?)</title>", content, re.DOTALL)

        self.assertIsNotNone(title_match)
        browser_title = title_match.group(1)
        self.assertTrue(browser_title.startswith("Mis tareas y hitos"))
        self.assertNotIn("<span", browser_title)
        self.assertNotIn("data-key=", browser_title)
        self.assertContains(
            response,
            '<span data-key="tareas.personal.title">Mis tareas y hitos</span>',
        )

    def test_dashboard_vacio_muestra_mensajes(self):
        Hito.objects.filter(responsable=self.usuario).delete()
        Tarea.objects.filter(responsable=self.usuario, empresa=self.empresa).update(responsable=self.otro_usuario)

        response = self.client.get(reverse("tareas:mis_tareas"))

        self.assertContains(response, "No tienes tareas asignadas en esta empresa.")
        self.assertContains(response, "No tienes hitos asignados en esta empresa.")

    def test_dashboard_requiere_permiso_ingresar(self):
        assign_permission(self.usuario, self.empresa, "Tareas - Dashboard personal", ingresar=False)

        response = self.client.get(reverse("tareas:mis_tareas"))

        self.assertEqual(response.status_code, 403)