from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import MiniTarea, Tarea
from tareas.services.closure import create_mini_task, set_mini_task_done
from tareas.services.lifecycle import approve_closure, complete_task, transition_task
from tareas.tests.factories import assign_permission, create_user


class MiniTaskClosureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="T31", descripcion="T031")
        cls.creador = create_user("t31_creador")
        cls.responsable = create_user("t31_responsable")
        assign_permission(cls.creador, cls.empresa, "Tareas - Listado", ingresar=True)
        assign_permission(cls.responsable, cls.empresa, "Tareas - Listado", ingresar=True)

    def make_task(self):
        tarea = Tarea.objects.create(
            titulo="Tarea con mini-tareas",
            empresa=self.empresa,
            creada_por=self.creador,
            responsable=self.responsable,
            fecha_tope=date.today(),
        )
        tarea.publicar(self.creador)
        transition_task(tarea, Tarea.Estado.GESTION, self.creador, "INICIAR_GESTION")
        complete_task(tarea, self.responsable)
        return tarea

    def test_mini_tarea_una_persona_y_pendiente_bloquea_cierre(self):
        tarea = self.make_task()
        mini_tarea = create_mini_task(
            tarea=tarea,
            descripcion="Validar documento",
            persona=self.responsable,
        )
        self.assertEqual(mini_tarea.persona, self.responsable)
        with self.assertRaises(ValidationError):
            approve_closure(tarea, self.creador)

    def test_marcar_hecha_permite_cierre_y_no_pondera_avance(self):
        tarea = self.make_task()
        mini_tarea = create_mini_task(
            tarea=tarea,
            descripcion="Validar documento",
            persona=self.responsable,
        )
        set_mini_task_done(mini_tarea)
        mini_tarea.refresh_from_db()
        self.assertTrue(mini_tarea.hecho)
        self.assertIsNotNone(mini_tarea.fecha_completado)
        approve_closure(tarea, self.creador)
        tarea.refresh_from_db()
        self.assertEqual(tarea.estado, Tarea.Estado.CERRADA)

    def test_persona_inactiva_o_de_otra_empresa_no_puede_asignarse(self):
        otra_empresa = Empresa.objects.create(codigo="T32", descripcion="Otra")
        otro_usuario = create_user("t31_otro_contexto")
        tarea = self.make_task()
        with self.assertRaises(ValidationError):
            create_mini_task(tarea=tarea, descripcion="Fuera", persona=otro_usuario)
        otro_usuario.is_active = False
        otro_usuario.save(update_fields=["is_active"])
        with self.assertRaises(ValidationError):
            create_mini_task(tarea=tarea, descripcion="Inactivo", persona=otro_usuario)
        self.assertFalse(MiniTarea.objects.filter(tarea=tarea).exists())