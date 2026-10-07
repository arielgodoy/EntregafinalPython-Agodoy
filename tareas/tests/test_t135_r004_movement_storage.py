from contextlib import nullcontext
from datetime import date, datetime, timezone
from unittest.mock import patch

from django.test import TestCase

from access_control.models import Empresa
from tareas.models import (
    DocumentoHistorial,
    DocumentoTarea,
    Hito,
    HitoHistorial,
    Tarea,
    TareaTransicion,
)
from tareas.services.movement_storage import (
    DjangoMovementStorage,
    MySQLMovementStorage,
)
from django.contrib.auth.models import User


class R004MovementStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Empresa.objects.create(codigo="R004", descripcion="R004")
        cls.other_company = Empresa.objects.create(codigo="R004X", descripcion="R004 other")
        cls.user = User.objects.create_user("r004-user")
        cls.task = Tarea.objects.create(
            titulo="Movement task",
            correlativo="R0040001",
            empresa=cls.company,
            creada_por=cls.user,
            responsable=cls.user,
            prioridad=Tarea.Prioridad.NORMAL,
            estado=Tarea.Estado.GESTION,
            fecha_tope=date(2026, 10, 30),
            fecha_publicacion=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        cls.other_task = Tarea.objects.create(
            titulo="Other company task",
            correlativo="R0040002",
            empresa=cls.other_company,
            creada_por=cls.user,
            responsable=cls.user,
            prioridad=Tarea.Prioridad.NORMAL,
            estado=Tarea.Estado.GESTION,
            fecha_tope=date(2026, 10, 30),
            fecha_publicacion=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )

    def test_django_latest_movement_uses_all_sources_and_company_scope(self):
        transition = TareaTransicion.objects.create(
            tarea=self.task,
            estado_origen=Tarea.Estado.ACTIVA,
            estado_destino=Tarea.Estado.GESTION,
            accion_evento="GESTIONAR",
            usuario=self.user,
        )
        TareaTransicion.objects.filter(pk=transition.pk).update(
            timestamp=datetime(2026, 10, 3, tzinfo=timezone.utc),
        )
        hito = Hito.objects.create(
            tarea=self.task,
            nombre="Movement milestone",
            responsable=self.user,
            peso=1,
        )
        HitoHistorial.objects.create(
            hito=hito,
            tipo_evento=HitoHistorial.Evento.CAMBIO_NOMBRE,
            usuario=self.user,
            fecha=datetime(2026, 10, 5, tzinfo=timezone.utc),
        )
        documento = DocumentoTarea.objects.create(
            tarea=self.task,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            url="https://example.test/r004.pdf",
            usuario=self.user,
        )
        DocumentoHistorial.objects.create(
            documento=documento,
            accion="AGREGADO",
            usuario=self.user,
            fecha=datetime(2026, 10, 7, tzinfo=timezone.utc),
        )

        rows = DjangoMovementStorage("default").latest_movements(
            empresa_id=self.company.pk,
            task_ids=(self.task.pk, self.other_task.pk),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].task_id, self.task.pk)
        self.assertEqual(rows[0].publication, self.task.fecha_publicacion)
        self.assertEqual(
            rows[0].transition,
            TareaTransicion.objects.get(pk=transition.pk).timestamp,
        )
        self.assertEqual(rows[0].milestone, HitoHistorial.objects.get(hito=hito).fecha)
        self.assertEqual(rows[0].document, DocumentoHistorial.objects.get(documento=documento).fecha)

    def test_empty_task_ids_do_not_open_connection(self):
        with patch("tareas.services.movement_storage.open_mysql_connection") as open_connection:
            rows = MySQLMovementStorage(object(), "tareas").latest_movements(
                empresa_id=self.company.pk, task_ids=(),
            )

        self.assertEqual(rows, ())
        open_connection.assert_not_called()

    def test_mysql_materializes_latest_movement_row(self):
        row = (
            self.task.pk,
            datetime(2026, 10, 1),
            datetime(2026, 10, 3),
            datetime(2026, 10, 5),
            datetime(2026, 10, 7),
        )

        class Cursor:
            def execute(self, sql, params=()):
                self.sql = sql
                self.params = params

            def fetchall(self):
                return [row]

            def close(self):
                pass

        class Connection:
            def cursor(self):
                return Cursor()

        with patch(
            "tareas.services.movement_storage.open_mysql_connection",
            return_value=nullcontext(Connection()),
        ):
            movement = MySQLMovementStorage(object(), "tareas").latest_movements(
                empresa_id=self.company.pk, task_ids=(self.task.pk,),
            )[0]

        self.assertEqual(movement.task_id, self.task.pk)
        self.assertEqual(movement.transition, datetime(2026, 10, 3, tzinfo=timezone.utc))
        self.assertEqual(movement.milestone, datetime(2026, 10, 5, tzinfo=timezone.utc))
        self.assertEqual(movement.document, datetime(2026, 10, 7, tzinfo=timezone.utc))
