from datetime import date, datetime, timezone
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from access_control.models import Empresa
from gestiondte.models import (
    CesionRPETC,
    CesionRPETCHistorial,
    TareaCesionRPETC,
    TareaRPETC,
)


class RPETCModelTestMixin:
    def setUp(self):
        self.empresa_a = Empresa.objects.create(codigo="09", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="10", descripcion="Empresa B")

    def tarea(self, empresa, id_tarea="tarea-1"):
        return TareaRPETC.objects.create(
            empresa=empresa,
            id_tarea=id_tarea,
            tipo_consulta="DEUDOR",
            rut_consultado="77575300",
            dv_consultado="5",
            fecha_desde=date(2026, 7, 1),
            fecha_hasta=date(2026, 7, 31),
            formato="TXT",
            rut_autenticado="07762388",
            dv_autenticado="4",
            nombre_tarea="CESIONES_POR_DEUDOR",
            estado="CREADO",
        )

    def cesion(self, id_cesion="52009291", folio_doc="00064240"):
        return CesionRPETC.objects.create(
            id_cesion=id_cesion,
            estado_cesion="Cesion Vigente",
            vendedor_rut="076856463",
            vendedor_dv="9",
            deudor_rut="77575300",
            deudor_dv="5",
            deudor_email="deudor@example.test",
            tipo_doc="33",
            nombre_doc="Factura Electronica",
            folio_doc=folio_doc,
            fecha_emision=date(2026, 6, 30),
            monto_total=Decimal("567487"),
            cedente_rut="76856463",
            cedente_dv="9",
            cedente_razon_social="Cedente Test",
            cedente_email="cedente@example.test",
            cesionario_rut="99580240",
            cesionario_dv="6",
            cesionario_razon_social="Cesionario Test",
            cesionario_email="cesionario@example.test",
            fecha_cesion=datetime(2026, 7, 1, 11, 41, 26, tzinfo=timezone.utc),
            monto_cesion=Decimal("567487"),
            fecha_vencimiento=date(2026, 6, 30),
        )


class TareaRPETCTest(RPETCModelTestMixin, TestCase):
    def test_creacion_empresa_y_str(self):
        tarea = self.tarea(self.empresa_a)
        self.assertEqual(tarea.empresa_id, "09")
        self.assertIn("tarea-1", str(tarea))
        self.assertEqual(tarea.formato, "TXT")

    def test_id_tarea_es_unico(self):
        self.tarea(self.empresa_a)
        with self.assertRaises(IntegrityError):
            self.tarea(self.empresa_b)

    def test_choices_rechazan_valores_invalidos_en_full_clean(self):
        tarea = self.tarea(self.empresa_a)
        tarea.tipo_consulta = "OTRO"
        with self.assertRaises(ValidationError):
            tarea.full_clean()

    def test_parametros_raw_y_json_son_independientes(self):
        tarea = self.tarea(self.empresa_a)
        tarea.parametros_raw = '{"desde":"2026-07-01"}'
        tarea.parametros = {"desde": "2026-07-01"}
        tarea.save()
        tarea.refresh_from_db()
        self.assertEqual(tarea.parametros["desde"], "2026-07-01")
        self.assertIn("desde", tarea.parametros_raw)


class CesionRPETCTest(RPETCModelTestMixin, TestCase):
    def test_creacion_con_montos_rut_y_folio_string(self):
        cesion = self.cesion()
        self.assertEqual(cesion.monto_total, Decimal("567487"))
        self.assertEqual(cesion.monto_cesion, Decimal("567487"))
        self.assertEqual(cesion.deudor_rut, "77575300")
        self.assertEqual(cesion.folio_doc, "00064240")
        self.assertNotEqual(cesion._meta.pk.name, "id_cesion")
        self.assertIn("52009291", str(cesion))

    def test_constraint_conservador_id_cesion_y_documento(self):
        self.cesion()
        with self.assertRaises(IntegrityError):
            self.cesion()

    def test_mismo_id_cesion_puede_existir_con_otra_clave_documental(self):
        self.cesion()
        self.cesion(id_cesion="52009291", folio_doc="00064241")
        self.assertEqual(CesionRPETC.objects.filter(id_cesion="52009291").count(), 2)


class TareaCesionRPETCTest(RPETCModelTestMixin, TestCase):
    def test_vinculo_y_duplicado_rechazado(self):
        tarea = self.tarea(self.empresa_a)
        cesion = self.cesion()
        vinculo = TareaCesionRPETC.objects.create(
            tarea=tarea,
            cesion=cesion,
            rol_consulta="DEUDOR",
            fila_origen=3,
        )
        self.assertEqual(vinculo.cesion, cesion)
        with self.assertRaises(IntegrityError):
            TareaCesionRPETC.objects.create(
                tarea=tarea,
                cesion=cesion,
                rol_consulta="DEUDOR",
            )

    def test_misma_cesion_compartida_por_dos_empresas(self):
        cesion = self.cesion()
        TareaCesionRPETC.objects.create(
            tarea=self.tarea(self.empresa_a, "tarea-a"),
            cesion=cesion,
            rol_consulta="DEUDOR",
        )
        TareaCesionRPETC.objects.create(
            tarea=self.tarea(self.empresa_b, "tarea-b"),
            cesion=cesion,
            rol_consulta="CEDENTE",
        )
        self.assertEqual(cesion.tareas.count(), 2)
        self.assertEqual(
            set(cesion.tareas.values_list("tarea__empresa_id", flat=True)),
            {"09", "10"},
        )


class CesionRPETCHistorialTest(RPETCModelTestMixin, TestCase):
    def test_estado_anterior_y_tarea_origen_son_nullable(self):
        cesion = self.cesion()
        historial = CesionRPETCHistorial.objects.create(
            cesion=cesion,
            estado="Cesion Vigente",
        )
        self.assertIsNone(historial.estado_anterior)
        self.assertIsNone(historial.tarea_origen)

    def test_historial_puede_referenciar_tarea(self):
        tarea = self.tarea(self.empresa_a)
        historial = CesionRPETCHistorial.objects.create(
            cesion=self.cesion(),
            estado="Revocada",
            estado_anterior="Cesion Vigente",
            tarea_origen=tarea,
            observacion="Cambio detectado en nueva consulta",
        )
        self.assertEqual(historial.tarea_origen, tarea)
