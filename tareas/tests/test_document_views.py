from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from tareas.models import DocumentoHistorial, DocumentoTarea, EvidenciaCierre, FormatoArchivo
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
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            usuario=self.usuario,
            url="https://example.com/informe",
            fecha_documento=date(2026, 9, 1),
        )
        response = self.client.get(reverse("tareas:documentos_tarea", args=[self.tarea.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, documento.url)
        self.assertContains(response, "CREADO")

    def test_modal_evidencia_no_exige_documento_y_muestra_fuentes(self):
        response = self.client.get(reverse("tareas:documentos_tarea", args=[self.tarea.pk]))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        panel = content.split('id="evidenciaPanel"', 1)[1].split('id="agregarDocumentoModal"', 1)[0]
        modal = content.split('id="agregarEvidenciaModal"', 1)[1]
        modal_form = content.split('<form id="evidenciaRegistroForm"', 1)[1].split('</form>', 1)[0]

        self.assertIn('data-bs-target="#agregarEvidenciaModal"', panel)
        self.assertIn("Agregar evidencia", panel)
        self.assertNotIn('id="evidenciaConfigForm"', panel)
        self.assertNotIn("Requiere evidencia de cierre", panel)
        self.assertNotIn('name="formato_archivo"', panel)
        self.assertNotIn('name="archivo"', panel)
        self.assertNotIn('name="url"', panel)
        self.assertNotIn('id="evidenciaRegistroForm"', panel)
        self.assertEqual(panel.count("<form"), 0)
        self.assertEqual(panel.count("</form>"), 0)

        self.assertIn("Formato de archivo", modal_form)
        self.assertIn('name="formato_archivo"', modal_form)
        self.assertIn('name="archivo"', modal_form)
        self.assertIn('name="url"', modal_form)
        self.assertNotIn('name="documento"', modal_form)
        self.assertNotIn(">Documento<", modal_form)
        self.assertEqual(modal_form.count("<form"), 0)

    def test_pagina_carga_filtro_de_extensiones_para_documento_y_evidencia(self):
        response = self.client.get(reverse("tareas:documentos_tarea", args=[self.tarea.pk]))
        content = response.content.decode()

        self.assertContains(response, 'src="/static/tareas/js/documentos_evidencia.js"')
        self.assertEqual(content.count('name="formato_archivo"'), 2)
        self.assertEqual(content.count('name="archivo"'), 2)

        script_path = "tareas/static/tareas/js/documentos_evidencia.js"
        with open(script_path, encoding="utf-8") as script_file:
            script = script_file.read()
        for formato, accept in {
            "PDF": 'PDF: ".pdf"',
            "JPG": 'JPG: ".jpg,.jpeg"',
            "JPEG": 'JPEG: ".jpg,.jpeg"',
            "PNG": 'PNG: ".png"',
            "DOC": 'DOC: ".doc"',
            "DOCX": 'DOCX: ".docx"',
            "XLS": 'XLS: ".xls"',
            "XLSX": 'XLSX: ".xlsx"',
        }.items():
            self.assertIn(accept, script, formato)
        self.assertIn('select[name="formato_archivo"]', script)
        self.assertIn('input[type="file"][name="archivo"]', script)
        self.assertIn('addEventListener("change"', script)

    def test_get_muestra_altas_en_modales_y_configuracion_visible(self):
        response = self.client.get(reverse("tareas:documentos_tarea", args=[self.tarea.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-bs-target="#agregarDocumentoModal"')
        self.assertContains(response, 'id="agregarDocumentoModal"')
        self.assertContains(response, "Agregar documento")
        self.assertContains(response, "Tipo")
        self.assertContains(response, "Formato")
        self.assertContains(response, "Archivo")
        self.assertContains(response, "URL")
        self.assertContains(response, "Fecha documento")
        self.assertContains(response, "Fecha vencimiento")
        self.assertContains(response, 'data-bs-target="#agregarEvidenciaModal"')
        self.assertContains(response, 'id="agregarEvidenciaModal"')
        self.assertContains(response, "Agregar evidencia de cierre")
        self.assertContains(response, "Evidencias de cierre")
        self.assertEqual(response.content.decode().count('name="accion" value="documento"'), 1)
        self.assertEqual(
            response.content.decode().count('name="accion" value="registrar_evidencia"'),
            1,
        )

    def test_post_crea_documento_url_con_fechas(self):
        response = self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {
                "accion": "documento",
                "tipo": DocumentoTarea.Tipo.CONTRATO,
                "formato_archivo": DocumentoTarea.FormatoArchivo.PDF,
                "url": "https://example.com/contrato",
                "fecha_documento": "2026-09-01",
                "fecha_vencimiento": "2027-09-01",
            },
        )
        self.assertRedirects(response, reverse("tareas:documentos_tarea", args=[self.tarea.pk]))
        documento = DocumentoTarea.objects.get(tarea=self.tarea)
        self.assertEqual(documento.fecha_vencimiento, date(2027, 9, 1))
        self.assertTrue(DocumentoHistorial.objects.filter(documento=documento).exists())

    def test_listado_documentos_muestra_usuario_que_subio(self):
        create_document(
            tarea=self.tarea,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            usuario=self.usuario,
            url="https://example.com/informe.pdf",
        )

        response = self.client.get(reverse("tareas:documentos_tarea", args=[self.tarea.pk]))

        self.assertContains(response, "Subido por")
        self.assertContains(response, self.usuario.username)
        self.assertContains(response, "CREADO")

    def test_post_crea_documento_archivo(self):
        archivo = SimpleUploadedFile("informe.pdf", b"contenido", content_type="application/pdf")
        response = self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {
                "accion": "documento",
                "tipo": DocumentoTarea.Tipo.INFORME,
                "formato_archivo": DocumentoTarea.FormatoArchivo.PDF,
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
                "formato_archivo": DocumentoTarea.FormatoArchivo.PDF,
                "url": "https://example.com/informe",
                "archivo": SimpleUploadedFile("informe.txt", b"contenido"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "exactamente un archivo o una URL")
        self.assertContains(response, 'id="agregarDocumentoModal"')
        self.assertContains(response, 'class="modal fade show d-block"')
        self.assertContains(response, 'aria-hidden="false"')
        self.assertFalse(DocumentoTarea.objects.filter(tarea=self.tarea).exists())

    def test_post_invalido_evidencia_reabre_modal(self):
        response = self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {"accion": "registrar_evidencia"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="agregarEvidenciaModal"')
        self.assertContains(response, 'class="modal fade show d-block"')
        self.assertContains(response, 'aria-hidden="false"')
        self.assertContains(response, 'id="evidenciaRegistroForm"')
        self.assertTrue(response.context["evidencia_registro_form"].errors)

    def test_post_evidencia_rechaza_extension_y_preserva_sin_evidencia(self):
        response = self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {
                "accion": "registrar_evidencia",
                "formato_archivo": FormatoArchivo.JPG,
                "archivo": SimpleUploadedFile("Pago_cip.pdf", b"contenido"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="modal fade show d-block"')
        self.assertContains(response, "El formato declarado no coincide con la extensión de la evidencia.")
        self.assertIn(
            "formato_archivo",
            response.context["evidencia_registro_form"].errors,
        )
        self.assertFalse(EvidenciaCierre.objects.filter(tarea=self.tarea).exists())

    def test_post_evidencia_invalida_preserva_evidencia_existente(self):
        self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {
                "accion": "registrar_evidencia",
                "formato_archivo": FormatoArchivo.PDF,
                "archivo": SimpleUploadedFile("anterior.pdf", b"anterior"),
            },
        )
        anterior = EvidenciaCierre.objects.get(tarea=self.tarea)
        valores_anteriores = (anterior.formato_archivo, anterior.archivo.name, anterior.url, anterior.usuario_id, anterior.fecha)

        response = self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {
                "accion": "registrar_evidencia",
                "formato_archivo": FormatoArchivo.JPG,
                "archivo": SimpleUploadedFile("nuevo.pdf", b"nuevo"),
            },
        )

        self.assertEqual(response.status_code, 200)
        actual = EvidenciaCierre.objects.get(tarea=self.tarea)
        self.assertEqual(
            (actual.formato_archivo, actual.archivo.name, actual.url, actual.usuario_id, actual.fecha),
            valores_anteriores,
        )

    def test_post_evidencia_registra_pdf_y_jpg_validos(self):
        response = self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {
                "accion": "registrar_evidencia",
                "formato_archivo": FormatoArchivo.PDF,
                "archivo": SimpleUploadedFile("pago.pdf", b"pdf"),
            },
        )
        self.assertRedirects(response, reverse("tareas:documentos_tarea", args=[self.tarea.pk]))
        evidencia = EvidenciaCierre.objects.get(tarea=self.tarea)
        self.assertEqual(evidencia.formato_archivo, FormatoArchivo.PDF)

        response = self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {
                "accion": "registrar_evidencia",
                "formato_archivo": FormatoArchivo.JPG,
                "archivo": SimpleUploadedFile("pago.jpg", b"jpg"),
            },
        )
        self.assertRedirects(response, reverse("tareas:documentos_tarea", args=[self.tarea.pk]))
        evidencia.refresh_from_db()
        self.assertEqual(EvidenciaCierre.objects.filter(tarea=self.tarea).count(), 2)
        self.assertEqual(
            set(EvidenciaCierre.objects.filter(tarea=self.tarea).values_list("formato_archivo", flat=True)),
            {FormatoArchivo.PDF, FormatoArchivo.JPG},
        )

    def test_evidencia_configurable_y_registrable(self):
        self.client.post(
            reverse("tareas:documentos_tarea", args=[self.tarea.pk]),
            {
                "accion": "registrar_evidencia",
                "formato_archivo": FormatoArchivo.PDF,
                "url": "https://example.com/evidencia",
            },
        )
        evidencia = EvidenciaCierre.objects.get(tarea=self.tarea)
        self.assertIsNone(evidencia.documento)
        self.assertEqual(evidencia.formato_archivo, FormatoArchivo.PDF)
        self.assertEqual(evidencia.url, "https://example.com/evidencia")
        response = self.client.get(reverse("tareas:documentos_tarea", args=[self.tarea.pk]))
        self.assertContains(response, "Formato")
        self.assertContains(response, "PDF")
        self.assertContains(response, "https://example.com/evidencia")

    def test_otra_empresa_no_es_accesible(self):
        response = self.client.get(reverse("tareas:documentos_tarea", args=[self.tarea_externa.pk]))
        self.assertEqual(response.status_code, 404)
