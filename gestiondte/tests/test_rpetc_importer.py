from datetime import date
from decimal import Decimal

from django.test import TestCase

from access_control.models import Empresa
from gestiondte.models import CesionRPETC, CesionRPETCHistorial, TareaCesionRPETC, TareaRPETC
from gestiondte.services.rpetc_importer import (
    RPETCImportError,
    importar_resultado_rpetc,
    normalizar_rut,
)


COLUMNS = [
    "VENDEDOR", "ESTADO_CESION", "DEUDOR", "MAIL_DEUDOR", "TIPO_DOC",
    "NOMBRE_DOC", "FOLIO_DOC", "FCH_EMIS_DTE", "MNT_TOTAL", "CEDENTE",
    "RZ_CEDENTE", "MAIL_CEDENTE", "CESIONARIO", "RZ_CESIONARIO",
    "MAIL_CESIONARIO", "FCH_CESION", "MNT_CESION", "FCH_VENCIMIENTO",
    "ID_CESION",
]


def row(id_cesion="100", estado="Cesion Vigente", folio="0001", **overrides):
    value = {
        "VENDEDOR": "77.575.300-5",
        "ESTADO_CESION": estado,
        "DEUDOR": "07762388-4",
        "MAIL_DEUDOR": "deudor@example.test",
        "TIPO_DOC": "33",
        "NOMBRE_DOC": "Factura Electronica",
        "FOLIO_DOC": folio,
        "FCH_EMIS_DTE": "2026-07-01",
        "MNT_TOTAL": "1000",
        "CEDENTE": "76.856.463-9",
        "RZ_CEDENTE": "Cedente Test",
        "MAIL_CEDENTE": "cedente@example.test",
        "CESIONARIO": "99.580.240-6",
        "RZ_CESIONARIO": "Cesionario Test",
        "MAIL_CESIONARIO": "cesionario@example.test",
        "FCH_CESION": "2026-07-02T12:30:00",
        "MNT_CESION": "1000",
        "FCH_VENCIMIENTO": "2026-08-01",
        "ID_CESION": id_cesion,
    }
    value.update(overrides)
    return value


def task(id_tarea="task-1", rut="77575300", dv="5", **overrides):
    value = {
        "idTarea": id_tarea,
        "rut": rut,
        "dv": dv,
        "rutAutenticado": "07762388",
        "dvAutenticado": "4",
        "nombre": "CESIONES_POR_DEUDOR",
        "estado": "CREADO",
        "horaCreado": "2026-08-19T18:00:00Z",
        "parametros": '{"desde":"2026-07-01"}',
    }
    value.update(overrides)
    return value


def final(estado="TERMINADO", **overrides):
    value = {
        "estado": estado,
        "resultado": None,
        "horaEnProceso": "2026-08-19T18:00:01Z",
        "horaTerminado": "2026-08-19T18:00:02Z",
        "fileSize": 100,
        "cantidadDeLineas": 3,
        "comprimido": 0,
        "codigoError": 0,
        "descripcionError": "",
        "parametros": '{"desde":"2026-07-01"}',
    }
    value.update(overrides)
    return value


def parsed(rows):
    return {"consulta": {}, "columnas": COLUMNS, "registros": rows, "cantidad_registros": len(rows)}


