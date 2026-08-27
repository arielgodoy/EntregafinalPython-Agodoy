from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from gestiondte.models import (
    CesionRPETC,
    CertificadoSII,
    TareaCesionRPETC,
    TareaRPETC,
)
from auditoria.models import AuditoriaGestionDTEEvent
from gestiondte.views import _rpetc_request_filters
from settings.models import UserPreferences


class SincronizarRPETCViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sync-user', password='pass')
        self.empresa = Empresa.objects.create(codigo='09', descripcion='Empresa activa')
        self.otra_empresa = Empresa.objects.create(codigo='10', descripcion='Otra empresa')
        vista, _ = Vista.objects.get_or_create(nombre='Gestión DTE - Control de Cesiones')
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            ingresar=True,
            modificar=True,
        )
        self.client = Client()
        self.client.login(username='sync-user', password='pass')
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()
        UserPreferences.objects.update_or_create(
            user=self.user,
            defaults={'fecha_sistema': date(2026, 8, 27)},
        )
        CertificadoSII.objects.create(
            empresa_codigo='09', archivo='certificado.pfx', activo=True,
        )
        self.initial = {
            'idTarea': 'task-real', 'rut': 77575300, 'dv': '5',
            'rutAutenticado': 7762388, 'dvAutenticado': '4',
            'nombre': 'CESIONES_POR_DEUDOR', 'estado': 'CREADO',
        }
        self.final = {
            'estado': 'TERMINADO', 'codigoError': 0,
            'descripcionError': '', 'fileSize': 10,
            'cantidadDeLineas': 3, 'comprimido': 0,
        }
        self.parsed = {
            'consulta': {'TIPO_CONSULTA': 'DEUDOR', 'RUT': '77575300-5'},
            'columnas': ['ID_CESION'],
            'registros': [{'ID_CESION': '100'}],
            'cantidad_registros': 1,
        }

    def test_control_cesiones_usa_inicio_del_ano_actual_en_contexto_y_ajax(self):
        for today in (date(2027, 3, 15), date(2028, 1, 2)):
            with self.subTest(today=today), patch('gestiondte.views.timezone.localdate', return_value=today):
                response = self.client.get(reverse('gestion_dte:cesiones'))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['filtros']['fecha_desde'], date(today.year, 1, 1))
                self.assertEqual(response.context['filtros']['fecha_hasta'], today)
                filters = _rpetc_request_filters(response.wsgi_request)
                self.assertEqual(filters['fecha_desde'], date(today.year, 1, 1))
                self.assertEqual(filters['fecha_hasta'], today)
                self.assertContains(response, f'value="{today.year}-01-01"')
                self.assertContains(response, f'value="{today.isoformat()}"')

    def test_control_cesiones_limpiar_conserva_defaults_anuales_y_pagos(self):
        today = date(2026, 8, 27)
        with patch('gestiondte.views.timezone.localdate', return_value=today):
            response = self.client.get(reverse('gestion_dte:cesiones'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="sin_pago_factoring"')
        self.assertContains(response, 'id="sin_pago_proveedor"')
        self.assertContains(response, 'href="/gestiondte/cesiones/"')
        self.assertContains(response, 'value="2026-01-01"')
        self.assertContains(response, 'value="2026-08-27"')

    def test_sin_permiso_modificar_recibe_403(self):
        Permiso.objects.update(modificar=False)
        response = self.client.post(reverse('gestion_dte:sincronizar_cesiones_rpetc'), {
            'fecha_desde': '2026-07-01', 'fecha_hasta': '2026-07-31',
        })
        self.assertEqual(response.status_code, 403)

    def test_sin_empresa_activa_no_ejecuta(self):
        session = self.client.session
        session.pop('empresa_id', None)
        session.save()
        response = self.client.post(reverse('gestion_dte:sincronizar_cesiones_rpetc'), {})
        self.assertEqual(response.status_code, 302)

    def test_formulario_rechaza_rango_mayor_a_un_mes(self):
        response = self.client.post(reverse('gestion_dte:sincronizar_cesiones_rpetc'), {
            'fecha_desde': '2026-07-01', 'fecha_hasta': '2026-08-02',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'rango solicitado')

    @patch('gestiondte.services.rpetc_importer.importar_resultado_rpetc')
    @patch('gestiondte.services.rpetc_parser.parsear_txt_rpetc')
    @patch('gestiondte.services.rpetc.RPETCClient')
    @patch('gestiondte.views.get_maestroempresa_by_codigo')
    def test_mes_ignora_ano_manipulado_y_usa_fecha_sistema(self, maestro, client_class, parser, importer):
        maestro.return_value = {'rut': '77575300-5', 'nombre': 'Empresa activa'}
        client_class.return_value.obtener_cesiones_deudor.return_value = {
            'tarea_inicial': self.initial,
            'estado_final': self.final,
            'resultado': {'bytes': b'contenido'},
        }
        parser.return_value = self.parsed
        importer.return_value = {'registros_recibidos': 0, 'cesiones_creadas': 0, 'cesiones_actualizadas': 0}
        response = self.client.post(reverse('gestion_dte:sincronizar_cesiones_rpetc'), {
            'mes': '3', 'anio': '2030', 'fecha_desde': '2030-03-01', 'fecha_hasta': '2030-03-31',
        })
        self.assertEqual(response.status_code, 200)
        call = client_class.return_value.obtener_cesiones_deudor.call_args
        self.assertEqual(call.kwargs['desde'], '01032026')
        self.assertEqual(call.kwargs['hasta'], '31032026')

    @patch('gestiondte.services.rpetc.RPETCClient')
    def test_mes_posterior_a_fecha_sistema_no_procesa(self, client_class):
        response = self.client.post(reverse('gestion_dte:sincronizar_cesiones_rpetc'), {
            'mes': '9', 'fecha_desde': '2026-09-01', 'fecha_hasta': '2026-09-30',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'mes posterior a la fecha de sistema')
        client_class.assert_not_called()

    def test_botones_mensuales_usan_fecha_sistema_y_bloquean_futuros(self):
        response = self.client.get(reverse('gestion_dte:cesiones'))
        self.assertContains(response, 'data-month="3" data-desde="2026-03-01" data-hasta="2026-03-31"')
        self.assertContains(response, 'data-month="8" data-desde="2026-08-01" data-hasta="2026-08-27"')
        self.assertContains(response, 'data-month="9" data-desde="" data-hasta="" disabled')

    @patch('gestiondte.services.rpetc_importer.importar_resultado_rpetc')
    @patch('gestiondte.services.rpetc_parser.parsear_txt_rpetc')
    @patch('gestiondte.services.rpetc.RPETCClient')
    @patch('gestiondte.views.get_maestroempresa_by_codigo')
    def test_exito_usa_rut_empresa_y_servicios_reales(self, maestro, client_class, parser, importer):
        maestro.return_value = {'rut': '77575300-5', 'nombre': 'Empresa activa'}
        client_class.return_value.obtener_cesiones_deudor.return_value = {
            'tarea_inicial': self.initial,
            'estado_final': self.final,
            'resultado': {'bytes': b'contenido'},
        }
        parser.return_value = self.parsed
        importer.return_value = {
            'registros_recibidos': 1, 'cesiones_creadas': 1,
            'cesiones_actualizadas': 0, 'cesiones_sin_cambios': 0,
            'vinculos_creados': 1, 'transiciones_estado': 1, 'errores': [],
        }
        response = self.client.post(reverse('gestion_dte:sincronizar_cesiones_rpetc'), {
            'fecha_desde': '2026-07-01', 'fecha_hasta': '2026-07-31',
        })
        self.assertEqual(response.status_code, 200)
        call = client_class.return_value.obtener_cesiones_deudor.call_args
        self.assertEqual(call.kwargs['rut_deudor'], '77575300')
        self.assertEqual(call.kwargs['dv_deudor'], '5')
        self.assertEqual(call.kwargs['desde'], '01072026')
        self.assertEqual(call.kwargs['hasta'], '31072026')
        self.assertEqual(call.kwargs['formato'], 'TXT')
        importer.assert_called_once()
        self.assertContains(response, 'Sincronización completada')
        event = AuditoriaGestionDTEEvent.objects.get(action='UPDATE')
        self.assertEqual(event.empresa_id, self.empresa.id)
        self.assertEqual(event.vista_nombre, 'Gestión DTE - Control de Cesiones')
        self.assertEqual(event.meta['procesados'], 1)
        self.assertEqual(event.meta['actualizados'], 0)

    @patch('gestiondte.services.rpetc_importer.importar_resultado_rpetc')
    @patch('gestiondte.services.rpetc_parser.parsear_txt_rpetc')
    @patch('gestiondte.services.rpetc.RPETCClient')
    @patch('gestiondte.views.get_maestroempresa_by_codigo')
    def test_resultado_deudor_valido_sin_registros_es_exitoso(self, maestro, client_class, parser, importer):
        maestro.return_value = {'rut': '77575300-5', 'nombre': 'Empresa activa'}
        client_class.return_value.obtener_cesiones_deudor.return_value = {
            'tarea_inicial': self.initial,
            'estado_final': self.final,
            'resultado': {'bytes': b'contenido'},
        }
        parser.return_value = {
            'consulta': {'TIPO_CONSULTA': 'DEUDOR', 'RUT': '77575300-5'},
            'columnas': ['ID_CESION'],
            'registros': [],
            'cantidad_registros': 0,
        }
        importer.return_value = {
            'registros_recibidos': 0, 'cesiones_creadas': 0,
            'cesiones_actualizadas': 0, 'cesiones_sin_cambios': 0,
            'vinculos_creados': 0, 'transiciones_estado': 0, 'errores': [],
        }
        response = self.client.post(reverse('gestion_dte:sincronizar_cesiones_rpetc'), {
            'fecha_desde': '2026-08-01', 'fecha_hasta': '2026-08-20',
        })
        self.assertEqual(response.status_code, 200)
        importer.assert_called_once()
        self.assertContains(response, 'Sincronización completada')
        self.assertContains(response, 'No existen cesiones registradas por el SII para este período.')
        self.assertNotContains(response, 'No fue posible completar la sincronización RPETC.')

    @patch('gestiondte.services.rpetc.RPETCClient')
    @patch('gestiondte.views.get_maestroempresa_by_codigo')
    def test_bloquea_tarea_local_en_progreso(self, maestro, client_class):
        maestro.return_value = {'rut': '77575300-5'}
        TareaRPETC.objects.create(
            empresa=self.empresa, id_tarea='pending', tipo_consulta='DEUDOR',
            rut_consultado='77575300', dv_consultado='5',
            fecha_desde=date(2026, 7, 1), fecha_hasta=date(2026, 7, 31),
            formato='TXT', estado='EN_PROCESO',
        )
        response = self.client.post(reverse('gestion_dte:sincronizar_cesiones_rpetc'), {
            'fecha_desde': '2026-07-01', 'fecha_hasta': '2026-07-31',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'sincronización en progreso')
        client_class.assert_not_called()

    def test_historial_get_solo_empresa_activa(self):
        TareaRPETC.objects.create(
            empresa=self.otra_empresa, id_tarea='other', tipo_consulta='DEUDOR',
            rut_consultado='1', dv_consultado='9',
            fecha_desde=date(2026, 7, 1), fecha_hasta=date(2026, 7, 31),
            formato='TXT', estado='TERMINADO',
        )
        response = self.client.get(reverse('gestion_dte:cesiones'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['cesiones_por_fecha']), [])

    @patch('gestiondte.views.timezone.localdate', return_value=date(2026, 8, 20))
    def test_sin_get_aplica_default_anual_al_queryset(self, localdate):
        tarea = TareaRPETC.objects.create(
            empresa=self.empresa, id_tarea='task-defaults', tipo_consulta='DEUDOR',
            rut_consultado='1', dv_consultado='9', fecha_desde=date(2026, 8, 1),
            fecha_hasta=date(2026, 8, 20), formato='TXT', estado='TERMINADO',
        )
        dentro = CesionRPETC.objects.create(
            id_cesion='default-in', estado_cesion='Vigente', cedente_rut='11111111', cedente_dv='1',
            cedente_razon_social='Proveedor A', deudor_rut='1', deudor_dv='9', tipo_doc='33', folio_doc='1',
            fecha_cesion=datetime(2026, 8, 20, tzinfo=timezone.utc), monto_cesion=Decimal('100'),
        )
        fuera = CesionRPETC.objects.create(
            id_cesion='default-out', estado_cesion='Vigente', cedente_rut='22222222', cedente_dv='2',
            cedente_razon_social='Proveedor B', deudor_rut='1', deudor_dv='9', tipo_doc='33', folio_doc='2',
            fecha_cesion=datetime(2025, 12, 31, tzinfo=timezone.utc), monto_cesion=Decimal('200'),
        )
        for cesion in (dentro, fuera):
            TareaCesionRPETC.objects.create(tarea=tarea, cesion=cesion, rol_consulta='DEUDOR')
        response = self.client.get(reverse('gestion_dte:cesiones'))
        self.assertEqual(response.context['filtros']['fecha_desde'], date(2026, 1, 1))
        self.assertEqual(response.context['filtros']['fecha_hasta'], date(2026, 8, 20))
        self.assertEqual(response.context['total_cesiones_rpetc'], 1)
        self.assertEqual(response.context['cesiones_detalle'], [])
        localdate.assert_called_once_with()

    @patch('gestiondte.views.timezone.localdate', return_value=date(2026, 8, 20))
    def test_get_explicito_conserva_fechas(self, localdate):
        response = self.client.get(reverse('gestion_dte:cesiones'), {
            'fecha_desde': '2026-07-01', 'fecha_hasta': '2026-07-31',
        })
        self.assertEqual(response.context['filtros']['fecha_desde'], date(2026, 7, 1))
        self.assertEqual(response.context['filtros']['fecha_hasta'], date(2026, 7, 31))

    def test_combo_proveedores_unico_ordenado_y_aislado(self):
        tarea_a = TareaRPETC.objects.create(
            empresa=self.empresa, id_tarea='task-suppliers-a', tipo_consulta='DEUDOR',
            rut_consultado='1', dv_consultado='9', fecha_desde=date(2026, 8, 1),
            fecha_hasta=date(2026, 8, 20), formato='TXT', estado='TERMINADO',
        )
        tarea_b = TareaRPETC.objects.create(
            empresa=self.otra_empresa, id_tarea='task-suppliers-b', tipo_consulta='DEUDOR',
            rut_consultado='2', dv_consultado='9', fecha_desde=date(2026, 8, 1),
            fecha_hasta=date(2026, 8, 20), formato='TXT', estado='TERMINADO',
        )
        for index in range(2):
            cesion = CesionRPETC.objects.create(
                id_cesion=f'supplier-a-{index}', estado_cesion='Vigente', cedente_rut='11111111', cedente_dv='1',
                cedente_razon_social='Proveedor A', deudor_rut='1', deudor_dv='9', tipo_doc='33', folio_doc=str(index),
                fecha_cesion=datetime(2026, 8, 20, tzinfo=timezone.utc), monto_cesion=Decimal('100'),
            )
            TareaCesionRPETC.objects.create(tarea=tarea_a, cesion=cesion, rol_consulta='DEUDOR')
        other = CesionRPETC.objects.create(
            id_cesion='supplier-b', estado_cesion='Vigente', cedente_rut='99999999', cedente_dv='9',
            cedente_razon_social='Proveedor Z', deudor_rut='2', deudor_dv='9', tipo_doc='33', folio_doc='9',
            fecha_cesion=datetime(2026, 8, 20, tzinfo=timezone.utc), monto_cesion=Decimal('100'),
        )
        TareaCesionRPETC.objects.create(tarea=tarea_b, cesion=other, rol_consulta='DEUDOR')
        response = self.client.get(reverse('gestion_dte:cesiones'))
        suppliers = response.context['proveedores_filtro']
        self.assertEqual(len(suppliers), 1)
        self.assertEqual(suppliers[0]['value'], '11111111-1')
        self.assertIn('Proveedor A', suppliers[0]['label'])

    def test_cesiones_se_agrupan_sin_duplicar_por_tareas(self):
        tareas = []
        for suffix in ('a', 'b', 'c'):
            tareas.append(TareaRPETC.objects.create(
                empresa=self.empresa, id_tarea=f'task-{suffix}',
                tipo_consulta='DEUDOR', rut_consultado='77575300', dv_consultado='5',
                fecha_desde=date(2026, 7, 1), fecha_hasta=date(2026, 7, 31),
                formato='TXT', estado='TERMINADO', cantidad_lineas=1,
            ))
        cesion = CesionRPETC.objects.create(
            id_cesion='cesion-1', estado_cesion='Cesion Vigente',
            deudor_rut='77575300', deudor_dv='5', tipo_doc='33', folio_doc='100',
            cedente_rut='11111111', cedente_dv='1', cesionario_rut='22222222',
            cesionario_dv='2', fecha_cesion=datetime(2026, 8, 19, 10, tzinfo=timezone.utc),
            monto_cesion=Decimal('4032482'), deudor_email='hidden@example.test',
        )
        for tarea in tareas:
            TareaCesionRPETC.objects.create(tarea=tarea, cesion=cesion, rol_consulta='DEUDOR')
        response = self.client.get(reverse('gestion_dte:cesiones'))
        self.assertEqual(response.context['total_cesiones_rpetc'], 1)
        self.assertEqual(response.context['cesiones_por_fecha'][0]['cantidad'], 1)
        self.assertEqual(response.context['cesiones_por_fecha'][0]['monto'], Decimal('4032482'))
        self.assertNotContains(response, 'hidden@example.test')

    def test_fecha_query_muestra_solo_detalle_de_esa_fecha(self):
        tarea = TareaRPETC.objects.create(
            empresa=self.empresa, id_tarea='task-date', tipo_consulta='DEUDOR',
            rut_consultado='77575300', dv_consultado='5', fecha_desde=date(2026, 7, 1),
            fecha_hasta=date(2026, 7, 31), formato='TXT', estado='TERMINADO',
        )
        for suffix, day in (('one', 19), ('two', 18)):
            cesion = CesionRPETC.objects.create(
                id_cesion=f'cesion-{suffix}', estado_cesion='Cesion Vigente',
                deudor_rut='77575300', deudor_dv='5', tipo_doc='33', folio_doc=suffix,
                cedente_rut='11111111', cedente_dv='1', cesionario_rut='22222222',
                cesionario_dv='2', fecha_cesion=datetime(2026, 8, day, 10, tzinfo=timezone.utc),
                monto_cesion=Decimal('100'),
            )
            TareaCesionRPETC.objects.create(tarea=tarea, cesion=cesion, rol_consulta='DEUDOR')
        response = self.client.get(reverse('gestion_dte:cesiones'), {
            'fecha_desde': '2026-08-19', 'fecha_hasta': '2026-08-19',
        })
        self.assertEqual(response.context['cesiones_detalle'], [])

    def _crear_cesiones_para_filtros(self):
        tarea = TareaRPETC.objects.create(
            empresa=self.empresa, id_tarea='task-filters', tipo_consulta='DEUDOR',
            rut_consultado='77575300', dv_consultado='5', fecha_desde=date(2026, 7, 1),
            fecha_hasta=date(2026, 8, 31), formato='TXT', estado='TERMINADO',
        )
        first = CesionRPETC.objects.create(
            id_cesion='filter-1', estado_cesion='Cesion Vigente',
            vendedor_rut='88888888', vendedor_dv='8', deudor_rut='77575300', deudor_dv='5',
            tipo_doc='33', folio_doc='0010', cedente_rut='76376142', cedente_dv='2',
            cesionario_rut='76682670', cesionario_dv='0',
            fecha_cesion=datetime(2026, 8, 19, 10, tzinfo=timezone.utc), monto_cesion=Decimal('100'),
        )
        second = CesionRPETC.objects.create(
            id_cesion='filter-2', estado_cesion='Revocada',
            vendedor_rut='76376142', vendedor_dv='2', deudor_rut='77575300', deudor_dv='5',
            tipo_doc='34', folio_doc='0020', cedente_rut='99999999', cedente_dv='9',
            cesionario_rut='76682670', cesionario_dv='0',
            fecha_cesion=datetime(2026, 8, 18, 10, tzinfo=timezone.utc), monto_cesion=Decimal('200'),
        )
        for cesion in (first, second):
            TareaCesionRPETC.objects.create(tarea=tarea, cesion=cesion, rol_consulta='DEUDOR')
        return first, second

    def test_filtros_rut_tipo_folio_estado_y_fecha_reducen_agrupacion(self):
        first, second = self._crear_cesiones_para_filtros()
        response = self.client.get(reverse('gestion_dte:cesiones'), {
            'rut_proveedor': '76.376.142-2',
            'tipo_doc': '34',
            'folio': '0020',
            'estado': 'Revocada',
            'fecha_desde': '2026-08-18',
            'fecha_hasta': '2026-08-18',
        })
        self.assertEqual(response.context['total_cesiones_rpetc'], 1)
        self.assertEqual(response.context['monto_total_cedido'], Decimal('200'))
        self.assertEqual(response.context['cesiones_por_fecha'][0]['cantidad'], 1)
        self.assertEqual(response.context['cesiones_detalle'], [])

    def test_rut_proveedor_considera_vendedor_distinto_de_cedente(self):
        first, _ = self._crear_cesiones_para_filtros()
        response = self.client.get(reverse('gestion_dte:cesiones'), {'rut_proveedor': '88888888'})
        self.assertEqual(response.context['total_cesiones_rpetc'], 1)
        self.assertEqual(response.context['cesiones_detalle'], [])

    def test_click_fecha_conserva_filtros_en_url(self):
        self._crear_cesiones_para_filtros()
        response = self.client.get(reverse('gestion_dte:cesiones'), {
            'rut_proveedor': '76376142', 'tipo_doc': '34',
        })
        self.assertContains(response, 'id="cesionesRpetcTable"')

    def test_limpiar_filtros_vuelve_a_url_sin_query(self):
        self._crear_cesiones_para_filtros()
        response = self.client.get(reverse('gestion_dte:cesiones'), {'tipo_doc': '34'})
        self.assertContains(response, 'href="/gestiondte/cesiones/"')

    def test_filtro_sin_resultados_muestra_mensaje(self):
        self._crear_cesiones_para_filtros()
        response = self.client.get(reverse('gestion_dte:cesiones'), {'folio': 'inexistente'})
        self.assertEqual(response.context['total_cesiones_rpetc'], 0)
        self.assertContains(response, 'id="cesionesRpetcTable"')

    @patch('gestiondte.services.rpetc_contabilidad.obtener_estados_contables_cesiones')
    def test_detalle_visible_consulta_contabilidad_en_un_batch(self, accounting):
        tarea = TareaRPETC.objects.create(
            empresa=self.empresa, id_tarea='task-accounting', tipo_consulta='DEUDOR',
            rut_consultado='77575300', dv_consultado='5', fecha_desde=date(2026, 7, 1),
            fecha_hasta=date(2026, 7, 31), formato='TXT', estado='TERMINADO',
        )
        cesion = CesionRPETC.objects.create(
            id_cesion='accounting-1', estado_cesion='Cesion Vigente',
            deudor_rut='77575300', deudor_dv='5', tipo_doc='33', folio_doc='2587',
            cedente_rut='76376142', cedente_dv='8', cesionario_rut='76682670', cesionario_dv='9',
            fecha_cesion=datetime(2026, 8, 19, 10, tzinfo=timezone.utc), monto_cesion=Decimal('100'),
        )
        TareaCesionRPETC.objects.create(tarea=tarea, cesion=cesion, rol_consulta='DEUDOR')
        accounting.return_value = {cesion.pk: {
            'contabilizacion': {'estado': 'CONTABILIZADA', 'cantidad_movimientos': 1, 'movimientos': []},
            'pago': {'estado': 'PAGADA', 'cantidad_movimientos': 1, 'movimientos': []},
        }}
        response = self.client.get(reverse('gestion_dte:cesiones'), {'fecha_cesion': '2026-08-19'})
        self.assertEqual(response.status_code, 200)
        accounting.assert_not_called()
        self.assertEqual(response.context['cesiones_detalle'], [])

    @patch('gestiondte.services.rpetc_contabilidad.obtener_detalle_contable_cesion')
    def test_endpoint_detalle_contable_respeta_empresa_activa(self, detail):
        tarea = TareaRPETC.objects.create(
            empresa=self.empresa, id_tarea='task-detail', tipo_consulta='DEUDOR',
            rut_consultado='77575300', dv_consultado='5', fecha_desde=date(2026, 7, 1),
            fecha_hasta=date(2026, 7, 31), formato='TXT', estado='TERMINADO',
        )
        cesion = CesionRPETC.objects.create(
            id_cesion='detail-1', estado_cesion='Cesion Vigente', deudor_rut='77575300',
            deudor_dv='5', tipo_doc='33', folio_doc='2587', fecha_cesion=datetime(2026, 8, 19, tzinfo=timezone.utc),
        )
        TareaCesionRPETC.objects.create(tarea=tarea, cesion=cesion, rol_consulta='DEUDOR')
        detail.return_value = {
            'contabilizacion': {'movimientos': [{'rutctacte': '0763761428', 'monto': Decimal('100')}]},
            'pago': {'movimientos': []},
        }
        response = self.client.get(reverse('gestion_dte:detalle_contable_cesion', args=[cesion.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['factura']['folio'], '2587')
        self.assertNotIn('schema', response.json())
        detail.assert_called_once_with('09', cesion)

        other_tarea = TareaRPETC.objects.create(
            empresa=self.otra_empresa, id_tarea='task-other-detail', tipo_consulta='DEUDOR',
            rut_consultado='1', dv_consultado='9', fecha_desde=date(2026, 7, 1),
            fecha_hasta=date(2026, 7, 31), formato='TXT', estado='TERMINADO',
        )
        other_cesion = CesionRPETC.objects.create(
            id_cesion='other-detail', estado_cesion='Cesion Vigente', deudor_rut='1', deudor_dv='9',
            tipo_doc='33', folio_doc='1',
        )
        TareaCesionRPETC.objects.create(tarea=other_tarea, cesion=other_cesion, rol_consulta='DEUDOR')
        blocked = self.client.get(reverse('gestion_dte:detalle_contable_cesion', args=[other_cesion.pk]))
        self.assertEqual(blocked.status_code, 404)

    @patch('gestiondte.services.rpetc_contabilidad.obtener_estados_contables_cesiones')
    def test_server_side_endpoint_pagina_antes_de_contabilidad(self, accounting):
        tarea = TareaRPETC.objects.create(
            empresa=self.empresa, id_tarea='task-server-side', tipo_consulta='DEUDOR',
            rut_consultado='77575300', dv_consultado='5', fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 8, 20), formato='TXT', estado='TERMINADO',
        )
        for index in range(30):
            cesion = CesionRPETC.objects.create(
                id_cesion=f'server-{index}', estado_cesion='Vigente',
                cedente_rut='11111111', cedente_dv='1', cedente_razon_social='Proveedor',
                cesionario_rut='22222222', cesionario_dv='2', deudor_rut='77575300', deudor_dv='5',
                tipo_doc='33', folio_doc=str(index),
                fecha_cesion=datetime(2026, 8, 20, 10, index % 60, tzinfo=timezone.utc),
                monto_cesion=Decimal('100'),
            )
            TareaCesionRPETC.objects.create(tarea=tarea, cesion=cesion, rol_consulta='DEUDOR')
        accounting.return_value = {
            cesion.pk: {
                'contabilizacion': {'estado': 'NO_CONTABILIZADA', 'movimientos': []},
                'pago': {'estado': 'NO_PAGADA', 'movimientos': []},
            }
            for cesion in CesionRPETC.objects.all()
        }
        response = self.client.get(reverse('gestion_dte:cesiones_data'), {
            'draw': '4', 'start': '0', 'length': '25',
            'fecha_desde': '2026-01-01', 'fecha_hasta': '2026-08-20',
            'order[0][column]': '0', 'order[0][dir]': 'desc',
        })
        payload = response.json()
        self.assertEqual(payload['draw'], 4)
        self.assertEqual(payload['recordsTotal'], 30)
        self.assertEqual(payload['recordsFiltered'], 30)
        self.assertEqual(len(payload['data']), 25)
        accounting.assert_called_once()
        self.assertEqual(len(accounting.call_args.args[1]), 25)

    def test_server_side_busqueda_y_pagina_siguiente(self):
        tarea = TareaRPETC.objects.create(
            empresa=self.empresa, id_tarea='task-search', tipo_consulta='DEUDOR',
            rut_consultado='77575300', dv_consultado='5', fecha_desde=date(2026, 8, 1),
            fecha_hasta=date(2026, 8, 20), formato='TXT', estado='TERMINADO',
        )
        for index in range(3):
            cesion = CesionRPETC.objects.create(
                id_cesion=f'search-{index}', estado_cesion='Vigente',
                cedente_rut='33333333', cedente_dv='3', cedente_razon_social='Proveedor Buscado',
                deudor_rut='77575300', deudor_dv='5', tipo_doc='33', folio_doc=f'F-{index}',
                fecha_cesion=datetime(2026, 8, 20, tzinfo=timezone.utc), monto_cesion=Decimal('50'),
            )
            TareaCesionRPETC.objects.create(tarea=tarea, cesion=cesion, rol_consulta='DEUDOR')
        with patch('gestiondte.services.rpetc_contabilidad.obtener_estados_contables_cesiones', return_value={}):
            response = self.client.get(reverse('gestion_dte:cesiones_data'), {
                'draw': '1', 'start': '1', 'length': '1', 'search[value]': 'Buscado',
            })
        payload = response.json()
        self.assertEqual(payload['recordsFiltered'], 3)
        self.assertEqual(len(payload['data']), 1)
