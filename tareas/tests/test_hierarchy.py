from datetime import date

"""Tests Phase 3 T028: task hierarchy and effective annulment."""

from django.core.exceptions import ValidationError
from django.test import TestCase

from tareas.models import Tarea, TareaRelacion
from tareas.services.hierarchy import (
    add_child,
    get_children,
    get_descendants,
    get_depth,
    get_parent,
    has_open_operational_descendants,
    is_effectively_annulled,
)
from tareas.services.lifecycle import (
    annul_task,
    approve_closure,
    complete_task,
    reactivate_task,
    transition_task,
)
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class HierarchyPhase3Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="H3", descripcion="Empresa jerarquia")
        cls.otra_empresa = create_empresa(codigo="H4", descripcion="Otra empresa")
        cls.creator = create_user(username="h3_creator")
        cls.responsible = create_user(username="h3_resp")
        assign_permission(cls.creator, cls.empresa, "Tareas - Listado", ingresar=True)
        assign_permission(cls.responsible, cls.empresa, "Tareas - Listado", ingresar=True)

    def make_task(self, titulo="Tarea", empresa=None):
        return create_tarea(
            empresa or self.empresa,
            self.creator,
            titulo=titulo,
            responsable=self.responsible,
            fecha_tope=date.today(),
        )

    def make_active_task(self, titulo="Tarea", empresa=None):
        task = self.make_task(titulo, empresa)
        task.publicar(self.creator)
        return task

    def make_gestion_task(self, titulo="Tarea", empresa=None):
        task = self.make_active_task(titulo, empresa)
        transition_task(task, Tarea.Estado.GESTION, self.creator, "INICIAR_GESTION")
        task.refresh_from_db()
        return task

    def close_task(self, task):
        if task.estado == Tarea.Estado.ACTIVA:
            transition_task(task, Tarea.Estado.GESTION, self.creator, "INICIAR_GESTION")
        complete_task(task, self.responsible)
        approve_closure(task, self.creator)
        task.refresh_from_db()
        return task

    def test_crear_padre_hija(self):
        parent = self.make_task("Padre")
        child = self.make_task("Hija")
        relation = add_child(parent, child)
        self.assertEqual(relation.padre, parent)
        self.assertEqual(relation.hija, child)

    def test_padre_con_multiples_hijas(self):
        parent = self.make_task("Padre")
        child_a = self.make_task("Hija A")
        child_b = self.make_task("Hija B")
        add_child(parent, child_a)
        add_child(parent, child_b)
        self.assertEqual(list(get_children(parent)), [child_a, child_b])

    def test_hija_nieta(self):
        parent = self.make_task("Padre")
        child = self.make_task("Hija")
        grandchild = self.make_task("Nieta")
        add_child(parent, child)
        add_child(child, grandchild)
        self.assertEqual(get_parent(grandchild), child)
        self.assertEqual(get_depth(grandchild), 2)

    def test_impedir_cuarto_nivel(self):
        parent = self.make_task("Padre")
        child = self.make_task("Hija")
        grandchild = self.make_task("Nieta")
        great_grandchild = self.make_task("Bisnieta")
        add_child(parent, child)
        add_child(child, grandchild)
        with self.assertRaises(ValidationError):
            add_child(grandchild, great_grandchild)

    def test_impedir_self_parent(self):
        task = self.make_task("Self")
        with self.assertRaises(ValidationError):
            add_child(task, task)

    def test_impedir_ciclo_directo(self):
        a = self.make_task("A")
        b = self.make_task("B")
        add_child(a, b)
        with self.assertRaises(ValidationError):
            add_child(b, a)

    def test_impedir_ciclo_indirecto(self):
        a = self.make_task("A")
        b = self.make_task("B")
        c = self.make_task("C")
        add_child(a, b)
        add_child(b, c)
        with self.assertRaises(ValidationError):
            add_child(c, a)

    def test_hija_no_puede_tener_dos_padres(self):
        parent_a = self.make_task("Padre A")
        parent_b = self.make_task("Padre B")
        child = self.make_task("Hija")
        add_child(parent_a, child)
        with self.assertRaises(ValidationError):
            add_child(parent_b, child)

    def test_empresa_distinta_rechazada(self):
        parent = self.make_task("Padre")
        child = self.make_task("Hija externa", empresa=self.otra_empresa)
        with self.assertRaises(ValidationError):
            add_child(parent, child)

    def test_get_parent_get_children(self):
        parent = self.make_task("Padre")
        child = self.make_task("Hija")
        add_child(parent, child)
        self.assertEqual(get_parent(child), parent)
        self.assertEqual(list(get_children(parent)), [child])

    def test_get_descendants_incluye_hijas_y_nietas(self):
        parent = self.make_task("Padre")
        child = self.make_task("Hija")
        grandchild = self.make_task("Nieta")
        add_child(parent, child)
        add_child(child, grandchild)
        self.assertEqual(list(get_descendants(parent)), [child, grandchild])

    def test_anulacion_efectiva_por_padre(self):
        parent = self.make_gestion_task("Padre")
        child = self.make_gestion_task("Hija")
        grandchild = self.make_gestion_task("Nieta")
        add_child(parent, child)
        add_child(child, grandchild)
        annul_task(parent, self.creator)
        parent.refresh_from_db()
        child.refresh_from_db()
        grandchild.refresh_from_db()
        self.assertTrue(parent.anulada)
        self.assertFalse(child.anulada)
        self.assertFalse(grandchild.anulada)
        self.assertTrue(is_effectively_annulled(parent))
        self.assertTrue(is_effectively_annulled(child))
        self.assertTrue(is_effectively_annulled(grandchild))

    def test_reactivar_padre_revierte_anulacion_efectiva(self):
        parent = self.make_gestion_task("Padre")
        child = self.make_gestion_task("Hija")
        grandchild = self.make_gestion_task("Nieta")
        add_child(parent, child)
        add_child(child, grandchild)
        annul_task(parent, self.creator)
        reactivate_task(parent, self.creator)
        child.refresh_from_db()
        grandchild.refresh_from_db()
        self.assertFalse(is_effectively_annulled(child))
        self.assertFalse(is_effectively_annulled(grandchild))

    def test_hija_anulada_directa_sigue_anulada_tras_reactivar_padre(self):
        parent = self.make_gestion_task("Padre")
        child = self.make_gestion_task("Hija")
        add_child(parent, child)
        annul_task(parent, self.creator)
        annul_task(child, self.creator)
        reactivate_task(parent, self.creator)
        child.refresh_from_db()
        self.assertTrue(child.anulada)
        self.assertTrue(is_effectively_annulled(child))

    def test_estado_funcional_no_cambia_por_anulacion_efectiva(self):
        parent = self.make_gestion_task("Padre")
        child = self.make_gestion_task("Hija")
        add_child(parent, child)
        child_state = child.estado
        annul_task(parent, self.creator)
        child.refresh_from_db()
        self.assertEqual(child.estado, child_state)

    def test_relaciones_permanecen_al_anular_reactivar(self):
        parent = self.make_gestion_task("Padre")
        child = self.make_gestion_task("Hija")
        add_child(parent, child)
        annul_task(parent, self.creator)
        reactivate_task(parent, self.creator)
        self.assertEqual(get_parent(child), parent)
        self.assertEqual(TareaRelacion.objects.count(), 1)

    def test_anulacion_no_escribe_flags_en_descendientes(self):
        parent = self.make_gestion_task("Padre")
        child = self.make_gestion_task("Hija")
        grandchild = self.make_gestion_task("Nieta")
        add_child(parent, child)
        add_child(child, grandchild)
        annul_task(parent, self.creator)
        child.refresh_from_db()
        grandchild.refresh_from_db()
        self.assertFalse(child.anulada)
        self.assertFalse(grandchild.anulada)

    def test_relacion_invalida_no_crea_registro_parcial(self):
        parent = self.make_task("Padre")
        child = self.make_task("Hija", empresa=self.otra_empresa)
        with self.assertRaises(ValidationError):
            add_child(parent, child)
        self.assertFalse(TareaRelacion.objects.exists())

    def test_cerrar_padre_con_descendiente_operativa_abierta_rechazado(self):
        parent = self.make_gestion_task("Padre")
        child = self.make_gestion_task("Hija")
        add_child(parent, child)
        complete_task(parent, self.responsible)
        with self.assertRaises(ValidationError):
            approve_closure(parent, self.creator)

    def test_cerrar_padre_con_descendientes_cerradas_permitido(self):
        parent = self.make_gestion_task("Padre")
        child = self.make_gestion_task("Hija")
        add_child(parent, child)
        self.close_task(child)
        complete_task(parent, self.responsible)
        approve_closure(parent, self.creator)
        parent.refresh_from_db()
        self.assertEqual(parent.estado, Tarea.Estado.CERRADA)

    def test_descendiente_anulada_efectivamente_no_bloquea_cierre(self):
        parent = self.make_gestion_task("Padre")
        child = self.make_gestion_task("Hija")
        add_child(parent, child)
        annul_task(child, self.creator)
        complete_task(parent, self.responsible)
        approve_closure(parent, self.creator)
        parent.refresh_from_db()
        self.assertEqual(parent.estado, Tarea.Estado.CERRADA)

    def test_nieta_abierta_bloquea_cierre(self):
        parent = self.make_gestion_task("Padre")
        child = self.make_gestion_task("Hija")
        grandchild = self.make_gestion_task("Nieta")
        add_child(parent, child)
        add_child(child, grandchild)
        child.estado = Tarea.Estado.CERRADA
        child.save(update_fields=["estado"])
        complete_task(parent, self.responsible)
        with self.assertRaises(ValidationError):
            approve_closure(parent, self.creator)

    def test_aislamiento_multiempresa_en_relacion(self):
        parent = self.make_task("Padre")
        child = self.make_task("Hija externa", empresa=self.otra_empresa)
        with self.assertRaises(ValidationError):
            add_child(parent, child)
        self.assertFalse(TareaRelacion.objects.exists())
