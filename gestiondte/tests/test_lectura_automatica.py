from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.test import TestCase, SimpleTestCase
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa
from gestiondte.models import (
    CertificadoSII,
    LecturaAutomaticaConfig,
    LecturaAutomaticaEjecucion,
)
from gestiondte.services.lectura_automatica import (
    LecturaAutomaticaError,
    empresas_elegibles,
    ejecutar_lote,
    periodos_mensuales_rpetc,
    rango_mensual_rpetc,
    rango_automatico,
    validar_rango_lectura,
)
from auditoria.models import AuditoriaGestionDTEEvent, UserPresence
from access_control.models import Permiso, Vista


class LecturaAutomaticaAuditViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='lectura-auditor', password='pass')
        self.empresa = Empresa.objects.create(codigo='09', descripcion='Empresa')
        vista, _ = Vista.objects.get_or_create(nombre='Gestión DTE - Lectura Automática de Cesiones')
        Permiso.objects.create(usuario=self.user, empresa=self.empresa, vista=vista, modificar=True, ingresar=True)
        self.assertTrue(Permiso.objects.filter(
            usuario=self.user,
            empresa=self.empresa,
            vista__nombre='Gestión DTE - Lectura Automática de Cesiones',
            modificar=True,
        ).exists())
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()
        self.assertEqual(self.client.session.get('empresa_id'), self.empresa.id)

    @patch('gestiondte.services.lectura_automatica.ejecutar_lote')
    def test_save_registra_update_sin_alterar_presence(self, ejecutar_lote_mock):
        presence = UserPresence.objects.create(
            user=self.user,
            empresa_id=self.empresa.id,
            app_label='gestiondte',
            vista_nombre='Cesiones',
            path='/gestiondte/lectura-automatica-cesiones/',
        )

        response = self.client.post(
            reverse('gestion_dte:ejecutar_lectura_automatica_cesiones'),
            {'action': 'save', 'intervalo_minutos': '30', 'habilitado': 'on'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ejecutar_lote_mock.called)
        event = AuditoriaGestionDTEEvent.objects.get(action='UPDATE')
        self.assertEqual(event.object_type, 'configuracion_lectura_cesiones')
        self.assertEqual(event.after['intervalo_minutos'], 30)
        self.assertEqual(UserPresence.objects.get(pk=presence.pk).path, presence.path)

    @patch('gestiondte.services.lectura_automatica.ejecutar_lote')
    def test_execution_registra_execute(self, ejecutar_lote_mock):
        ejecutar_lote_mock.return_value = {
            'bloqueado': False,
            'ejecuciones': [],
            'lote_id': 'lote-test',
        }

        response = self.client.post(
            reverse('gestion_dte:ejecutar_lectura_automatica_cesiones'),
            {
                'intervalo_minutos': '60',
                'habilitado': '',
                'fecha_desde': '2026-08-01',
                'fecha_hasta': '2026-08-20',
            },
        )

        self.assertEqual(response.status_code, 302)
        event = AuditoriaGestionDTEEvent.objects.get(action='EXECUTE')
        self.assertEqual(event.object_type, 'lectura_cesiones')
        self.assertEqual(event.meta['empresas_procesadas'], 0)


class RangoLecturaAutomaticaTest(SimpleTestCase):
    def test_rango_mensual_usa_fecha_sistema_y_resuelve_mes_completo(self):
        self.assertEqual(rango_mensual_rpetc(date(2025, 12, 31), 3), (date(2025, 3, 1), date(2025, 3, 31)))
        self.assertEqual(rango_mensual_rpetc(date(2026, 8, 15), 3), (date(2026, 3, 1), date(2026, 3, 31)))
        self.assertEqual(rango_mensual_rpetc(date(2026, 8, 15), 8), (date(2026, 8, 1), date(2026, 8, 15)))
        self.assertEqual(rango_mensual_rpetc(date(2024, 12, 31), 2), (date(2024, 2, 1), date(2024, 2, 29)))

    def test_rango_mensual_rechaza_mes_futuro(self):
        with self.assertRaises(LecturaAutomaticaError):
            rango_mensual_rpetc(date(2026, 8, 15), 9)

    def test_periodos_mensuales_marca_futuros_deshabilitados(self):
        periodos = periodos_mensuales_rpetc(date(2026, 8, 15))
        self.assertEqual([periodo['mes'] for periodo in periodos if periodo['habilitado']], list(range(1, 9)))
        self.assertEqual([periodo['mes'] for periodo in periodos if not periodo['habilitado']], list(range(9, 13)))

    def test_rechaza_rango_mayor_a_30_dias(self):
        with self.assertRaises(LecturaAutomaticaError):
            validar_rango_lectura(date(2026, 8, 1), date(2026, 8, 31), date(2026, 8, 31))

    def test_rechaza_fecha_futura_y_desde_posterior(self):
        with self.assertRaises(LecturaAutomaticaError):
            validar_rango_lectura(date(2026, 8, 2), date(2026, 8, 1), date(2026, 8, 31))
        with self.assertRaises(LecturaAutomaticaError):
            validar_rango_lectura(date(2026, 8, 1), date(2026, 9, 1), date(2026, 8, 31))

    def test_rango_automatico_avanza_por_mes_y_limita_30_dias(self):
        self.assertEqual(rango_automatico(date(2026, 8, 22)), (date(2026, 8, 1), date(2026, 8, 22)))
        self.assertEqual(rango_automatico(date(2026, 8, 31)), (date(2026, 8, 2), date(2026, 8, 31)))
        self.assertEqual(rango_automatico(date(2026, 9, 1)), (date(2026, 9, 1), date(2026, 9, 1)))


class EmpresasElegiblesTest(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.empresa_vigente = Empresa.objects.create(codigo='09', descripcion='Vigente')
        self.empresa_vencida = Empresa.objects.create(codigo='10', descripcion='Vencida')
        self.empresa_inactiva = Empresa.objects.create(codigo='11', descripcion='Inactiva')
        self.empresa_desconocida = Empresa.objects.create(codigo='12', descripcion='Desconocida')
        CertificadoSII.objects.create(
            empresa_codigo='09', archivo='vigente.pfx', activo=True,
            valido_hasta=self.now + timedelta(days=10),
        )
        CertificadoSII.objects.create(
            empresa_codigo='10', archivo='vencido.pfx', activo=True,
            valido_hasta=self.now - timedelta(days=1),
        )
        CertificadoSII.objects.create(
            empresa_codigo='11', archivo='inactivo.pfx', activo=False,
            valido_hasta=self.now + timedelta(days=10),
        )
        CertificadoSII.objects.create(
            empresa_codigo='12', archivo='desconocido.pfx', activo=True,
            valido_hasta=None,
        )

    def test_solo_incluye_certificado_activo_vigente_con_archivo(self):
        with patch('django.core.files.storage.FileSystemStorage.exists', return_value=True):
            result = empresas_elegibles()
        self.assertEqual([empresa.codigo for empresa, _certificado in result], ['09'])


class EjecucionLoteTest(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(codigo='09', descripcion='A')
        self.empresa_b = Empresa.objects.create(codigo='10', descripcion='B')
        expires = timezone.now() + timedelta(days=10)
        CertificadoSII.objects.create(empresa_codigo='09', archivo='a.pfx', activo=True, valido_hasta=expires)
        CertificadoSII.objects.create(empresa_codigo='10', archivo='b.pfx', activo=True, valido_hasta=expires)

    @patch('gestiondte.services.lectura_automatica.get_maestroempresa_by_codigo')
    @patch('gestiondte.services.lectura_automatica.sincronizar_empresa_rpetc')
    def test_procesa_empresas_secuencialmente_y_continua_ante_error(self, sync, maestro):
        maestro.return_value = {'rut': '77575300-5'}
        sync.side_effect = [RuntimeError('fallo externo'), {'stats': {'registros_recibidos': 2}, 'tarea': None}]
        with patch('django.core.files.storage.FileSystemStorage.exists', return_value=True):
            result = ejecutar_lote(date(2026, 8, 1), date(2026, 8, 20), tipo_ejecucion='MANUAL', ahora=timezone.now())
        self.assertFalse(result['bloqueado'])
        self.assertEqual([row.estado for row in result['ejecuciones']], ['ERROR', 'ACTUALIZADO'])
        self.assertEqual(sync.call_count, 2)
        self.assertEqual(result['ejecuciones'][0].mensaje_error, 'No fue posible completar la lectura automática para esta empresa.')

    def test_ejecucion_global_activa_bloquea_nuevo_lote(self):
        LecturaAutomaticaEjecucion.objects.create(
            lote_id='11111111-1111-1111-1111-111111111111', empresa=self.empresa_a,
            tipo_ejecucion='MANUAL', fecha_desde=date(2026, 8, 1), fecha_hasta=date(2026, 8, 20),
            estado='EN_PROCESO',
        )
        result = ejecutar_lote(date(2026, 8, 1), date(2026, 8, 20), tipo_ejecucion='MANUAL', ahora=timezone.now())
        self.assertTrue(result['bloqueado'])


class ConfigCommandTest(TestCase):
    def test_command_sale_limpiamente_deshabilitado(self):
        LecturaAutomaticaConfig.objects.create(pk=1, habilitado=False)
        call_command('ejecutar_lectura_automatica_cesiones')

    def test_configuracion_tiene_intervalos_permitidos(self):
        config = LecturaAutomaticaConfig.objects.create(pk=1, intervalo_minutos=15)
        config.full_clean()
        self.assertEqual(config.intervalo_minutos, 15)
        with self.assertRaises(ValidationError):
            LecturaAutomaticaConfig(intervalo_minutos=20).full_clean()
