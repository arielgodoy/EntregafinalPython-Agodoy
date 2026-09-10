from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from tareas.models import HitoEvidencia
from tareas.services.progress import complete_milestone, create_milestone
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class HitoT081Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="81", descripcion="Empresa T081")
        cls.otra_empresa = create_empresa(codigo="82", descripcion="Otra T081")
        cls.manager = create_user("t081_manager")
        cls.owner = create_user("t081_owner")
        cls.observer = create_user("t081_observer")
        cls.no_access = create_user("t081_no_access")
        cls.foreign = create_user("t081_foreign")
        for user in [cls.manager, cls.owner, cls.observer]:
            assign_permission(user, cls.empresa, "Tareas - Hitos", ingresar=True)
        assign_permission(cls.manager, cls.empresa, "Tareas - Hitos", ingresar=True, modificar=True)
        assign_permission(cls.foreign, cls.otra_empresa, "Tareas - Hitos", ingresar=True)
        cls.tarea = create_tarea(
            cls.empresa,
            cls.manager,
            titulo="Tarea T081",
            responsable=cls.manager,
        )
        cls.hito = create_milestone(
            cls.tarea,
            "Hito pendiente T081",
            20,
            2,
            responsable=cls.owner,
            actor=cls.manager,
        )

    def _login_with_company(self, user, empresa=None):
        self.client.force_login(user)
        session = self.client.session
        session["empresa_id"] = (empresa or self.empresa).pk
        session.save()

    def _url(self):
        return f"/tareas/{self.tarea.pk}/hitos/"

    def _complete(self):
        complete_milestone(
            self.hito,
            self.owner,
            resena_cierre="Cierre documentado por correo.",
            formato_archivo="PDF",
            url="https://example.com/cierre.pdf",
        )
        self.hito.refresh_from_db()

    def test_pending_hito_does_not_show_completion_query(self):
        self._login_with_company(self.owner)
        response = self.client.get(self._url())
        self.assertNotContains(response, "Ver cumplimiento Hito")

    def test_completed_hito_shows_read_only_query_and_allowed_annul(self):
        self._complete()
        self._login_with_company(self.manager)
        response = self.client.get(self._url())
        content = response.content.decode()
        table = content[content.index("<table"):content.index("</table>")]
        self.assertIn("Ver cumplimiento Hito", table)
        self.assertIn(f'verCumplimientoHitoModal-{self.hito.pk}', table)
        self.assertIn("Anular", table)
        for text in ["Editar", "Reasignar", "Completar Hito", "Actualizar avance", "Eliminar"]:
            self.assertNotIn(text, table)

    def test_completion_modal_shows_canonical_fields_and_is_read_only(self):
        self._complete()
        self._login_with_company(self.owner)
        content = self.client.get(self._url()).content.decode()
        start = content.index(f'id="verCumplimientoHitoModal-{self.hito.pk}"')
        modal = content[start:content.index("id=\"crearHitoModal\"", start)]
        self.assertIn("Hito pendiente T081", modal)
        self.assertIn("Completado", modal)
        self.assertIn("t081_owner", modal)
        self.assertIn("Cierre documentado por correo.", modal)
        self.assertIn("https://example.com/cierre.pdf", modal)
        self.assertNotIn("<input", modal)
        self.assertNotIn("<select", modal)
        self.assertNotIn("<textarea", modal)
        self.assertIn("Cerrar", modal)

    def test_multiple_evidences_show_file_and_url_links(self):
        self._complete()
        evidencia_archivo = HitoEvidencia.objects.create(
            hito=self.hito,
            formato_archivo="JPG",
            archivo=SimpleUploadedFile("foto.jpg", b"image"),
            usuario=self.manager,
        )
        self._login_with_company(self.observer)
        content = self.client.get(self._url()).content.decode()
        self.assertIn("cierre.pdf", content)
        self.assertIn("https://example.com/cierre.pdf", content)
        self.assertIn(evidencia_archivo.archivo.name, content)
        self.assertIn("Ver archivo", content)
        self.assertIn("t081_owner", content)
        self.assertIn("t081_manager", content)
        self.assertIn('rel="noopener noreferrer"', content)
        self.assertEqual(content.count('id="verCumplimientoHitoModal-'), 1)

    def test_read_access_roles_can_consult_without_mutation(self):
        self._complete()
        self._login_with_company(self.owner)
        before = {
            "completado": self.hito.completado,
            "cumplimiento": self.hito.cumplimiento,
            "responsable_id": self.hito.responsable_id,
            "resena_cierre": self.hito.resena_cierre,
            "evidencias": self.hito.evidencias.count(),
        }
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.hito.refresh_from_db()
        self.assertEqual(self.hito.completado, before["completado"])
        self.assertEqual(self.hito.cumplimiento, before["cumplimiento"])
        self.assertEqual(self.hito.responsable_id, before["responsable_id"])
        self.assertEqual(self.hito.resena_cierre, before["resena_cierre"])
        self.assertEqual(self.hito.evidencias.count(), before["evidencias"])

        self._login_with_company(self.observer)
        self.assertEqual(self.client.get(self._url()).status_code, 200)

    def test_user_without_access_and_foreign_company_cannot_consult(self):
        self._complete()
        self._login_with_company(self.no_access)
        self.assertNotEqual(self.client.get(self._url()).status_code, 200)

        self._login_with_company(self.foreign, self.otra_empresa)
        self.assertNotEqual(self.client.get(self._url()).status_code, 200)
