from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from access_control.models import Empresa
from organizacion.models import Departamento, Local, OrganizationalSource
from tareas.models import (
    CorrelativoEmpresa,
    Tarea,
    TareaConnectionRole,
    TareaRelacion,
)
from tareas.services.hierarchy_creation import (
    create_child_task_atomic,
    list_eligible_hierarchy_parents,
)
from tareas.services.task_storage import CreateTaskDraftInput


class AtomicChildTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="2G", descripcion="Fase 2G")
        cls.otra_empresa = Empresa.objects.create(
            codigo="2G-OTRA",
            descripcion="Fase 2G otra empresa",
        )
        cls.actor = User.objects.create_user(
            username="fase-2g-actor",
            password="test-password",
        )
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="DJANGO",
            django_alias="default",
        )
        CorrelativoEmpresa.objects.create(
            empresa=cls.empresa,
            siguiente_numero=10,
        )

    def _data(self):
        return CreateTaskDraftInput(
            titulo="Hija atómica",
            descripcion="Prueba transaccional",
            prioridad=Tarea.Prioridad.NORMAL,
            responsable_id=None,
            fecha_tope=date(2026, 10, 20),
        )

    def _task(
        self,
        empresa=None,
        *,
        anulada=False,
        correlativo="A0000001",
        estado=Tarea.Estado.ACTIVA,
        tipo_ambito=None,
        local=None,
        departamento=None,
    ):
        return Tarea.objects.create(
            titulo="Padre",
            descripcion="Padre de prueba",
            prioridad=Tarea.Prioridad.NORMAL,
            correlativo=correlativo,
            empresa=empresa or self.empresa,
            creada_por=self.actor,
            estado=estado,
            anulada=anulada,
            tipo_ambito=tipo_ambito,
            local=local,
            departamento=departamento,
        )

    def test_creates_task_and_relation_in_one_operation(self):
        parent = self._task()

        result = create_child_task_atomic(
            self._data(),
            active_company=self.empresa,
            actor=self.actor,
            parent_id=parent.pk,
        )

        self.assertTrue(Tarea.objects.filter(pk=result.task.id).exists())
        self.assertTrue(
            TareaRelacion.objects.filter(
                pk=result.relation_id,
                padre_id=parent.pk,
                hija_id=result.task.id,
            ).exists()
        )

    def test_failure_after_insert_rolls_back_task_and_relation(self):
        parent = self._task()
        before = Tarea.objects.count()

        with patch(
            "tareas.services.hierarchy_creation.validate_relation",
            side_effect=ValidationError("relación inválida"),
        ):
            with self.assertRaises(ValidationError):
                create_child_task_atomic(
                    self._data(),
                    active_company=self.empresa,
                    actor=self.actor,
                    parent_id=parent.pk,
                )

        self.assertEqual(Tarea.objects.count(), before)
        self.assertFalse(
            Tarea.objects.filter(titulo=self._data().titulo).exists()
        )
        self.assertFalse(TareaRelacion.objects.filter(padre_id=parent.pk).exists())

    def test_missing_parent_is_rejected_without_orphan(self):
        before = Tarea.objects.count()

        with self.assertRaises(ValidationError):
            create_child_task_atomic(
                self._data(),
                active_company=self.empresa,
                actor=self.actor,
                parent_id=999999,
            )

        self.assertEqual(Tarea.objects.count(), before)

    def test_parent_from_other_company_is_rejected(self):
        parent = self._task(self.otra_empresa, correlativo="B0000002")
        before = Tarea.objects.count()

        with self.assertRaises(ValidationError):
            create_child_task_atomic(
                self._data(),
                active_company=self.empresa,
                actor=self.actor,
                parent_id=parent.pk,
            )

        self.assertEqual(Tarea.objects.count(), before)

    def test_annulled_parent_is_incompatible(self):
        parent = self._task(anulada=True, correlativo="B0000003")

        with self.assertRaises(ValidationError):
            create_child_task_atomic(
                self._data(),
                active_company=self.empresa,
                actor=self.actor,
                parent_id=parent.pk,
            )

        self.assertFalse(TareaRelacion.objects.filter(padre_id=parent.pk).exists())

    def test_parent_must_be_active_and_due_date_is_required_in_service(self):
        for index, state in enumerate(
            (
                Tarea.Estado.BORRADOR,
                Tarea.Estado.GESTION,
                Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
                Tarea.Estado.CERRADA,
            ),
            start=1,
        ):
            with self.subTest(state=state):
                parent = self._task(
                    estado=state,
                    correlativo=f"A{index:07d}",
                )
                before = Tarea.objects.count()
                with self.assertRaises(ValidationError):
                    create_child_task_atomic(
                        self._data(),
                        active_company=self.empresa,
                        actor=self.actor,
                        parent_id=parent.pk,
                    )
                self.assertEqual(Tarea.objects.count(), before)

    def test_child_and_grandchild_are_created_as_full_draft_tasks(self):
        root = self._task(correlativo="A0000001")
        child_result = create_child_task_atomic(
            self._data(),
            active_company=self.empresa,
            actor=self.actor,
            parent_id=root.pk,
        )
        child = child_result.task.task
        child.responsable = self.actor
        child.save(update_fields=["responsable"])
        child.publicar(self.actor)

        grandchild_result = create_child_task_atomic(
            self._data(),
            active_company=self.empresa,
            actor=self.actor,
            parent_id=child.pk,
        )
        grandchild = Tarea.objects.get(pk=grandchild_result.task.id)

        self.assertEqual(child_result.task.estado, Tarea.Estado.BORRADOR)
        self.assertEqual(grandchild.estado, Tarea.Estado.BORRADOR)
        self.assertEqual(grandchild.empresa_id, self.empresa.pk)
        self.assertTrue(
            TareaRelacion.objects.filter(
                padre_id=root.pk,
                hija_id=child.pk,
            ).exists()
        )
        self.assertTrue(
            TareaRelacion.objects.filter(
                padre_id=child.pk,
                hija_id=grandchild.pk,
            ).exists()
        )

        active_parent = self._task(correlativo="A0000009")
        invalid_data = CreateTaskDraftInput(
            titulo="Hija sin fecha",
            descripcion="",
            prioridad=Tarea.Prioridad.NORMAL,
            responsable_id=None,
            fecha_tope=None,
        )
        before = Tarea.objects.count()
        with self.assertRaises(ValidationError):
            create_child_task_atomic(
                invalid_data,
                active_company=self.empresa,
                actor=self.actor,
                parent_id=active_parent.pk,
            )
        self.assertEqual(Tarea.objects.count(), before)

    def test_effectively_annulled_ancestor_cannot_receive_new_descendant(self):
        root = self._task(correlativo="A0000011", anulada=True)
        parent = self._task(correlativo="A0000012")
        TareaRelacion.objects.create(padre=root, hija=parent)
        before = Tarea.objects.count()

        with self.assertRaises(ValidationError):
            create_child_task_atomic(
                self._data(),
                active_company=self.empresa,
                actor=self.actor,
                parent_id=parent.pk,
            )

        self.assertEqual(Tarea.objects.count(), before)
        self.assertFalse(TareaRelacion.objects.filter(padre=parent).exists())

    def test_fourth_level_is_rejected_by_atomic_child_creation(self):
        root = self._task(correlativo="A0000021")
        child = self._task(correlativo="A0000022")
        grandchild = self._task(correlativo="A0000023")
        TareaRelacion.objects.create(padre=root, hija=child)
        TareaRelacion.objects.create(padre=child, hija=grandchild)
        before = Tarea.objects.count()

        with self.assertRaises(ValidationError):
            create_child_task_atomic(
                self._data(),
                active_company=self.empresa,
                actor=self.actor,
                parent_id=grandchild.pk,
            )

        self.assertEqual(Tarea.objects.count(), before)
        self.assertFalse(TareaRelacion.objects.filter(padre=grandchild).exists())

    def test_local_dimension_is_inherited_and_department_override_is_rejected(self):
        local = Local.objects.create(
            empresa=self.empresa,
            codigo="LOCAL-1",
            nombre="Local 1",
            source=OrganizationalSource.LOCAL,
        )
        parent = self._task(
            correlativo="A0000031",
            tipo_ambito=Tarea.Ambito.LOCAL,
            local=local,
        )

        result = create_child_task_atomic(
            self._data(),
            active_company=self.empresa,
            actor=self.actor,
            parent_id=parent.pk,
        )

        child = Tarea.objects.get(pk=result.task.id)
        self.assertEqual(child.tipo_ambito, Tarea.Ambito.LOCAL)
        self.assertEqual(child.local_id, local.pk)
        self.assertIsNone(child.departamento_id)

        department = Departamento.objects.create(
            empresa=self.empresa,
            codigo="DEP-1",
            nombre="Departamento 1",
            source=OrganizationalSource.LOCAL,
        )
        before = Tarea.objects.count()
        with self.assertRaises(ValidationError):
            create_child_task_atomic(
                self._data(),
                active_company=self.empresa,
                actor=self.actor,
                parent_id=parent.pk,
                departamento_id=department.pk,
            )
        self.assertEqual(Tarea.objects.count(), before)

    def test_department_dimension_is_inherited_or_changed_within_company(self):
        original_department = Departamento.objects.create(
            empresa=self.empresa,
            codigo="DEP-2",
            nombre="Departamento 2",
            source=OrganizationalSource.LOCAL,
        )
        alternate_department = Departamento.objects.create(
            empresa=self.empresa,
            codigo="DEP-3",
            nombre="Departamento 3",
            source=OrganizationalSource.LOCAL,
        )
        foreign_department = Departamento.objects.create(
            empresa=self.otra_empresa,
            codigo="DEP-4",
            nombre="Departamento externo",
            source=OrganizationalSource.LOCAL,
        )
        parent = self._task(
            correlativo="A0000041",
            tipo_ambito=Tarea.Ambito.DEPARTAMENTO,
            departamento=original_department,
        )

        inherited = create_child_task_atomic(
            self._data(),
            active_company=self.empresa,
            actor=self.actor,
            parent_id=parent.pk,
        )
        changed = create_child_task_atomic(
            self._data(),
            active_company=self.empresa,
            actor=self.actor,
            parent_id=parent.pk,
            departamento_id=alternate_department.pk,
        )

        inherited_task = Tarea.objects.get(pk=inherited.task.id)
        changed_task = Tarea.objects.get(pk=changed.task.id)
        self.assertEqual(inherited_task.tipo_ambito, Tarea.Ambito.DEPARTAMENTO)
        self.assertEqual(inherited_task.departamento_id, original_department.pk)
        self.assertIsNone(inherited_task.local_id)
        self.assertEqual(changed_task.tipo_ambito, Tarea.Ambito.DEPARTAMENTO)
        self.assertEqual(changed_task.departamento_id, alternate_department.pk)
        self.assertIsNone(changed_task.local_id)

        before = Tarea.objects.count()
        with self.assertRaises(ValidationError):
            create_child_task_atomic(
                self._data(),
                active_company=self.empresa,
                actor=self.actor,
                parent_id=parent.pk,
                departamento_id=foreign_department.pk,
            )
        self.assertEqual(Tarea.objects.count(), before)

    def test_only_active_non_annulled_parents_with_depth_below_two_are_listed(self):
        root = self._task(correlativo="A0000051")
        child = self._task(correlativo="A0000052")
        grandchild = self._task(correlativo="A0000053")
        draft = self._task(
            correlativo="B0000054",
            estado=Tarea.Estado.BORRADOR,
        )
        closed = self._task(
            correlativo="A0000055",
            estado=Tarea.Estado.CERRADA,
        )
        annulled = self._task(correlativo="A0000056", anulada=True)
        foreign = self._task(
            self.otra_empresa,
            correlativo="A0000057",
        )
        TareaRelacion.objects.create(padre=root, hija=child)
        TareaRelacion.objects.create(padre=child, hija=grandchild)
        TareaRelacion.objects.create(padre=root, hija=draft)

        parents = list_eligible_hierarchy_parents(empresa_id=self.empresa.pk)
        parent_ids = {item.task_id for item in parents}
        self.assertEqual(parent_ids, {root.pk, child.pk})
        self.assertNotIn(grandchild.pk, parent_ids)
        self.assertNotIn(draft.pk, parent_ids)
        self.assertNotIn(closed.pk, parent_ids)
        self.assertNotIn(annulled.pk, parent_ids)
        self.assertNotIn(foreign.pk, parent_ids)
