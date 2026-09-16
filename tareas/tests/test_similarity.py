from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from access_control.models import Empresa
from organizacion.models import Departamento, Local, OrganizationalSource
from tareas.models import EvaluacionSimilitud, Tarea, Todo, UmbralSimilitudEmpresa
from tareas.services.similarity import (
    confirm_similarity,
    evaluate_task_similarity,
    get_similarity_threshold,
    set_similarity_threshold,
)


class SimilarityTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        cls.otra_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        cls.usuario = User.objects.create_user(username="similitud", password="x")
        cls.otro_usuario = User.objects.create_user(username="otro", password="x")
        cls.local = Local.objects.create(
            empresa=cls.empresa, codigo="L1", nombre="Local 1", source=OrganizationalSource.LOCAL
        )
        cls.otro_local = Local.objects.create(
            empresa=cls.empresa, codigo="L2", nombre="Local 2", source=OrganizationalSource.LOCAL
        )
        cls.departamento = Departamento.objects.create(
            empresa=cls.empresa, codigo="D1", nombre="Departamento 1", source=OrganizationalSource.LOCAL
        )
        cls.otro_departamento = Departamento.objects.create(
            empresa=cls.empresa, codigo="D2", nombre="Departamento 2", source=OrganizationalSource.LOCAL
        )

    def tarea(self, empresa=None, titulo="Problema compartido", descripcion="Descripción compartida", **kwargs):
        defaults = {
            "empresa": empresa or self.empresa,
            "creada_por": self.usuario,
            "titulo": titulo,
            "descripcion": descripcion,
            "fecha_tope": date.today(),
        }
        defaults.update(kwargs)
        return Tarea.objects.create(**defaults)

    def activar(self, tarea, estado=Tarea.Estado.ACTIVA):
        tarea.estado = estado
        tarea.fecha_publicacion = tarea.fecha_publicacion or timezone.now()
        tarea.responsable = self.usuario
        tarea.save(update_fields=["estado", "fecha_publicacion", "responsable"])
        return tarea

    def evaluar(self, tarea, candidata, threshold=Decimal("80")):
        if candidata.estado == Tarea.Estado.BORRADOR:
            self.activar(candidata)
        return evaluate_task_similarity(tarea=tarea, threshold=threshold)

    def test_misma_empresa_y_estados_permitidos(self):
        tarea = self.tarea()
        candidatas = [
            self.activar(self.tarea(titulo="Activa"), Tarea.Estado.ACTIVA),
            self.activar(self.tarea(titulo="Gestion"), Tarea.Estado.GESTION),
            self.activar(self.tarea(titulo="Pendiente"), Tarea.Estado.PENDIENTE_APROBACION_CIERRE),
            self.activar(self.tarea(titulo="Cerrada"), Tarea.Estado.CERRADA),
        ]
        resultados = evaluate_task_similarity(tarea=tarea, threshold=80)
        self.assertEqual({item.tarea_candidata_id for item in resultados}, {item.id for item in candidatas})

    def test_excluye_empresa_distinta_borrador_anulada_y_self(self):
        tarea = self.tarea()
        externa = self.tarea(empresa=self.otra_empresa)
        borrador = self.tarea(titulo="Borrador")
        anulada = self.activar(self.tarea(titulo="Anulada"))
        anulada.anulada = True
        anulada.save(update_fields=["anulada"])
        resultados = evaluate_task_similarity(tarea=tarea, threshold=80)
        ids = {item.tarea_candidata_id for item in resultados}
        self.assertNotIn(externa.id, ids)
        self.assertNotIn(borrador.id, ids)
        self.assertNotIn(anulada.id, ids)
        self.assertNotIn(tarea.id, ids)

    def test_ambitos_exigen_mismo_tipo_y_referencia(self):
        tarea = self.tarea(tipo_ambito=Tarea.Ambito.LOCAL, local=self.local)
        misma_local = self.activar(self.tarea(titulo="Misma local", tipo_ambito=Tarea.Ambito.LOCAL, local=self.local))
        distinta_local = self.activar(self.tarea(titulo="Otra local", tipo_ambito=Tarea.Ambito.LOCAL, local=self.otro_local))
        mismo_departamento = self.activar(self.tarea(titulo="Mismo departamento", tipo_ambito=Tarea.Ambito.DEPARTAMENTO, departamento=self.departamento))
        sin_ambito = self.activar(self.tarea(titulo="Histórica sin ámbito"))
        resultados = evaluate_task_similarity(tarea=tarea, threshold=80)
        ids = {item.tarea_candidata_id for item in resultados}
        self.assertIn(misma_local.id, ids)
        self.assertNotIn(distinta_local.id, ids)
        self.assertNotIn(mismo_departamento.id, ids)
        self.assertIn(sin_ambito.id, ids)

    def test_ambito_departamento_y_referencia_distinta(self):
        tarea = self.tarea(tipo_ambito=Tarea.Ambito.DEPARTAMENTO, departamento=self.departamento)
        misma = self.activar(self.tarea(tipo_ambito=Tarea.Ambito.DEPARTAMENTO, departamento=self.departamento))
        distinta = self.activar(self.tarea(tipo_ambito=Tarea.Ambito.DEPARTAMENTO, departamento=self.otro_departamento))
        ids = {item.tarea_candidata_id for item in evaluate_task_similarity(tarea=tarea, threshold=80)}
        self.assertIn(misma.id, ids)
        self.assertNotIn(distinta.id, ids)

    def test_normalizacion_ponderacion_rango_redondeo_y_umbral(self):
        tarea = self.tarea(titulo="  Falla   crítica ", descripcion="Detalle\nimportante")
        candidata = self.activar(self.tarea(titulo="falla crítica", descripcion="Detalle importante"))
        resultados = evaluate_task_similarity(tarea=tarea, threshold=Decimal("90.123"))
        evaluation = next(item for item in resultados if item.tarea_candidata_id == candidata.id)
        self.assertEqual(evaluation.porcentaje, Decimal("100.00"))
        self.assertEqual(evaluation.umbral_aplicado, Decimal("90.12"))
        self.assertTrue(evaluation.supera_umbral)
        self.assertGreaterEqual(evaluation.porcentaje, 0)
        self.assertLessEqual(evaluation.porcentaje, 100)

    def test_persistencia_unica_y_orden(self):
        tarea = self.tarea()
        primera = self.activar(self.tarea(titulo="zzzz"))
        segunda = self.activar(self.tarea(titulo="Problema compartido"))
        resultados = evaluate_task_similarity(tarea=tarea, threshold=80)
        self.assertEqual([item.tarea_candidata_id for item in resultados], [segunda.id, primera.id])
        evaluate_task_similarity(tarea=tarea, threshold=70)
        self.assertEqual(EvaluacionSimilitud.objects.filter(tarea=tarea).count(), 2)
        with self.assertRaises(IntegrityError):
            EvaluacionSimilitud.objects.create(
                tarea=tarea, tarea_candidata=primera, porcentaje=1, umbral_aplicado=1, supera_umbral=False
            )

    def test_confirmaciones_pendiente_distinta_y_misma_origen(self):
        tarea = self.tarea()
        candidata = self.activar(self.tarea(titulo="Mismo origen"))
        evaluation = self.evaluar(tarea, candidata)[0]
        confirm_similarity(evaluacion=evaluation, decision=EvaluacionSimilitud.Decision.PENDIENTE, actor=self.usuario)
        evaluation.refresh_from_db()
        self.assertIsNone(evaluation.confirmada_por_id)
        confirm_similarity(evaluacion=evaluation, decision=EvaluacionSimilitud.Decision.DISTINTO_PROBLEMA, actor=self.usuario)
        tarea.refresh_from_db()
        self.assertIsNone(tarea.tarea_origen_id)
        confirm_similarity(evaluacion=evaluation, decision=EvaluacionSimilitud.Decision.MISMO_PROBLEMA, actor=self.usuario)
        tarea.refresh_from_db()
        self.assertEqual(tarea.tarea_origen_id, candidata.id)

    def test_mismo_problema_rechaza_todo_origen_y_segundo_origen(self):
        tarea = self.tarea()
        candidata = self.activar(self.tarea(titulo="Candidata"))
        evaluation = self.evaluar(tarea, candidata)[0]
        todo = Todo.objects.create(
            empresa=self.empresa,
            correlativo="TD-000001",
            titulo="Origen TO-DO",
            creada_por=self.usuario,
        )
        tarea.todo_origen = todo
        tarea.save(update_fields=["todo_origen"])
        with self.assertRaises(ValidationError):
            confirm_similarity(evaluacion=evaluation, decision=EvaluacionSimilitud.Decision.MISMO_PROBLEMA, actor=self.usuario)

    def test_confirmar_no_cambia_estado_cerrado_ni_candidata(self):
        tarea = self.activar(self.tarea(), Tarea.Estado.CERRADA)
        candidata = self.activar(self.tarea(titulo="Candidata"), Tarea.Estado.CERRADA)
        estado = candidata.estado
        evaluation = self.evaluar(tarea, candidata)[0]
        confirm_similarity(evaluacion=evaluation, decision=EvaluacionSimilitud.Decision.MISMO_PROBLEMA, actor=self.usuario)
        tarea.refresh_from_db()
        candidata.refresh_from_db()
        self.assertEqual(tarea.estado, Tarea.Estado.CERRADA)
        self.assertEqual(candidata.estado, estado)

    def test_service_no_depende_de_umbral_ni_tarea_relacion(self):
        tarea = self.tarea()
        candidata = self.activar(self.tarea())
        resultados = evaluate_task_similarity(tarea=tarea, threshold=0)
        self.assertEqual(resultados[0].tarea_candidata_id, candidata.id)

    def test_threshold_sin_fila_usa_fallback_virtual_y_no_crea(self):
        self.assertEqual(get_similarity_threshold(self.empresa), Decimal("80.00"))
        self.assertFalse(UmbralSimilitudEmpresa.objects.filter(empresa=self.empresa).exists())

    def test_threshold_setter_crea_y_actualiza_auditoria(self):
        configuration = set_similarity_threshold(
            empresa=self.empresa,
            porcentaje=Decimal("70.00"),
            actor=self.usuario,
        )
        self.assertEqual(configuration.porcentaje, Decimal("70.00"))
        self.assertEqual(configuration.actualizado_por_id, self.usuario.id)
        first_updated_at = configuration.actualizado_at
        configuration = set_similarity_threshold(
            empresa=self.empresa,
            porcentaje=Decimal("65.00"),
            actor=self.otro_usuario,
        )
        self.assertEqual(UmbralSimilitudEmpresa.objects.filter(empresa=self.empresa).count(), 1)
        self.assertEqual(configuration.porcentaje, Decimal("65.00"))
        self.assertEqual(configuration.actualizado_por_id, self.otro_usuario.id)
        self.assertGreaterEqual(configuration.actualizado_at, first_updated_at)

    def test_threshold_es_unico_por_empresa_y_aislado(self):
        set_similarity_threshold(empresa=self.empresa, porcentaje=70, actor=self.usuario)
        self.assertEqual(get_similarity_threshold(self.empresa), Decimal("70.00"))
        self.assertEqual(get_similarity_threshold(self.otra_empresa), Decimal("80.00"))
        with self.assertRaises(IntegrityError):
            UmbralSimilitudEmpresa.objects.create(
                empresa=self.empresa,
                porcentaje=60,
                actualizado_por=self.usuario,
            )

    def test_threshold_acepta_extremos_y_rechaza_fuera_de_rango(self):
        set_similarity_threshold(empresa=self.empresa, porcentaje=0, actor=self.usuario)
        self.assertEqual(get_similarity_threshold(self.empresa), Decimal("0.00"))
        set_similarity_threshold(empresa=self.empresa, porcentaje=100, actor=self.usuario)
        self.assertEqual(get_similarity_threshold(self.empresa), Decimal("100.00"))
        with self.assertRaises(ValidationError):
            set_similarity_threshold(empresa=self.empresa, porcentaje=-1, actor=self.usuario)
        with self.assertRaises(ValidationError):
            set_similarity_threshold(empresa=self.empresa, porcentaje=100.01, actor=self.usuario)

    def test_threshold_exige_actor(self):
        with self.assertRaises(ValidationError):
            set_similarity_threshold(empresa=self.empresa, porcentaje=70, actor=None)

    def test_threshold_nuevo_no_recalcula_evaluacion_historica(self):
        tarea = self.tarea(titulo="Problema histórico")
        candidata = self.activar(self.tarea(titulo="Problema histórico"))
        evaluation = evaluate_task_similarity(
            tarea=tarea,
            threshold=get_similarity_threshold(self.empresa),
        )[0]
        confirm_similarity(
            evaluacion=evaluation,
            decision=EvaluacionSimilitud.Decision.DISTINTO_PROBLEMA,
            actor=self.usuario,
        )
        historical_values = (
            evaluation.umbral_aplicado,
            evaluation.supera_umbral,
            evaluation.porcentaje,
            evaluation.decision,
            evaluation.confirmada_por_id,
            evaluation.confirmada_at,
        )
        set_similarity_threshold(empresa=self.empresa, porcentaje=100, actor=self.usuario)
        evaluation.refresh_from_db()
        self.assertEqual(
            (
                evaluation.umbral_aplicado,
                evaluation.supera_umbral,
                evaluation.porcentaje,
                evaluation.decision,
                evaluation.confirmada_por_id,
                evaluation.confirmada_at,
            ),
            historical_values,
        )
        self.assertEqual(candidata.estado, Tarea.Estado.ACTIVA)

    def test_evaluacion_futura_usa_threshold_efectivo(self):
        set_similarity_threshold(empresa=self.empresa, porcentaje=100, actor=self.usuario)
        tarea = self.tarea(titulo="Nuevo problema")
        candidata = self.activar(self.tarea(titulo="Nuevo problema"))
        evaluations = evaluate_task_similarity(
            tarea=tarea,
            threshold=get_similarity_threshold(self.empresa),
        )
        evaluation = next(item for item in evaluations if item.tarea_candidata_id == candidata.id)
        self.assertEqual(evaluation.umbral_aplicado, Decimal("100.00"))
        self.assertTrue(evaluation.supera_umbral)
