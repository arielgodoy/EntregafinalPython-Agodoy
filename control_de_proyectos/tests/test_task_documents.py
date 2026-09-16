from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from access_control.services.permissions import ensure_user_view_permissions
from access_control.services.view_catalog import audit_protected_views, discover_protected_views
from control_de_proyectos.models import ClienteEmpresa, Proyecto, Tarea, TareaDocumento
from control_de_proyectos.views import SubirDocumentoTareaView


class TaskDocumentsViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="document-user", password="pass")
        self.other_user = User.objects.create_user(username="other-document-user", password="pass")
        self.empresa = Empresa.objects.create(codigo="06", descripcion="Empresa 06")
        self.other_empresa = Empresa.objects.create(codigo="07", descripcion="Empresa 07")
        self.vista = Vista.objects.create(nombre="Control de Proyectos - Documentos de Tarea")
        self.legacy_vista = Vista.objects.create(nombre="Control de Proyectos - Subir documento de tarea")
        self.permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            crear=True,
            modificar=True,
        )
        self.legacy_permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.legacy_vista,
            crear=True,
        )
        cliente = ClienteEmpresa.objects.create(
            nombre="Cliente Documentos",
            rut="11.111.111-1",
        )
        self.tarea = self._create_task(self.empresa, cliente, "Tarea propia")
        self.other_tarea = self._create_task(self.other_empresa, cliente, "Tarea ajena")
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    @staticmethod
    def _create_task(empresa, cliente, nombre):
        proyecto = Proyecto.objects.create(
            nombre=f"Proyecto {nombre}",
            descripcion="Proyecto documental",
            empresa_interna=empresa,
            cliente=cliente,
            tipo_texto="Tipo",
        )
        return Tarea.objects.create(proyecto=proyecto, nombre=nombre)

    def test_metadata_and_catalog_use_document_mother_view(self):
        self.assertEqual(
            SubirDocumentoTareaView.vista_nombre,
            "Control de Proyectos - Documentos de Tarea",
        )
        self.assertEqual(SubirDocumentoTareaView.permiso_requerido, "crear")
        self.assertEqual(
            sum(
                definition.vista_nombre == "Control de Proyectos - Documentos de Tarea"
                for definition in discover_protected_views()
            ),
            1,
        )
        _, issues = audit_protected_views()
        self.assertFalse(
            any(
                issue.route_name == "control_de_proyectos:subir_documento_tarea"
                for issue in issues
            )
        )

    def test_missing_mother_permission_is_deny_by_default(self):
        self.permission.delete()

        response = self.client.post(
            reverse("control_de_proyectos:subir_documento_tarea", args=[self.tarea.id]),
            {"nombre_documento": "Especificación", "tipo_doc": "ENTRADA", "url_documento": "https://example.com/doc"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(TareaDocumento.objects.exists())

    def test_upload_requires_active_company_scope(self):
        response = self.client.post(
            reverse("control_de_proyectos:subir_documento_tarea", args=[self.other_tarea.id]),
            {"nombre_documento": "Documento ajeno", "tipo_doc": "ENTRADA", "url_documento": "https://example.com/doc"},
        )

        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(TareaDocumento.objects.exists())

    def test_upload_creates_document_and_assigns_responsible_user(self):
        response = self.client.post(
            reverse("control_de_proyectos:subir_documento_tarea", args=[self.tarea.id]),
            {"nombre_documento": "Especificación", "tipo_doc": "ENTRADA", "url_documento": "https://example.com/doc"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        document = TareaDocumento.objects.get()
        self.assertEqual(document.tarea, self.tarea)
        self.assertEqual(document.responsable, self.user)
        self.assertEqual(document.url_documento, "https://example.com/doc")

    def test_existing_mother_flags_are_not_reset(self):
        ensure_user_view_permissions(self.user, self.empresa.id, view_names=[self.vista.nombre])

        self.permission.refresh_from_db()
        self.assertTrue(self.permission.crear)
        self.assertTrue(self.permission.modificar)
        self.assertFalse(self.permission.eliminar)

    def test_legacy_permission_does_not_control_active_endpoint(self):
        self.permission.delete()

        response = self.client.post(
            reverse("control_de_proyectos:subir_documento_tarea", args=[self.tarea.id]),
            {"nombre_documento": "Documento", "tipo_doc": "ENTRADA", "url_documento": "https://example.com/doc"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Permiso.objects.filter(pk=self.legacy_permission.pk).exists())
