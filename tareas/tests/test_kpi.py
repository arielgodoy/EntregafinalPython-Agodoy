from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from organizacion.models import Departamento, OrganizationalSource
from tareas.models import (
    DocumentoHistorial,
    DocumentoTarea,
    Hito,
    HitoHistorial,
    Tarea,
    TareaLectura,
    TareaParticipante,
    TareaTransicion,
)
from tareas.services.kpi import (
    DashboardPermissionError,
    get_department_dashboard,
    get_general_dashboard,
    get_kpis,
    get_personal_dashboard,
    get_task_dashboard,
    get_company_dashboard,
    get_user_dashboard,
)


class T059KpiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        cls.otra_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        cls.usuario = User.objects.create_user(username="usuario", password="x")
        cls.responsable = User.objects.create_user(username="responsable", password="x")
        cls.otro_responsable = User.objects.create_user(username="otro", password="x")
        cls.vista_tareas = Vista.objects.create(nombre="Tareas")
        Permiso.objects.create(
            usuario=cls.usuario,
            empresa=cls.empresa,
            vista=cls.vista_tareas,
            supervisor=True,
        )

    def setUp(self):
        self.counter = 0
        self.reference_date = date(2026, 9, 16)
        self.reference_now = timezone.make_aware(datetime(2026, 9, 16, 12, 0, 0))

    def crear_tarea(self, *, estado=Tarea.Estado.GESTION, empresa=None, **kwargs):
        self.counter += 1
        defaults = {
            "titulo": f"Tarea {self.counter}",
            "correlativo": f"A{self.counter:07d}",
            "empresa": empresa or self.empresa,
            "creada_por": self.usuario,
            "responsable": self.responsable,
            "estado": estado,
            "fecha_publicacion": self.reference_now - timedelta(days=1),
            "fecha_asignacion": self.reference_now - timedelta(days=1),
            "fecha_tope": self.reference_date + timedelta(days=3),
        }
        defaults.update(kwargs)
        return Tarea.objects.create(**defaults)

    def kpis(self, queryset=None):
        return get_kpis(
            queryset=queryset or Tarea.objects.filter(empresa=self.empresa),
            reference_date=self.reference_date,
            reference_now=self.reference_now,
        )

    def test_poblacion_excluye_borrador_anulada_y_cuenta_estados(self):
        self.crear_tarea(estado=Tarea.Estado.BORRADOR)
        self.crear_tarea(estado=Tarea.Estado.ACTIVA)
        self.crear_tarea(estado=Tarea.Estado.GESTION)
        self.crear_tarea(estado=Tarea.Estado.PENDIENTE_APROBACION_CIERRE)
        self.crear_tarea(estado=Tarea.Estado.CERRADA)
        self.crear_tarea(estado=Tarea.Estado.GESTION, anulada=True)

        kpis = self.kpis()

        self.assertEqual(
            list(kpis["por_estado"].values()),
            [1, 1, 1, 1],
        )
        self.assertEqual(sum(kpis["por_estado"].values()), 4)

    def test_atrasada_no_incluye_cerrada_y_cumplida_no_es_actual(self):
        self.crear_tarea(
            estado=Tarea.Estado.GESTION,
            fecha_tope=self.reference_date - timedelta(days=1),
        )
        self.crear_tarea(
            estado=Tarea.Estado.GESTION,
            fecha_tope=self.reference_date - timedelta(days=2),
            fecha_cumplimiento=self.reference_now - timedelta(days=1),
        )
        self.crear_tarea(
            estado=Tarea.Estado.CERRADA,
            fecha_tope=self.reference_date - timedelta(days=3),
        )

        self.assertEqual(self.kpis()["atrasadas"], 1)

    def test_proximas_vencer_incluye_dia_cero_y_siete_no_dia_ocho_ni_vencida(self):
        for offset in (0, 7):
            self.crear_tarea(
                fecha_tope=self.reference_date + timedelta(days=offset)
            )
        self.crear_tarea(fecha_tope=self.reference_date + timedelta(days=8))
        self.crear_tarea(fecha_tope=self.reference_date - timedelta(days=1))

        self.assertEqual(self.kpis()["proximas_vencer"], 2)

    def test_sin_movimiento_usa_historial_y_no_lectura(self):
        stale = self.crear_tarea(
            fecha_publicacion=self.reference_now - timedelta(days=8),
        )
        recent = self.crear_tarea(
            fecha_publicacion=self.reference_now - timedelta(days=8),
        )
        transition = TareaTransicion.objects.create(
            tarea=recent,
            estado_origen=Tarea.Estado.ACTIVA,
            estado_destino=Tarea.Estado.GESTION,
            accion_evento="GESTIONAR",
            usuario=self.usuario,
        )
        TareaTransicion.objects.filter(pk=transition.pk).update(
            timestamp=self.reference_now - timedelta(days=1)
        )
        TareaLectura.objects.create(tarea=stale, usuario=self.usuario, leido=True)

        self.assertEqual(self.kpis()["sin_movimiento"], 1)

    def test_sin_movimiento_considera_hito_y_documento(self):
        hito_task = self.crear_tarea(
            fecha_publicacion=self.reference_now - timedelta(days=10),
        )
        hito = Hito.objects.create(
            tarea=hito_task,
            nombre="Hito",
            responsable=self.responsable,
            peso=Decimal("1"),
        )
        HitoHistorial.objects.create(
            hito=hito,
            tipo_evento=HitoHistorial.Evento.CAMBIO_NOMBRE,
            fecha=self.reference_now - timedelta(days=1),
        )
        document_task = self.crear_tarea(
            fecha_publicacion=self.reference_now - timedelta(days=10),
        )
        document = DocumentoTarea.objects.create(
            tarea=document_task,
            tipo=DocumentoTarea.Tipo.OTRO,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            url="https://example.com/document.pdf",
            usuario=self.usuario,
        )
        DocumentoHistorial.objects.create(
            documento=document,
            accion="AGREGADO",
            usuario=self.usuario,
            fecha=self.reference_now - timedelta(days=1),
        )

        self.assertEqual(self.kpis()["sin_movimiento"], 0)

    def test_aprobacion_carga_no_pondera_prioridad_ni_participantes(self):
        self.crear_tarea(estado=Tarea.Estado.PENDIENTE_APROBACION_CIERRE)
        self.crear_tarea(estado=Tarea.Estado.ACTIVA, prioridad=Tarea.Prioridad.CRITICA)
        participant_task = self.crear_tarea(estado=Tarea.Estado.GESTION)
        participant_task.responsable = self.otro_responsable
        participant_task.save(update_fields=["responsable"])
        TareaParticipante.objects.create(
            tarea=participant_task,
            usuario=self.responsable,
            rol=TareaParticipante.Rol.INVITADO_OBSERVADOR,
        )

        kpis = self.kpis()

        self.assertEqual(kpis["esperando_aprobacion"], 1)
        load_by_user = {
            row["responsable_id"]: row["cantidad"]
            for row in kpis["carga_por_responsable"]
        }
        self.assertEqual(load_by_user[self.responsable.pk], 2)

    def test_cumplimiento_y_tiempo_promedio(self):
        self.crear_tarea(estado=Tarea.Estado.CERRADA)
        self.crear_tarea(estado=Tarea.Estado.GESTION)
        closed = self.crear_tarea(
            estado=Tarea.Estado.CERRADA,
            fecha_publicacion=self.reference_now - timedelta(hours=6),
            fecha_cumplimiento=self.reference_now,
        )
        self.assertIsNotNone(closed.fecha_cumplimiento)

        kpis = self.kpis()

        self.assertEqual(kpis["cumplimiento"], Decimal("66.67"))
        self.assertEqual(kpis["tiempo_promedio_cierre_horas"], Decimal("6.00"))

    def test_cumplimiento_sin_poblacion_es_cero(self):
        kpis = self.kpis()
        self.assertEqual(kpis["cumplimiento"], Decimal("0.00"))
        self.assertEqual(kpis["tiempo_promedio_cierre_horas"], Decimal("0.00"))

    def test_dashboard_personal_incluye_responsable_participante_hito_y_lectura(self):
        direct = self.crear_tarea()
        participant = self.crear_tarea(responsable=self.otro_responsable)
        TareaParticipante.objects.create(
            tarea=participant,
            usuario=self.responsable,
            rol=TareaParticipante.Rol.PARTICIPANTE,
        )
        TareaLectura.objects.create(tarea=direct, usuario=self.responsable, leido=True)
        hito = Hito.objects.create(
            tarea=participant,
            nombre="Hito asignado",
            responsable=self.responsable,
            peso=Decimal("1"),
        )

        context = get_personal_dashboard(
            user=self.responsable,
            empresa_id=self.empresa.pk,
            reference_date=self.reference_date,
        )

        self.assertEqual({task.pk for task in context["tareas"]}, {direct.pk, participant.pk})
        self.assertEqual(context["read_status"][direct.pk], True)
        self.assertEqual(context["hitos"][0].pk, hito.pk)
        assignments = {task.pk: task.assignment_type for task in context["tareas"]}
        self.assertEqual(assignments[direct.pk], "RESPONSABLE")
        self.assertEqual(assignments[participant.pk], TareaParticipante.Rol.PARTICIPANTE)

    def test_general_solo_incluye_empresas_con_supervisor(self):
        self.crear_tarea()
        self.crear_tarea(empresa=self.otra_empresa)

        context = get_general_dashboard(user=self.usuario)

        self.assertEqual([row["empresa_id"] for row in context["rows"]], [self.empresa.pk])

    def test_departamento_valida_empresa_y_excluye_local(self):
        departamento = Departamento.objects.create(
            empresa=self.empresa,
            codigo="DEP-01",
            nombre="Departamento",
            source=OrganizationalSource.LOCAL,
        )
        self.crear_tarea(
            tipo_ambito=Tarea.Ambito.DEPARTAMENTO,
            departamento=departamento,
        )

        context = get_department_dashboard(
            user=self.usuario,
            empresa_id=self.empresa.pk,
            departamento_id=departamento.pk,
        )

        self.assertEqual(context["kpis"]["por_estado"][Tarea.Estado.GESTION], 1)
        with self.assertRaises(DashboardPermissionError):
            get_department_dashboard(
                user=self.usuario,
                empresa_id=self.otra_empresa.pk,
                departamento_id=departamento.pk,
            )

    def test_t061_rows_y_ocho_kpi_en_dimensiones_activas(self):
        departamento = Departamento.objects.create(
            empresa=self.empresa,
            codigo="DEP-T061",
            nombre="Departamento T061",
            source=OrganizationalSource.LOCAL,
        )
        tarea = self.crear_tarea(
            responsable=self.usuario,
            tipo_ambito=Tarea.Ambito.DEPARTAMENTO,
            departamento=departamento,
        )

        general = get_general_dashboard(user=self.usuario)
        company = get_company_dashboard(user=self.usuario, empresa_id=self.empresa.pk)
        department = get_department_dashboard(
            user=self.usuario,
            empresa_id=self.empresa.pk,
            departamento_id=departamento.pk,
        )
        user = get_user_dashboard(
            user=self.usuario,
            empresa_id=self.empresa.pk,
            usuario_id=self.usuario.pk,
        )
        task = get_task_dashboard(
            user=self.usuario,
            empresa_id=self.empresa.pk,
            tarea_id=tarea.pk,
        )

        expected_kpis = {
            "por_estado",
            "atrasadas",
            "proximas_vencer",
            "sin_movimiento",
            "esperando_aprobacion",
            "carga_por_responsable",
            "cumplimiento",
            "tiempo_promedio_cierre_horas",
        }
        for context in (general, company, department, user, task):
            self.assertEqual(set(context["kpis"]), expected_kpis)
        self.assertEqual(company["rows"][0]["departamento_id"], departamento.pk)
        self.assertEqual(department["rows"][0]["usuario_id"], self.usuario.pk)
        self.assertEqual(user["rows"][0]["id"], tarea.pk)
        self.assertEqual(task["rows"][0]["id"], tarea.pk)
