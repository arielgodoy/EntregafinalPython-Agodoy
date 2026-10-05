from datetime import datetime, timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from tareas.models import Tarea, TareaConnectionRole, TareaParticipante


class ListTaskCharacterizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="132A", descripcion="Empresa A")
        cls.otra_empresa = Empresa.objects.create(codigo="132B", descripcion="Empresa B")
        cls.user = User.objects.create_user(username="t132-list-user", password="pass")
        cls.responsible = User.objects.create_user(
            username="t132-responsible", password="pass"
        )
        cls.vista = Vista.objects.create(nombre="Tareas")
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="DJANGO",
            django_alias="default",
        )
        for user in (cls.user, cls.responsible):
            Permiso.objects.create(
                usuario=user,
                empresa=cls.empresa,
                vista=cls.vista,
                ingresar=True,
                crear=True,
                modificar=True,
            )

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def _task(self, **kwargs):
        values = {
            "titulo": "Tarea de listado",
            "descripcion": "Descripción de listado",
            "empresa": self.empresa,
            "creada_por": self.user,
            "fecha_tope": datetime(2026, 10, 31, tzinfo=timezone.utc).date(),
        }
        values.update(kwargs)
        return Tarea.objects.create(**values)

    def test_empty_state_keeps_create_action(self):
        response = self.client.get(reverse("tareas:listar_tareas"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No hay tareas registradas.")
        self.assertContains(response, reverse("tareas:crear_tarea"))

    def test_default_order_is_newest_first(self):
        older = self._task(titulo="Tarea antigua", correlativo="B0000101")
        newer = self._task(titulo="Tarea nueva", correlativo="B0000102")
        Tarea.objects.filter(pk=older.pk).update(
            fecha_creacion=datetime(2026, 1, 1, tzinfo=timezone.utc)
        )
        Tarea.objects.filter(pk=newer.pk).update(
            fecha_creacion=datetime(2026, 1, 2, tzinfo=timezone.utc)
        )

        response = self.client.get(reverse("tareas:listar_tareas"))

        self.assertEqual(
            [task.id for task in response.context["tareas"]],
            [newer.pk, older.pk],
        )

    def test_invalid_state_and_priority_are_ignored_like_current_view(self):
        task = self._task(titulo="Visible con filtros inválidos", correlativo="B0000103")

        response = self.client.get(
            reverse("tareas:listar_tareas"),
            {"estado": "NO_EXISTE", "prioridad": "NO_EXISTE"},
        )

        self.assertContains(response, task.titulo)

    def test_row_links_and_labels_are_rendered(self):
        task = self._task(
            titulo="Fila etiquetada",
            correlativo="B0000104",
            estado=Tarea.Estado.GESTION,
            prioridad=Tarea.Prioridad.URGENTE,
            responsable=self.responsible,
        )

        response = self.client.get(reverse("tareas:listar_tareas"))

        self.assertContains(response, reverse("tareas:detalle_tarea", args=[task.pk]))
        self.assertContains(response, reverse("tareas:editar_tarea", args=[task.pk]))
        self.assertContains(response, "tareas.state.gestion")
        self.assertContains(response, "tareas.priority.urgente")
        self.assertContains(response, self.responsible.username)

    def test_participants_show_four_and_report_remaining_count(self):
        participants = [
            User.objects.create_user(username=f"t132-participant-{index}", password="pass")
            for index in range(5)
        ]
        task = self._task(titulo="Fila con participantes", correlativo="B0000105")
        for participant in participants:
            TareaParticipante.objects.create(
                tarea=task,
                usuario=participant,
                rol=TareaParticipante.Rol.PARTICIPANTE,
            )

        response = self.client.get(reverse("tareas:listar_tareas"))
        listed = response.context["tareas"][0]

        self.assertEqual(len(listed.participantes_visibles), 4)
        self.assertEqual(listed.participantes_restantes, 2)
        self.assertContains(response, "t132-participant-0")
