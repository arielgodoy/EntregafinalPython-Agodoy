from datetime import date
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from access_control.models import Empresa
from proveedores.models import Proveedor
from tareas.models import Cotizacion, EvidenciaCierre, MiniTarea, Tarea
from tareas.services.closure import (
    create_mini_task,
    set_mini_task_done,
)
from tareas.services.documents import register_closure_evidence
from tareas.services.hierarchy import add_child
from tareas.services.lifecycle import approve_closure, complete_task, transition_task
from tareas.services.quotations import create_quotation, create_quotation_round, open_next_quotation_round
from tareas.tests.factories import assign_permission, create_user


class MiniTaskClosureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="T31", descripcion="T031")
        cls.creador = create_user("t31_creador")
        cls.responsable = create_user("t31_responsable")
        cls.proveedor = Proveedor.objects.create(nombre="Proveedor de cierre")
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

    def test_evidence_requirement_blocks_without_evidence(self):
        tarea = self.make_task()
        tarea.requiere_evidencia_cierre = True
        tarea.save(update_fields=["requiere_evidencia_cierre"])

        with self.assertRaisesMessage(ValidationError, "CLOSURE_EVIDENCE_REQUIRED"):
            approve_closure(tarea, self.creador)

    def test_evidence_requirement_allows_valid_evidence(self):
        tarea = self.make_task()
        tarea.requiere_evidencia_cierre = True
        tarea.save(update_fields=["requiere_evidencia_cierre"])
        register_closure_evidence(
            tarea=tarea,
            usuario=self.creador,
            formato_archivo="PDF",
            url="https://example.com/cierre.pdf",
        )

        approve_closure(tarea, self.creador)
        self.assertEqual(tarea.__class__.objects.get(pk=tarea.pk).estado, Tarea.Estado.CERRADA)

    def test_evidence_requirement_disabled_allows_empty_evidence(self):
        tarea = self.make_task()

        approve_closure(tarea, self.creador)

        self.assertFalse(EvidenciaCierre.objects.filter(tarea=tarea).exists())

    def test_evidence_from_other_task_does_not_satisfy_requirement(self):
        tarea = self.make_task()
        tarea.requiere_evidencia_cierre = True
        tarea.save(update_fields=["requiere_evidencia_cierre"])
        otra_empresa = Empresa.objects.create(codigo="T33", descripcion="Otra empresa")
        assign_permission(self.creador, otra_empresa, "Tareas - Listado", ingresar=True)
        otra_tarea = Tarea.objects.create(
            titulo="Otra tarea",
            empresa=otra_empresa,
            creada_por=self.creador,
            responsable=self.responsable,
            fecha_tope=date.today(),
        )
        register_closure_evidence(
            tarea=otra_tarea,
            usuario=self.creador,
            formato_archivo="PDF",
            url="https://example.com/otra.pdf",
        )

        with self.assertRaisesMessage(ValidationError, "CLOSURE_EVIDENCE_REQUIRED"):
            approve_closure(tarea, self.creador)

    def test_invalid_evidence_does_not_satisfy_requirement(self):
        tarea = self.make_task()
        tarea.requiere_evidencia_cierre = True
        tarea.save(update_fields=["requiere_evidencia_cierre"])
        EvidenciaCierre.objects.create(
            tarea=tarea,
            formato_archivo="PDF",
            url="https://example.com/cierre.jpg",
            usuario=self.creador,
        )

        with self.assertRaisesMessage(ValidationError, "CLOSURE_EVIDENCE_REQUIRED"):
            approve_closure(tarea, self.creador)

    def test_quotation_closure_check_remains_deferred(self):
        tarea = self.make_task()

        approve_closure(tarea, self.creador)

        self.assertEqual(Tarea.objects.get(pk=tarea.pk).estado, Tarea.Estado.CERRADA)

    def test_quotation_minimum_blocks_task_closure(self):
        tarea = self.make_task()
        ronda = create_quotation_round(tarea=tarea, minimo_cotizaciones=2)
        create_quotation(
            ronda=ronda,
            version=1,
            monto="10",
            fecha_cotizacion=date.today(),
            proveedor=self.proveedor,
        )

        with self.assertRaisesMessage(ValidationError, "QUOTATION_MINIMUM_NOT_MET"):
            approve_closure(tarea, self.creador)

    def test_quotation_minimum_allows_task_closure(self):
        tarea = self.make_task()
        ronda = create_quotation_round(tarea=tarea, minimo_cotizaciones=1)
        create_quotation(
            ronda=ronda,
            version=1,
            monto="10",
            fecha_cotizacion=date.today(),
            proveedor=self.proveedor,
        )

        approve_closure(tarea, self.creador)
        self.assertEqual(Tarea.objects.get(pk=tarea.pk).estado, Tarea.Estado.CERRADA)

    def test_three_versions_same_provider_do_not_satisfy_three_provider_minimum(self):
        tarea = self.make_task()
        ronda = create_quotation_round(tarea=tarea, minimo_cotizaciones=3)
        for version in (1, 2, 3):
            create_quotation(
                ronda=ronda,
                version=version,
                monto="10",
                fecha_cotizacion=date.today(),
                proveedor=self.proveedor,
            )

        with self.assertRaisesMessage(ValidationError, "QUOTATION_MINIMUM_NOT_MET"):
            approve_closure(tarea, self.creador)

        providers = [
            Proveedor.objects.create(nombre=f"Proveedor cierre distinto {index}")
            for index in (1, 2)
        ]
        for provider in providers:
            create_quotation(
                ronda=ronda,
                version=1,
                monto="10",
                fecha_cotizacion=date.today(),
                proveedor=provider,
            )

        approve_closure(tarea, self.creador)
        self.assertEqual(Tarea.objects.get(pk=tarea.pk).estado, Tarea.Estado.CERRADA)

    def test_only_latest_round_controls_task_closure(self):
        tarea = self.make_task()
        primera = create_quotation_round(tarea=tarea, minimo_cotizaciones=1)
        create_quotation(
            ronda=primera,
            version=1,
            monto="10",
            fecha_cotizacion=date.today(),
            proveedor=self.proveedor,
        )
        segunda = open_next_quotation_round(primera)

        with self.assertRaisesMessage(ValidationError, "QUOTATION_MINIMUM_NOT_MET"):
            approve_closure(tarea, self.creador)

        create_quotation(
            ronda=segunda,
            version=1,
            monto="10",
            fecha_cotizacion=date.today(),
            proveedor=self.proveedor,
            estado=Cotizacion.Estado.DESCARTADA,
        )
        approve_closure(tarea, self.creador)
        self.assertEqual(Tarea.objects.get(pk=tarea.pk).estado, Tarea.Estado.CERRADA)

    def test_quotation_from_another_task_does_not_satisfy_minimum(self):
        tarea = self.make_task()
        ronda = create_quotation_round(tarea=tarea, minimo_cotizaciones=1)
        otra_tarea = Tarea.objects.create(
            titulo="Otra tarea",
            empresa=self.empresa,
            creada_por=self.creador,
            responsable=self.responsable,
            fecha_tope=date.today(),
        )
        otra_ronda = create_quotation_round(tarea=otra_tarea, minimo_cotizaciones=1)
        create_quotation(
            ronda=otra_ronda,
            version=1,
            monto="10",
            fecha_cotizacion=date.today(),
            proveedor=self.proveedor,
        )

        self.assertFalse(ronda.cotizaciones.filter(vigente=True).exists())
        with self.assertRaisesMessage(ValidationError, "QUOTATION_MINIMUM_NOT_MET"):
            approve_closure(tarea, self.creador)

    def test_active_child_blocks_parent_closure_and_closed_descendant_allows_it(self):
        parent = self.make_task()
        child = Tarea.objects.create(
            titulo="Hija",
            empresa=self.empresa,
            creada_por=self.creador,
            responsable=self.responsable,
            fecha_tope=date.today(),
        )
        add_child(parent, child)
        child.publicar(self.creador)

        with self.assertRaisesMessage(ValidationError, "DESCENDANTS_PENDING"):
            approve_closure(parent, self.creador)

        transition_task(child, Tarea.Estado.GESTION, self.creador, "INICIAR_GESTION")
        complete_task(child, self.responsable)
        approve_closure(child, self.creador)
        approve_closure(parent, self.creador)
        self.assertEqual(Tarea.objects.get(pk=parent.pk).estado, Tarea.Estado.CERRADA)

    def test_lifecycle_uses_canonical_closure_validation(self):
        tarea = self.make_task()

        with patch("tareas.services.lifecycle.validate_closure_requirements") as validate:
            approve_closure(tarea, self.creador)

        validate.assert_called_once_with(tarea)