class RPETCImporterTest(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(codigo="09", descripcion="A")
        self.empresa_b = Empresa.objects.create(codigo="10", descripcion="B")

    def importar(self, empresa, tarea_data, rows, tipo="DEUDOR", id_tarea="task-1", **final_overrides):
        return importar_resultado_rpetc(
            empresa,
            tarea_data,
            final(**final_overrides),
            parsed(rows),
            tipo,
            date(2026, 7, 1),
            date(2026, 7, 31),
            "TXT",
        )

    def test_normaliza_rut_y_preserva_ceros_y_dv_k(self):
        self.assertEqual(normalizar_rut("77.575.300-5"), ("77575300", "5"))
        self.assertEqual(normalizar_rut("07762388-k"), ("07762388", "K"))
        self.assertEqual(normalizar_rut(""), (None, None))

    def test_importacion_inicial_crea_tarea_cesion_vinculo_e_historial(self):
        stats = self.importar(self.empresa_a, task(), [row()])
        self.assertEqual(stats["cesiones_creadas"], 1)
        self.assertEqual(stats["vinculos_creados"], 1)
        self.assertEqual(stats["transiciones_estado"], 1)
        cesion = CesionRPETC.objects.get()
        self.assertEqual(cesion.deudor_rut, "07762388")
        self.assertEqual(cesion.monto_total, Decimal("1000"))
        self.assertEqual(cesion.fecha_cesion.hour, 12)
        self.assertEqual(CesionRPETCHistorial.objects.count(), 1)
        self.assertIsNone(CesionRPETCHistorial.objects.get().estado_anterior)

    def test_reimportar_misma_tarea_es_idempotente(self):
        self.importar(self.empresa_a, task(), [row()])
        stats = self.importar(self.empresa_a, task(), [row()])
        self.assertEqual(TareaRPETC.objects.count(), 1)
        self.assertEqual(CesionRPETC.objects.count(), 1)
        self.assertEqual(TareaCesionRPETC.objects.count(), 1)
        self.assertEqual(CesionRPETCHistorial.objects.count(), 1)
        self.assertEqual(stats["vinculos_creados"], 0)
        self.assertEqual(stats["transiciones_estado"], 0)

    def test_cambio_estado_crea_una_transicion_y_nuevo_vinculo(self):
        self.importar(self.empresa_a, task("task-a"), [row()])
        self.importar(self.empresa_a, task("task-b"), [row(estado="Revocada")])
        cesion = CesionRPETC.objects.get()
        self.assertEqual(cesion.estado_cesion, "Revocada")
        self.assertEqual(CesionRPETCHistorial.objects.count(), 2)
        transition = CesionRPETCHistorial.objects.order_by("id").last()
        self.assertEqual(transition.estado_anterior, "Cesion Vigente")
        self.assertEqual(transition.estado, "Revocada")
        self.assertEqual(TareaCesionRPETC.objects.count(), 2)

    def test_misma_cesion_otras_empresa_y_perspectiva_no_duplica(self):
        self.importar(self.empresa_a, task("task-a"), [row()])
        self.importar(self.empresa_b, task("task-b"), [row()], tipo="CEDENTE")
        self.assertEqual(CesionRPETC.objects.count(), 1)
        self.assertEqual(TareaRPETC.objects.count(), 2)
        self.assertEqual(TareaCesionRPETC.objects.count(), 2)
        self.assertEqual(set(TareaCesionRPETC.objects.values_list("rol_consulta", flat=True)), {"DEUDOR", "CEDENTE"})

    def test_vacios_no_pisan_datos_existentes(self):
        self.importar(self.empresa_a, task(), [row()])
        updated = row(MAIL_DEUDOR="", RZ_CEDENTE="", MNT_TOTAL="")
        self.importar(self.empresa_a, task("task-b"), [updated])
        cesion = CesionRPETC.objects.get()
        self.assertEqual(cesion.deudor_email, "deudor@example.test")
        self.assertEqual(cesion.cedente_razon_social, "Cedente Test")
        self.assertEqual(cesion.monto_total, Decimal("1000"))

    def test_parametros_invalidos_se_conservan_raw_sin_fallar(self):
        self.importar(self.empresa_a, task(), [row()], parametros="no-json")
        tarea = TareaRPETC.objects.get()
        self.assertIsNone(tarea.parametros)
        self.assertEqual(tarea.parametros_raw, "no-json")

    def test_resultado_valido_sin_registros_persiste_solo_tarea(self):
        stats = self.importar(self.empresa_a, task(), [])
        self.assertEqual(stats['registros_recibidos'], 0)
        self.assertEqual(stats['cesiones_creadas'], 0)
        self.assertEqual(stats['vinculos_creados'], 0)
        self.assertEqual(stats['transiciones_estado'], 0)
        self.assertEqual(TareaRPETC.objects.count(), 1)
        self.assertEqual(CesionRPETC.objects.count(), 0)
        self.assertEqual(TareaCesionRPETC.objects.count(), 0)
        self.assertEqual(CesionRPETCHistorial.objects.count(), 0)

    def test_id_cesion_vacio_aborta_y_revierte_todo(self):
        with self.assertRaises(RPETCImportError):
            self.importar(self.empresa_a, task(), [row(), row(id_cesion="")])
        self.assertEqual(TareaRPETC.objects.count(), 0)
        self.assertEqual(CesionRPETC.objects.count(), 0)
        self.assertEqual(TareaCesionRPETC.objects.count(), 0)

    def test_fecha_invalida_y_monto_invalido_abortan(self):
        for invalid in (row(FCH_EMIS_DTE="2026-02-30"), row(MNT_TOTAL="abc")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(RPETCImportError):
                    self.importar(self.empresa_a, task(), [invalid])
                self.assertEqual(CesionRPETC.objects.count(), 0)
