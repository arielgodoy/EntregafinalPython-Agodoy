"""Tests de la migración de datos 0004 (anulación por flag).

Cubre PASO 6.12 y 6.13: tareas históricas con estado=ANULADA migran a anulada=True
restaurando el estado funcional desde el snapshot; una tarea ANULADA sin snapshot válido
aborta la migración de forma segura.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import Tarea, TareaAnulacionSnapshot


def _import_migrar():
    # Importa la función de la migración 0004 sin cargar el módulo de migración como modelo.
    import importlib.util
    import pathlib

    ruta = (
        pathlib.Path(__file__).resolve().parent.parent
        / "migrations"
        / "0004_tarea_anulada_alter_tarea_estado.py"
    )
    spec = importlib.util.spec_from_file_location("mig0004", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.migrar_anuladas_a_flag


class _FakeModel:
    """Envoltura mínima para usar los modelos reales en la función de migración."""

    def __init__(self, model):
        self._model = model

    def __getattr__(self, item):
        return getattr(self._model, item)


class _Apps:
    def get_model(self, app_label, model_name):
        from django.apps import apps

        return apps.get_model(app_label, model_name)


class MigracionAnuladaFlagTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="M4", descripcion="Mig 0004")
        cls.user = User.objects.create_user(username="m4_user", password="x")

    def _tarea_anulada_con_snapshot(self, estado_anterior):
        tarea = Tarea.objects.create(
            titulo="Histórica",
            empresa=self.empresa,
            creada_por=self.user,
            responsable=self.user,
        )
        # Forzar estado histórico ANULADA (bypass del modelo, simula dato legacy).
        Tarea.objects.filter(pk=tarea.pk).update(estado="ANULADA")
        TareaAnulacionSnapshot.objects.create(
            tarea=tarea,
            estado_anterior=estado_anterior,
            usuario_anulo=self.user,
        )
        return tarea

    def test_migracion_restaura_estado_desde_snapshot(self):
        tarea = self._tarea_anulada_con_snapshot("GESTION")
        migrar = _import_migrar()
        migrar(_Apps(), None)
        tarea.refresh_from_db()
        self.assertTrue(tarea.anulada)
        self.assertEqual(tarea.estado, "GESTION")

    def test_migracion_aborta_si_no_hay_snapshot(self):
        tarea = Tarea.objects.create(
            titulo="Sin snapshot",
            empresa=self.empresa,
            creada_por=self.user,
            responsable=self.user,
        )
        Tarea.objects.filter(pk=tarea.pk).update(estado="ANULADA")
        migrar = _import_migrar()
        with self.assertRaises(RuntimeError):
            migrar(_Apps(), None)
        # No se modificó la tarea sin snapshot.
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, "ANULADA")
        self.assertFalse(tarea.anulada)
