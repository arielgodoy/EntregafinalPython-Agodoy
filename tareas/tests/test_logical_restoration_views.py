import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.contrib.auth.models import User
from django.core import signing
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa
from tareas.models import TareaEliminacionElemento, TareaEliminacionOperacion
from tareas.services.logical_restoration import LogicalRestorationError
from tareas.tests.factories import assign_permission, create_empresa, create_user


class _PreviewI18nTextAudit(HTMLParser):
    _VOID_ELEMENTS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_preview = False
        self.keyed_text = False
        self.untranslated_text = []
        self._stack = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        parent_in_preview = self._stack[-1][1] if self._stack else False
        parent_keyed = self._stack[-1][2] if self._stack else False
        in_preview = parent_in_preview or attributes.get("id") == "l5-restoration-preview"
        keyed = parent_keyed or "data-key" in attributes
        self.in_preview = self.in_preview or in_preview
        if in_preview and "data-key" in attributes:
            self.keyed_text = True
        if tag not in self._VOID_ELEMENTS:
            self._stack.append((tag, in_preview, keyed))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data):
        if not self._stack or not self._stack[-1][1] or self._stack[-1][2]:
            return
        visible = re.sub(r"\{\{.*?\}\}|\{%.*?%\}", "", data, flags=re.DOTALL).strip()
        if visible.strip("—:·"):
            self.untranslated_text.append(visible)


