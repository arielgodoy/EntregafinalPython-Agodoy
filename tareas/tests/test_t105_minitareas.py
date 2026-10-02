from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa
from tareas.models import MiniTarea, MiniTareaEvento, Tarea
from tareas.services.closure import create_mini_task, delete_mini_task
from tareas.services.lifecycle import transition_task
from tareas.services.participants import effective_participant_ids, is_effective_participant
from tareas.tests.factories import activate_company, assign_permission
from django.contrib.auth.models import User


class MiniTareaT105Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="T105", descripcion="Empresa T105")
        cls.otra_empresa = Empresa.objects.create(codigo="T105B", descripcion="Empresa T105 B")
        cls.responsable = User.objects.create_user("t105_responsable")
        cls.supervisor = User.objects.create_user("t105_supervisor")
        cls.tercero = User.objects.create_user("t105_tercero")
        cls.asignado = User.objects.create_user("t105_asignado")
        for user in (cls.responsable, cls.supervisor, cls.tercero, cls.asignado):
            assign_permission(
                user,
                cls.empresa,
                "Tareas",
                ingresar=True,
                modificar=True,
                crear=user in {cls.responsable, cls.supervisor},
                supervisor=user == cls.supervisor,
            )
        assign_permission(
            cls.asignado,
            cls.empresa,
            "Tareas - Dashboard personal",
            ingresar=True,
        )

    def make_task(self, empresa=None):
        tarea = Tarea.objects.create(
            titulo="Tarea T105",
            empresa=empresa or self.empresa,
            creada_por=self.responsable,
            responsable=self.responsable,
            fecha_tope=date.today(),
        )
        tarea.publicar(self.responsable)
        transition_task(tarea, Tarea.Estado.GESTION, self.responsable, "INICIAR_GESTION")
        return tarea

    def test_responsable_puede_eliminar_minitarea_sin_historial(self):
        tarea = self.make_task()
        mini_tarea = create_mini_task(
            tarea=tarea,
            descripcion="Eliminar esta mini-tarea",
            persona=self.asignado,
            actor=self.responsable,
        )

        delete_mini_task(tarea=tarea, mini_tarea=mini_tarea, actor=self.responsable)

        self.assertFalse(MiniTarea.objects.filter(pk=mini_tarea.pk).exists())

    def test_historial_y_hecha_bloquean_eliminacion(self):
        tarea = self.make_task()
        mini_tarea = create_mini_task(
            tarea=tarea,
            descripcion="Conservar historial",
            persona=self.asignado,
            actor=self.responsable,
        )
        MiniTareaEvento.objects.create(
            mini_tarea=mini_tarea,
            tipo=MiniTareaEvento.Tipo.REAPERTURA,
            actor=self.responsable,
            comentario="Historial de prueba",
        )

        with self.assertRaises(ValidationError):
            delete_mini_task(tarea=tarea, mini_tarea=mini_tarea, actor=self.responsable)

        mini_tarea.eventos.all().delete()
        mini_tarea.hecho = True
        mini_tarea.save(update_fields=["hecho"])
        with self.assertRaises(ValidationError):
            delete_mini_task(tarea=tarea, mini_tarea=mini_tarea, actor=self.responsable)

    def test_solo_responsable_o_supervisor_pueden_eliminar(self):
        tarea = self.make_task()
        mini_tarea = create_mini_task(
            tarea=tarea,
            descripcion="Restricción de actor",
            persona=self.asignado,
            actor=self.responsable,
        )

        with self.assertRaises(ValidationError):
            delete_mini_task(tarea=tarea, mini_tarea=mini_tarea, actor=self.tercero)

        delete_mini_task(tarea=tarea, mini_tarea=mini_tarea, actor=self.supervisor)
        self.assertFalse(MiniTarea.objects.filter(pk=mini_tarea.pk).exists())

    def test_asignado_de_minitarea_es_participante_efectivo(self):
        tarea = self.make_task()
        create_mini_task(
            tarea=tarea,
            descripcion="Participación dinámica",
            persona=self.asignado,
            actor=self.responsable,
        )

        self.assertTrue(is_effective_participant(tarea, self.asignado))
        self.assertIn(self.asignado.pk, effective_participant_ids(tarea))

    def test_dashboard_muestra_minitarea_asignada_y_filtra_empresa(self):
        tarea = self.make_task()
        create_mini_task(
            tarea=tarea,
            descripcion="MiniTarea visible",
            persona=self.asignado,
            actor=self.responsable,
        )
        tarea_externa = self.make_task(empresa=self.otra_empresa)
        MiniTarea.objects.create(
            tarea=tarea_externa,
            descripcion="MiniTarea fuera de empresa",
            persona=self.asignado,
        )

        self.client.force_login(self.asignado)
        activate_company(self.client, self.empresa)
        response = self.client.get(reverse("tareas:mis_tareas"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MiniTarea visible")
        self.assertNotContains(response, "MiniTarea fuera de empresa")

    def test_endpoint_exige_empresa_activa_y_es_post(self):
        tarea = self.make_task()
        mini_tarea = create_mini_task(
            tarea=tarea,
            descripcion="Protección web",
            persona=self.asignado,
            actor=self.responsable,
        )
        self.client.force_login(self.responsable)
        activate_company(self.client, self.otra_empresa)

        response = self.client.post(
            reverse("tareas:eliminar_minitarea", args=[tarea.pk, mini_tarea.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(MiniTarea.objects.filter(pk=mini_tarea.pk).exists())

        activate_company(self.client, self.empresa)
        response = self.client.get(
            reverse("tareas:eliminar_minitarea", args=[tarea.pk, mini_tarea.pk])
        )
        self.assertEqual(response.status_code, 405)
        self.assertTrue(MiniTarea.objects.filter(pk=mini_tarea.pk).exists())
