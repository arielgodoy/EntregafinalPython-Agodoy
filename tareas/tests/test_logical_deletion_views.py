import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.conf import settings
from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from auditoria.models import AuditoriaTareasEvent
from access_control.models import Empresa, Permiso, Vista
from tareas import urls as tareas_urls
from tareas.models import (
    DocumentoTarea,
    LOGICAL_DELETION_RESULT_CODE,
    Tarea,
    TareaConnectionRole,
    TareaEliminacionElemento,
    TareaEliminacionOperacion,
    TareaRelacion,
)


class LogicalTaskDeletionWebTests(TestCase):
    def test_logical_deletion_route_is_registered_once(self):
        self.assertEqual(
            sum(
                pattern.name == "eliminacion_logica"
                for pattern in tareas_urls.urlpatterns
            ),
            1,
        )

    def setUp(self):
        self.company = Empresa.objects.create(
            codigo="00",
            descripcion="Empresa Base",
        )
        self.other_company = Empresa.objects.create(
            codigo="02",
            descripcion="Otra empresa",
        )
        self.user = User.objects.create_user(
            username="logical-deletion-web-user",
            password="not-used",
        )
        self.tasks_view = Vista.objects.create(
            nombre="Tareas",
            route_name="tareas:listar_tareas",
        )
        self.history_view = Vista.objects.create(
            nombre="Tareas - Tareas eliminadas",
            route_name="tareas:eliminadas_lista",
        )
        TareaConnectionRole.objects.update_or_create(
            role="BASE_TAREAS",
            defaults={
                "source_type": "DJANGO",
                "django_alias": "default",
            },
        )

    def _grant(self, vista, **flags):
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
            usuario=self.user,
            empresa=self.company,
            vista=vista,
            **defaults,
        )

    def _activate(self, client=None):
        client = client or self.client
        client.force_login(self.user)
        session = client.session
        session["empresa_id"] = self.company.pk
        session.save()

    def _task(self, empresa=None, *, number=1, title=None):
        return Tarea.objects.create(
            titulo=title or f"Tarea prueba {number}",
            correlativo=f"X{number:07d}",
            empresa=empresa or self.company,
            creada_por=self.user,
        )

    def _logical_deletion_url(self, task):
        return reverse("tareas:eliminacion_logica", kwargs={"pk": task.pk})

    def test_supervisor_can_see_button_and_read_only_preview_shows_tree_and_scope(self):
        root, child, grandchild = (
            self._task(number=1),
            self._task(number=2),
            self._task(number=3),
        )
        TareaRelacion.objects.create(padre=root, hija=child)
        TareaRelacion.objects.create(padre=child, hija=grandchild)
        self._grant(self.tasks_view, supervisor=True)
        self._activate()

        detail = self.client.get(
            reverse("tareas:detalle_tarea", kwargs={"pk": root.pk})
        )

        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Eliminar tarea")
        self.assertContains(detail, f"/tareas/{root.pk}/eliminacion-logica/")

        preview = self.client.get(self._logical_deletion_url(root))

        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, root.correlativo)
        self.assertContains(preview, root.titulo)
        self.assertContains(preview, self.company.codigo)
        self.assertContains(preview, child.correlativo)
        self.assertContains(preview, grandchild.correlativo)
        self.assertContains(preview, "Motivo de eliminación")
        self.assertEqual(len(preview.context["preview"]["tasks"]), 3)
        self.assertEqual(preview.context["preview"]["task_count"], 3)
        self.assertFalse(
            Tarea.all_objects.filter(pk__in=(root.pk, child.pk, grandchild.pk), eliminada=True).exists()
        )
        self.assertFalse(TareaEliminacionOperacion.objects.exists())

    def test_eliminar_flag_without_supervisor_cannot_see_or_open_the_flow(self):
        task = self._task()
        self._grant(self.tasks_view, ingresar=True, eliminar=True)
        self._activate()

        detail = self.client.get(
            reverse("tareas:detalle_tarea", kwargs={"pk": task.pk})
        )

        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, "Eliminar tarea")
        with patch("tareas.views.build_deletion_preview") as preview_reader:
            self.assertEqual(
                self.client.get(self._logical_deletion_url(task)).status_code,
                403,
            )
        preview_reader.assert_not_called()
        self.assertFalse(task.eliminada)

    def test_inactive_supervisor_is_denied_before_preview_data_is_read(self):
        task = self._task()
        self._grant(self.tasks_view, supervisor=True)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self._activate()

        with patch("tareas.views.build_deletion_preview") as preview_reader:
            response = self.client.get(self._logical_deletion_url(task))

        self.assertEqual(response.status_code, 302)
        preview_reader.assert_not_called()
        self.assertFalse(TareaEliminacionOperacion.objects.exists())

    def test_get_never_executes_deletion_and_post_without_supervisor_is_denied(self):
        task = self._task()
        self._grant(self.tasks_view, ingresar=True, eliminar=True)
        self._activate()

        with (
            patch("tareas.views.build_deletion_preview") as preview_reader,
            patch("tareas.views.logically_delete_task_tree") as delete_tree,
        ):
            response = self.client.post(
                self._logical_deletion_url(task),
                {"motivo": "No autorizado"},
            )

        self.assertEqual(response.status_code, 403)
        preview_reader.assert_not_called()
        delete_tree.assert_not_called()
        task.refresh_from_db()
        self.assertFalse(task.eliminada)
        self.assertFalse(TareaEliminacionOperacion.objects.exists())

    def test_confirmation_post_requires_csrf(self):
        task = self._task()
        self._grant(self.tasks_view, supervisor=True, ingresar=True)
        csrf_client = Client(enforce_csrf_checks=True)
        self._activate(csrf_client)

        preview = csrf_client.get(self._logical_deletion_url(task))

        self.assertEqual(preview.status_code, 200)
        response = csrf_client.post(
            self._logical_deletion_url(task),
            {
                "preview_token": preview.context["preview_token"],
                "motivo": "Sin CSRF",
            },
        )

        self.assertEqual(response.status_code, 403)
        task.refresh_from_db()
        self.assertFalse(task.eliminada)
        self.assertFalse(TareaEliminacionOperacion.objects.exists())

    def test_foreign_company_task_is_not_previewable_or_deletable(self):
        foreign_task = self._task(
            empresa=self.other_company,
            number=2,
        )
        self._grant(self.tasks_view, supervisor=True, ingresar=True)
        self._activate()

        response = self.client.get(self._logical_deletion_url(foreign_task))

        self.assertEqual(response.status_code, 404)
        foreign_task.refresh_from_db()
        self.assertFalse(foreign_task.eliminada)
        self.assertFalse(TareaEliminacionOperacion.objects.exists())

    def test_preview_blockers_disable_confirmation_and_prevent_service_call(self):
        root = self._task(number=1)
        foreign_child = self._task(
            empresa=self.other_company,
            number=2,
        )
        TareaRelacion.objects.create(padre=root, hija=foreign_child)
        self._grant(self.tasks_view, supervisor=True)
        self._activate()

        preview = self.client.get(self._logical_deletion_url(root))

        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.context["has_blockers"])
        self.assertContains(
            preview,
            'data-key="tareas.logical_deletion.preview.confirm_disabled"',
        )
        with patch("tareas.views.logically_delete_task_tree") as delete_tree:
            response = self.client.post(
                self._logical_deletion_url(root),
                {
                    "preview_token": preview.context["preview_token"],
                    "motivo": "Debe bloquearse",
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertContains(
            preview,
            "Hay relaciones jerárquicas que conectan el alcance con tareas externas.",
        )
        self.assertNotContains(preview, "Detalle del bloqueo")
        delete_tree.assert_not_called()
        self.assertFalse(TareaEliminacionOperacion.objects.exists())

    def test_real_confirmation_deletes_tree_records_ledger_and_audit_and_opens_l4(self):
        root, child, grandchild = (
            self._task(number=1),
            self._task(number=2),
            self._task(number=3),
        )
        TareaRelacion.objects.create(padre=root, hija=child)
        TareaRelacion.objects.create(padre=child, hija=grandchild)
        self._grant(self.tasks_view, supervisor=True)
        history_permission = self._grant(self.history_view, ingresar=True)
        temporary_media = TemporaryDirectory()
        self.addCleanup(temporary_media.cleanup)
        media_settings = override_settings(MEDIA_ROOT=temporary_media.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        document = DocumentoTarea(
            tarea=root,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo="PDF",
            usuario=self.user,
        )
        document.archivo.save(
            "A0000001.pdf",
            ContentFile(b"retained logical-deletion test file"),
            save=True,
        )
        stored_file_name = document.archivo.name
        file_storage = document.archivo.storage
        self.assertTrue(file_storage.exists(stored_file_name))
        with file_storage.open(stored_file_name, "rb") as stored_file:
            original_file_contents = stored_file.read()
        self._activate()

        preview = self.client.get(self._logical_deletion_url(root))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.context["preview"]["blockers"], [])
        self.assertContains(
            preview,
            "La eliminación lógica conservará los documentos y archivos; no se ejecutará limpieza física.",
        )
        self.assertNotContains(preview, "Detalle de la advertencia")
        operation_id = UUID(preview.context["operation_id"])

        with patch.object(file_storage, "delete") as physical_file_delete:
            response = self.client.post(
                self._logical_deletion_url(root),
                {
                    "preview_token": preview.context["preview_token"],
                    "motivo": "Prueba web L2 autorizada",
                },
                follow=True,
            )
        physical_file_delete.assert_not_called()

        self.assertEqual(response.status_code, 200)
        self.assertRedirects(
            response,
            reverse(
                "tareas:eliminacion_operacion_detalle",
                kwargs={"operation_id": operation_id},
            ),
        )
        self.assertContains(response, "Eliminación lógica completada.")
        self.assertEqual(
            response.content.decode().count("Eliminación lógica completada."),
            1,
        )
        self.assertContains(response, "Prueba web L2 autorizada")
        self.assertContains(response, str(operation_id))
        operation = TareaEliminacionOperacion.objects.get(
            operation_id=operation_id.hex,
        )
        self.assertEqual(operation.status, TareaEliminacionOperacion.Estado.COMMITTED)
        self.assertEqual(operation.result_code, LOGICAL_DELETION_RESULT_CODE)
        self.assertEqual(operation.actor_id, self.user.pk)
        self.assertEqual(operation.empresa_id, self.company.pk)
        self.assertEqual(operation.motivo, "Prueba web L2 autorizada")
        self.assertEqual(
            operation.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )
        self.assertEqual(
            operation.file_cleanup_status,
            TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA,
        )
        self.assertEqual(
            set(
                TareaEliminacionElemento.objects.filter(
                    operacion=operation,
                    tipo=Tarea._meta.label_lower,
                ).values_list("object_id", flat=True)
            ),
            {root.pk, child.pk, grandchild.pk},
        )
        for task in (root, child, grandchild):
            task.refresh_from_db()
            self.assertTrue(task.eliminada)
            self.assertTrue(
                Tarea.all_objects.filter(
                    pk=task.pk,
                    eliminada_por=self.user,
                    eliminacion_operacion_id=operation_id,
                    eliminada_en__isnull=False,
                ).exists()
            )
            self.assertFalse(Tarea.objects.filter(pk=task.pk).exists())

        self.assertTrue(
            AuditoriaTareasEvent.objects.filter(
                idempotency_key=operation_id.hex,
            ).exists()
        )
        self.assertTrue(
            Permiso.objects.filter(
                pk=history_permission.pk,
                vista=self.history_view,
                ingresar=True,
            ).exists()
        )
        self.assertEqual(
            self.client.get(
                reverse("tareas:detalle_tarea", kwargs={"pk": root.pk})
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(self._logical_deletion_url(root)).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                self._logical_deletion_url(root),
                {
                    "preview_token": preview.context["preview_token"],
                    "motivo": "No volver a eliminar",
                },
            ).status_code,
            404,
        )
        self.assertEqual(TareaEliminacionOperacion.objects.count(), 1)
        normal_list = self.client.get(reverse("tareas:listar_tareas"))
        self.assertEqual(normal_list.status_code, 200)
        self.assertNotContains(normal_list, root.correlativo)
        history_list = self.client.get(reverse("tareas:eliminadas_lista"))
        self.assertEqual(history_list.status_code, 200)
        self.assertContains(history_list, root.correlativo)
        historical_detail = self.client.get(
            reverse(
                "tareas:eliminada_detalle",
                kwargs={
                    "operation_id": operation_id,
                    "task_id": root.pk,
                },
            )
        )
        self.assertEqual(historical_detail.status_code, 200)
        self.assertContains(historical_detail, "Prueba web L2 autorizada")
        self.assertContains(historical_detail, str(operation_id))
        self.assertContains(historical_detail, "A0000001.pdf")
        document.refresh_from_db()
        self.assertEqual(document.archivo.name, stored_file_name)
        self.assertTrue(DocumentoTarea.objects.filter(pk=document.pk).exists())
        self.assertTrue(file_storage.exists(stored_file_name))
        with file_storage.open(stored_file_name, "rb") as stored_file:
            self.assertEqual(stored_file.read(), original_file_contents)

    def test_success_without_history_permission_does_not_grant_or_expose_l4(self):
        task = self._task()
        self._grant(self.tasks_view, supervisor=True, ingresar=True)
        self._activate()
        preview = self.client.get(self._logical_deletion_url(task))
        operation_id = UUID(preview.context["operation_id"])
        service_result = SimpleNamespace(
            operation_id=operation_id,
            audit_status=TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        )

        with patch(
            "tareas.views.logically_delete_task_tree",
            return_value=service_result,
        ):
            response = self.client.post(
                self._logical_deletion_url(task),
                {
                    "preview_token": preview.context["preview_token"],
                    "motivo": "Prueba sin acceso a L4",
                },
                follow=True,
            )

        self.assertRedirects(response, reverse("tareas:listar_tareas"))
        self.assertContains(response, "Eliminación lógica completada.")
        self.assertEqual(
            response.content.decode().count("Eliminación lógica completada."),
            1,
        )
        self.assertFalse(
            Permiso.objects.filter(
                usuario=self.user,
                empresa=self.company,
                vista=self.history_view,
            ).exists()
        )
        self.assertEqual(
            self.client.get(reverse("tareas:eliminadas_lista")).status_code,
            403,
        )

    def test_missing_confirmation_token_does_not_execute_and_l4_is_read_only(self):
        task = self._task()
        self._grant(self.tasks_view, supervisor=True, ingresar=True)
        self._grant(self.history_view, ingresar=True)
        self._activate()

        response = self.client.post(self._logical_deletion_url(task))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(TareaEliminacionOperacion.objects.exists())
        self.assertEqual(
            self.client.post(reverse("tareas:eliminadas_lista")).status_code,
            405,
        )

    def test_non_root_task_does_not_show_button_and_preview_disables_confirmation(self):
        parent, child = self._task(number=1), self._task(number=2)
        TareaRelacion.objects.create(padre=parent, hija=child)
        self._grant(self.tasks_view, supervisor=True)
        self._activate()

        detail = self.client.get(
            reverse("tareas:detalle_tarea", kwargs={"pk": child.pk})
        )

        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, "Eliminar tarea")

        preview = self.client.get(self._logical_deletion_url(child))

        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.context["logical_root_blocked"])
        self.assertTrue(preview.context["has_blockers"])
        self.assertContains(
            preview,
            'data-key="tareas.logical_deletion.preview.confirm_disabled"',
        )

    def test_changed_scope_requires_review_of_fresh_preview(self):
        task = self._task()
        self._grant(self.tasks_view, supervisor=True)
        self._activate()
        preview = self.client.get(self._logical_deletion_url(task))
        old_token = preview.context["preview_token"]
        task.titulo = "Título actualizado después de previsualizar"
        task.save(update_fields=["titulo"])

        response = self.client.post(
            self._logical_deletion_url(task),
            {
                "preview_token": old_token,
                "motivo": "Prueba de alcance cambiante",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertContains(
            response,
            'data-key="tareas.logical_deletion.errors.preview_stale"',
            status_code=409,
        )
        task.refresh_from_db()
        self.assertFalse(task.eliminada)
        self.assertFalse(TareaEliminacionOperacion.objects.exists())

    def test_logical_deletion_templates_have_translation_keys_in_both_catalogs(self):
        root = Path(settings.BASE_DIR)
        templates = (
            root / "tareas" / "templates" / "tareas" / "tarea_eliminacion_logica_preview.html",
            root / "tareas" / "templates" / "tareas" / "tarea_detalle.html",
            root / "tareas" / "templates" / "tareas" / "_i18n_message.html",
        )
        used = set()
        for template in templates:
            for key in re.findall(
                r'data-key=["\']([^"\']+)["\']',
                template.read_text(encoding="utf-8"),
            ):
                if "{{" not in key and key.startswith("tareas.logical_deletion."):
                    used.add(key)
        for language in ("sp", "en"):
            catalog = json.loads(
                (root / "static" / "lang" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(used - catalog.keys(), set(), language)
