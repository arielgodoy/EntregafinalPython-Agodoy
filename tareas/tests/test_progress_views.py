from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from tareas.models import Avance, Hito, Tarea
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class ProgressViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="PV1")
        cls.otra_empresa = create_empresa(codigo="PV2")
        cls.usuario = create_user(username="progress-view-user")
        assign_permission(cls.usuario, cls.empresa, "Tareas - Hitos", modificar=True)
        cls.tarea = create_tarea(cls.empresa, cls.usuario, titulo="Tarea progreso")
        cls.tarea_externa = create_tarea(cls.otra_empresa, cls.usuario, titulo="Tarea externa")

    def setUp(self):
        self.client.login(username="progress-view-user", password="password-prueba")
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def test_login_requerido(self):
        self.client.logout()
        response = self.client.get(reverse("tareas:hitos_tarea", args=[self.tarea.pk]))
        self.assertEqual(response.status_code, 302)

    def test_get_muestra_hitos_y_avance_de_la_empresa(self):
        Hito.objects.create(tarea=self.tarea, nombre="Plan", peso=2)
        response = self.client.get(reverse("tareas:hitos_tarea", args=[self.tarea.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Plan")
        self.assertContains(response, "Hitos y avance")
        self.assertContains(response, "Cumplimiento (%)")
        self.assertContains(response, "Peso del hito (%)")

    def test_post_crea_hito_mediante_servicio(self):
        response = self.client.post(
            reverse("tareas:hitos_tarea", args=[self.tarea.pk]),
            {"accion": "hito", "nombre": "Ejecución", "cumplimiento": "25", "peso": "2"},
        )
        self.assertRedirects(response, reverse("tareas:hitos_tarea", args=[self.tarea.pk]))
        self.assertTrue(Hito.objects.filter(tarea=self.tarea, nombre="Ejecución").exists())

    def test_post_configura_avance_manual_y_ponderado(self):
        self.client.post(
            reverse("tareas:hitos_tarea", args=[self.tarea.pk]),
            {"accion": "manual", "porcentaje": "42.50"},
        )
        avance = Avance.objects.get(tarea=self.tarea)
        self.assertEqual(avance.porcentaje, Decimal("42.50"))
        self.client.post(
            reverse("tareas:hitos_tarea", args=[self.tarea.pk]),
            {"accion": "ponderado", "confirmar": "on"},
        )
        avance.refresh_from_db()
        self.assertEqual(avance.modo, Avance.Modo.PONDERADO)

    def test_otra_empresa_no_es_accesible(self):
        response = self.client.get(reverse("tareas:hitos_tarea", args=[self.tarea_externa.pk]))
        self.assertEqual(response.status_code, 404)
