from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import (
    CorrelativoEmpresa,
    Tarea,
    TareaCierre,
    TareaTransicion,
)
from tareas.services.lifecycle import (
    annul_task,
    approve_closure,
    complete_task,
    reject_closure,
    reactivate_task,
    transition_task,
)


class Phase2LifecycleTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="P2", descripcion="Phase 2")
        cls.creator = User.objects.create_user(username="p2_creator", password="x")
        cls.responsible = User.objects.create_user(username="p2_resp", password="x")
        cls.authorizer = User.objects.create_user(username="p2_auth", password="x")

    def make_task(self):
        return Tarea.objects.create(
            titulo="Phase 2 task",
            empresa=self.empresa,
            creada_por=self.creator,
            responsable=self.responsible,
            fecha_tope=date.today(),
        )

    def test_creation_reserves_one_company_sequence(self):
        first = self.make_task()
        second = self.make_task()
        self.assertEqual(first.correlativo, "B0000001")
        self.assertEqual(second.correlativo, "B0000002")
        self.assertEqual(CorrelativoEmpresa.objects.get(empresa=self.empresa).siguiente_numero, 3)

    def test_publish_changes_prefix_without_consuming_number(self):
        task = self.make_task()
        original_pk = task.pk
        original_sequence = CorrelativoEmpresa.objects.get(empresa=self.empresa).siguiente_numero
        task.publicar(self.creator)
        task.refresh_from_db()
        self.assertEqual(task.estado, Tarea.Estado.ACTIVA)
        self.assertEqual(task.correlativo, "A0000001")
        self.assertEqual(task.pk, original_pk)
        self.assertEqual(
            CorrelativoEmpresa.objects.get(empresa=self.empresa).siguiente_numero,
            original_sequence,
        )
        self.assertEqual(Tarea.objects.filter(correlativo="A0000001").count(), 1)

    def test_publish_rejects_invalid_draft_correlativo(self):
        task = self.make_task()
        task.correlativo = "A0000001"
        task.save(update_fields=["correlativo"])
        with self.assertRaises(ValidationError):
            task.publicar(self.creator)

    def test_td_is_not_generated(self):
        task = self.make_task()
        self.assertRegex(task.correlativo, r"^B[0-9]{7}$")
        self.assertNotRegex(task.correlativo, r"^TD[0-9]{7}$")

    def test_lifecycle_and_rejected_closure(self):
        task = self.make_task()
        self.assertFalse(task.cierre_completado)
        task.publicar(self.creator)
        transition_task(task, Tarea.Estado.GESTION, self.creator, "INICIAR_GESTION")
        complete_task(task, self.responsible)
        task.refresh_from_db()
        self.assertTrue(task.cierre_completado)
        self.assertEqual(task.estado, Tarea.Estado.PENDIENTE_APROBACION_CIERRE)
        reject_closure(task, self.authorizer, "Falta información")
        task.refresh_from_db()
        self.assertEqual(task.estado, Tarea.Estado.GESTION)
        self.assertTrue(task.cierre_completado)
        self.assertEqual(TareaTransicion.objects.filter(tarea=task).count(), 4)
        self.assertEqual(TareaCierre.objects.get(tarea=task).resultado, TareaCierre.Resultado.RECHAZADO)
        complete_task(task, self.responsible)
        approve_closure(task, self.authorizer, "OK")
        task.refresh_from_db()
        self.assertEqual(task.estado, Tarea.Estado.CERRADA)
        self.assertTrue(task.cierre_completado)

    def test_invalid_published_to_draft_transition(self):
        task = self.make_task()
        task.publicar(self.creator)
        task.estado = Tarea.Estado.BORRADOR
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_anular_no_cambia_estado_funcional(self):
        task = self.make_task()
        task.publicar(self.creator)
        transition_task(task, Tarea.Estado.GESTION, self.creator, "INICIAR_GESTION")
        task.refresh_from_db()
        annul_task(task, self.authorizer, "Pausa")
        task.refresh_from_db()
        self.assertEqual(task.estado, Tarea.Estado.GESTION)
        self.assertTrue(task.anulada)

    def test_reactivar_no_cambia_estado_funcional(self):
        task = self.make_task()
        task.publicar(self.creator)
        transition_task(task, Tarea.Estado.GESTION, self.creator, "INICIAR_GESTION")
        annul_task(task, self.authorizer)
        task.refresh_from_db()
        reactivate_task(task, self.authorizer)
        task.refresh_from_db()
        self.assertEqual(task.estado, Tarea.Estado.GESTION)
        self.assertFalse(task.anulada)

    def test_anular_tarea_cerrada_conserva_estado(self):
        task = self.make_task()
        task.publicar(self.creator)
        transition_task(task, Tarea.Estado.GESTION, self.creator, "INICIAR_GESTION")
        complete_task(task, self.responsible)
        approve_closure(task, self.authorizer)
        task.refresh_from_db()
        self.assertEqual(task.estado, Tarea.Estado.CERRADA)
        # Anular una tarea CERRADA: el estado funcional se conserva; solo cambia el flag.
        annul_task(task, self.authorizer)
        task.refresh_from_db()
        self.assertEqual(task.estado, Tarea.Estado.CERRADA)
        self.assertTrue(task.anulada)

    def test_reactivar_tarea_cerrada_conserva_estado(self):
        task = self.make_task()
        task.publicar(self.creator)
        transition_task(task, Tarea.Estado.GESTION, self.creator, "INICIAR_GESTION")
        complete_task(task, self.responsible)
        approve_closure(task, self.authorizer)
        annul_task(task, self.authorizer)
        task.refresh_from_db()
        reactivate_task(task, self.authorizer)
        task.refresh_from_db()
        self.assertEqual(task.estado, Tarea.Estado.CERRADA)
        self.assertFalse(task.anulada)

    def test_reactivar_conserva_datos(self):
        task = self.make_task()
        task.publicar(self.creator)
        transition_task(task, Tarea.Estado.GESTION, self.creator, "INICIAR_GESTION")
        complete_task(task, self.responsible)
        correlativo = task.correlativo
        cierre = task.cierre_completado
        annul_task(task, self.authorizer)
        reactivate_task(task, self.authorizer)
        task.refresh_from_db()
        self.assertEqual(task.correlativo, correlativo)
        self.assertEqual(task.cierre_completado, cierre)
        self.assertEqual(task.responsable, self.responsible)
        self.assertEqual(task.empresa, self.empresa)

    def test_lifecycle_bloqueado_cuando_anulada(self):
        task = self.make_task()
        task.publicar(self.creator)
        transition_task(task, Tarea.Estado.GESTION, self.creator, "INICIAR_GESTION")
        annul_task(task, self.authorizer)
        task.refresh_from_db()
        with self.assertRaises(ValidationError):
            transition_task(task, Tarea.Estado.PENDIENTE_APROBACION_CIERRE, self.responsible, "MARCAR_100")
        with self.assertRaises(ValidationError):
            complete_task(task, self.responsible)
        with self.assertRaises(ValidationError):
            approve_closure(task, self.authorizer)
        with self.assertRaises(ValidationError):
            reject_closure(task, self.authorizer)

    def test_transicion_registra_anular_y_reactivar(self):
        task = self.make_task()
        task.publicar(self.creator)
        transition_task(task, Tarea.Estado.GESTION, self.creator, "INICIAR_GESTION")
        annul_task(task, self.authorizer, "motivo anulación")
        reactivate_task(task, self.authorizer, "motivo reactivación")
        acciones = list(
            TareaTransicion.objects.filter(tarea=task)
            .values_list("accion_evento", flat=True)
        )
        self.assertIn("ANULAR", acciones)
        self.assertIn("REACTIVAR", acciones)

    def test_anular_no_crea_snapshot_de_restauracion(self):
        from tareas.models import TareaAnulacionSnapshot

        task = self.make_task()
        task.publicar(self.creator)
        transition_task(task, Tarea.Estado.GESTION, self.creator, "INICIAR_GESTION")
        annul_task(task, self.authorizer)
        self.assertFalse(TareaAnulacionSnapshot.objects.filter(tarea=task).exists())
