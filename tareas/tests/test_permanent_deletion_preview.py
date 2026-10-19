from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import User
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from tareas.services.base_tareas_schema import get_operational_models
from tareas.services.deletion_preview import (
    DeletionPreviewError,
    DeletionPreviewNotFound,
    _MySQLReader,
    build_deletion_preview,
)
from tareas.models import (
    DocumentoTarea,
    EvaluacionSimilitud,
    Tarea,
    TareaConnectionRole,
    TareaRelacion,
    Todo,
)


class PermanentDeletionPreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="00", descripcion="Empresa Base")
        cls.otra_empresa = Empresa.objects.create(codigo="02", descripcion="Otra empresa")
        cls.user = User.objects.create_user(
            username="deletion-preview",
            password="test-password",
        )
        cls.vista = Vista.objects.create(nombre="Tareas")
        cls.otra_vista = Vista.objects.create(nombre="Tareas - Hitos")
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="DJANGO",
            django_alias="default",
        )

    def _grant(self, user=None, empresa=None, vista=None, **flags):
        defaults = {
            "ver": False,
            "ingresar": False,
            "crear": False,
            "modificar": False,
            "eliminar": False,
            "autorizar": False,
            "supervisor": False,
        }
        defaults.update(flags)
        return Permiso.objects.create(
            usuario=user or self.user,
            empresa=empresa or self.empresa,
            vista=vista or self.vista,
            **defaults,
        )

    def _activate(self, empresa=None):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = (empresa or self.empresa).pk
        session.save()

    def _task(self, empresa=None, **kwargs):
        number = Tarea.objects.count() + 1
        return Tarea.objects.create(
            titulo=kwargs.pop("titulo", f"Tarea {number}"),
            correlativo=f"X{number:07d}",
            empresa=empresa or self.empresa,
            creada_por=self.user,
            **kwargs,
        )

    def _mark_deleted_for_storage_fixture(self, task):
        table = connection.ops.quote_name(Tarea._meta.db_table)
        columns = {
            name: connection.ops.quote_name(Tarea._meta.get_field(name).column)
            for name in (
                "eliminada",
                "eliminada_en",
                "eliminada_por",
                "eliminacion_operacion_id",
            )
        }
        pk_column = connection.ops.quote_name(Tarea._meta.pk.column)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET {columns['eliminada']}=%s, "
                f"{columns['eliminada_en']}=%s, "
                f"{columns['eliminada_por']}=%s, "
                f"{columns['eliminacion_operacion_id']}=%s "
                f"WHERE {pk_column}=%s",
                (True, timezone.now(), self.user.pk, uuid4().hex, task.pk),
            )

    def _preview(self, task):
        return self.client.get(
            reverse("tareas:previsualizar_eliminacion_definitiva", args=[task.pk]),
            HTTP_ACCEPT="application/json",
        )

    def test_supervisor_alone_can_preview_and_inventory_is_read_only(self):
        self._grant(supervisor=True, ingresar=True)
        root = self._task()
        child = self._task()
        grandchild = self._task()
        TareaRelacion.objects.create(padre=root, hija=child)
        TareaRelacion.objects.create(padre=child, hija=grandchild)
        self._activate()
        initial_count = Tarea.objects.count()
        response = self._preview(root)

        self.assertEqual(response.status_code, 200)
        payload = response.json()["preview"]
        self.assertEqual(payload["task"]["id"], root.pk)
        self.assertEqual(payload["task_count"], 3)
        self.assertEqual(payload["descendant_count"], 2)
        self.assertEqual(Tarea.objects.count(), initial_count)

    def test_deleted_root_is_not_previewable(self):
        self._grant(supervisor=True)
        task = self._task()
        self._mark_deleted_for_storage_fixture(task)
        self._activate()

        response = self._preview(task)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(task.titulo.encode(), response.content)

    def test_deleted_descendant_is_not_in_operational_preview(self):
        self._grant(supervisor=True)
        root, deleted_child = self._task(), self._task()
        TareaRelacion.objects.create(padre=root, hija=deleted_child)
        self._mark_deleted_for_storage_fixture(deleted_child)
        self._activate()

        response = self._preview(root)

        self.assertEqual(response.status_code, 409)
        payload = response.json()["preview"]
        self.assertEqual(payload["task_count"], 1)
        self.assertEqual(payload["descendant_count"], 0)
        self.assertNotIn(deleted_child.titulo, response.content.decode())
        self.assertIn(
            "Hay relaciones jerárquicas que conectan el alcance con tareas externas.",
            " ".join(payload["blockers"]),
        )
        self.assertNotIn("otra empresa", " ".join(payload["blockers"]))

    def test_deleted_and_foreign_children_have_the_same_public_blocker(self):
        self._grant(supervisor=True)
        deleted_root, deleted_child = self._task(), self._task()
        foreign_root = self._task()
        foreign_child = self._task(empresa=self.otra_empresa)
        TareaRelacion.objects.create(padre=deleted_root, hija=deleted_child)
        TareaRelacion.objects.create(padre=foreign_root, hija=foreign_child)
        self._mark_deleted_for_storage_fixture(deleted_child)
        self._activate()

        deleted_response = self._preview(deleted_root)
        foreign_response = self._preview(foreign_root)

        self.assertEqual(deleted_response.status_code, 409)
        self.assertEqual(foreign_response.status_code, 409)
        deleted_preview = deleted_response.json()["preview"]
        foreign_preview = foreign_response.json()["preview"]
        for field in (
            "task_count",
            "descendant_count",
            "counts",
            "shared_references",
            "warnings",
            "blockers",
            "integrity_status",
            "backend",
        ):
            with self.subTest(field=field):
                self.assertEqual(deleted_preview[field], foreign_preview[field])
        self.assertNotIn(deleted_child.titulo, deleted_response.content.decode())
        self.assertNotIn(foreign_child.titulo, foreign_response.content.decode())

    def test_preview_recurses_beyond_normal_hierarchy_depth(self):
        self._grant(supervisor=True)
        tasks = [self._task() for _ in range(5)]
        for parent, child in zip(tasks, tasks[1:]):
            TareaRelacion.objects.create(padre=parent, hija=child)
        self._activate()

        response = self._preview(tasks[0])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["preview"]["task_count"], 5)

    def test_child_preview_does_not_include_parent_or_sibling(self):
        self._grant(supervisor=True)
        parent, selected, sibling, grandchild = [self._task() for _ in range(4)]
        TareaRelacion.objects.create(padre=parent, hija=selected)
        TareaRelacion.objects.create(padre=parent, hija=sibling)
        TareaRelacion.objects.create(padre=selected, hija=grandchild)
        self._activate()

        response = self._preview(selected)

        self.assertEqual(response.status_code, 200)
        payload = response.json()["preview"]
        self.assertEqual(payload["task_count"], 2)
        self.assertEqual(payload["descendant_count"], 1)

    def test_cycle_is_reported_as_integrity_blocker_without_writes(self):
        self._grant(supervisor=True)
        root, child = self._task(), self._task()
        TareaRelacion.objects.create(padre=root, hija=child)
        TareaRelacion.objects.create(padre=child, hija=root)
        self._activate()
        initial_count = Tarea.objects.count()

        response = self._preview(root)

        self.assertEqual(response.status_code, 409)
        self.assertIn("ciclo", " ".join(response.json()["preview"]["blockers"]))
        self.assertEqual(Tarea.objects.count(), initial_count)

    def test_cross_company_child_is_blocked_and_excluded(self):
        self._grant(supervisor=True)
        root = self._task()
        foreign = self._task(empresa=self.otra_empresa)
        TareaRelacion.objects.create(padre=root, hija=foreign)
        self._activate()

        response = self._preview(root)

        self.assertEqual(response.status_code, 409)
        payload = response.json()["preview"]
        self.assertEqual(payload["task_count"], 1)
        self.assertIn(
            "Hay relaciones jerárquicas que conectan el alcance con tareas externas.",
            " ".join(payload["blockers"]),
        )
        self.assertNotIn("otra empresa", " ".join(payload["blockers"]))
        self.assertNotIn(foreign.titulo, response.content.decode())

    def test_cross_task_similarity_blocks_preview_without_expanding_scope(self):
        self._grant(supervisor=True)
        root, unrelated = self._task(), self._task()
        EvaluacionSimilitud.objects.create(
            tarea=root,
            tarea_candidata=unrelated,
            porcentaje=50,
            umbral_aplicado=40,
            supera_umbral=True,
        )
        self._activate()

        response = self._preview(root)

        self.assertEqual(response.status_code, 409)
        payload = response.json()["preview"]
        self.assertEqual(payload["task_count"], 1)
        self.assertEqual(payload["shared_references"][0]["type"], "similarity")

    def test_external_task_origin_reference_blocks_preview(self):
        self._grant(supervisor=True)
        root = self._task()
        self._task(tarea_origen=root)
        self._activate()

        response = self._preview(root)

        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["preview"]["shared_references"])

    def test_todo_origin_is_counted_and_external_notifications_are_unverified(self):
        self._grant(supervisor=True)
        todo = Todo.objects.create(
            empresa=self.empresa,
            correlativo="TD0000001",
            titulo="Pendiente",
            creada_por=self.user,
        )
        task = self._task(todo_origen=todo)
        self._activate()

        response = self._preview(task)

        self.assertEqual(response.status_code, 200)
        payload = response.json()["preview"]
        self.assertEqual(payload["counts"]["Tareas con Todo de origen"], 1)
        self.assertTrue(
            any(
                reference["classification"] == "NO_VERIFICADA"
                and "notificaciones externas" in reference["message"]
                for reference in payload["shared_references"]
            )
        )

    def test_authorize_is_not_required_but_supervisor_is_required(self):
        task = self._task()
        self._activate()

        self._grant(autorizar=True, supervisor=False)
        self.assertEqual(self._preview(task).status_code, 403)

        Permiso.objects.filter(usuario=self.user, vista=self.vista).delete()
        self._grant(autorizar=False, supervisor=True)
        self.assertEqual(self._preview(task).status_code, 200)

    def test_anonymous_user_cannot_preview(self):
        task = self._task()

        response = self._preview(task)

        self.assertEqual(response.status_code, 302)

    def test_supervisor_in_another_view_or_company_is_not_sufficient(self):
        task = self._task()
        self._activate()
        self._grant(vista=self.otra_vista, supervisor=True)
        self.assertEqual(self._preview(task).status_code, 403)

        self._grant(empresa=self.otra_empresa, supervisor=True)
        self.assertEqual(self._preview(task).status_code, 403)

    def test_staff_and_superuser_without_explicit_supervisor_are_denied(self):
        task = self._task()
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=("is_staff", "is_superuser"))
        self._activate()

        self.assertEqual(self._preview(task).status_code, 403)

    def test_non_base_company_is_rejected_before_preview(self):
        self._grant(empresa=self.otra_empresa, supervisor=True)
        self._activate(self.otra_empresa)

        response = self._preview(self._task(empresa=self.otra_empresa))

        self.assertEqual(response.status_code, 403)

    def test_list_button_is_only_rendered_for_vicmeas_supervisor(self):
        self._grant(ingresar=True)
        self._task()
        self._activate()
        response = self.client.get(reverse("tareas:listar_tareas"))
        self.assertNotContains(response, "js-permanent-deletion-preview")

        Permiso.objects.filter(usuario=self.user, vista=self.vista).update(
            supervisor=True
        )
        response = self.client.get(reverse("tareas:listar_tareas"))
        self.assertContains(response, "js-permanent-deletion-preview")
        self.assertContains(response, "disabled")

    def test_preview_endpoint_is_get_only(self):
        self._grant(supervisor=True)
        task = self._task()
        self._activate()

        response = self.client.post(
            reverse("tareas:previsualizar_eliminacion_definitiva", args=[task.pk])
        )

        self.assertEqual(response.status_code, 405)

    def test_physical_preview_still_blocks_unverified_file_exclusivity(self):
        self._grant(supervisor=True)
        task = self._task()
        DocumentoTarea.objects.create(
            tarea=task,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo="PDF",
            archivo="tareas/documentos/physical-preview/file.pdf",
            usuario=self.user,
        )
        self._activate()

        response = self._preview(task)

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            "La exclusividad de archivos físicos frente a otros módulos no está verificada.",
            response.json()["preview"]["blockers"],
        )


