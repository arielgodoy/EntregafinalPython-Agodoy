"""Tests del formulario TareaForm (T020)."""

from django.contrib.auth.models import User
from django.test import TestCase
from datetime import date

from tareas.forms import TareaForm
from tareas.models import Tarea


class TareaFormTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.responsable = User.objects.create_user(username="resp", password="x")

    def test_titulo_requerido(self):
        form = TareaForm(data={"titulo": ""})
        self.assertFalse(form.is_valid())
        self.assertIn("titulo", form.errors)

    def test_responsable_opcional_en_borrador(self):
        form = TareaForm(data={"titulo": "Solo título"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_fecha_tope_es_opcional_y_usa_input_date(self):
        form = TareaForm(data={"titulo": "Solo título"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.fields["fecha_tope"].widget.input_type, "date")

    def test_fecha_tope_se_conserva_en_edicion_de_borrador(self):
        tarea = Tarea(
            titulo="Borrador",
            correlativo="B0000001",
            creada_por=self.responsable,
            empresa_id=1,
            fecha_tope=date(2026, 9, 20),
        )
        form = TareaForm(instance=tarea)
        self.assertEqual(form.initial["fecha_tope"], date(2026, 9, 20))

    def test_fecha_tope_queda_desactivada_en_tarea_operativa(self):
        tarea = Tarea(
            titulo="Operativa",
            correlativo="A0000001",
            creada_por=self.responsable,
            empresa_id=1,
            estado=Tarea.Estado.GESTION,
            fecha_tope=date(2026, 9, 20),
        )
        form = TareaForm(instance=tarea)
        self.assertTrue(form.fields["fecha_tope"].disabled)

    def test_prioridad_rechaza_valor_fuera_de_aprobados(self):
        form = TareaForm(data={"titulo": "X", "prioridad": "MEDIA"})
        self.assertFalse(form.is_valid())
        self.assertIn("prioridad", form.errors)

    def test_prioridad_acepta_valores_aprobados(self):
        for valor in ["SIMPLE", "NORMAL", "URGENTE", "CRITICA"]:
            form = TareaForm(data={"titulo": "X", "prioridad": valor})
            self.assertTrue(form.is_valid(), f"{valor}: {form.errors}")
