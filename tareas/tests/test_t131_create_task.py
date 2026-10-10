from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from tareas.models import (
    CorrelativoEmpresa,
    Tarea,
    TareaConnectionRole,
    TareaParticipante,
    TareaReasignacion,
)
from tareas.services.task_storage import CreatedTaskResult


class CreateTaskCharacterizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa_a = Empresa.objects.create(codigo="00", descripcion="Empresa A")
        cls.empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        cls.creator = User.objects.create_user(username="t131-creator", password="pass")
        cls.valid_responsible = User.objects.create_user(
            username="t131-valid", password="pass"
        )
        cls.cross_company = User.objects.create_user(
            username="t131-cross", password="pass"
        )
        cls.inactive = User.objects.create_user(
            username="t131-inactive", password="pass", is_active=False
        )
        cls.vista = Vista.objects.create(nombre="Tareas")
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="DJANGO",
            django_alias="default",
        )
        for user, empresa, crear in (
            (cls.creator, cls.empresa_a, True),
            (cls.valid_responsible, cls.empresa_a, False),
            (cls.cross_company, cls.empresa_b, False),
            (cls.inactive, cls.empresa_a, False),
        ):
            Permiso.objects.create(
                usuario=user,
                empresa=empresa,
                vista=cls.vista,
                ingresar=True,
                crear=crear,
            )

    def setUp(self):
        self.client.force_login(self.creator)
        session = self.client.session
        session["empresa_id"] = self.empresa_a.pk
        session.save()

    def _post(self, **data):
        payload = {"titulo": "Crear Tarea 131", "fecha_tope": "2026-10-20"}
        payload.update(data)
        return self.client.post(reverse("tareas:crear_tarea"), payload)

    def test_creates_draft_from_session_company_and_redirects_to_detail(self):
        response = self._post()

        self.assertEqual(response.status_code, 302)
        task = Tarea.objects.get(titulo="Crear Tarea 131")
        self.assertEqual(task.estado, Tarea.Estado.BORRADOR)
        self.assertEqual(task.empresa_id, self.empresa_a.pk)
        self.assertEqual(task.creada_por_id, self.creator.pk)
        self.assertRegex(task.correlativo, r"^B[0-9]{7}$")
        self.assertIsNone(task.fecha_publicacion)
        self.assertIsNone(task.fecha_asignacion)
        self.assertRedirects(response, reverse("tareas:detalle_tarea", args=[task.pk]))

    def test_posted_company_id_cannot_change_session_company(self):
        response = self._post(empresa_id=str(self.empresa_b.pk))

        self.assertEqual(response.status_code, 302)
        task = Tarea.objects.get(titulo="Crear Tarea 131")
        self.assertEqual(task.empresa_id, self.empresa_a.pk)

    def test_no_responsible_creates_draft_without_assignment_records(self):
        with patch("tareas.services.task_storage.emit_task_event") as emit_task_event:
            response = self._post()

        task = Tarea.objects.get(titulo="Crear Tarea 131")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(task.responsable_id)
        self.assertFalse(TareaParticipante.objects.filter(tarea=task).exists())
        self.assertFalse(TareaReasignacion.objects.filter(tarea=task).exists())
        emit_task_event.assert_not_called()

    def test_active_responsible_in_active_company_is_allowed(self):
        with patch("tareas.services.task_storage.emit_task_event") as emit_task_event:
            response = self._post(responsable=str(self.valid_responsible.pk))

        task = Tarea.objects.get(titulo="Crear Tarea 131")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(task.responsable_id, self.valid_responsible.pk)
        self.assertFalse(TareaParticipante.objects.filter(tarea=task).exists())
        emit_task_event.assert_called_once()

    def test_cross_company_responsible_is_rejected_without_consuming_sequence(self):
        before = CorrelativoEmpresa.objects.filter(empresa=self.empresa_a).values_list(
            "siguiente_numero", flat=True
        ).first()

        response = self._post(responsable=str(self.cross_company.pk))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Tarea.objects.filter(titulo="Crear Tarea 131").exists())
        after = CorrelativoEmpresa.objects.filter(empresa=self.empresa_a).values_list(
            "siguiente_numero", flat=True
        ).first()
        self.assertEqual(after, before)
        self.assertContains(response, "responsable")

    def test_inactive_responsible_is_rejected_without_consuming_sequence(self):
        before = CorrelativoEmpresa.objects.filter(empresa=self.empresa_a).values_list(
            "siguiente_numero", flat=True
        ).first()

        response = self._post(responsable=str(self.inactive.pk))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Tarea.objects.filter(titulo="Crear Tarea 131").exists())
        after = CorrelativoEmpresa.objects.filter(empresa=self.empresa_a).values_list(
            "siguiente_numero", flat=True
        ).first()
        self.assertEqual(after, before)
        self.assertContains(response, "responsable")

    def test_second_creation_increments_company_sequence(self):
        first = self._post()
        second = self.client.post(
            reverse("tareas:crear_tarea"),
            {"titulo": "Crear Tarea 131 second", "fecha_tope": "2026-10-20"},
        )

        first_task = Tarea.objects.get(pk=first.url.split("/")[-2])
        second_task = Tarea.objects.get(pk=second.url.split("/")[-2])
        self.assertEqual(int(second_task.correlativo[1:]), int(first_task.correlativo[1:]) + 1)

    @patch("tareas.views.create_task_draft")
    def test_redirect_uses_result_id_without_orm_task_instance(self, create_task):
        create_task.return_value = CreatedTaskResult(
            id=123,
            empresa_id=self.empresa_a.pk,
            correlativo="B0000123",
            estado=Tarea.Estado.BORRADOR,
            task=None,
        )

        response = self._post()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/tareas/123/")

    def test_model_save_failure_rolls_back_sequence_and_task(self):
        with patch.object(models.Model, "save", side_effect=RuntimeError("insert failed")):
            with self.assertRaises(RuntimeError):
                Tarea.objects.create(
                    titulo="No persistir",
                    empresa=self.empresa_a,
                    creada_por=self.creator,
                )

        self.assertFalse(Tarea.objects.filter(titulo="No persistir").exists())
        self.assertFalse(CorrelativoEmpresa.objects.filter(empresa=self.empresa_a).exists())
