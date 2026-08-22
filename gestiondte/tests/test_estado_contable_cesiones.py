from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase

from access_control.models import Empresa
from gestiondte.models import CesionRPETC, EstadoContableCesion, TareaCesionRPETC, TareaRPETC
from gestiondte.services.estado_contable_cesiones import (
    actualizar_estados_contables_cesiones,
    determinar_estado_pago_resumen,
)


class EstadoPagoResumenTest(SimpleTestCase):
    def test_precedencia_y_clasificacion(self):
        cases = (
            ('NO_DISPONIBLE', 'PAGADA', 'NO_DISPONIBLE'),
            ('REVISAR', 'PAGADA', 'REVISAR'),
            ('PAGADA', 'PAGADA', 'PAGADA_AMBOS'),
            ('PAGADA', 'NO_PAGADA', 'PAGADA_FACTORING'),
            ('NO_PAGADA', 'PAGADA', 'PAGADA_PROVEEDOR'),
            ('NO_PAGADA', 'NO_PAGADA', 'PENDIENTE'),
        )
        for factoring, proveedor, esperado in cases:
            with self.subTest(factoring=factoring, proveedor=proveedor):
                self.assertEqual(determinar_estado_pago_resumen(factoring, proveedor), esperado)


class EstadoContableCesionServiceTest(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(codigo='09', descripcion='Empresa A')
        self.empresa_b = Empresa.objects.create(codigo='10', descripcion='Empresa B')
        self.tarea_a = TareaRPETC.objects.create(
            empresa=self.empresa_a, id_tarea='estado-task-a', tipo_consulta='DEUDOR',
            rut_consultado='77575300', dv_consultado='5', fecha_desde=date(2026, 8, 1),
            fecha_hasta=date(2026, 8, 22), formato='TXT', estado='TERMINADO',
        )
        self.tarea_b = TareaRPETC.objects.create(
            empresa=self.empresa_b, id_tarea='estado-task-b', tipo_consulta='DEUDOR',
            rut_consultado='77575300', dv_consultado='5', fecha_desde=date(2026, 8, 1),
            fecha_hasta=date(2026, 8, 22), formato='TXT', estado='TERMINADO',
        )

    def cesion(self, numero, monto='100'):
        cesion = CesionRPETC.objects.create(
            id_cesion=f'estado-{numero}', estado_cesion='Cesion Vigente',
            deudor_rut='77575300', deudor_dv='5', tipo_doc='33', folio_doc=str(numero),
            cedente_rut='76376142', cedente_dv='8', cedente_razon_social='Cedente',
            cesionario_rut='76682670', cesionario_dv='9', cesionario_razon_social='Factor',
            fecha_cesion=datetime(2026, 8, 22, 12, tzinfo=timezone.utc), monto_cesion=Decimal(monto),
        )
        return cesion

    def vincular(self, tarea, cesion, rol='DEUDOR'):
        TareaCesionRPETC.objects.create(tarea=tarea, cesion=cesion, rol_consulta=rol)

    def estados(self, factoring='NO_PAGADA', proveedor='NO_PAGADA', contabilizacion='CONTABILIZADA', movimientos=None):
        movimiento = {'fecha': '2026-08-22T13:00:00+00:00', 'monto': '100'}
        return {
            'contabilizacion': {'estado': contabilizacion, 'movimientos': []},
            'pagada_factoring': {'estado': factoring, 'movimientos': movimientos or ([movimiento] if factoring == 'PAGADA_FACTORING' else [])},
            'pagada_proveedor': {'estado': proveedor, 'movimientos': movimientos or ([movimiento] if proveedor == 'PAGADA_PROVEEDOR' else [])},
        }

    @patch('gestiondte.services.estado_contable_cesiones.obtener_estados_contables_cesiones')
    def test_crea_snapshot_y_guarda_fecha_monto_inequivocos(self, legacy):
        cesion = self.cesion(1)
        self.vincular(self.tarea_a, cesion)
        legacy.return_value = {cesion.pk: self.estados(factoring='PAGADA_FACTORING')}
        result = actualizar_estados_contables_cesiones(self.empresa_a, [cesion])
        snapshot = EstadoContableCesion.objects.get(empresa=self.empresa_a, cesion=cesion)
        self.assertEqual(result['creadas'], 1)
        self.assertEqual(snapshot.estado_factoring, 'PAGADA')
        self.assertEqual(snapshot.estado_pago_resumen, 'PAGADA_FACTORING')
        self.assertEqual(snapshot.monto_pago_factoring, Decimal('100'))
        self.assertEqual(snapshot.fecha_pago_factoring.hour, 13)
        self.assertEqual(snapshot.estado_contabilizacion, 'CONTABILIZADA')

    @patch('gestiondte.services.estado_contable_cesiones.obtener_estados_contables_cesiones')
    def test_guarda_pago_proveedor_y_pago_ambos(self, legacy):
        cesion = self.cesion(2)
        legacy.return_value = {cesion.pk: self.estados(factoring='PAGADA_FACTORING', proveedor='PAGADA_PROVEEDOR')}
        actualizar_estados_contables_cesiones(self.empresa_a, [cesion])
        snapshot = EstadoContableCesion.objects.get()
        self.assertEqual(snapshot.estado_proveedor, 'PAGADA')
        self.assertEqual(snapshot.estado_pago_resumen, 'PAGADA_AMBOS')
        self.assertEqual(snapshot.monto_pago_proveedor, Decimal('100'))

    @patch('gestiondte.services.estado_contable_cesiones.obtener_estados_contables_cesiones')
    def test_multiples_movimientos_no_eligen_fecha(self, legacy):
        cesion = self.cesion(3)
        movements = [
            {'fecha': '2026-08-22T13:00:00+00:00', 'monto': '100'},
            {'fecha': '2026-08-22T14:00:00+00:00', 'monto': '100'},
        ]
        legacy.return_value = {cesion.pk: self.estados(factoring='REVISAR', movimientos=movements)}
        actualizar_estados_contables_cesiones(self.empresa_a, [cesion])
        snapshot = EstadoContableCesion.objects.get()
        self.assertEqual(snapshot.estado_pago_resumen, 'REVISAR')
        self.assertIsNone(snapshot.fecha_pago_factoring)
        self.assertIsNone(snapshot.monto_pago_factoring)

    @patch('gestiondte.services.estado_contable_cesiones.obtener_estados_contables_cesiones')
    def test_estados_no_disponible_y_no_contabilizada(self, legacy):
        cesion = self.cesion(4)
        legacy.return_value = {cesion.pk: self.estados(factoring='NO_DISPONIBLE', contabilizacion='NO_CONTABILIZADA')}
        actualizar_estados_contables_cesiones(self.empresa_a, [cesion])
        snapshot = EstadoContableCesion.objects.get()
        self.assertEqual(snapshot.estado_contabilizacion, 'NO_CONTABILIZADA')
        self.assertEqual(snapshot.estado_pago_resumen, 'NO_DISPONIBLE')

    @patch('gestiondte.services.estado_contable_cesiones.obtener_estados_contables_cesiones')
    def test_bulk_create_y_bulk_update(self, legacy):
        cesion = self.cesion(5)
        legacy.return_value = {cesion.pk: self.estados()}
        with patch.object(EstadoContableCesion.objects, 'bulk_create', wraps=EstadoContableCesion.objects.bulk_create) as create:
            actualizar_estados_contables_cesiones(self.empresa_a, [cesion])
        create.assert_called_once()
        legacy.return_value = {cesion.pk: self.estados(factoring='PAGADA_FACTORING')}
        with patch.object(EstadoContableCesion.objects, 'bulk_update', wraps=EstadoContableCesion.objects.bulk_update) as update:
            actualizar_estados_contables_cesiones(self.empresa_a, [cesion])
        update.assert_called_once()
        self.assertEqual(EstadoContableCesion.objects.get().estado_pago_resumen, 'PAGADA_FACTORING')

    @patch('gestiondte.services.estado_contable_cesiones.obtener_estados_contables_cesiones')
    def test_chunks_de_250_y_mas_de_un_chunk(self, legacy):
        cesiones = [self.cesion(index, '1') for index in range(1, 253)]
        legacy.side_effect = lambda _codigo, chunk: {cesion.pk: self.estados() for cesion in chunk}
        result = actualizar_estados_contables_cesiones(self.empresa_a, cesiones, chunk_size=250)
        self.assertEqual(legacy.call_count, 2)
        self.assertEqual(len(legacy.call_args_list[0].args[1]), 250)
        self.assertEqual(len(legacy.call_args_list[1].args[1]), 2)
        self.assertEqual(result['procesadas'], 252)
        self.assertEqual(result['creadas'], 252)

    @patch('gestiondte.services.estado_contable_cesiones.obtener_estados_contables_cesiones')
    def test_error_no_destruye_ultimo_estado_valido(self, legacy):
        cesion = self.cesion(6)
        legacy.return_value = {cesion.pk: self.estados(factoring='PAGADA_FACTORING')}
        actualizar_estados_contables_cesiones(self.empresa_a, [cesion])
        snapshot = EstadoContableCesion.objects.get()
        verificacion_anterior = snapshot.fecha_verificacion
        legacy.side_effect = RuntimeError('password=secreto traceback')
        actualizar_estados_contables_cesiones(self.empresa_a, [cesion])
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.estado_pago_resumen, 'PAGADA_FACTORING')
        self.assertEqual(snapshot.estado_factoring, 'PAGADA')
        self.assertEqual(snapshot.estado_verificacion, 'ERROR')
        self.assertNotEqual(snapshot.fecha_verificacion, verificacion_anterior)
        self.assertNotIn('secreto', snapshot.mensaje_error)
        self.assertNotIn('password', snapshot.mensaje_error)

    @patch('gestiondte.services.estado_contable_cesiones.obtener_estados_contables_cesiones', side_effect=RuntimeError('fallo'))
    def test_error_de_snapshot_nuevo_inicializa_no_disponible(self, legacy):
        cesion = self.cesion(9)
        result = actualizar_estados_contables_cesiones(self.empresa_a, [cesion])
        snapshot = EstadoContableCesion.objects.get()
        self.assertEqual(result['errores'], 1)
        self.assertEqual(snapshot.estado_contabilizacion, 'NO_DISPONIBLE')
        self.assertEqual(snapshot.estado_pago_resumen, 'NO_DISPONIBLE')
        self.assertEqual(snapshot.estado_verificacion, 'ERROR')

    @patch('gestiondte.services.estado_contable_cesiones.obtener_estados_contables_cesiones')
    def test_misma_cesion_tiene_snapshots_independientes_por_empresa(self, legacy):
        cesion = self.cesion(7)
        self.vincular(self.tarea_a, cesion)
        self.vincular(self.tarea_b, cesion, rol='CEDENTE')
        legacy.side_effect = [
            {cesion.pk: self.estados(factoring='PAGADA_FACTORING')},
            {cesion.pk: self.estados(proveedor='PAGADA_PROVEEDOR')},
        ]
        actualizar_estados_contables_cesiones(self.empresa_a, [cesion])
        actualizar_estados_contables_cesiones(self.empresa_b, [cesion])
        self.assertEqual(EstadoContableCesion.objects.count(), 2)
        self.assertEqual(EstadoContableCesion.objects.get(empresa=self.empresa_a).estado_pago_resumen, 'PAGADA_FACTORING')
        self.assertEqual(EstadoContableCesion.objects.get(empresa=self.empresa_b).estado_pago_resumen, 'PAGADA_PROVEEDOR')

    def test_constraint_rechaza_snapshot_duplicado(self):
        cesion = self.cesion(8)
        values = dict(empresa=self.empresa_a, cesion=cesion, estado_contabilizacion='NO_CONTABILIZADA', estado_factoring='NO_PAGADA', estado_proveedor='NO_PAGADA', estado_pago_resumen='PENDIENTE')
        EstadoContableCesion.objects.create(**values)
        with self.assertRaises(IntegrityError):
            EstadoContableCesion.objects.create(**values)
