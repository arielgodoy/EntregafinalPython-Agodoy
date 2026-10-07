from contextlib import nullcontext
from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import Tarea, TareaParticipante
from tareas.services.task_storage import DjangoTaskListStorage, MySQLTaskListStorage


class R003PersonalTaskStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Empresa.objects.create(codigo="R003", descripcion="R003")
        cls.other_company = Empresa.objects.create(codigo="R003X", descripcion="R003 other")
        cls.creator = User.objects.create_user("r003-creator")
        cls.responsible = User.objects.create_user("r003-responsible")
        cls.participant = User.objects.create_user("r003-participant")
        cls.outsider = User.objects.create_user("r003-outsider")

        def task(number, *, company, creator, responsible, priority, deadline, state, annulled=False):
            return Tarea.objects.create(
                titulo=f"R003 task {number}",
                correlativo=f"R{number:07d}",
                descripcion="personal",
                empresa=company,
                creada_por=creator,
                responsable=responsible,
                prioridad=priority,
                fecha_tope=deadline,
                estado=state,
                anulada=annulled,
            )

        cls.responsible_task = task(
            1, company=cls.company, creator=cls.creator, responsible=cls.participant,
            priority=Tarea.Prioridad.NORMAL, deadline=date(2026, 10, 4),
            state=Tarea.Estado.GESTION,
        )
        cls.participant_task = task(
            2, company=cls.company, creator=cls.creator, responsible=cls.responsible,
            priority=Tarea.Prioridad.CRITICA, deadline=date(2026, 10, 3),
            state=Tarea.Estado.ACTIVA,
        )
        TareaParticipante.objects.create(
            tarea=cls.participant_task,
            usuario=cls.participant,
            rol=TareaParticipante.Rol.PARTICIPANTE,
        )
        cls.unrelated_task = task(
            3, company=cls.company, creator=cls.creator, responsible=cls.responsible,
            priority=Tarea.Prioridad.SIMPLE, deadline=date(2026, 10, 1),
            state=Tarea.Estado.GESTION,
        )
        cls.other_company_task = task(
            4, company=cls.other_company, creator=cls.creator, responsible=cls.participant,
            priority=Tarea.Prioridad.NORMAL, deadline=date(2026, 10, 2),
            state=Tarea.Estado.GESTION,
        )
        cls.annulled_task = task(
            5, company=cls.company, creator=cls.creator, responsible=cls.responsible,
            priority=Tarea.Prioridad.NORMAL, deadline=date(2026, 10, 5),
            state=Tarea.Estado.GESTION, annulled=True,
        )
        cls.draft_task = task(
            6, company=cls.company, creator=cls.creator, responsible=cls.responsible,
            priority=Tarea.Prioridad.NORMAL, deadline=date(2026, 10, 6),
            state=Tarea.Estado.BORRADOR,
        )
        for excluded in (cls.annulled_task, cls.draft_task):
            TareaParticipante.objects.create(
                tarea=excluded,
                usuario=cls.participant,
                rol=TareaParticipante.Rol.PARTICIPANTE,
            )

    def test_django_population_preserves_effective_scope_and_order(self):
        tasks = DjangoTaskListStorage("default").list_personal_tasks(
            empresa_id=self.company.pk,
            user_id=self.participant.pk,
        )

        self.assertEqual(
            [task.pk for task in tasks],
            [self.participant_task.pk, self.responsible_task.pk],
        )
        self.assertNotIn(self.unrelated_task.pk, [task.pk for task in tasks])
        self.assertNotIn(self.other_company_task.pk, [task.pk for task in tasks])
        self.assertNotIn(self.annulled_task.pk, [task.pk for task in tasks])
        self.assertNotIn(self.draft_task.pk, [task.pk for task in tasks])

    def test_mysql_population_matches_django_ids_and_order(self):
        django_tasks = DjangoTaskListStorage("default").list_personal_tasks(
            empresa_id=self.company.pk,
            user_id=self.participant.pk,
        )
        rows = [
            (
                task.pk, task.empresa_id, task.correlativo, task.titulo, task.descripcion,
                task.prioridad, task.estado, int(task.anulada), task.responsable_id,
                task.fecha_tope, task.fecha_publicacion, task.fecha_asignacion,
                task.fecha_cumplimiento, task.fecha_creacion,
            )
            for task in django_tasks
        ]

        class Cursor:
            def execute(self, sql, params=()):
                self.sql = sql
                self.params = params

            def fetchall(self):
                return rows

            def close(self):
                pass

        class Connection:
            def __init__(self):
                self.cursor_value = Cursor()

            def cursor(self):
                return self.cursor_value

        storage = MySQLTaskListStorage(object(), "tareas")
        with patch(
            "tareas.services.task_storage.open_mysql_connection",
            return_value=nullcontext(Connection()),
        ):
            mysql_tasks = storage.list_personal_tasks(
                empresa_id=self.company.pk,
                user_id=self.participant.pk,
            )

        self.assertEqual([task.pk for task in mysql_tasks], [task.pk for task in django_tasks])
        self.assertEqual([task.prioridad for task in mysql_tasks], [task.prioridad for task in django_tasks])
        self.assertEqual([task.responsable_id for task in mysql_tasks], [task.responsable_id for task in django_tasks])
