from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from tareas.models import EvaluacionSimilitud, Tarea


class T060SimilarityViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="T60", descripcion="Empresa T060")
        cls.usuario = User.objects.create_user("t060_user", password="pass")
        cls.responsable = User.objects.create_user("t060_resp", password="pass")
        cls.vista = Vista.objects.create(nombre="Tareas - Ciclo de vida")
        cls.vista_tareas = Vista.objects.create(nombre="Tareas")
        Permiso.objects.create(
            usuario=cls.usuario,
            empresa=cls.empresa,
            vista=cls.vista,
            modificar=True,
        )
        Permiso.objects.create(
            usuario=cls.usuario,
            empresa=cls.empresa,
            vista=cls.vista_tareas,
            ingresar=True,
        )

    def setUp(self):
        self.client.login(username="t060_user", password="pass")
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def tarea(self, **changes):
        values = {
            "titulo": "Problema de prueba",
            "descripcion": "Descripción de prueba",
            "correlativo": f"B{Tarea.objects.count() + 1:07d}",
            "empresa": self.empresa,
            "creada_por": self.usuario,
            "responsable": self.responsable,
            "fecha_tope": date(2026, 10, 1),
        }
        values.update(changes)
        return Tarea.objects.create(**values)

    def test_publication_without_relevant_matches_continues(self):
        tarea = self.tarea()
        response = self.client.post(reverse("tareas:publicar_tarea", args=[tarea.pk]))
        tarea.refresh_from_db()
        self.assertRedirects(response, reverse("tareas:detalle_tarea", args=[tarea.pk]))
        self.assertEqual(tarea.estado, Tarea.Estado.ACTIVA)

    def test_pending_match_redirects_to_similarity_and_stays_draft(self):
        candidate = self.tarea(
            correlativo="A9999999",
            estado=Tarea.Estado.ACTIVA,
            fecha_publicacion=None,
        )
        tarea = self.tarea(correlativo="B9999998")
        response = self.client.post(reverse("tareas:publicar_tarea", args=[tarea.pk]))
        tarea.refresh_from_db()
        self.assertRedirects(response, reverse("tareas:similitud_tarea", args=[tarea.pk]))
        self.assertEqual(tarea.estado, Tarea.Estado.BORRADOR)
        self.assertTrue(
            EvaluacionSimilitud.objects.filter(
                tarea=tarea,
                tarea_candidata=candidate,
                supera_umbral=True,
                decision=EvaluacionSimilitud.Decision.PENDIENTE,
            ).exists()
        )

    def test_similarity_confirmation_uses_contract_decision_and_allows_publish(self):
        candidate = self.tarea(
            correlativo="A9999997",
            estado=Tarea.Estado.ACTIVA,
            fecha_publicacion=None,
        )
        tarea = self.tarea(correlativo="B9999996")
        self.client.post(reverse("tareas:publicar_tarea", args=[tarea.pk]))
        evaluation = EvaluacionSimilitud.objects.get(
            tarea=tarea,
            tarea_candidata=candidate,
        )
        response = self.client.post(
            reverse(
                "tareas:confirmar_similitud",
                args=[tarea.pk, evaluation.pk],
            ),
            {"decision": EvaluacionSimilitud.Decision.DISTINTO_PROBLEMA},
        )
        tarea.refresh_from_db()
        self.assertRedirects(response, reverse("tareas:detalle_tarea", args=[tarea.pk]))
        self.assertEqual(tarea.estado, Tarea.Estado.ACTIVA)

    def test_similarity_rejects_invalid_decision(self):
        tarea = self.tarea()
        response = self.client.post(
            reverse(
                "tareas:confirmar_similitud",
                args=[tarea.pk, 999],
            ),
            {"decision": "INVALIDA"},
        )
        self.assertEqual(response.status_code, 404)