class MySQLDeletionPreviewAdapterTests(SimpleTestCase):
    class Cursor:
        def __init__(self, tables):
            self.tables = set(tables)
            self.statements = []
            self.current_sql = ""
            self.closed = False
            self.deleted_root = False

        def execute(self, sql, params=()):
            self.statements.append((sql, params))
            self.current_sql = sql

        def fetchall(self):
            if "INFORMATION_SCHEMA.TABLES" in self.current_sql:
                return [(table,) for table in sorted(self.tables)]
            if "hija_id" in self.current_sql:
                if "eliminada" in self.current_sql and "empresa_id" in self.current_sql:
                    return [(22,)]
                return [(22,), (23,)]
            if self.current_sql.startswith("SELECT id, empresa_id FROM"):
                return [(22, 1)]
            return []

        def fetchone(self):
            if "SELECT id, empresa_id, correlativo, titulo, estado" in self.current_sql:
                if self.deleted_root and "eliminada" in self.current_sql:
                    return None
                return (21, 1, "T0000021", "Tarea de prueba", "BORRADOR")
            if self.current_sql.startswith("SELECT COUNT(*) FROM"):
                return (1,)
            return None

        def close(self):
            self.closed = True

    class Connection:
        def __init__(self, cursor):
            self._cursor = cursor

        def cursor(self):
            return self._cursor

    def _reader(self, tables=None):
        expected_tables = {
            model._meta.db_table for model in get_operational_models()
        }
        cursor = self.Cursor(expected_tables if tables is None else tables)
        return _MySQLReader(self.Connection(cursor), "tasks_db"), cursor

    def test_mysql_inventory_schema_and_queries_are_read_only(self):
        reader, cursor = self._reader()
        self.addCleanup(reader.close)

        self.assertEqual(reader.missing_tables, ())
        self.assertEqual(
            reader.task(21, 1),
            {
                "id": 21,
                "empresa_id": 1,
                "correlativo": "T0000021",
                "titulo": "Tarea de prueba",
                "estado": "BORRADOR",
            },
        )
        self.assertEqual(reader.children(21, 1), [22])
        task_sql = next(
            sql for sql, _ in cursor.statements if "correlativo" in sql
        )
        children_sql = next(
            sql for sql, _ in cursor.statements if "hija_id" in sql
        )
        self.assertIn("eliminada", task_sql)
        self.assertIn("eliminada", children_sql)
        self.assertIn("empresa_id", children_sql)
        self.assertEqual(reader.companies([22]), {22: 1})
        self.assertEqual(reader.todo_source_references([21]), 1)
        self.assertTrue(cursor.statements)
        self.assertTrue(
            all(sql.lstrip().upper().startswith("SELECT") for sql, _ in cursor.statements)
        )

    def test_mysql_reader_rejects_a_deleted_root(self):
        reader, cursor = self._reader()
        cursor.deleted_root = True
        self.addCleanup(reader.close)

        with self.assertRaises(DeletionPreviewNotFound):
            reader.task(21, 1)

        self.assertIn("eliminada", cursor.statements[-1][0])

    def test_mysql_reader_omits_deleted_descendants(self):
        reader, cursor = self._reader()
        self.addCleanup(reader.close)

        children = reader.children(21, 1)

        self.assertEqual(children, [22])
        self.assertNotIn(23, children)
        self.assertIn("eliminada", cursor.statements[-1][0])
        self.assertIn("empresa_id", cursor.statements[-1][0])
        self.assertEqual(cursor.statements[-1][1], (21, 1, False))

    def test_mysql_inventory_reports_missing_schema_tables(self):
        tables = {
            model._meta.db_table for model in get_operational_models()
        }
        omitted = next(iter(tables))
        reader, _cursor = self._reader(tables - {omitted})

        self.assertEqual(reader.missing_tables, (omitted,))
        reader.close()

    def test_mysql_connection_failure_is_sanitized(self):
        with (
            patch(
                "tareas.services.deletion_preview.resolve_operational_backend",
                return_value=SimpleNamespace(
                    backend_type="MYSQL_CONFIG",
                    mysql_connection=object(),
                    database_name="tasks_db",
                ),
            ),
            patch(
                "tareas.services.deletion_preview.open_mysql_connection",
                side_effect=RuntimeError("password=must-not-leak"),
            ),
        ):
            with self.assertRaises(DeletionPreviewError) as error:
                build_deletion_preview(task_id=21, empresa_id=1)

        self.assertNotIn("must-not-leak", str(error.exception))
