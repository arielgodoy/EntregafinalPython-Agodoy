from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from tareas.forms import CompletarHitoForm
from tareas.models import HitoEvidencia, HitoHistorial
from tareas.services.progress import (
    complete_milestone,
    create_milestone,
    set_milestone_annulled,
    set_weighted_progress_mode,
    update_milestone,
)
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class HitoT080Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="80", descripcion="Empresa T080")
        cls.otra_empresa = create_empresa(codigo="81", descripcion="Otra T080")
        cls.manager = create_user("t080_manager")
        cls.owner = create_user("t080_owner")
        cls.creator = create_user("t080_creator")
        cls.observer = create_user("t080_observer")
        cls.foreign = create_user("t080_foreign")
        for user in [cls.manager, cls.owner, cls.creator, cls.observer]:
            assign_permission(user, cls.empresa, "Tareas - Hitos", ingresar=True)
        assign_permission(cls.manager, cls.empresa, "Tareas - Hitos", ingresar=True, modificar=True)
        assign_permission(cls.foreign, cls.otra_empresa, "Tareas - Hitos", ingresar=True)
        cls.tarea = create_tarea(
            cls.empresa,
            cls.manager,
            titulo="Tarea T080",
            responsable=cls.manager,
        )
        cls.hito = create_milestone(
            cls.tarea,
            "Hito T080",
            20,
            2,
            responsable=cls.owner,
            actor=cls.manager,
        )

    def _login_with_company(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def _url(self):
        return f"/tareas/{self.tarea.pk}/hitos/"

    def _complete(self, actor, **kwargs):
        defaults = {
            "resena_cierre": "Evidencia revisada y validada.",
            "formato_archivo": "PDF",
            "url": "https://example.com/cierre.pdf",
        }
        defaults.update(kwargs)
        return complete_milestone(self.hito, actor, **defaults)

    def test_authorized_actors_can_complete_and_preserve_assigned_responsible(self):
        self._complete(self.owner)
        self.hito.refresh_from_db()
        self.assertTrue(self.hito.completado)
        self.assertEqual(self.hito.cumplimiento, Decimal("100.00"))
        self.assertEqual(self.hito.completado_por, self.owner)
        self.assertEqual(self.hito.responsable, self.owner)
        self.assertIsNotNone(self.hito.fecha_completado)
        self.assertEqual(self.hito.resena_cierre, "Evidencia revisada y validada.")
        self.assertTrue(self.hito.evidencias.filter(usuario=self.owner).exists())
        self.assertTrue(
            self.hito.historial.filter(
                tipo_evento=HitoHistorial.Evento.COMPLETADO,
                usuario=self.owner,
            ).exists()
        )

    def test_task_responsible_and_creator_can_complete_other_owner_hito(self):
        self._complete(self.manager)
        self.hito.refresh_from_db()
        self.assertEqual(self.hito.completado_por, self.manager)
        self.assertEqual(self.hito.responsable, self.owner)

        creator_task = create_tarea(
            self.empresa,
            self.creator,
            titulo="Tarea creador T080",
            responsable=self.owner,
        )
        other_hito = create_milestone(
            creator_task,
            "Otro hito",
            0,
            1,
            responsable=self.owner,
            actor=self.creator,
        )
        complete_milestone(
            other_hito,
            self.creator,
            resena_cierre="Cierre por creador",
            formato_archivo="PDF",
            url="https://example.com/otro.pdf",
        )
        other_hito.refresh_from_db()
        self.assertEqual(other_hito.completado_por, self.creator)

    def test_observer_foreign_and_annulled_hito_cannot_complete(self):
        with self.assertRaises(ValidationError):
            self._complete(self.observer)
        with self.assertRaises(ValidationError):
            self._complete(self.foreign)
        set_milestone_annulled(self.hito, self.manager, True)
        with self.assertRaises(ValidationError):
            self._complete(self.manager)

    def test_completed_hito_cannot_be_completed_twice(self):
        self._complete(self.owner)
        with self.assertRaises(ValidationError):
            self._complete(self.manager)
        self.assertEqual(self.hito.evidencias.count(), 1)

    def test_form_rejects_empty_review_and_invalid_evidence_combinations(self):
        form = CompletarHitoForm(
            data={"resena_cierre": "   ", "formato_archivo": "PDF", "url": "https://example.com/a.pdf"}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("resena_cierre", form.errors)

        form = CompletarHitoForm(
            data={
                "resena_cierre": "Reseña",
                "formato_archivo": "PDF",
                "url": "https://example.com/a.pdf",
            },
            files={"archivo": SimpleUploadedFile("a.pdf", b"pdf")},
        )
        self.assertFalse(form.is_valid())

        form = CompletarHitoForm(
            data={"resena_cierre": "Reseña", "formato_archivo": "PDF"}
        )
        self.assertFalse(form.is_valid())

    def test_evidence_accepts_jpeg_and_rejects_incompatible_extension(self):
        self._complete(
            self.owner,
            formato_archivo="JPEG",
            archivo=SimpleUploadedFile("foto.jpeg", b"jpeg"),
            url="",
        )
        self.assertTrue(HitoEvidencia.objects.filter(hito=self.hito, formato_archivo="JPEG").exists())

        other_hito = create_milestone(
            self.tarea,
            "Hito incompatible",
            0,
            1,
            responsable=self.owner,
            actor=self.manager,
        )
        with self.assertRaises(ValidationError):
            complete_milestone(
                other_hito,
                self.owner,
                resena_cierre="Reseña",
                formato_archivo="PDF",
                archivo=SimpleUploadedFile("foto.jpg", b"jpg"),
            )
        other_hito.refresh_from_db()
        self.assertFalse(other_hito.completado)
        self.assertEqual(other_hito.evidencias.count(), 0)

    def test_manual_100_does_not_mark_hito_completed(self):
        update_milestone(self.hito, self.owner, cumplimiento=100)
        self.hito.refresh_from_db()
        self.assertEqual(self.hito.cumplimiento, Decimal("100.00"))
        self.assertFalse(self.hito.completado)

    def test_completion_recalculates_weighted_progress(self):
        set_weighted_progress_mode(self.tarea)
        self._complete(self.owner)
        self.tarea.avance.refresh_from_db()
        self.assertEqual(self.tarea.avance.porcentaje, Decimal("100.00"))

    def test_completion_rolls_back_when_history_fails(self):
        with patch(
            "tareas.services.progress._record_history",
            side_effect=RuntimeError("history failure"),
        ):
            with self.assertRaises(RuntimeError):
                self._complete(self.owner)
        self.hito.refresh_from_db()
        self.assertFalse(self.hito.completado)
        self.assertEqual(self.hito.evidencias.count(), 0)

    def test_completion_controls_and_modal_are_role_scoped(self):
        self._login_with_company(self.owner)
        response = self.client.get(self._url())
        self.assertContains(response, "Completar Hito")
        self.assertContains(response, f'id="completarHitoModal-{self.hito.pk}"')
        self.assertContains(response, "Reseña de cierre")
        self.assertContains(response, "Formato de evidencia")
        self.assertContains(response, "Adjunte un archivo o indique una URL.")

        self._login_with_company(self.observer)
        response = self.client.get(self._url())
        self.assertNotContains(response, 'data-key="tareas.actions.complete_milestone"')

    def test_invalid_completion_reopens_the_correct_modal(self):
        self._login_with_company(self.owner)
        response = self.client.post(
            self._url(),
            data={
                "accion": "completar_hito",
                "hito_id": self.hito.pk,
                "resena_cierre": "   ",
                "formato_archivo": "PDF",
                "url": "https://example.com/cierre.pdf",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'class="modal fade show d-block" id="completarHitoModal-{self.hito.pk}"',
        )
        self.hito.refresh_from_db()
        self.assertFalse(self.hito.completado)
