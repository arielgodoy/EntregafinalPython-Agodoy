from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


class PersonaImportProgressEndpointsTests(TestCase):
    def setUp(self):
        cache.clear()

        self.user = User.objects.create_user(username="u", password="p")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 1")
        self.vista = Vista.objects.create(nombre="Evaluaciones - Importar Personas")
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=True,
        )

        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session.save()
        self.session_key = session.session_key

    def _ajax_headers(self):
        return {
            "HTTP_ACCEPT": "application/json",
            "HTTP_X_REQUESTED_WITH": "XMLHttpRequest",
        }

    def test_import_start_requires_permission(self):
        user2 = User.objects.create_user(username="u2", password="p")
        self.client.force_login(user2)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session.save()

        url = reverse("evaluaciones:importar_personas_start")
        resp = self.client.post(url, {"date": "2026-03-07"}, **self._ajax_headers())
        self.assertEqual(resp.status_code, 403)
        payload = resp.json()
        self.assertFalse(payload.get("success"))
        self.assertIn("error", payload)

    def test_import_status_requires_permission(self):
        user2 = User.objects.create_user(username="u2", password="p")
        self.client.force_login(user2)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session.save()

        url = reverse("evaluaciones:importar_personas_status")
        resp = self.client.get(url, **self._ajax_headers())
        self.assertEqual(resp.status_code, 403)
        payload = resp.json()
        self.assertFalse(payload.get("success"))
        self.assertIn("error", payload)

    def test_import_status_returns_controlled_json(self):
        url = reverse("evaluaciones:importar_personas_status")
        resp = self.client.get(url, **self._ajax_headers())

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload.get("success"))

        for key in (
            "status",
            "current_page",
            "total_pages",
            "total_received",
            "created",
            "updated",
            "omitted",
            "errors",
            "message_key",
            "started_at",
            "finished_at",
        ):
            self.assertIn(key, payload)

    @patch("evaluaciones.services.persona_import_job._spawn_persona_import_thread")
    def test_start_sets_running_status(self, mock_spawn):
        mock_spawn.return_value = None

        url = reverse("evaluaciones:importar_personas_start")
        resp = self.client.post(url, {"date": "2026-03-07"}, **self._ajax_headers())

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))

        status_url = reverse("evaluaciones:importar_personas_status")
        status_resp = self.client.get(status_url, **self._ajax_headers())
        self.assertEqual(status_resp.status_code, 200)

        status_payload = status_resp.json()
        self.assertEqual(status_payload.get("status"), "running")
        self.assertEqual(status_payload.get("message_key"), "evaluaciones.personas.import.progress_starting")

    def test_status_updates_with_mocked_progress(self):
        from evaluaciones.services import persona_import_job
        from evaluaciones.services.persona_importer import PersonaImportResult

        status_key = persona_import_job.build_persona_import_cache_key(
            user_id=self.user.id,
            empresa_id=self.empresa.id,
            session_key=self.session_key,
        )

        def fake_import(date_value, exclude_pending, request_user=None, progress_callback=None):
            if progress_callback:
                progress_callback(
                    {
                        "message_key": "evaluaciones.personas.import.in_progress",
                        "current_page": 1,
                        "total_pages": 3,
                        "total_received": 50,
                    }
                )
                mid = persona_import_job.get_status(status_key=status_key)
                self.assertEqual(mid.get("current_page"), 1)
                self.assertEqual(mid.get("total_received"), 50)

            if progress_callback:
                progress_callback(
                    {
                        "message_key": "evaluaciones.personas.import.in_progress",
                        "current_page": 2,
                        "total_pages": 3,
                        "total_received": 100,
                    }
                )

            return PersonaImportResult(
                total_recibidos=100,
                creados=1,
                actualizados=2,
                omitidos=3,
                errores=4,
                paginas_procesadas=2,
            )

        def spawn_sync(*, status_key: str, date_str: str, exclude_pending: bool):
            persona_import_job._run_persona_import(
                status_key=status_key,
                date_str=date_str,
                exclude_pending=exclude_pending,
            )

        with patch("evaluaciones.services.persona_import_job.importar_personas_desde_api_interna", side_effect=fake_import):
            with patch("evaluaciones.services.persona_import_job._spawn_persona_import_thread", side_effect=spawn_sync):
                url = reverse("evaluaciones:importar_personas_start")
                resp = self.client.post(url, {"date": "2026-03-07"}, **self._ajax_headers())
                self.assertEqual(resp.status_code, 200)

        status_url = reverse("evaluaciones:importar_personas_status")
        status_resp = self.client.get(status_url, **self._ajax_headers())
        self.assertEqual(status_resp.status_code, 200)

        status_payload = status_resp.json()
        self.assertEqual(status_payload.get("status"), "success")
        self.assertEqual(status_payload.get("total_received"), 100)
        self.assertEqual(status_payload.get("created"), 1)
        self.assertEqual(status_payload.get("updated"), 2)
        self.assertEqual(status_payload.get("omitted"), 3)
        self.assertEqual(status_payload.get("errors"), 4)
