from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from gestiondte.models import (
    CesionRPETC,
    RevisionCesionRPETC,
    RevisionCesionComentario,
    TareaCesionRPETC,
    TareaRPETC,
)


class RevisionCesionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='revision-user', password='pass')
        self.user_b = User.objects.create_user(username='revision-user-b', password='pass')
        self.other_user = User.objects.create_user(username='other-user', password='pass')
        self.empresa = Empresa.objects.create(codigo='09', descripcion='Empresa A')
        self.otra_empresa = Empresa.objects.create(codigo='10', descripcion='Empresa B')
        self.vista, _ = Vista.objects.get_or_create(nombre='Gestión DTE - Control de Cesiones')
        Permiso.objects.create(
            usuario=self.user, empresa=self.empresa, vista=self.vista,
            ingresar=True, crear=True, modificar=True, eliminar=True,
        )
        Permiso.objects.create(
            usuario=self.other_user, empresa=self.otra_empresa, vista=self.vista,
            ingresar=True, crear=True, modificar=True, eliminar=True,
        )
        Permiso.objects.create(
            usuario=self.user_b, empresa=self.empresa, vista=self.vista,
            ingresar=True, crear=True, modificar=True, eliminar=True,
        )
        self.client.force_login(self.user)
        self._set_empresa(self.empresa)
        tarea = TareaRPETC.objects.create(
            empresa=self.empresa, id_tarea='revision-task', tipo_consulta='DEUDOR',
            rut_consultado='1', dv_consultado='9', fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 1, 31), formato='TXT', estado='TERMINADO',
        )
        self.cesion = CesionRPETC.objects.create(
            id_cesion='revision-cesion', estado_cesion='Vigente', deudor_rut='1',
            deudor_dv='9', tipo_doc='33', folio_doc='2383', cedente_rut='76376142',
            cedente_dv='8', monto_total=Decimal('3122579'), monto_cesion=Decimal('3122579'),
            fecha_cesion=timezone.now(),
        )
        TareaCesionRPETC.objects.create(tarea=tarea, cesion=self.cesion, rol_consulta='DEUDOR')

    def _set_empresa(self, empresa):
        session = self.client.session
        session['empresa_id'] = empresa.id
        session.save()

    def test_crud_revision_conserva_creador_y_actualiza_metadatos(self):
        url = reverse('gestion_dte:revision_cesion', args=[self.cesion.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['revisado'])
        self.assertTrue(response.json()['permisos']['crear'])

        create = self.client.post(reverse('gestion_dte:crear_comentario_revision', args=[self.cesion.pk]), {'comentario': '  Revisado  '})
        self.assertEqual(create.status_code, 201)
        revision = RevisionCesionRPETC.objects.get(empresa=self.empresa, cesion=self.cesion)
        self.assertEqual(revision.glosa, 'Revisado')
        comentario = RevisionCesionComentario.objects.get(revision=revision)
        self.assertEqual(comentario.comentario, 'Revisado')
        self.assertEqual(comentario.creado_por, self.user)
        creator = comentario.creado_por_id

        detail = self.client.get(url).json()
        self.assertTrue(detail['revisado'])
        self.assertEqual(detail['comentarios'][0]['glosa'], 'Revisado')
        self.assertIsNotNone(detail['comentarios'][0]['creado_en'])

        edit = self.client.post(reverse('gestion_dte:editar_comentario_revision', args=[self.cesion.pk, comentario.pk]), {'comentario': 'Revisión actualizada'})
        self.assertEqual(edit.status_code, 200)
        revision.refresh_from_db()
        comentario.refresh_from_db()
        self.assertEqual(comentario.comentario, 'Revisión actualizada')
        self.assertEqual(comentario.creado_por_id, creator)

        delete = self.client.post(reverse('gestion_dte:eliminar_comentario_revision', args=[self.cesion.pk, comentario.pk]))
        self.assertEqual(delete.status_code, 200)
        self.assertFalse(RevisionCesionRPETC.objects.filter(pk=revision.pk).exists())
        self.assertFalse(delete.json()['revisado'])

    def test_glosa_obligatoria_y_unicidad_empresa_cesion(self):
        url = reverse('gestion_dte:crear_comentario_revision', args=[self.cesion.pk])
        self.assertEqual(self.client.post(url, {'comentario': '   '}).status_code, 400)
        self.assertEqual(self.client.post(url, {'comentario': 'Primera'}).status_code, 201)
        self.assertEqual(self.client.post(url, {'comentario': 'Segunda'}).status_code, 201)
        self.assertEqual(RevisionCesionComentario.objects.filter(revision__empresa=self.empresa, revision__cesion=self.cesion).count(), 2)

    def test_historial_respeta_autoria_y_permite_agregar_a_otro_usuario(self):
        create_a = self.client.post(reverse('gestion_dte:crear_comentario_revision', args=[self.cesion.pk]), {'comentario': 'Comentario A'})
        self.assertEqual(create_a.status_code, 201)
        comentario_a = RevisionCesionComentario.objects.get()
        self.client.force_login(self.user_b)
        self._set_empresa(self.empresa)
        history = self.client.get(reverse('gestion_dte:revision_cesion', args=[self.cesion.pk])).json()
        self.assertEqual([item['autor'] for item in history['comentarios']], ['revision-user'])
        self.assertFalse(history['comentarios'][0]['puede_editar'])
        self.assertFalse(history['comentarios'][0]['puede_eliminar'])
        create_b = self.client.post(reverse('gestion_dte:crear_comentario_revision', args=[self.cesion.pk]), {'comentario': 'Comentario B'})
        self.assertEqual(create_b.status_code, 201)
        self.assertEqual(RevisionCesionComentario.objects.count(), 2)
        self.assertEqual(self.client.post(reverse('gestion_dte:editar_comentario_revision', args=[self.cesion.pk, comentario_a.pk]), {'comentario': 'Manipulado'}).status_code, 403)
        self.assertEqual(self.client.post(reverse('gestion_dte:eliminar_comentario_revision', args=[self.cesion.pk, comentario_a.pk])).status_code, 403)

    def test_autor_puede_editar_y_eliminar_su_comentario(self):
        self.client.post(reverse('gestion_dte:crear_comentario_revision', args=[self.cesion.pk]), {'comentario': 'Original'})
        comentario = RevisionCesionComentario.objects.get()
        edit = self.client.post(reverse('gestion_dte:editar_comentario_revision', args=[self.cesion.pk, comentario.pk]), {'comentario': 'Editado'})
        self.assertEqual(edit.status_code, 200)
        comentario.refresh_from_db()
        self.assertEqual(comentario.comentario, 'Editado')
        self.assertEqual(self.client.post(reverse('gestion_dte:eliminar_comentario_revision', args=[self.cesion.pk, comentario.pk])).status_code, 200)
        self.assertFalse(RevisionCesionRPETC.objects.filter(pk=comentario.revision_id).exists())

    def test_permisos_crear_modificar_eliminar_se_aplican(self):
        Permiso.objects.filter(usuario=self.user, empresa=self.empresa).update(crear=False, modificar=False, eliminar=False)
        self.assertEqual(self.client.post(reverse('gestion_dte:crear_comentario_revision', args=[self.cesion.pk]), {'comentario': 'No'}).status_code, 403)
        revision = RevisionCesionRPETC.objects.create(empresa=self.empresa, cesion=self.cesion, glosa='Existente', creado_por=self.user)
        self.assertEqual(self.client.post(reverse('gestion_dte:editar_comentario_revision', args=[self.cesion.pk, 1]), {'comentario': 'No'}).status_code, 403)
        self.assertEqual(self.client.post(reverse('gestion_dte:eliminar_comentario_revision', args=[self.cesion.pk, 1])).status_code, 403)
        self.assertTrue(RevisionCesionRPETC.objects.filter(pk=revision.pk).exists())

    def test_otra_empresa_no_puede_operar_sobre_cesion(self):
        RevisionCesionRPETC.objects.create(empresa=self.empresa, cesion=self.cesion, glosa='Privada', creado_por=self.user)
        self.client.force_login(self.other_user)
        self._set_empresa(self.otra_empresa)
        self.assertEqual(self.client.get(reverse('gestion_dte:revision_cesion', args=[self.cesion.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('gestion_dte:editar_comentario_revision', args=[self.cesion.pk, 1]), {'comentario': 'No'}).status_code, 404)

    @patch('gestiondte.services.rpetc_contabilidad.obtener_estados_contables_cesiones', return_value={})
    def test_datatables_devuelve_revision_sin_n_plus_one(self, accounting):
        revision = RevisionCesionRPETC.objects.create(empresa=self.empresa, cesion=self.cesion, glosa='Revisada', creado_por=self.user)
        RevisionCesionComentario.objects.create(revision=revision, comentario='Revisada', creado_por=self.user)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('gestion_dte:cesiones_data'), {'draw': '1', 'start': '0', 'length': '25'})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('recordsTotal', payload)
        self.assertTrue(payload['data'][0]['revision']['revisado'])
        accounting.assert_called_once()
        revision_queries = [query for query in queries if 'gestiondte_revisioncesionrpetc' in query['sql']]
        self.assertLessEqual(len(revision_queries), 1)

    def test_datatables_sin_revisar_filtra_por_empresa_activa_y_resumen(self):
        revision = RevisionCesionRPETC.objects.create(
            empresa=self.empresa, cesion=self.cesion, glosa='Revisada', creado_por=self.user,
        )
        RevisionCesionComentario.objects.create(revision=revision, comentario='Revisada', creado_por=self.user)
        with patch('gestiondte.services.rpetc_contabilidad.obtener_estados_contables_cesiones', return_value={}):
            response = self.client.get(reverse('gestion_dte:cesiones_data'), {
                'draw': '1', 'start': '0', 'length': '25', 'sin_revisar': '1',
            })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['recordsTotal'], 1)
        self.assertEqual(payload['recordsFiltered'], 0)
        self.assertEqual(payload['summary']['cantidad'], 0)
        self.assertTrue(RevisionCesionRPETC.objects.filter(pk=revision.pk).exists())

    def test_triple_filter_es_interseccion_f_p_y_r(self):
        cesiones = {'A': self.cesion}
        tarea = self.cesion.tareas.first().tarea
        for label in ('B', 'C', 'D'):
            cesiones[label] = CesionRPETC.objects.create(
                id_cesion=f'revision-{label}', estado_cesion='Vigente', deudor_rut='1',
                deudor_dv='9', tipo_doc='33', folio_doc=f'23{label}', cedente_rut='76376142',
                cedente_dv='8', monto_total=Decimal('100'), monto_cesion=Decimal('100'),
                fecha_cesion=timezone.now(),
            )
            TareaCesionRPETC.objects.create(tarea=tarea, cesion=cesiones[label], rol_consulta='DEUDOR')
        revision_b = RevisionCesionRPETC.objects.create(empresa=self.empresa, cesion=cesiones['B'], glosa='Ya revisada', creado_por=self.user)
        RevisionCesionComentario.objects.create(revision=revision_b, comentario='Ya revisada', creado_por=self.user)
        states = {
            cesiones['A'].pk: {'pagada_factoring': {'estado': 'NO_PAGADA'}, 'pagada_proveedor': {'estado': 'NO_PAGADA'}},
            cesiones['B'].pk: {'pagada_factoring': {'estado': 'NO_PAGADA'}, 'pagada_proveedor': {'estado': 'NO_PAGADA'}},
            cesiones['C'].pk: {'pagada_factoring': {'estado': 'PAGADA_FACTORING'}, 'pagada_proveedor': {'estado': 'NO_PAGADA'}},
            cesiones['D'].pk: {'pagada_factoring': {'estado': 'NO_PAGADA'}, 'pagada_proveedor': {'estado': 'PAGADA_PROVEEDOR'}},
        }
        with patch('gestiondte.services.rpetc_contabilidad.obtener_estados_contables_cesiones', return_value=states):
            response = self.client.get(reverse('gestion_dte:cesiones_data'), {
                'draw': '1', 'start': '0', 'length': '25',
                'sin_pago_factoring': '1', 'sin_pago_proveedor': '1', 'sin_revisar': '1',
            })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['recordsTotal'], 4)
        self.assertEqual(payload['recordsFiltered'], 1)
        self.assertEqual([row['id'] for row in payload['data']], [cesiones['A'].pk])

        expected = {
            'all': (4, {}),
            'factoring': (3, {'sin_pago_factoring': '1'}),
            'proveedor': (3, {'sin_pago_proveedor': '1'}),
            'review': (3, {'sin_revisar': '1'}),
            'factoring_proveedor': (2, {'sin_pago_factoring': '1', 'sin_pago_proveedor': '1'}),
            'factoring_review': (2, {'sin_pago_factoring': '1', 'sin_revisar': '1'}),
            'proveedor_review': (2, {'sin_pago_proveedor': '1', 'sin_revisar': '1'}),
            'triple': (1, {'sin_pago_factoring': '1', 'sin_pago_proveedor': '1', 'sin_revisar': '1'}),
        }
        for label, (count, params) in expected.items():
            with self.subTest(label=label), patch(
                'gestiondte.services.rpetc_contabilidad.obtener_estados_contables_cesiones',
                return_value=states,
            ):
                response = self.client.get(reverse('gestion_dte:cesiones_data'), {
                    'draw': '1', 'start': '0', 'length': '25', **params,
                })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['recordsTotal'], 4)
            self.assertEqual(response.json()['recordsFiltered'], count)
            self.assertEqual(response.json()['summary']['cantidad'], count)

    def test_sin_revisar_respeta_revision_de_otra_empresa(self):
        revision = RevisionCesionRPETC.objects.create(empresa=self.empresa, cesion=self.cesion, glosa='Empresa A', creado_por=self.user)
        RevisionCesionComentario.objects.create(revision=revision, comentario='Empresa A', creado_por=self.user)
        other_task = TareaRPETC.objects.create(
            empresa=self.otra_empresa, id_tarea='revision-other-task', tipo_consulta='DEUDOR',
            rut_consultado='1', dv_consultado='9', fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 1, 31), formato='TXT', estado='TERMINADO',
        )
        TareaCesionRPETC.objects.create(tarea=other_task, cesion=self.cesion, rol_consulta='DEUDOR')
        self.client.force_login(self.other_user)
        self._set_empresa(self.otra_empresa)
        with patch('gestiondte.services.rpetc_contabilidad.obtener_estados_contables_cesiones', return_value={}):
            response = self.client.get(reverse('gestion_dte:cesiones_data'), {'sin_revisar': '1', 'length': '25'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.json()['data']], [self.cesion.pk])

    def test_template_incluye_columna_modal_y_delegacion(self):
        response = self.client.get(reverse('gestion_dte:cesiones'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<th>Revisado</th>')
        self.assertContains(response, 'name="sin_revisar"')
        self.assertContains(response, 'id="sin_revisar"')
        self.assertContains(response, 'id="revisionCesionModal"')
        self.assertContains(response, 'id="revisionCesionComentario"')
        self.assertContains(response, 'Revisado por:')
        self.assertContains(response, 'Última modificación:')
        self.assertContains(response, "$(document).on('click','.btn-revision-cesion'")
        self.assertContains(response, 'ajax.reload(null,false)')
        self.assertContains(response, 'input[type="checkbox"]')
