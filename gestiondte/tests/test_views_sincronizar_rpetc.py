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
        response = self.client.get(reverse('gestion_dte:cesiones'), {'fecha_cesion': '2026-08-19'})
        self.assertEqual(len(response.context['cesiones_detalle']), 1)
        self.assertEqual(response.context['cesiones_detalle'][0].folio_doc, 'one')

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
        self.assertEqual(response.context['cesiones_detalle'][0].id_cesion, second.id_cesion)
        self.assertNotIn(first.id_cesion, [item.id_cesion for item in response.context['cesiones_detalle']])

    def test_rut_proveedor_considera_vendedor_distinto_de_cedente(self):
        first, _ = self._crear_cesiones_para_filtros()
        response = self.client.get(reverse('gestion_dte:cesiones'), {'rut_proveedor': '88888888'})
        self.assertEqual(response.context['total_cesiones_rpetc'], 1)
        self.assertEqual(response.context['cesiones_detalle'][0].id_cesion, first.id_cesion)

    def test_click_fecha_conserva_filtros_en_url(self):
        self._crear_cesiones_para_filtros()
        response = self.client.get(reverse('gestion_dte:cesiones'), {
            'rut_proveedor': '76376142', 'tipo_doc': '34',
        })
        self.assertContains(response, 'rut_proveedor=76376142&amp;tipo_doc=34&amp;fecha_cesion=2026-08-18')

    def test_limpiar_filtros_vuelve_a_url_sin_query(self):
        self._crear_cesiones_para_filtros()
        response = self.client.get(reverse('gestion_dte:cesiones'), {'tipo_doc': '34'})
        self.assertContains(response, 'href="/gestiondte/cesiones/"')

    def test_filtro_sin_resultados_muestra_mensaje(self):
        self._crear_cesiones_para_filtros()
        response = self.client.get(reverse('gestion_dte:cesiones'), {'folio': 'inexistente'})
        self.assertEqual(response.context['total_cesiones_rpetc'], 0)
        self.assertContains(response, 'No se encontraron documentos cedidos con los filtros seleccionados.')
