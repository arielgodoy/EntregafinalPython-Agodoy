from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from access_control.models import Empresa
from tareas.models import CausaAtraso, Tarea, TareaTransicion
from tareas.services.lifecycle import (
    annul_task,
    complete_task,
    reject_closure,
    reactivate_task,
    transition_task,
)
from tareas.services.scheduling import dias_atraso, esta_vencida, reprogramar
from tareas.tests.factories import assign_permission, create_user


class SchedulingT030Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="T30", descripcion="T030")
        cls.creador = create_user("t30_creador")
        cls.responsable = create_user("t30_responsable")
        cls.autorizador = create_user("t30_autorizador")
        assign_permission(cls.creador, cls.empresa, "Tareas - Listado", ingresar=True)

    def make_task(self, **kwargs):
        defaults = {
            "titulo": "Tarea T030",
            "empresa": self.empresa,
            "creada_por": self.creador,
            "responsable": self.responsable,
        }
        defaults.update(kwargs)
        return Tarea.objects.create(**defaults)

    def publish_and_start(self, **kwargs):
        task = self.make_task(fecha_tope=date.today() - timedelta(days=2), **kwargs)
        task.publicar(self.creador)
        transition_task(task, Tarea.Estado.GESTION, self.creador, "INICIAR_GESTION")
        return task

    def test_publicacion_exige_fecha_tope_y_fija_asignacion(self):
        task = self.make_task()
        with self.assertRaises(ValidationError):
            task.publicar(self.creador)
        task.fecha_tope = date.today()
        task.publicar(self.creador)
        self.assertIsNotNone(task.fecha_asignacion)

    def test_atraso_derivado_y_cumplimiento_corta_calculo(self):
        task = self.publish_and_start()
        referencia = timezone.now()
        self.assertTrue(esta_vencida(task, referencia))
        self.assertEqual(dias_atraso(task, referencia), 2)
        complete_task(task, self.responsable)
        task.refresh_from_db()
        self.assertIsNotNone(task.fecha_cumplimiento)
        self.assertEqual(dias_atraso(task, task.fecha_cumplimiento), 2)

    def test_borrador_sin_fecha_no_tiene_atraso(self):
        task = self.make_task()
        self.assertFalse(esta_vencida(task, timezone.now()))
        self.assertEqual(dias_atraso(task, timezone.now()), 0)

    def test_fecha_tope_en_el_limite_no_esta_vencida(self):
        task = self.make_task(fecha_tope=date.today())
        task.publicar(self.creador)
        transition_task(task, Tarea.Estado.GESTION, self.creador, "INICIAR_GESTION")
        referencia = timezone.make_aware(
            timezone.datetime.combine(task.fecha_tope, timezone.datetime.min.time())
        )
        self.assertFalse(esta_vencida(task, referencia))
        self.assertEqual(dias_atraso(task, referencia), 0)

    def test_rechazo_limpia_cumplimiento_y_conserva_cierre(self):
        task = self.publish_and_start()
        complete_task(task, self.responsable)
        reject_closure(task, self.autorizador)
        task.refresh_from_db()
        self.assertIsNone(task.fecha_cumplimiento)
        self.assertTrue(task.cierre_completado)

    def test_anulacion_y_reactivacion_conservan_fechas_y_corte(self):
        task = self.publish_and_start()
        fecha_tope = task.fecha_tope
        annul_task(task, self.autorizador)
        task.refresh_from_db()
        self.assertEqual(dias_atraso(task, timezone.now()), 2)
        reactivate_task(task, self.autorizador)
        task.refresh_from_db()
        self.assertEqual(task.fecha_tope, fecha_tope)
        self.assertEqual(
            TareaTransicion.objects.filter(tarea=task, accion_evento="ANULAR").count(),
            1,
        )

    def test_reprogramacion_es_atomica_y_m_n(self):
        task = self.publish_and_start()
        causas = list(CausaAtraso.objects.order_by("codigo")[:2])
        historial = reprogramar(
            task,
            date.today() + timedelta(days=5),
            "Dependencia externa",
            self.creador,
            causas,
        )
        task.refresh_from_db()
        self.assertEqual(task.fecha_tope, date.today() + timedelta(days=5))
        self.assertEqual(historial.causas.count(), 2)
        with self.assertRaises(ValidationError):
            reprogramar(task, date.today() + timedelta(days=6), "", self.creador, causas)

    def test_reprogramacion_sin_causas_no_cambia_fecha(self):
        task = self.publish_and_start()
        fecha_original = task.fecha_tope
        with self.assertRaises(ValidationError):
            reprogramar(
                task,
                fecha_original + timedelta(days=1),
                "Nueva dependencia",
                self.creador,
                [],
            )
        task.refresh_from_db()
        self.assertEqual(task.fecha_tope, fecha_original)
        self.assertFalse(task.reprogramaciones.exists())

    def test_reprogramacion_rechaza_usuario_de_otra_empresa_sin_cambios(self):
        otra_empresa = Empresa.objects.create(codigo="T31", descripcion="Otra")
        otro_usuario = create_user("t30_otro_contexto")
        assign_permission(otro_usuario, otra_empresa, "Tareas - Listado", ingresar=True)
        task = self.publish_and_start()
        fecha_original = task.fecha_tope
        causas = list(CausaAtraso.objects.order_by("codigo")[:1])
        with self.assertRaises(ValidationError):
            reprogramar(
                task,
                fecha_original + timedelta(days=1),
                "Nueva dependencia",
                otro_usuario,
                causas,
            )
        task.refresh_from_db()
        self.assertEqual(task.fecha_tope, fecha_original)
        self.assertFalse(task.reprogramaciones.exists())

    def test_reprogramacion_conserva_fecha_de_asignacion(self):
        task = self.publish_and_start()
        fecha_asignacion = task.fecha_asignacion
        causas = list(CausaAtraso.objects.order_by("codigo")[:1])
        reprogramar(
            task,
            task.fecha_tope + timedelta(days=1),
            "Nueva dependencia",
            self.creador,
            causas,
        )
        task.refresh_from_db()
        self.assertEqual(task.fecha_asignacion, fecha_asignacion)