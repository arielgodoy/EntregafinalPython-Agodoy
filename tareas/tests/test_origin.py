from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import Tarea, Todo
from tareas.services.origin import create_task_from_todo


class OriginDomainTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="OR1", descripcion="Empresa origen")
        self.user = User.objects.create_user(username="origin_user", password="x")

    def test_tarea_a_tarea_sigue_permitiendo_cadena_directa(self):
        source = Tarea.objects.create(
            titulo="Origen",
            empresa=self.empresa,
            creada_por=self.user,
        )
        derived = Tarea.objects.create(
            titulo="Derivada",
            empresa=self.empresa,
            creada_por=self.user,
            tarea_origen=source,
        )
        self.assertEqual(derived.tarea_origen, source)
        self.assertIsNone(derived.todo_origen)

    def test_task_from_todo_no_acepta_origen_tarea(self):
        todo = Todo.objects.create(
            empresa=self.empresa,
            creada_por=self.user,
            titulo="Pendiente",
        )
        source = Tarea.objects.create(
            titulo="Origen",
            empresa=self.empresa,
            creada_por=self.user,
        )
        with self.assertRaises(ValidationError):
            create_task_from_todo(
                todo,
                self.user,
                "Invalida",
                tarea_origen=source,
            )