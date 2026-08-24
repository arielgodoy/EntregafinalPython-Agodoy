from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from gestiondte.models import CesionRPETC, TareaCesionRPETC, TareaRPETC


class DashboardDteTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='dashboard-user', password='pass')
        self.empresa = Empresa.objects.create(codigo='09', descripcion='Empresa activa')
        self.otra_empresa = Empresa.objects.create(codigo='10', descripcion='Otra empresa')
        vista, _ = Vista.objects.get_or_create(nombre='Gestión DTE - Dashboard DTE-SII-RPETC')
        Permiso.objects.create(usuario=self.user, empresa=self.empresa, vista=vista, ingresar=True)
        self.client = Client()
        self.client.login(username='dashboard-user', password='pass')
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()
        self.tarea = TareaRPETC.objects.create(
            empresa=self.empresa, id_tarea='dashboard-task', tipo_consulta='DEUDOR',
            rut_consultado='77575300', dv_consultado='5', fecha_desde=timezone.localdate(),
            fecha_hasta=timezone.localdate(), formato='TXT', estado='TERMINADO',
        )

    def crear_cesion(self, tarea=None, fecha=None, folio='1', cedente='11111111', cesionario='22222222', monto='100', estado='Vigente'):
        tarea = tarea or self.tarea
        cesion = CesionRPETC.objects.create(
            id_cesion=f'dashboard-{tarea.pk}-{folio}', estado_cesion=estado,
            deudor_rut='77575300', deudor_dv='5', tipo_doc='33', folio_doc=folio,
            cedente_rut=cedente, cedente_dv='1', cedente_razon_social=f'Cedente {cedente}',
            cesionario_rut=cesionario, cesionario_dv='2', cesionario_razon_social=f'Cesionario {cesionario}',
            fecha_cesion=fecha or timezone.now(), monto_cesion=Decimal(monto),
        )
        TareaCesionRPETC.objects.create(tarea=tarea, cesion=cesion, rol_consulta='DEUDOR')
        return cesion

    def test_anonymous_is_redirected(self):
        self.client.logout()
        response = self.client.get(reverse('gestion_dte:index'))
        self.assertEqual(response.status_code, 302)

    def test_without_permission_is_forbidden(self):
        Permiso.objects.update(ingresar=False)
        response = self.client.get(reverse('gestion_dte:index'))
        self.assertEqual(response.status_code, 403)

    def test_dashboard_uses_active_company_and_exposes_kpis(self):
        self.crear_cesion(folio='1', monto='100', estado='Vigente')
        other_task = TareaRPETC.objects.create(
            empresa=self.otra_empresa, id_tarea='dashboard-other-task', tipo_consulta='DEUDOR',
            rut_consultado='1', dv_consultado='9', fecha_desde=timezone.localdate(),
            fecha_hasta=timezone.localdate(), formato='TXT', estado='TERMINADO',
        )
        self.crear_cesion(other_task, folio='2', monto='999')
        response = self.client.get(reverse('gestion_dte:dashboard_resumen'))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['periodo'], 'mes')
        self.assertEqual(payload['kpis']['total_cesiones'], 1)
        self.assertEqual(payload['kpis']['monto_total'], 100)
        self.assertEqual(payload['kpis']['cedentes'], 1)
        self.assertEqual(payload['kpis']['cesionarios'], 1)
        self.assertEqual(payload['kpis']['monto_promedio'], 100)
        self.assertEqual(len(payload['estados_rpetc']), 1)
        self.assertEqual(len(payload['cesionarios_top']), 1)

    def test_all_supported_periods_are_accepted(self):
        for periodo in ('hoy', 'semana', 'mes', 'anio'):
            response = self.client.get(reverse('gestion_dte:dashboard_resumen'), {'periodo': periodo})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['periodo'], periodo)

    def test_invalid_period_is_rejected(self):
        response = self.client.get(reverse('gestion_dte:dashboard_resumen'), {'periodo': 'invalido'})
        self.assertEqual(response.status_code, 400)

    def test_aggregations_and_activity_use_fecha_cesion(self):
        now = timezone.now()
        self.crear_cesion(fecha=now - timedelta(hours=1), folio='1', cedente='11111111', cesionario='22222222', monto='100')
        self.crear_cesion(fecha=now - timedelta(hours=2), folio='2', cedente='33333333', cesionario='44444444', monto='300', estado='Cesion Vigente')
        response = self.client.get(reverse('gestion_dte:dashboard_resumen'), {'periodo': 'hoy'})
        payload = response.json()
        self.assertEqual(payload['kpis']['total_cesiones'], 2)
        self.assertEqual(payload['kpis']['monto_total'], 400)
        self.assertEqual(payload['kpis']['monto_promedio'], 200)
        self.assertEqual(sum(item['cantidad'] for item in payload['evolucion']), 2)
        self.assertEqual(sum(item['monto'] for item in payload['actividad']), 400)

    @patch('gestiondte.services.rpetc_contabilidad.obtener_estados_contables_cesiones')
    def test_endpoint_does_not_call_legacy_contability(self, accounting):
        self.crear_cesion()
        response = self.client.get(reverse('gestion_dte:dashboard_resumen'))
        self.assertEqual(response.status_code, 200)
        accounting.assert_not_called()
