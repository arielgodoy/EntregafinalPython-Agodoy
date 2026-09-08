"""Tests Phase 3 T025-T027: participants, reads, assignment and cloning."""

from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from tareas.models import Tarea, TareaLectura, TareaParticipante, TareaReasignacion
from tareas.services.assignment import (
    add_participant,
    assign_responsible,
    create_independent_tasks_for_responsibles,
    mark_task_read,
)
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class AssignmentPhase3Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="A3", descripcion="Empresa Phase 3")
        cls.otra_empresa = create_empresa(codigo="B3", descripcion="Otra Empresa")
        cls.creador = create_user(username="p3_creador")
        cls.responsable = create_user(username="p3_responsable")
        cls.participante = create_user(username="p3_participante")
        cls.otro_participante = create_user(username="p3_otro_participante")
        cls.nuevo_responsable = create_user(username="p3_nuevo_responsable")
        cls.usuario_otra_empresa = create_user(username="p3_otro_contexto")
        cls.inactivo = create_user(username="p3_inactivo")
        cls.inactivo.is_active = False
        cls.inactivo.save()

        for user in [
            cls.creador,
            cls.responsable,
            cls.participante,
            cls.otro_participante,
            cls.nuevo_responsable,
            cls.inactivo,
        ]:
            assign_permission(user, cls.empresa, "Tareas - Listado", ingresar=True)
        assign_permission(cls.usuario_otra_empresa, cls.otra_empresa, "Tareas - Listado", ingresar=True)

    def make_task(self, **kwargs):
        defaults = {
            "responsable": self.responsable,
        }
        defaults.update(kwargs)
        return create_tarea(self.empresa, self.creador, **defaults)

    def test_agregar_participante(self):
        tarea = self.make_task()
        participante = add_participant(tarea, self.participante)
        self.assertEqual(participante.tarea, tarea)
        self.assertEqual(participante.usuario, self.participante)
        self.assertEqual(participante.rol, TareaParticipante.Rol.PARTICIPANTE)

    def test_persistencia_de_roles_canonicos(self):
        roles = [
            TareaParticipante.Rol.CREADOR,
            TareaParticipante.Rol.RESPONSABLE_LIDER,
            TareaParticipante.Rol.SUPERVISOR,
            TareaParticipante.Rol.AUTORIZADOR,
            TareaParticipante.Rol.PARTICIPANTE,
            TareaParticipante.Rol.INVITADO_OBSERVADOR,
        ]
        for index, rol in enumerate(roles):
            user = create_user(username=f"rol_user_{index}")
            assign_permission(user, self.empresa, "Tareas - Listado", ingresar=True)
            tarea = self.make_task(titulo=f"Tarea rol {index}")
            participante = add_participant(tarea, user, rol)
            participante.refresh_from_db()
            self.assertEqual(participante.rol, rol)

    def test_multiples_participantes(self):
        tarea = self.make_task()
        add_participant(tarea, self.participante)
        add_participant(tarea, self.otro_participante, TareaParticipante.Rol.INVITADO_OBSERVADOR)
        self.assertEqual(tarea.participantes.count(), 2)

    def test_usuario_inactivo_rechazado_como_participante(self):
        tarea = self.make_task()
        with self.assertRaises(ValidationError):
            add_participant(tarea, self.inactivo)

    def test_participante_no_reemplaza_responsable(self):
        tarea = self.make_task()
        add_participant(tarea, self.participante)
        tarea.refresh_from_db()
        self.assertEqual(tarea.responsable, self.responsable)

    def test_marcar_lectura(self):
        tarea = self.make_task()
        lectura = mark_task_read(tarea, self.participante)
        self.assertTrue(lectura.leido)
        self.assertIsNotNone(lectura.fecha_lectura)

    def test_lectura_por_usuario_independiente(self):
        tarea = self.make_task()
        mark_task_read(tarea, self.participante)
        lectura_otro = mark_task_read(tarea, self.otro_participante, leido=False)
        self.assertTrue(TareaLectura.objects.get(tarea=tarea, usuario=self.participante).leido)
        self.assertFalse(lectura_otro.leido)

    def test_participante_de_otra_empresa_rechazado(self):
        tarea = self.make_task()
        with self.assertRaises(ValidationError):
            add_participant(tarea, self.usuario_otra_empresa)

    def test_asignacion_uno_a_uno(self):
        tarea = create_tarea(self.empresa, self.creador)
        reasignacion = assign_responsible(tarea, self.responsable, self.creador, "Asignación inicial")
        tarea.refresh_from_db()
        self.assertEqual(tarea.responsable, self.responsable)
        self.assertIsNone(reasignacion.responsable_anterior)
        self.assertEqual(reasignacion.responsable_nuevo, self.responsable)

    def test_reasignacion_valida(self):
        tarea = self.make_task()
        assign_responsible(tarea, self.nuevo_responsable, self.creador, "Cambio")
        tarea.refresh_from_db()
        self.assertEqual(tarea.responsable, self.nuevo_responsable)

    def test_reasignacion_mismo_responsable_noop(self):
        tarea = self.make_task()
        resultado = assign_responsible(tarea, self.responsable, self.creador, "Sin cambio")
        tarea.refresh_from_db()
        self.assertIsNone(resultado)
        self.assertEqual(tarea.responsable, self.responsable)
        self.assertEqual(tarea.reasignaciones.count(), 0)

    def test_historial_de_reasignacion(self):
        tarea = self.make_task()
        reasignacion = assign_responsible(tarea, self.nuevo_responsable, self.creador, "Cambio")
        self.assertEqual(tarea.reasignaciones.count(), 1)
        self.assertEqual(reasignacion.responsable_anterior, self.responsable)
        self.assertEqual(reasignacion.responsable_nuevo, self.nuevo_responsable)
        self.assertEqual(reasignacion.usuario, self.creador)
        self.assertEqual(reasignacion.motivo, "Cambio")

    def test_reasignacion_rechaza_usuario_inactivo(self):
        tarea = self.make_task()
        with self.assertRaises(ValidationError):
            assign_responsible(tarea, self.inactivo, self.creador)

    def test_asignacion_rechaza_usuario_inactivo_sin_mutar_tarea(self):
        tarea = create_tarea(self.empresa, self.creador)
        with self.assertRaises(ValidationError):
            assign_responsible(tarea, self.inactivo, self.creador)
        tarea.refresh_from_db()
        self.assertIsNone(tarea.responsable)
        self.assertFalse(TareaReasignacion.objects.filter(tarea=tarea).exists())

    def test_asignacion_rechaza_usuario_de_otra_empresa_sin_mutar_tarea(self):
        tarea = create_tarea(self.empresa, self.creador)
        with self.assertRaises(ValidationError):
            assign_responsible(tarea, self.usuario_otra_empresa, self.creador)
        tarea.refresh_from_db()
        self.assertIsNone(tarea.responsable)
        self.assertFalse(TareaReasignacion.objects.filter(tarea=tarea).exists())

    def test_reasignacion_preserva_empresa_y_creador(self):
        tarea = self.make_task()
        assign_responsible(tarea, self.nuevo_responsable, self.creador)
        tarea.refresh_from_db()
        self.assertEqual(tarea.empresa, self.empresa)
        self.assertEqual(tarea.creada_por, self.creador)

    def test_clonar_a_n_responsables_crea_n_tareas_independientes(self):
        responsables = [self.responsable, self.nuevo_responsable, self.participante]
        titulos = {user.pk: f"Tarea de {user.username}" for user in responsables}
        tareas = create_independent_tasks_for_responsibles(
            empresa=self.empresa,
            creada_por=self.creador,
            responsables=responsables,
            titulos_por_usuario=titulos,
        )
        self.assertEqual(len(tareas), 3)
        self.assertEqual(Tarea.objects.filter(titulo__startswith="Tarea de ").count(), 3)

    def test_clones_tienen_pk_y_correlativos_distintos_misma_empresa(self):
        responsables = [self.responsable, self.nuevo_responsable]
        titulos = {user.pk: f"Tarea de {user.username}" for user in responsables}
        tareas = create_independent_tasks_for_responsibles(
            empresa=self.empresa,
            creada_por=self.creador,
            responsables=responsables,
            titulos_por_usuario=titulos,
        )
        self.assertEqual(len({tarea.pk for tarea in tareas}), 2)
        self.assertEqual(len({tarea.correlativo for tarea in tareas}), 2)
        self.assertEqual({tarea.empresa_id for tarea in tareas}, {self.empresa.id})

    def test_cada_clon_tiene_su_responsable(self):
        responsables = [self.responsable, self.nuevo_responsable]
        titulos = {user.pk: f"Tarea de {user.username}" for user in responsables}
        tareas = create_independent_tasks_for_responsibles(
            empresa=self.empresa,
            creada_por=self.creador,
            responsables=responsables,
            titulos_por_usuario=titulos,
        )
        self.assertEqual([tarea.responsable for tarea in tareas], responsables)

    def test_clones_no_crean_relacion_jerarquica(self):
        responsables = [self.responsable, self.nuevo_responsable]
        titulos = {user.pk: f"Tarea de {user.username}" for user in responsables}
        tareas = create_independent_tasks_for_responsibles(
            empresa=self.empresa,
            creada_por=self.creador,
            responsables=responsables,
            titulos_por_usuario=titulos,
        )
        try:
            TareaRelacion = apps.get_model("tareas", "TareaRelacion")
        except LookupError:
            TareaRelacion = None
        if TareaRelacion is not None:
            self.assertFalse(TareaRelacion.objects.filter(padre__in=tareas).exists())
            self.assertFalse(TareaRelacion.objects.filter(hija__in=tareas).exists())

    def test_usuario_inactivo_no_recibe_clon_y_operacion_es_atomica(self):
        responsables = [self.responsable, self.inactivo]
        titulos = {user.pk: f"Tarea de {user.username}" for user in responsables}
        before = Tarea.objects.count()
        with self.assertRaises(ValidationError):
            create_independent_tasks_for_responsibles(
                empresa=self.empresa,
                creada_por=self.creador,
                responsables=responsables,
                titulos_por_usuario=titulos,
            )
        self.assertEqual(Tarea.objects.count(), before)

    def test_clonacion_sin_responsables_rechazada_sin_crear_tareas(self):
        before = Tarea.objects.count()
        with self.assertRaises(ValidationError):
            create_independent_tasks_for_responsibles(
                empresa=self.empresa,
                creada_por=self.creador,
                responsables=[],
                titulos_por_usuario={},
            )
        self.assertEqual(Tarea.objects.count(), before)

    def test_clonacion_sin_nombre_propio_rechazada_sin_crear_tareas(self):
        responsables = [self.responsable, self.nuevo_responsable]
        before = Tarea.objects.count()
        with self.assertRaises(ValidationError):
            create_independent_tasks_for_responsibles(
                empresa=self.empresa,
                creada_por=self.creador,
                responsables=responsables,
                titulos_por_usuario={self.responsable.pk: "Con nombre"},
            )
        self.assertEqual(Tarea.objects.count(), before)

    def test_fecha_comun_en_reasignaciones_de_clones(self):
        responsables = [self.responsable, self.nuevo_responsable]
        titulos = {user.pk: f"Tarea de {user.username}" for user in responsables}
        fecha = timezone.now()
        tareas = create_independent_tasks_for_responsibles(
            empresa=self.empresa,
            creada_por=self.creador,
            responsables=responsables,
            titulos_por_usuario=titulos,
            fecha_comun=fecha,
        )
        fechas = list(
            TareaReasignacion.objects.filter(tarea__in=tareas).values_list("fecha", flat=True)
        )
        self.assertEqual(fechas, [fecha, fecha])
