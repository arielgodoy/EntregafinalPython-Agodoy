from datetime import date, timedelta
from dataclasses import fields, is_dataclass
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.db.models import Model, QuerySet
from django.db.models.manager import BaseManager
from django.db.models.fields.files import FieldFile
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from settings.models import SettingsMySQLConnection
from tareas.models import (
    Comentario,
    ComentarioAdjunto,
    DocumentoTarea,
    DocumentoHistorial,
    EnlaceTarea,
    EvidenciaCierre,
    MiniTarea,
    MiniTareaEvento,
    Hito,
    HitoEvidencia,
    Tarea,
    TareaConnectionRole,
    TareaParticipante,
)
from tareas.services.hierarchy import add_child
from tareas.services.detail_storage import (
    DjangoTaskDetailStorage,
    MySQLTaskDetailStorage,
    TaskDetailSections,
    resolve_detail_storage,
)


class DetailCharacterizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="00", descripcion="Empresa A")
        cls.otra_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        cls.user = User.objects.create_user(username="t133-user", password="pass")
        cls.responsible = User.objects.create_user(
            username="t133-responsible", password="pass"
        )
        cls.vista_tareas = Vista.objects.create(nombre="Tareas")
        cls.vista_hitos = Vista.objects.create(nombre="Tareas - Hitos")
        cls.vista_documentos = Vista.objects.create(
            nombre="Tareas - Documentos y evidencia"
        )
        for vista in (cls.vista_tareas, cls.vista_hitos, cls.vista_documentos):
            Permiso.objects.create(
                usuario=cls.user,
                empresa=cls.empresa,
                vista=vista,
                ingresar=True,
                modificar=True,
            )
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="DJANGO",
            django_alias="default",
        )

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def _task(self, **kwargs):
        values = {
            "titulo": "Detail characterization",
            "descripcion": "Descripción detail",
            "empresa": self.empresa,
            "creada_por": self.user,
            "responsable": self.responsible,
            "fecha_tope": date(2026, 10, 31),
            "correlativo": "B0013301",
        }
        values.update(kwargs)
        return Tarea.objects.create(**values)

    def test_initial_get_renders_core_and_dates(self):
        task = self._task()

        response = self.client.get(reverse("tareas:detalle_tarea", args=[task.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tarea"].pk, task.pk)
        self.assertContains(response, task.titulo)
        self.assertContains(response, task.correlativo)
        self.assertContains(response, 'data-key="tareas.fields.asignacion_short"')
        self.assertContains(response, 'data-key="tareas.fields.cumplimiento_short"')
        self.assertContains(response, self.responsible.username)

    def test_initial_get_is_company_scoped(self):
        task = self._task(empresa=self.otra_empresa, correlativo="B0013302")

        response = self.client.get(reverse("tareas:detalle_tarea", args=[task.pk]))

        self.assertEqual(response.status_code, 404)

    def test_comments_are_secondary_boundary_not_initial_feed(self):
        task = self._task(correlativo="B0013303")

        response = self.client.get(reverse("tareas:detalle_tarea", args=[task.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("comentarios", response.context)
        self.assertIn("comentarios_puede_ver", response.context)

    def test_hitos_context_is_conditional_on_permission(self):
        task = self._task(correlativo="B0013304")
        Permiso.objects.filter(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_hitos,
        ).update(ingresar=False)

        without_permission = self.client.get(
            reverse("tareas:detalle_tarea", args=[task.pk])
        )
        self.assertFalse(without_permission.context["puede_ver_hitos"])

        Permiso.objects.filter(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_hitos,
        ).update(ingresar=True)
        with_permission = self.client.get(
            reverse("tareas:detalle_tarea", args=[task.pk])
        )
        self.assertTrue(with_permission.context["puede_ver_hitos"])
        self.assertIn("avance", with_permission.context)

    def test_documents_context_is_conditional_on_permission(self):
        task = self._task(correlativo="B0013305")
        Permiso.objects.filter(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_documentos,
        ).update(modificar=False)

        without_permission = self.client.get(
            reverse("tareas:detalle_tarea", args=[task.pk])
        )
        self.assertFalse(without_permission.context["puede_ver_documentos"])

        Permiso.objects.filter(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_documentos,
        ).update(modificar=True)
        with_permission = self.client.get(
            reverse("tareas:detalle_tarea", args=[task.pk])
        )
        self.assertTrue(with_permission.context["puede_ver_documentos"])
        self.assertIn("documentos", with_permission.context)

    def test_hierarchy_context_preserves_parent_and_children(self):
        parent = self._task(titulo="Parent", correlativo="B0013310")
        child = self._task(titulo="Child", correlativo="B0013311")
        add_child(parent, child)

        response = self.client.get(reverse("tareas:detalle_tarea", args=[parent.pk]))

        self.assertIsNone(response.context["tarea_padre"])
        self.assertEqual([item.pk for item in response.context["tareas_hijas"]], [child.pk])

    def test_participants_context_preserves_user_and_role(self):
        participant = User.objects.create_user(
            username="t133-explicit-participant", password="pass"
        )
        Permiso.objects.create(
            usuario=participant,
            empresa=self.empresa,
            vista=self.vista_tareas,
            ingresar=True,
        )
        task = self._task(correlativo="B0013312")
        TareaParticipante.objects.create(
            tarea=task,
            usuario=participant,
            rol=TareaParticipante.Rol.INVITADO_OBSERVADOR,
        )

        response = self.client.get(reverse("tareas:detalle_tarea", args=[task.pk]))

        listed = response.context["participantes_explicitos"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].username, participant.username)
        self.assertEqual(listed[0].rol, TareaParticipante.Rol.INVITADO_OBSERVADOR)

    def test_minitasks_context_preserves_initial_get_contract(self):
        task = self._task(correlativo="B0013313")
        mini_task = MiniTarea.objects.create(
            tarea=task,
            descripcion="Preparar antecedentes",
            persona=self.responsible,
        )

        response = self.client.get(reverse("tareas:detalle_tarea", args=[task.pk]))

        listed = response.context["mini_tareas"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].id, mini_task.pk)
        self.assertEqual(listed[0].descripcion, mini_task.descripcion)
        self.assertEqual(listed[0].persona_username, self.responsible.username)
        self.assertFalse(listed[0].hecho)
        self.assertEqual(listed[0].eventos_t104, ())
        self.assertContains(response, mini_task.descripcion)

    def test_links_context_preserves_visible_fields_and_status_precedence(self):
        task = self._task(correlativo="B0013314")
        link = EnlaceTarea.objects.create(
            tarea=task,
            destinatario=self.responsible,
            creado_por=self.user,
            token_hash="a" * 64,
            fecha_expiracion=timezone.now() - timedelta(days=1),
            revocado_at=timezone.now(),
            revocado_por=self.user,
        )

        response = self.client.get(reverse("tareas:detalle_tarea", args=[task.pk]))

        listed = response.context["enlaces"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].id, link.pk)
        self.assertEqual(listed[0].destinatario_username, self.responsible.username)
        self.assertEqual(listed[0].creado_por_username, self.user.username)
        self.assertEqual(listed[0].revocado_por_username, self.user.username)
        self.assertEqual(listed[0].estado, "REVOCADO")
        self.assertNotContains(response, link.token_hash)
        self.assertContains(response, self.responsible.username)

    def test_storage_returns_last_closure_attachment_without_orm_objects(self):
        task = self._task(correlativo="B0013315")
        mini_task = MiniTarea.objects.create(
            tarea=task,
            descripcion="Adjuntar respaldo",
            persona=self.responsible,
            hecho=True,
        )
        comentario = Comentario.objects.create(
            tarea=task,
            autor=self.responsible,
            contenido="Cierre con respaldo",
        )
        evento = MiniTareaEvento.objects.create(
            mini_tarea=mini_task,
            comentario_feed=comentario,
            tipo=MiniTareaEvento.Tipo.CIERRE,
            actor=self.responsible,
            comentario="Cierre con respaldo",
        )
        documento = DocumentoTarea.objects.create(
            tarea=task,
            tipo=DocumentoTarea.Tipo.OTRO,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            url="https://example.test/respaldo.pdf",
            usuario=self.responsible,
        )
        ComentarioAdjunto.objects.create(comentario=comentario, documento=documento)

        result = DjangoTaskDetailStorage("default").get_task_detail(
            task_id=task.pk,
            empresa_id=self.empresa.pk,
            sections=TaskDetailSections(milestones=True),
        )

        listed = result.mini_tasks[0]
        self.assertEqual(listed.id, mini_task.pk)
        self.assertEqual(listed.eventos_t104[0].id, evento.pk)
        self.assertEqual(
            listed.ultimo_cierre_adjuntos_t104[0].nombre_archivo,
            "respaldo.pdf",
        )
        self.assertFalse(hasattr(listed, "persona"))
        self.assertFalse(hasattr(result.links, "objects"))

    def test_milestone_section_returns_progress_and_presentation_dto(self):
        task = self._task(correlativo="B0013316")
        milestone = Hito.objects.create(
            tarea=task,
            nombre="Validar entrega",
            responsable=self.responsible,
            cumplimiento="50.00",
            peso="2.00",
        )
        HitoEvidencia.objects.create(
            hito=milestone,
            formato_archivo="PDF",
            url="https://example.test/evidencia.pdf",
            usuario=self.responsible,
        )

        response = self.client.get(reverse("tareas:detalle_tarea", args=[task.pk]))

        self.assertEqual(response.context["progress"].weighted_percentage, 50)
        listed = response.context["hitos"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].nombre, "Validar entrega")
        self.assertEqual(listed[0].responsable_username, self.responsible.username)
        self.assertEqual(listed[0].evidencias[0].nombre_archivo, "evidencia.pdf")
        self.assertEqual(listed[0].evidencias[0].usuario_username, self.responsible.username)
        self.assertFalse(hasattr(listed[0], "responsable"))
        self.assertContains(response, "Validar entrega")

    def test_milestones_disabled_performs_no_milestone_section_reads(self):
        task = self._task(correlativo="B0013317")
        storage = DjangoTaskDetailStorage("default")

        with CaptureQueriesContext(connection) as queries:
            result = storage.get_task_detail(
                task_id=task.pk,
                empresa_id=self.empresa.pk,
                sections=TaskDetailSections(milestones=False),
            )

        milestone_tables = (
            "tareas_avance",
            "tareas_hitoevidencia",
            "tareas_hitohistorial",
        )
        sql = " ".join(query["sql"].lower() for query in queries)
        self.assertFalse(any(table in sql for table in milestone_tables))
        identity_reads = [query["sql"] for query in queries if 'FROM "tareas_hito"' in query["sql"]]
        self.assertEqual(len(identity_reads), 1)
        self.assertNotIn('"nombre"', identity_reads[0])
        self.assertEqual(result.effective_user_ids, ())
        self.assertIsNone(result.progress)
        self.assertEqual(result.milestones, ())

    def test_documents_context_preserves_dto_labels_history_and_closure_evidence(self):
        task = self._task(correlativo="B0013318")
        document = DocumentoTarea.objects.create(
            tarea=task,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            url="https://example.test/informe.pdf",
            usuario=self.user,
        )
        DocumentoHistorial.objects.create(
            documento=document,
            accion="CREADO",
            usuario=self.user,
        )
        evidence = EvidenciaCierre.objects.create(
            tarea=task,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            url="https://example.test/cierre.pdf",
            usuario=self.responsible,
        )

        response = self.client.get(reverse("tareas:detalle_tarea", args=[task.pk]))

        listed_document = response.context["documentos"][0]
        listed_evidence = response.context["evidencias"][0]
        self.assertEqual(listed_document.tipo_display, "Informe")
        self.assertEqual(listed_document.formato_archivo_display, "PDF")
        self.assertEqual(listed_document.nombre_archivo, "informe.pdf")
        self.assertEqual(listed_document.historial[0].accion, "CREADO")
        self.assertEqual(listed_evidence.id, evidence.pk)
        self.assertEqual(listed_evidence.formato_archivo_display, "PDF")
        self.assertEqual(listed_evidence.nombre_archivo, "cierre.pdf")
        self.assertEqual(listed_evidence.usuario_username, self.responsible.username)
        self.assertNotContains(response, "get_tipo_display")
        self.assertNotContains(response, "get_formato_archivo_display")

    def test_documents_disabled_performs_no_document_section_reads(self):
        task = self._task(correlativo="B0013319")
        storage = DjangoTaskDetailStorage("default")

        with CaptureQueriesContext(connection) as queries:
            result = storage.get_task_detail(
                task_id=task.pk,
                empresa_id=self.empresa.pk,
                sections=TaskDetailSections(documents=False),
            )

        document_tables = (
            "tareas_documentotarea",
            "tareas_documentohistorial",
            "tareas_evidenciacierre",
        )
        sql = " ".join(query["sql"].lower() for query in queries)
        self.assertFalse(any(table in sql for table in document_tables))
        self.assertEqual(result.documents, ())
        self.assertEqual(result.closure_evidence, ())

    def test_detail_result_contract_contains_no_orm_objects(self):
        result = DjangoTaskDetailStorage("default").get_task_detail(
            task_id=self._task(correlativo="B0013320").pk,
            empresa_id=self.empresa.pk,
            sections=TaskDetailSections(
                milestones=True,
                documents=True,
            ),
        )

        def assert_plain(value):
            self.assertFalse(isinstance(value, (Model, QuerySet, BaseManager, FieldFile)))
            if is_dataclass(value):
                for field in fields(value):
                    assert_plain(getattr(value, field.name))
            elif isinstance(value, (tuple, list)):
                for item in value:
                    assert_plain(item)
            elif isinstance(value, dict):
                for item in value.values():
                    assert_plain(item)

        assert_plain(result)

    def test_detail_view_does_not_second_lookup_task_after_storage_result(self):
        task = self._task(correlativo="B0013321")
        result = DjangoTaskDetailStorage("default").get_task_detail(
            task_id=task.pk,
            empresa_id=self.empresa.pk,
            sections=TaskDetailSections(),
        )
        fake_storage = type(
            "FakeDetailStorage",
            (),
            {"get_task_detail": lambda _self, **_kwargs: result},
        )()

        with patch("tareas.views.resolve_detail_storage", return_value=fake_storage), patch(
            "tareas.views.Tarea.objects.get",
            side_effect=AssertionError("Detail View performed a second Tarea lookup"),
        ):
            response = self.client.get(reverse("tareas:detalle_tarea", args=[task.pk]))

        self.assertEqual(response.status_code, 200)

    def test_mysql_detail_resolves_mysql_storage_without_django_fallback(self):
        catalog = self.empresa
        connection = SettingsMySQLConnection.objects.create(
            empresa=catalog,
            nombre_logico="mysql-detail",
            host="mysql.example.test",
            user="user",
            password="secret",
            db_name="tareas",
            is_active=True,
        )
        role = TareaConnectionRole.objects.get(role="BASE_TAREAS")
        role.source_type = "MYSQL_CONFIG"
        role.django_alias = None
        role.mysql_connection = connection
        role.database_name = "tareas"
        role.save()
        storage = resolve_detail_storage()

        self.assertIsInstance(storage, MySQLTaskDetailStorage)
        self.assertEqual(storage.database_name, "tareas")