class LogicalRestorationPreviewViewTests(TestCase):
    source_operation_id = UUID("25ffcbcf-5257-46ea-8b4b-9a5e29ebe7e0")
    restoration_operation_id = UUID("76a4cf0a-b972-4b25-9e61-11db893dc35f")

    def setUp(self):
        self.user = create_user("restoration-preview-user")
        self.company = create_empresa("00", "Base 00")
        self.other_company = create_empresa("01", "Empresa externa")

    def _activate_company(self, empresa=None, *, user=None, client=None):
        client = client or self.client
        client.force_login(user or self.user)
        session = client.session
        session["empresa_id"] = (empresa or self.company).pk
        session.save()

    def _grant(self, *, ingresar=False, supervisor=False, eliminar=False, user=None, empresa=None):
        user = user or self.user
        empresa = empresa or self.company
        if ingresar:
            assign_permission(
                user,
                empresa,
                "Tareas - Tareas eliminadas",
                ingresar=True,
            )
        if supervisor or eliminar:
            assign_permission(
                user,
                empresa,
                "Tareas",
                supervisor=supervisor,
                eliminar=eliminar,
            )

    def _preview(self, *, blockers=(), warnings=()):
        created_at = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
        committed_at = datetime(2026, 10, 20, 9, 1, tzinfo=timezone.utc)
        tasks = (
            SimpleNamespace(
                task_id=84,
                physically_present=True,
                correlativo="B0000084",
                titulo="Raíz de prueba",
                estado="ACTIVA",
                fecha_tope=None,
                responsable_id=self.user.pk,
                eliminada=True,
                eliminada_en=committed_at,
                eliminada_por_id=self.user.pk,
                eliminacion_operacion_id=self.source_operation_id,
            ),
            SimpleNamespace(
                task_id=85,
                physically_present=True,
                correlativo="B0000085",
                titulo="Hija de prueba",
                estado="GESTION",
                fecha_tope=None,
                responsable_id=self.user.pk,
                eliminada=True,
                eliminada_en=committed_at,
                eliminada_por_id=self.user.pk,
                eliminacion_operacion_id=self.source_operation_id,
            ),
        )
        return SimpleNamespace(
            deletion_operation_id=self.source_operation_id,
            root_task_id=84,
            root_correlativo="B0000084",
            empresa_id=self.company.pk,
            empresa_codigo=self.company.codigo,
            empresa_descripcion=self.company.descripcion,
            deletion_actor_id=self.user.pk,
            deletion_created_at=created_at,
            deletion_committed_at=committed_at,
            deletion_motivo="Motivo de eliminación original",
            source_audit_status="CONFIRMED",
            manifest=(
                SimpleNamespace(model_label="tareas.tarea", object_id=84),
                SimpleNamespace(model_label="tareas.tarea", object_id=85),
            ),
            task_ids=(84, 85),
            tasks=tasks,
            hierarchy=((84, 85),),
            documents=(
                SimpleNamespace(
                    document_id=19,
                    task_id=85,
                    tipo="INFORME",
                    formato_archivo="PDF",
                    estado="VIGENTE",
                    has_file=True,
                    has_url=False,
                ),
            ),
            external_origin_reference_count=0,
            restoration_operation_id=None,
            warnings=warnings,
            blockers=blockers,
            backend_type="DJANGO",
            backend_identity="default",
            backend_config_version="test",
            fingerprint="a" * 64,
            can_restore=not blockers,
        )

    def _url(self, operation_id=None):
        return reverse(
            "tareas:restauracion_logica",
            kwargs={"operation_id": operation_id or self.source_operation_id},
        )

    def _issue_preview(
        self,
        *,
        client=None,
        operation_id=None,
        restoration_operation_id=None,
    ):
        client = client or self.client
        restoration_operation_id = (
            restoration_operation_id or self.restoration_operation_id
        )
        self._grant(ingresar=True, supervisor=True)
        self._activate_company(client=client)
        with (
            patch(
                "tareas.views.build_logical_restoration_preview",
                return_value=self._preview(),
            ) as preview_builder,
            patch(
                "tareas.views.uuid4",
                return_value=restoration_operation_id,
            ),
        ):
            response = client.get(self._url(operation_id))
        return response, response.context["preview_token"], preview_builder

    def _signed_token(
        self,
        *,
        actor=None,
        empresa_id=None,
        deletion_operation_id=None,
        restoration_operation_id=None,
        manifest=None,
        fingerprint="a" * 64,
    ):
        return signing.dumps(
            {
                "actor_id": (actor or self.user).pk,
                "empresa_id": empresa_id or self.company.pk,
                "deletion_operation_id": (
                    deletion_operation_id or self.source_operation_id
                ).hex,
                "restoration_operation_id": (
                    restoration_operation_id or self.restoration_operation_id
                ).hex,
                "manifest": manifest
                or [
                    {"model_label": "tareas.tarea", "object_id": 84},
                    {"model_label": "tareas.tarea", "object_id": 85},
                ],
                "fingerprint": fingerprint,
            },
            salt="tareas.logical-restoration-preview",
            compress=True,
        )

    def _post_data(
        self,
        token,
        *,
        restoration_operation_id=None,
        motivo="Motivo de restauración confirmado",
        confirm=True,
    ):
        data = {
            "preview_token": token,
            "restoration_operation_id": (
                restoration_operation_id or self.restoration_operation_id
            ).hex,
            "motivo": motivo,
        }
        if confirm:
            data["confirm_restore"] = "yes"
        return data

    def _result(self, *, audit_status=None, replayed=False):
        return SimpleNamespace(
            operation_id=self.restoration_operation_id,
            reverses_operation_id=self.source_operation_id,
            root_task_id=84,
            task_ids=(84, 85),
            result_code="LOGICALLY_RESTORED",
            status=TareaEliminacionOperacion.Estado.COMMITTED,
            backend_type="DJANGO",
            audit_status=(
                audit_status
                or TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA
            ),
            replayed=replayed,
        )

    def test_get_with_both_permissions_renders_read_only_preview_and_signed_token(self):
        self._grant(ingresar=True, supervisor=True)
        self._activate_company()
        preview = self._preview(
            warnings=(
                SimpleNamespace(code="FILES_NOT_VERIFIED", message="not rendered"),
            )
        )

        with (
            patch(
                "tareas.views.build_logical_restoration_preview",
                return_value=preview,
            ) as preview_builder,
            patch(
                "tareas.views.uuid4",
                return_value=self.restoration_operation_id,
            ) as uuid_factory,
            patch(
                "tareas.views.restore_logical_task_tree",
            ) as restore_service,
        ):
            response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "B0000084")
        self.assertContains(response, "Hija de prueba")
        self.assertContains(response, "tareas.logical_restoration.preview.warning.files_not_verified")
        self.assertContains(response, "Confirmar restauración")
        self.assertContains(response, 'name="motivo"')
        self.assertContains(response, 'name="confirm_restore"')
        self.assertContains(response, "csrfmiddlewaretoken")
        template_source = (
            Path(__file__).resolve().parents[1]
            / "templates"
            / "tareas"
            / "tarea_restauracion_logica_preview.html"
        ).read_text(encoding="utf-8")
        self.assertRegex(
            template_source,
            r"<button[^>]*\btype=[\"']submit[\"']",
        )
        preview_builder.assert_called_once_with(
            actor=self.user,
            empresa_id=self.company.pk,
            deletion_operation_id=self.source_operation_id,
        )
        uuid_factory.assert_called_once_with()
        restore_service.assert_not_called()

        payload = signing.loads(
            response.context["preview_token"],
            salt="tareas.logical-restoration-preview",
            max_age=900,
        )
        self.assertEqual(payload["actor_id"], self.user.pk)
        self.assertEqual(payload["empresa_id"], self.company.pk)
        self.assertEqual(
            payload["deletion_operation_id"],
            self.source_operation_id.hex,
        )
        self.assertEqual(
            payload["restoration_operation_id"],
            self.restoration_operation_id.hex,
        )
        self.assertEqual(payload["fingerprint"], preview.fingerprint)
        self.assertEqual(
            payload["manifest"],
            [
                {"model_label": "tareas.tarea", "object_id": 84},
                {"model_label": "tareas.tarea", "object_id": 85},
            ],
        )

    def test_get_without_history_ingresar_is_forbidden(self):
        self._grant(supervisor=True)
        self._activate_company()

        with patch("tareas.views.build_logical_restoration_preview") as preview_builder:
            response = self.client.get(self._url())

        self.assertEqual(response.status_code, 403)
        preview_builder.assert_not_called()

    def test_get_without_supervisor_is_forbidden_even_with_history_ingresar(self):
        self._grant(ingresar=True)
        self._activate_company()

        with patch("tareas.views.build_logical_restoration_preview") as preview_builder:
            response = self.client.get(self._url())

        self.assertEqual(response.status_code, 403)
        preview_builder.assert_not_called()

    def test_eliminar_permission_does_not_substitute_supervisor(self):
        self._grant(ingresar=True, eliminar=True)
        self._activate_company()

        with patch("tareas.views.build_logical_restoration_preview") as preview_builder:
            response = self.client.get(self._url())

        self.assertEqual(response.status_code, 403)
        preview_builder.assert_not_called()

    def test_staff_and_superuser_do_not_substitute_supervisor(self):
        for attribute in ("is_staff", "is_superuser"):
            with self.subTest(attribute=attribute):
                user = create_user(f"restoration-preview-{attribute}")
                setattr(user, attribute, True)
                user.save(update_fields=[attribute])
                self._grant(ingresar=True, user=user)
                self._activate_company(user=user)

                with patch("tareas.views.build_logical_restoration_preview") as preview_builder:
                    response = self.client.get(self._url())

                self.assertEqual(response.status_code, 403)
                preview_builder.assert_not_called()

    def test_foreign_and_missing_operations_return_404_with_session_company_scope(self):
        self._grant(ingresar=True, supervisor=True)
        self._activate_company()
        operation_ids = (
            UUID("a7c29f18-41f6-44e0-82ef-2f3845edaf58"),
            UUID("c05cb940-37e0-48ec-a86e-2bde35df6ff0"),
        )
        error = LogicalRestorationError(
            "RESTORATION_NOT_FOUND",
            "No se debe filtrar este texto interno",
        )

        with patch(
            "tareas.views.build_logical_restoration_preview",
            side_effect=(error, error),
        ) as preview_builder:
            responses = tuple(
                self.client.get(self._url(operation_id))
                for operation_id in operation_ids
            )

        self.assertEqual(tuple(response.status_code for response in responses), (404, 404))
        for response in responses:
            self.assertNotContains(
                response,
                "No se debe filtrar",
                status_code=404,
            )
        self.assertEqual(preview_builder.call_count, 2)
        self.assertTrue(
            all(
                call.kwargs["empresa_id"] == self.company.pk
                for call in preview_builder.call_args_list
            )
        )

    def test_l4_preview_link_requires_supervisor_and_current_deleted_status(self):
        operation = SimpleNamespace(
            operation_id=self.source_operation_id,
            deletion_status="CURRENTLY_DELETED",
            actor_id=self.user.pk,
            root_task_id=84,
            root_correlativo="B0000084",
            motivo="Motivo original",
            created_at=datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc),
            committed_at=datetime(2026, 10, 20, 9, 1, tzinfo=timezone.utc),
            status="COMMITTED",
            result_code="LOGICALLY_DELETED",
            audit_status="CONFIRMED",
            audit_consistency="CONSISTENT",
            audit_event_id=1,
            file_cleanup_status="NOT_REQUIRED",
            hierarchy_status="COMPLETE",
            audit=None,
            restoration=None,
            items=(),
            files=(),
            relations=(),
        )
        operation_url = reverse(
            "tareas:eliminacion_operacion_detalle",
            kwargs={"operation_id": self.source_operation_id},
        )
        preview_url = self._url()

        self._grant(ingresar=True, supervisor=True)
        self._activate_company()
        with patch(
            "tareas.views.get_deleted_task_history_operation",
            return_value=operation,
        ):
            supervisor_response = self.client.get(operation_url)

        self.assertEqual(supervisor_response.status_code, 200)
        self.assertContains(supervisor_response, preview_url)

        inconsistent_operation = SimpleNamespace(
            **{**operation.__dict__, "deletion_status": "INCONSISTENT"}
        )
        with patch(
            "tareas.views.get_deleted_task_history_operation",
            return_value=inconsistent_operation,
        ):
            inconsistent_response = self.client.get(operation_url)

        self.assertEqual(inconsistent_response.status_code, 200)
        self.assertContains(inconsistent_response, preview_url)

        reader = create_user("restoration-preview-history-reader")
        self._grant(ingresar=True, user=reader)
        self._activate_company(user=reader)
        with patch(
            "tareas.views.get_deleted_task_history_operation",
            return_value=operation,
        ):
            reader_response = self.client.get(operation_url)

        self.assertEqual(reader_response.status_code, 200)
        self.assertNotContains(reader_response, preview_url)

        self._grant(ingresar=True, supervisor=True)
        self._activate_company()
        restored_operation = SimpleNamespace(
            **{**operation.__dict__, "deletion_status": "RESTORED"}
        )
        with patch(
            "tareas.views.get_deleted_task_history_operation",
            return_value=restored_operation,
        ):
            restored_response = self.client.get(operation_url)

        self.assertEqual(restored_response.status_code, 200)
        self.assertNotContains(restored_response, preview_url)

    def test_blocked_preview_returns_409_without_a_token(self):
        self._grant(ingresar=True, supervisor=True)
        self._activate_company()
        blocked = self._preview(
            blockers=(
                SimpleNamespace(
                    code="RESTORATION_TASK_MISSING",
                    message="raw message must not be shown",
                ),
            )
        )

        with (
            patch(
                "tareas.views.build_logical_restoration_preview",
                return_value=blocked,
            ),
            patch("tareas.views.uuid4") as uuid_factory,
        ):
            response = self.client.get(self._url())

        self.assertEqual(response.status_code, 409)
        self.assertIsNone(response.context["preview_token"])
        self.assertIsNone(response.context["restoration_operation_id"])
        self.assertContains(
            response,
            "tareas.logical_restoration.preview.blocker.task_missing",
            status_code=409,
        )
        self.assertNotContains(response, "raw message must not be shown", status_code=409)
        uuid_factory.assert_not_called()

    def test_backend_unavailable_returns_controlled_503(self):
        self._grant(ingresar=True, supervisor=True)
        self._activate_company()

        with patch(
            "tareas.views.build_logical_restoration_preview",
            side_effect=LogicalRestorationError(
                "RESTORATION_BACKEND_UNAVAILABLE",
                "database details must not leak",
            ),
        ):
            response = self.client.get(self._url())

        self.assertEqual(response.status_code, 503)
        self.assertContains(
            response,
            "tareas.logical_restoration.preview.error.unavailable",
            status_code=503,
        )
        self.assertNotContains(response, "database details", status_code=503)

    def test_active_non_base00_company_is_redirected_without_service_access(self):
        self._grant(ingresar=True, supervisor=True, empresa=self.other_company)
        self._activate_company(self.other_company)

        with patch("tareas.views.build_logical_restoration_preview") as preview_builder:
            response = self.client.get(self._url())

        self.assertEqual(response.status_code, 302)
        self.assertIn("seleccionar_empresa", response["Location"])
        preview_builder.assert_not_called()

    def test_authorized_post_restores_through_service_and_redirects_to_l4(self):
        csrf_client = Client(enforce_csrf_checks=True)
        preview_response, token, preview_builder = self._issue_preview(
            client=csrf_client,
        )
        csrf_match = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"',
            preview_response.content.decode(),
        )
        self.assertIsNotNone(csrf_match)
        data = self._post_data(token, motivo="  Motivo confirmado  ")
        data["csrfmiddlewaretoken"] = csrf_match.group(1)

        with patch(
            "tareas.views.restore_logical_task_tree",
            return_value=self._result(),
        ) as restore_service:
            response = csrf_client.post(self._url(), data)

        expected_url = reverse(
            "tareas:eliminacion_operacion_detalle",
            kwargs={"operation_id": self.source_operation_id},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], expected_url)
        preview_builder.assert_called_once()
        restore_service.assert_called_once_with(
            actor=self.user,
            empresa_id=self.company.pk,
            deletion_operation_id=self.source_operation_id,
            restoration_operation_id=self.restoration_operation_id,
            motivo="Motivo confirmado",
            expected_fingerprint="a" * 64,
        )

    def test_post_rejects_missing_and_invalid_csrf_tokens(self):
        for csrf_value in (None, "invalid-csrf-token"):
            with self.subTest(csrf_value=csrf_value):
                csrf_client = Client(enforce_csrf_checks=True)
                _, token, _ = self._issue_preview(client=csrf_client)
                data = self._post_data(token)
                if csrf_value is not None:
                    data["csrfmiddlewaretoken"] = csrf_value

                with patch("tareas.views.restore_logical_task_tree") as restore_service:
                    response = csrf_client.post(self._url(), data)

                self.assertEqual(response.status_code, 403)
                restore_service.assert_not_called()

    def test_post_requires_reason_and_explicit_confirmation(self):
        _, token, _ = self._issue_preview()
        invalid_requests = (
            (self._post_data(token, motivo="   "), "reason_required"),
            (self._post_data(token, confirm=False), "confirmation_required"),
        )

        with patch("tareas.views.restore_logical_task_tree") as restore_service:
            for data, error_key in invalid_requests:
                with self.subTest(error_key=error_key):
                    response = self.client.post(self._url(), data)
                    self.assertEqual(response.status_code, 400)
                    self.assertContains(
                        response,
                        f"tareas.logical_restoration.preview.error.{error_key}",
                        status_code=400,
                    )

        restore_service.assert_not_called()

    def test_post_rejects_tampered_crossed_and_malformed_confirmation_tokens(self):
        _, token, _ = self._issue_preview()
        another_user = create_user("restoration-token-other-actor")
        another_operation_id = UUID("a7c29f18-41f6-44e0-82ef-2f3845edaf58")
        cases = (
            (
                "tampered_signature",
                self._post_data(token + "x"),
                self._url(),
            ),
            (
                "other_actor",
                self._post_data(
                    self._signed_token(actor=another_user),
                ),
                self._url(),
            ),
            (
                "other_company",
                self._post_data(
                    self._signed_token(empresa_id=self.other_company.pk),
                ),
                self._url(),
            ),
            (
                "other_source_operation",
                self._post_data(
                    self._signed_token(
                        deletion_operation_id=another_operation_id,
                    ),
                ),
                self._url(),
            ),
            (
                "altered_restoration_uuid",
                self._post_data(
                    token,
                    restoration_operation_id=another_operation_id,
                ),
                self._url(),
            ),
            (
                "malformed_manifest",
                self._post_data(
                    self._signed_token(
                        manifest=[
                            {
                                "model_label": "tareas.tarea",
                                "object_id": True,
                            }
                        ],
                    ),
                ),
                self._url(),
            ),
        )

        with patch("tareas.views.restore_logical_task_tree") as restore_service:
            for case, data, url in cases:
                with self.subTest(case=case):
                    response = self.client.post(url, data)
                    self.assertEqual(response.status_code, 400)
                    self.assertContains(
                        response,
                        "tareas.logical_restoration.preview.error.token_invalid",
                        status_code=400,
                    )

        restore_service.assert_not_called()

    def test_post_rejects_expired_preview_token(self):
        _, token, _ = self._issue_preview()
        payload = signing.loads(
            token,
            salt="tareas.logical-restoration-preview",
            max_age=900,
        )
        timestamp = time.time()
        with patch(
            "django.core.signing.time.time",
            return_value=timestamp - 901,
        ):
            expired_token = signing.dumps(
                payload,
                salt="tareas.logical-restoration-preview",
                compress=True,
            )

        with patch("tareas.views.restore_logical_task_tree") as restore_service:
            response = self.client.post(
                self._url(),
                self._post_data(expired_token),
            )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "tareas.logical_restoration.preview.error.token_invalid",
            status_code=400,
        )
        restore_service.assert_not_called()

    def test_post_returns_404_for_foreign_or_missing_source_operation(self):
        self._grant(ingresar=True, supervisor=True)
        self._activate_company()
        foreign_operation_id = UUID("a7c29f18-41f6-44e0-82ef-2f3845edaf58")
        token = self._signed_token(deletion_operation_id=foreign_operation_id)
        error = LogicalRestorationError(
            "RESTORATION_NOT_FOUND",
            "No se debe revelar la existencia de otra empresa.",
        )

        with patch(
            "tareas.views.restore_logical_task_tree",
            side_effect=error,
        ) as restore_service:
            response = self.client.post(
                self._url(foreign_operation_id),
                self._post_data(token),
            )

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(
            response,
            "No se debe revelar",
            status_code=404,
        )
        restore_service.assert_called_once()

    def test_stale_fingerprint_and_concurrent_state_conflict_return_409(self):
        _, token, _ = self._issue_preview()
        errors = (
            "RESTORATION_PREVIEW_STALE",
            "RESTORATION_STATE_CONFLICT",
        )

        with (
            patch("tareas.views.build_logical_restoration_preview") as preview_builder,
            patch("tareas.views.restore_logical_task_tree") as restore_service,
        ):
            for code in errors:
                with self.subTest(code=code):
                    restore_service.side_effect = LogicalRestorationError(
                        code,
                        "raw service details must not be shown",
                    )
                    response = self.client.post(
                        self._url(),
                        self._post_data(token),
                    )
                    self.assertEqual(response.status_code, 409)
                    self.assertNotContains(
                        response,
                        "raw service details",
                        status_code=409,
                    )

        preview_builder.assert_not_called()
        self.assertEqual(restore_service.call_count, 2)
        self.assertTrue(
            all(
                call.kwargs["expected_fingerprint"] == "a" * 64
                for call in restore_service.call_args_list
            )
        )

    def test_post_backend_unavailable_returns_controlled_503(self):
        _, token, _ = self._issue_preview()

        with patch(
            "tareas.views.restore_logical_task_tree",
            side_effect=LogicalRestorationError(
                "RESTORATION_BACKEND_UNAVAILABLE",
                "database credentials must not leak",
            ),
        ) as restore_service:
            response = self.client.post(
                self._url(),
                self._post_data(token),
            )

        self.assertEqual(response.status_code, 503)
        self.assertContains(
            response,
            "tareas.logical_restoration.preview.error.unavailable",
            status_code=503,
        )
        self.assertNotContains(
            response,
            "database credentials",
            status_code=503,
        )
        restore_service.assert_called_once()

    def test_same_uuid_retry_uses_original_token_without_a_new_preview(self):
        _, token, preview_builder = self._issue_preview()
        data = self._post_data(token)

        with (
            patch("tareas.views.build_logical_restoration_preview") as preview_again,
            patch(
                "tareas.views.restore_logical_task_tree",
                side_effect=(self._result(), self._result(replayed=True)),
            ) as restore_service,
        ):
            first_response = self.client.post(self._url(), data)
            retry_response = self.client.post(self._url(), data)

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(retry_response.status_code, 302)
        preview_builder.assert_called_once()
        preview_again.assert_not_called()
        self.assertEqual(restore_service.call_count, 2)
        self.assertEqual(
            [
                call.kwargs["restoration_operation_id"]
                for call in restore_service.call_args_list
            ],
            [self.restoration_operation_id, self.restoration_operation_id],
        )

    def test_second_preview_uuid_cannot_restore_the_same_deletion_again(self):
        second_restoration_id = UUID("2e1d980d-4413-44ee-a1d2-bfac2ac07b61")
        _, first_token, _ = self._issue_preview()
        _, second_token, _ = self._issue_preview(
            restoration_operation_id=second_restoration_id,
        )
        conflict = LogicalRestorationError(
            "RESTORATION_ALREADY_COMPLETED",
            "La eliminación ya fue restaurada.",
        )

        with patch(
            "tareas.views.restore_logical_task_tree",
            side_effect=(self._result(), conflict),
        ) as restore_service:
            first_response = self.client.post(
                self._url(),
                self._post_data(first_token),
            )
            second_response = self.client.post(
                self._url(),
                self._post_data(
                    second_token,
                    restoration_operation_id=second_restoration_id,
                ),
            )

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 409)
        self.assertEqual(
            [
                call.kwargs["restoration_operation_id"]
                for call in restore_service.call_args_list
            ],
            [self.restoration_operation_id, second_restoration_id],
        )

    def test_reusing_uuid_with_a_different_reason_is_a_controlled_conflict(self):
        _, token, _ = self._issue_preview()
        conflict = LogicalRestorationError(
            "RESTORATION_OPERATION_ID_CONFLICT",
            "The UUID is already bound to another request.",
        )

        with patch(
            "tareas.views.restore_logical_task_tree",
            side_effect=conflict,
        ) as restore_service:
            response = self.client.post(
                self._url(),
                self._post_data(token, motivo="Different reason"),
            )

        self.assertEqual(response.status_code, 409)
        restore_service.assert_called_once_with(
            actor=self.user,
            empresa_id=self.company.pk,
            deletion_operation_id=self.source_operation_id,
            restoration_operation_id=self.restoration_operation_id,
            motivo="Different reason",
            expected_fingerprint="a" * 64,
        )

    def test_audit_pending_and_error_are_reported_as_committed_via_l4(self):
        _, token, _ = self._issue_preview()
        pending_error = LogicalRestorationError(
            "RESTORATION_AUDIT_PENDING",
            "Restoration commit is confirmed; audit is pending.",
        )
        cases = (
            pending_error,
            self._result(
                audit_status=TareaEliminacionOperacion.EstadoAuditoria.ERROR,
            ),
        )
        expected_url = reverse(
            "tareas:eliminacion_operacion_detalle",
            kwargs={"operation_id": self.source_operation_id},
        )

        for service_result in cases:
            with self.subTest(service_result=service_result):
                with patch(
                    "tareas.views.restore_logical_task_tree",
                    side_effect=(
                        service_result
                        if isinstance(service_result, Exception)
                        else None
                    ),
                    return_value=(
                        None
                        if isinstance(service_result, Exception)
                        else service_result
                    ),
                ) as restore_service:
                    response = self.client.post(
                        self._url(),
                        self._post_data(token),
                    )

                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], expected_url)
                restore_service.assert_called_once()

    def test_audit_conflict_does_not_report_rollback_or_offer_another_restore(self):
        _, token, _ = self._issue_preview()
        with patch(
            "tareas.views.restore_logical_task_tree",
            side_effect=LogicalRestorationError(
                "RESTORATION_AUDIT_CONFLICT",
                "audit payload conflict",
            ),
        ) as restore_service:
            response = self.client.post(
                self._url(),
                self._post_data(token),
            )

        self.assertEqual(response.status_code, 409)
        self.assertContains(
            response,
            "La restauración operacional está confirmada",
            status_code=409,
        )
        self.assertNotContains(
            response,
            "Reintentar la misma operación",
            status_code=409,
        )
        restore_service.assert_called_once()

    def test_uncertain_commit_retry_keeps_the_same_uuid_and_token(self):
        _, token, preview_builder = self._issue_preview()
        data = self._post_data(token)
        uncertain = LogicalRestorationError(
            "RESTORATION_COMMIT_UNCERTAIN",
            "Unresolved commit outcome.",
            operation_id=self.restoration_operation_id,
        )

        with (
            patch("tareas.views.build_logical_restoration_preview") as preview_again,
            patch(
                "tareas.views.restore_logical_task_tree",
                side_effect=(uncertain, self._result(replayed=True)),
            ) as restore_service,
        ):
            pending_response = self.client.post(self._url(), data)
            retry_response = self.client.post(self._url(), data)

        self.assertEqual(pending_response.status_code, 503)
        self.assertContains(
            pending_response,
            "tareas.logical_restoration.preview.error.commit_uncertain",
            status_code=503,
        )
        self.assertContains(
            pending_response,
            self.restoration_operation_id.hex,
            status_code=503,
        )
        self.assertContains(
            pending_response,
            f'name="preview_token" value="{token}"',
            status_code=503,
        )
        self.assertContains(
            pending_response,
            f'name="restoration_operation_id" value="{self.restoration_operation_id.hex}"',
            status_code=503,
        )
        self.assertEqual(retry_response.status_code, 302)
        preview_builder.assert_called_once()
        preview_again.assert_not_called()
        self.assertEqual(restore_service.call_count, 2)
        self.assertTrue(
            all(
                call.kwargs["restoration_operation_id"]
                == self.restoration_operation_id
                for call in restore_service.call_args_list
            )
        )
        self.assertTrue(
            all(
                call.kwargs["expected_fingerprint"] == "a" * 64
                for call in restore_service.call_args_list
            )
        )

    def test_post_requires_i_and_s_even_for_eliminar_staff_or_superuser(self):
        permission_cases = (
            ("missing_i", {"supervisor": True}),
            ("missing_s", {"ingresar": True}),
            ("eliminar_without_s", {"ingresar": True, "eliminar": True}),
            ("staff_without_s", {"ingresar": True, "is_staff": True}),
            ("superuser_without_s", {"ingresar": True, "is_superuser": True}),
        )

        with (
            patch("tareas.views.build_logical_restoration_preview") as preview_builder,
            patch("tareas.views.restore_logical_task_tree") as restore_service,
        ):
            for name, permissions in permission_cases:
                with self.subTest(case=name):
                    user = create_user(f"restoration-post-{name}")
                    is_staff = permissions.pop("is_staff", False)
                    is_superuser = permissions.pop("is_superuser", False)
                    if is_staff or is_superuser:
                        user.is_staff = is_staff
                        user.is_superuser = is_superuser
                        user.save(update_fields=["is_staff", "is_superuser"])
                    self._grant(user=user, **permissions)
                    client = Client()
                    self._activate_company(user=user, client=client)

                    response = client.post(self._url(), {})

                    self.assertEqual(response.status_code, 403)

        preview_builder.assert_not_called()
        restore_service.assert_not_called()

    def test_post_requires_authentication_and_base00_company(self):
        unauthenticated_client = Client()
        with patch("tareas.views.restore_logical_task_tree") as restore_service:
            unauthenticated = unauthenticated_client.post(self._url(), {})
        self.assertEqual(unauthenticated.status_code, 302)
        self.assertIn("login", unauthenticated["Location"])
        restore_service.assert_not_called()

        self._grant(ingresar=True, supervisor=True, empresa=self.other_company)
        self._activate_company(self.other_company)
        with patch("tareas.views.restore_logical_task_tree") as restore_service:
            non_base00 = self.client.post(self._url(), {})
        self.assertEqual(non_base00.status_code, 302)
        self.assertIn("seleccionar_empresa", non_base00["Location"])
        restore_service.assert_not_called()

    def test_head_remains_disabled(self):
        self._grant(ingresar=True, supervisor=True)
        self._activate_company()
        response = self.client.head(self._url())
        self.assertEqual(response.status_code, 405)

    def test_l4_operation_link_is_visible_only_with_supervisor_permission(self):
        operation = SimpleNamespace(
            operation_id=self.source_operation_id,
            deletion_status="CURRENTLY_DELETED",
            actor_id=self.user.pk,
            root_task_id=84,
            root_correlativo="B0000084",
            motivo="Motivo original",
            created_at=datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc),
            committed_at=datetime(2026, 10, 20, 9, 1, tzinfo=timezone.utc),
            status="COMMITTED",
            result_code="LOGICALLY_DELETED",
            audit_status="CONFIRMED",
            audit_consistency="CONSISTENT",
            audit_event_id=1,
            file_cleanup_status="NOT_REQUIRED",
            hierarchy_status="COMPLETE",
            audit=None,
            restoration=None,
            items=(),
            files=(),
            relations=(),
        )
        operation_url = reverse(
            "tareas:eliminacion_operacion_detalle",
            kwargs={"operation_id": self.source_operation_id},
        )

        self._grant(ingresar=True, supervisor=True)
        self._activate_company()
        with patch(
            "tareas.views.get_deleted_task_history_operation",
            return_value=operation,
        ):
            with_supervisor = self.client.get(operation_url)

        self.assertEqual(with_supervisor.status_code, 200)
        self.assertContains(
            with_supervisor,
            reverse("tareas:restauracion_logica", kwargs={"operation_id": self.source_operation_id}),
        )

        reader = create_user("restoration-preview-history-reader")
        self._grant(ingresar=True, user=reader)
        self._activate_company(user=reader)
        with patch(
            "tareas.views.get_deleted_task_history_operation",
            return_value=operation,
        ):
            without_supervisor = self.client.get(operation_url)

        self.assertEqual(without_supervisor.status_code, 200)
        self.assertNotContains(
            without_supervisor,
            reverse("tareas:restauracion_logica", kwargs={"operation_id": self.source_operation_id}),
        )

    def test_get_does_not_write_ledger_or_task_markers(self):
        self._grant(ingresar=True, supervisor=True)
        self._activate_company()
        preview = self._preview()
        before = (
            TareaEliminacionOperacion.objects.count(),
            TareaEliminacionElemento.objects.count(),
        )

        with (
            patch(
                "tareas.views.build_logical_restoration_preview",
                return_value=preview,
            ),
            patch(
                "tareas.views.restore_logical_task_tree",
            ) as restore_service,
        ):
            response = self.client.get(self._url())

        after = (
            TareaEliminacionOperacion.objects.count(),
            TareaEliminacionElemento.objects.count(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(after, before)
        restore_service.assert_not_called()

    def test_preview_template_has_static_catalogued_i18n_keys(self):
        template_path = (
            Path(__file__).resolve().parents[1]
            / "templates"
            / "tareas"
            / "tarea_restauracion_logica_preview.html"
        )
        source = template_path.read_text(encoding="utf-8")
        keys = set(re.findall(r'data-key=["\']([^"\']+)["\']', source))
        self.assertTrue(keys)
        self.assertFalse(any("{{" in key or "{%" in key for key in keys))

        root = Path(__file__).resolve().parents[2]
        for language in ("sp", "en"):
            catalog = json.loads(
                (root / "static" / "lang" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
            with self.subTest(language=language):
                self.assertEqual(keys - catalog.keys(), set())

        audit = _PreviewI18nTextAudit()
        audit.feed(re.sub(
            r"\{% block title %\}.*?\{% endblock title %\}",
            "",
            source,
            flags=re.DOTALL,
        ))
        self.assertTrue(audit.keyed_text)
        self.assertEqual(audit.untranslated_text, [])
