"""Tests del modelo Tarea (T009).

Reglas verificadas (spec/clarifications):
- Crear con solo título queda en BORRADOR (FR-001/FR-005).
- Publicar sin responsable falla (FR-007).
- Publicar con responsable inactivo falla (Q1).
- Publicar con responsable activo fija estado y fecha_publicacion (FR-008).
- Edición post-publicación sin responsable válido falla (FR-008).
- Transición PUBLICADA→BORRADOR imposible (Q2).
- Prioridad acepta solo valores aprobados; default NORMAL.

Nota: la empresa no se valida como inmutable a nivel de modelo (regla descartada); el
aislamiento multiempresa se verifica en las vistas (test_views.py).
"""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import Tarea


class TareaModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        cls.creador = User.objects.create_user(username="creador", password="x")
        cls.responsable = User.objects.create_user(username="responsable", password="x")

    def _crear_borrador(self, **kwargs):
        datos = {
            "titulo": "Tarea de prueba",
            "empresa": self.empresa,
            "creada_por": self.creador,
        }
        datos.update(kwargs)
        return Tarea.objects.create(**datos)

    def test_crear_solo_titulo_queda_borrador(self):
        tarea = self._crear_borrador()
        self.assertEqual(tarea.estado, Tarea.Estado.BORRADOR)
        self.assertIsNone(tarea.fecha_publicacion)
        self.assertIsNotNone(tarea.fecha_creacion)
        self.assertEqual(tarea.empresa, self.empresa)

    def test_prioridad_default_es_normal(self):
        tarea = self._crear_borrador()
        self.assertEqual(tarea.prioridad, Tarea.Prioridad.NORMAL)

    def test_prioridad_rechaza_valor_no_aprobado(self):
        tarea = self._crear_borrador(prioridad="MEDIA")
        with self.assertRaises(ValidationError):
            tarea.full_clean()

    def test_publicar_sin_responsable_falla(self):
        tarea = self._crear_borrador()
        with self.assertRaises(ValidationError):
            tarea.publicar()
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, Tarea.Estado.BORRADOR)

    def test_publicar_con_responsable_inactivo_falla(self):
        self.responsable.is_active = False
        self.responsable.save()
        tarea = self._crear_borrador(responsable=self.responsable)
        with self.assertRaises(ValidationError):
            tarea.publicar()
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, Tarea.Estado.BORRADOR)

    def test_publicar_con_responsable_activo_ok(self):
        tarea = self._crear_borrador(responsable=self.responsable)
        tarea.publicar()
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, Tarea.Estado.PUBLICADA)
        self.assertIsNotNone(tarea.fecha_publicacion)

    def test_publicada_sin_responsable_falla_validacion(self):
        tarea = self._crear_borrador(responsable=self.responsable)
        tarea.publicar()
        tarea.responsable = None
        with self.assertRaises(ValidationError):
            tarea.full_clean()

    def test_publicada_no_puede_volver_a_borrador(self):
        tarea = self._crear_borrador(responsable=self.responsable)
        tarea.publicar()
        tarea.refresh_from_db()
        tarea.estado = Tarea.Estado.BORRADOR
        with self.assertRaises(ValidationError):
            tarea.full_clean()

    def test_fecha_publicacion_inmutable(self):
        tarea = self._crear_borrador(responsable=self.responsable)
        tarea.publicar()
        tarea.refresh_from_db()
        tarea.fecha_publicacion = tarea.fecha_publicacion.replace(year=2000)
        with self.assertRaises(ValidationError):
            tarea.full_clean()

    def test_publicar_dos_veces_error_controlado(self):
        tarea = self._crear_borrador(responsable=self.responsable)
        tarea.publicar()
        tarea.refresh_from_db()
        fecha_original = tarea.fecha_publicacion
        with self.assertRaises(ValidationError):
            tarea.publicar()
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, Tarea.Estado.PUBLICADA)
        self.assertEqual(tarea.fecha_publicacion, fecha_original)
