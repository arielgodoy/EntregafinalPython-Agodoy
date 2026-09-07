"""Tests del formulario TareaForm (T020)."""

from django.contrib.auth.models import User
from django.test import TestCase

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

    def test_prioridad_rechaza_valor_fuera_de_aprobados(self):
        form = TareaForm(data={"titulo": "X", "prioridad": "MEDIA"})
        self.assertFalse(form.is_valid())
        self.assertIn("prioridad", form.errors)

    def test_prioridad_acepta_valores_aprobados(self):
        for valor in ["SIMPLE", "NORMAL", "URGENTE", "CRITICA"]:
            form = TareaForm(data={"titulo": "X", "prioridad": valor})
            self.assertTrue(form.is_valid(), f"{valor}: {form.errors}")
