from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import CorrelativoEmpresa, Tarea, Todo, TodoEvento
from tareas.services.origin import create_task_from_todo
from tareas.services.todos import close_todo, create_todo


class TodoDomainTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="TD1", descripcion="Empresa TD 1")
        cls.otra_empresa = Empresa.objects.create(codigo="TD2", descripcion="Empresa TD 2")
        cls.usuario = User.objects.create_user(username="todo_user", password="x")
        cls.otro_usuario = User.objects.create_user(username="todo_other", password="x")

    def test_correlativo_td_independiente_por_empresa(self):
        first = create_todo(self.empresa, self.usuario, "Uno")
        second = create_todo(self.empresa, self.usuario, "Dos")
        other = create_todo(self.otra_empresa, self.otro_usuario, "Otro")

        self.assertEqual(first.correlativo, "TD0000001")
        self.assertEqual(second.correlativo, "TD0000002")
        self.assertEqual(other.correlativo, "TD0000001")
        self.assertEqual(CorrelativoEmpresa.objects.count(), 0)

    def test_todo_abierto_y_cierre_auditado(self):
        todo = create_todo(self.empresa, self.usuario, "Pendiente")
        self.assertEqual(todo.estado, Todo.Estado.ABIERTO)

        close_todo(todo, self.otro_usuario, "Resuelto")
        todo.refresh_from_db()
        evento = TodoEvento.objects.get(todo=todo, tipo=TodoEvento.Tipo.CERRADO)
        self.assertEqual(todo.estado, Todo.Estado.CERRADO)
        self.assertEqual(todo.cerrada_por, self.otro_usuario)
        self.assertIsNotNone(todo.fecha_cierre)
        self.assertEqual(todo.comentario_cierre, "Resuelto")
        self.assertEqual(evento.usuario, self.otro_usuario)
        self.assertEqual(evento.comentario, "Resuelto")

    def test_todo_cerrado_no_se_reabre(self):
        todo = create_todo(self.empresa, self.usuario, "Pendiente")
        close_todo(todo, self.usuario)
        todo.estado = Todo.Estado.ABIERTO
        with self.assertRaises(ValidationError):
            todo.save(update_fields=["estado"])
        with self.assertRaises(ValidationError):
            close_todo(todo, self.usuario)

    def test_cierre_bloqueado_por_tarea_originada_pendiente(self):
        todo = create_todo(self.empresa, self.usuario, "Pendiente")
        create_task_from_todo(todo, self.usuario, "Tarea derivada")
        with self.assertRaises(ValidationError):
            close_todo(todo, self.usuario)

    def test_tarea_cerrada_o_anulada_no_bloquea_y_no_cierra_automaticamente(self):
        closed_todo = create_todo(self.empresa, self.usuario, "Cerrada")
        closed_task = create_task_from_todo(closed_todo, self.usuario, "Cerrada")
        Tarea.objects.filter(pk=closed_task.pk).update(estado=Tarea.Estado.CERRADA)
        close_todo(closed_todo, self.usuario)

        annulled_todo = create_todo(self.empresa, self.usuario, "Anulada")
        annulled_task = create_task_from_todo(annulled_todo, self.usuario, "Anulada")
        Tarea.objects.filter(pk=annulled_task.pk).update(anulada=True)
        close_todo(annulled_todo, self.usuario)

        open_todo = create_todo(self.empresa, self.usuario, "No automático")
        open_task = create_task_from_todo(open_todo, self.usuario, "Pendiente")
        Tarea.objects.filter(pk=open_task.pk).update(estado=Tarea.Estado.CERRADA)
        open_todo.refresh_from_db()
        self.assertEqual(open_todo.estado, Todo.Estado.ABIERTO)

    def test_nuevo_episodio_no_reabre_el_anterior(self):
        previous = create_todo(self.empresa, self.usuario, "Anterior")
        close_todo(previous, self.usuario)
        current = create_todo(self.empresa, self.usuario, "Nuevo episodio", todo_anterior=previous)

        self.assertEqual(current.todo_anterior, previous)
        self.assertEqual(previous.estado, Todo.Estado.CERRADO)
        self.assertEqual(current.estado, Todo.Estado.ABIERTO)

    def test_derivacion_audita_usuario_fecha_comentario_y_origen(self):
        todo = create_todo(self.empresa, self.usuario, "Pendiente")
        task = create_task_from_todo(
            todo,
            self.otro_usuario,
            "Formalizada",
            comentario="Se formaliza",
        )
        evento = TodoEvento.objects.get(todo=todo, tipo=TodoEvento.Tipo.TAREA_CREADA)

        self.assertEqual(task.todo_origen, todo)
        self.assertEqual(task.tarea_origen, None)
        self.assertEqual(evento.usuario, self.otro_usuario)
        self.assertIsNotNone(evento.timestamp)
        self.assertEqual(evento.comentario, "Se formaliza")
        self.assertRegex(task.correlativo, r"^B[0-9]{7}$")

    def test_derivacion_conserva_lifecycle_normal(self):
        todo = create_todo(self.empresa, self.usuario, "Pendiente")
        task = create_task_from_todo(todo, self.usuario, "Formalizada")
        task.responsable = self.usuario
        task.fecha_tope = date.today()
        task.save(update_fields=["responsable", "fecha_tope"])
        task.publicar(self.usuario)
        task.refresh_from_db()

        self.assertEqual(task.estado, Tarea.Estado.ACTIVA)
        self.assertRegex(task.correlativo, r"^A[0-9]{7}$")
        self.assertEqual(task.todo_origen, todo)

    def test_episodio_y_derivacion_respetan_empresa(self):
        previous = create_todo(self.empresa, self.usuario, "Anterior")
        close_todo(previous, self.usuario)
        with self.assertRaises(ValidationError):
            create_todo(self.otra_empresa, self.otro_usuario, "Cruza", todo_anterior=previous)

        todo = create_todo(self.empresa, self.usuario, "Origen")
        with self.assertRaises(ValidationError):
            create_task_from_todo(todo, self.otro_usuario, "Cruza", empresa=self.otra_empresa)

    def test_origen_canonico_no_admite_dos_origenes(self):
        todo = create_todo(self.empresa, self.usuario, "Origen")
        task = Tarea.objects.create(titulo="Tarea", empresa=self.empresa, creada_por=self.usuario)
        invalid = Tarea(
            titulo="Invalida",
            empresa=self.empresa,
            creada_por=self.usuario,
            todo_origen=todo,
            tarea_origen=task,
        )
        with self.assertRaises(ValidationError):
            invalid.full_clean()
        with self.assertRaises(IntegrityError):
            Tarea.objects.create(
                titulo="Invalida DB",
                empresa=self.empresa,
                creada_por=self.usuario,
                todo_origen=todo,
                tarea_origen=task,
            )