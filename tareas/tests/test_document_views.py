from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from tareas.models import DocumentoHistorial, DocumentoTarea, EvidenciaCierre
from tareas.services.documents import create_document
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class DocumentViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="DV1")
        cls.otra_empresa = create_empresa(codigo="DV2")
        cls.usuario = create_user(username="document-view-user")
        assign_permission(cls.usuario, cls.empresa, "Tareas - Documentos y evidencia", modificar=True)
        cls.tarea = create_tarea(cls.empresa, cls.usuario, titulo="Tarea documentos")
        cls.tarea_externa = create_tarea(cls.otra_empresa, cls.usuario, titulo="Documento externo")

    def setUp(self):
        self.client.login(username="document-view-user", password="password-prueba")
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def test_get_muestra_documento_e_historial(self):
        documento = create_document(
            tarea=self.tarea,
            tipo=DocumentoTarea.Tipo.INFORME,
            usuario=self.usuario,
            url="https://example.com/informe",
            fecha_documento=date(2026, 9, 1),
        )
        response = self.client.get(reverse("tareas:documentos_tarea", args=[self.tarea.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, documento.url)
        self.assertContains(response, "CREADO")

    def test_post_crea_documento_url_con_fechas(self):
        response = self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {
                "accion": "documento",
                "tipo": DocumentoTarea.Tipo.CONTRATO,
                "url": "https://example.com/contrato",
                "fecha_documento": "2026-09-01",
                "fecha_vencimiento": "2027-09-01",
            },
        )
        self.assertRedirects(response, reverse("tareas:documentos_tarea", args=[self.tarea.pk]))
        documento = DocumentoTarea.objects.get(tarea=self.tarea)
        self.assertEqual(documento.fecha_vencimiento, date(2027, 9, 1))
        self.assertTrue(DocumentoHistorial.objects.filter(documento=documento).exists())

    def test_post_crea_documento_archivo(self):
        archivo = SimpleUploadedFile("informe.txt", b"contenido", content_type="text/plain")
        response = self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {
                "accion": "documento",
                "tipo": DocumentoTarea.Tipo.INFORME,
                "archivo": archivo,
                "fecha_documento": "2026-09-01",
            },
        )
        self.assertRedirects(response, reverse("tareas:documentos_tarea", args=[self.tarea.pk]))
        self.assertEqual(DocumentoTarea.objects.filter(tarea=self.tarea).count(), 1)

    def test_xor_archivo_url_se_refleja_en_formulario_y_no_muta(self):
        response = self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {
                "accion": "documento",
                "tipo": DocumentoTarea.Tipo.INFORME,
                "url": "https://example.com/informe",
                "archivo": SimpleUploadedFile("informe.txt", b"contenido"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "exactamente un archivo o una URL")
        self.assertFalse(DocumentoTarea.objects.filter(tarea=self.tarea).exists())

    def test_evidencia_configurable_y_registrable(self):
        documento = create_document(
            tarea=self.tarea,
            tipo=DocumentoTarea.Tipo.CERTIFICADO,
            usuario=self.usuario,
            url="https://example.com/certificado",
        )
        self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {"accion": "configurar_evidencia", "requerida": "on"},
        )
        self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {"accion": "registrar_evidencia", "documento": documento.pk},
        )
        evidencia = EvidenciaCierre.objects.get(tarea=self.tarea)
        self.assertTrue(evidencia.requerida)
        self.assertEqual(evidencia.documento, documento)

    def test_otra_empresa_no_es_accesible(self):
        response = self.client.get(reverse("tareas:documentos_tarea", args=[self.tarea_externa.pk]))
        self.assertEqual(response.status_code, 404)
