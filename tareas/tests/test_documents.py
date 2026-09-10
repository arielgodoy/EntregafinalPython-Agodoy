from datetime import date
from importlib import import_module

from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import TestCase

from tareas.models import DocumentoHistorial, DocumentoTarea, EvidenciaCierre, FormatoArchivo
from tareas.services.documents import (
    configure_closure_evidence,
    create_document,
    register_closure_evidence,
    update_document,
)
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class DocumentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa()
        cls.usuario = create_user(username="documents-user")
        cls.tarea = create_tarea(cls.empresa, cls.usuario)
        assign_permission(cls.usuario, cls.empresa, "Tareas - Listado", ingresar=True)

    def test_tarea_evidence_requirement_defaults_false(self):
        self.assertFalse(self.tarea.requiere_evidencia_cierre)
        self.assertTrue(EvidenciaCierre._meta.get_field("tarea").many_to_one)
        self.assertFalse(EvidenciaCierre._meta.get_field("tarea").one_to_one)
        self.assertNotIn("requerida", {field.name for field in EvidenciaCierre._meta.fields})

    def test_configuration_does_not_create_evidence(self):
        configure_closure_evidence(
            tarea=self.tarea,
            usuario=self.usuario,
            requiere_evidencia_cierre=True,
        )
        self.tarea.refresh_from_db()
        self.assertTrue(self.tarea.requiere_evidencia_cierre)
        self.assertFalse(EvidenciaCierre.objects.filter(tarea=self.tarea).exists())

    def test_task_accepts_multiple_independent_evidences(self):
        primera = register_closure_evidence(
            tarea=self.tarea,
            usuario=self.usuario,
            formato_archivo=FormatoArchivo.PDF,
            url="https://example.com/primera.pdf",
        )
        segunda = register_closure_evidence(
            tarea=self.tarea,
            usuario=self.usuario,
            formato_archivo=FormatoArchivo.JPG,
            url="https://example.com/segunda.jpg",
        )
        self.assertNotEqual(primera.pk, segunda.pk)
        self.assertEqual(EvidenciaCierre.objects.filter(tarea=self.tarea).count(), 2)

    def test_document_types_and_informational_dates(self):
        self.assertEqual(
            {choice.value for choice in DocumentoTarea.Tipo},
            {
                "COTIZACION",
                "FOTOGRAFIA",
                "INFORME",
                "ORDEN_TRABAJO",
                "FACTURA",
                "CONTRATO",
                "PLANO",
                "CERTIFICADO",
                "OTRO",
            },
        )
        self.assertEqual(
            {choice.value for choice in DocumentoTarea.FormatoArchivo},
            {"PDF", "JPG", "JPEG", "PNG", "DOC", "DOCX", "XLS", "XLSX"},
        )
        documento = create_document(
            tarea=self.tarea,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            usuario=self.usuario,
            url="https://example.com/informe",
            fecha_documento=date(2026, 9, 1),
            fecha_vencimiento=date(2027, 9, 1),
        )
        self.assertEqual(documento.fecha_documento, date(2026, 9, 1))
        self.assertEqual(documento.fecha_vencimiento, date(2027, 9, 1))

    def test_document_supports_file_or_url_but_not_both(self):
        archivo = create_document(
            tarea=self.tarea,
            tipo=DocumentoTarea.Tipo.FOTOGRAFIA,
            formato_archivo=DocumentoTarea.FormatoArchivo.JPG,
            usuario=self.usuario,
            archivo="tareas/documentos/foto.jpg",
        )
        self.assertEqual(archivo.archivo.name, "tareas/documentos/foto.jpg")
        with self.assertRaises(ValidationError):
            create_document(
                tarea=self.tarea,
                tipo=DocumentoTarea.Tipo.INFORME,
                formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
                usuario=self.usuario,
                archivo="tareas/documentos/informe.pdf",
                url="https://example.com/informe",
            )
    def test_document_history_is_recorded_on_create_and_update(self):
        documento = create_document(
            tarea=self.tarea,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            usuario=self.usuario,
            url="https://example.com/v1",
        )
        update_document(documento, self.usuario, url="https://example.com/v2")

        historial = list(DocumentoHistorial.objects.filter(documento=documento))
        self.assertEqual([registro.accion for registro in historial], ["CREADO", "ACTUALIZADO"])
        self.assertEqual(historial[0].usuario, self.usuario)
        self.assertEqual(historial[1].usuario, self.usuario)
        self.assertIsNotNone(historial[0].fecha)
        self.assertIsNotNone(historial[1].fecha)

    def test_closure_evidence_is_configurable_and_registerable(self):
        configurada = configure_closure_evidence(
            tarea=self.tarea,
            usuario=self.usuario,
            requiere_evidencia_cierre=True,
        )
        registrada = register_closure_evidence(
            tarea=self.tarea,
            usuario=self.usuario,
            formato_archivo=FormatoArchivo.PDF,
            url="https://example.com/evidencia",
        )

        self.assertIs(configurada, self.tarea)
        self.tarea.refresh_from_db()
        self.assertTrue(self.tarea.requiere_evidencia_cierre)
        self.assertIsNone(registrada.documento)
        self.assertEqual(registrada.formato_archivo, FormatoArchivo.PDF)
        self.assertEqual(registrada.url, "https://example.com/evidencia")

    def test_document_and_evidence_reject_other_company_context(self):
        otra_empresa = create_empresa(codigo="02")
        otro_usuario = create_user(username="other-documents-user")
        otra_tarea = create_tarea(otra_empresa, otro_usuario)
        assign_permission(otro_usuario, otra_empresa, "Tareas - Listado", ingresar=True)

        with self.assertRaises(ValidationError):
            create_document(
                tarea=self.tarea,
                tipo=DocumentoTarea.Tipo.OTRO,
                formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
                usuario=otro_usuario,
                url="https://example.com/otro",
            )

        documento = create_document(
            tarea=otra_tarea,
            tipo=DocumentoTarea.Tipo.OTRO,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            usuario=otro_usuario,
            url="https://example.com/otro",
        )
        with self.assertRaises(ValidationError):
            register_closure_evidence(
                tarea=otra_tarea,
                usuario=self.usuario,
                formato_archivo=FormatoArchivo.PDF,
                url="https://example.com/otro",
            )

    def test_evidence_has_own_source_and_requires_xor(self):
        evidencia = register_closure_evidence(
            tarea=self.tarea,
            usuario=self.usuario,
            formato_archivo=FormatoArchivo.PDF,
            archivo="tareas/evidencias/evidencia.pdf",
        )
        self.assertEqual(evidencia.archivo.name, "tareas/evidencias/evidencia.pdf")
        self.assertEqual(evidencia.url, "")
        with self.assertRaises(ValidationError):
            register_closure_evidence(
                tarea=self.tarea,
                usuario=self.usuario,
                formato_archivo=FormatoArchivo.PDF,
                archivo="tareas/evidencias/evidencia.pdf",
                url="https://example.com/evidencia",
            )

    def test_evidence_formats_match_file_extensions(self):
        for formato, nombre in [
            (FormatoArchivo.PDF, "evidencia.pdf"),
            (FormatoArchivo.JPG, "foto.jpg"),
            (FormatoArchivo.JPEG, "foto.jpeg"),
            (FormatoArchivo.PNG, "foto.png"),
            (FormatoArchivo.DOC, "archivo.doc"),
            (FormatoArchivo.DOCX, "archivo.docx"),
            (FormatoArchivo.XLS, "planilla.xls"),
            (FormatoArchivo.XLSX, "planilla.xlsx"),
        ]:
            evidencia = register_closure_evidence(
                tarea=self.tarea,
                usuario=self.usuario,
                formato_archivo=formato,
                archivo=f"tareas/evidencias/{nombre}",
            )
            self.assertEqual(evidencia.formato_archivo, formato)
        with self.assertRaises(ValidationError):
            register_closure_evidence(
                tarea=self.tarea,
                usuario=self.usuario,
                formato_archivo=FormatoArchivo.PDF,
                archivo="tareas/evidencias/evidencia.jpg",
            )

    def test_evidence_url_without_detectable_extension_is_valid(self):
        evidencia = register_closure_evidence(
            tarea=self.tarea,
            usuario=self.usuario,
            formato_archivo=FormatoArchivo.PDF,
            url="https://example.com/evidencia",
        )
        self.assertEqual(evidencia.url, "https://example.com/evidencia")

    def test_document_remains_available_when_evidence_is_direct(self):
        documento = create_document(
            tarea=self.tarea,
            tipo=DocumentoTarea.Tipo.CERTIFICADO,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            usuario=self.usuario,
            url="https://example.com/documento",
        )
        evidencia = register_closure_evidence(
            tarea=self.tarea,
            usuario=self.usuario,
            formato_archivo=FormatoArchivo.PDF,
            url="https://example.com/evidencia",
        )
        self.assertTrue(DocumentoTarea.objects.filter(pk=documento.pk).exists())
        self.assertIsNone(evidencia.documento)

    def test_evidence_migration_copies_historical_document_source(self):
        documento = create_document(
            tarea=self.tarea,
            tipo=DocumentoTarea.Tipo.CERTIFICADO,
            formato_archivo=FormatoArchivo.PDF,
            usuario=self.usuario,
            url="https://example.com/historico.pdf",
        )
        evidencia = EvidenciaCierre.objects.create(
            tarea=self.tarea,
            documento=documento,
            usuario=self.usuario,
        )
        migration = import_module("tareas.migrations.0016_evidenciacierre_direct_source")
        migration.copy_historical_evidence(apps, None)

        evidencia.refresh_from_db()
        self.assertEqual(evidencia.formato_archivo, FormatoArchivo.PDF)
        self.assertEqual(evidencia.url, "https://example.com/historico.pdf")
        self.assertEqual(evidencia.archivo.name, "")
        self.assertTrue(DocumentoTarea.objects.filter(pk=documento.pk).exists())
    def test_format_matches_file_extension(self):
        for formato, nombre in [
            (DocumentoTarea.FormatoArchivo.PDF, "evidencia.pdf"),
            (DocumentoTarea.FormatoArchivo.JPG, "foto.jpg"),
            (DocumentoTarea.FormatoArchivo.JPEG, "foto.jpeg"),
            (DocumentoTarea.FormatoArchivo.DOCX, "informe.docx"),
            (DocumentoTarea.FormatoArchivo.XLSX, "planilla.xlsx"),
        ]:
            documento = create_document(
                tarea=self.tarea,
                tipo=DocumentoTarea.Tipo.OTRO,
                formato_archivo=formato,
                usuario=self.usuario,
                archivo=f"tareas/documentos/{nombre}",
            )
            self.assertEqual(documento.formato_archivo, formato)

    def test_format_rejects_incompatible_file_extension(self):
        with self.assertRaises(ValidationError):
            create_document(
                tarea=self.tarea,
                tipo=DocumentoTarea.Tipo.INFORME,
                formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
                usuario=self.usuario,
                archivo="tareas/documentos/foto.jpg",
            )

    def test_url_format_is_checked_only_when_extension_is_known(self):
        documento = create_document(
            tarea=self.tarea,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            usuario=self.usuario,
            url="https://example.com/documento",
        )
        self.assertEqual(documento.formato_archivo, DocumentoTarea.FormatoArchivo.PDF)
        with self.assertRaises(ValidationError):
            create_document(
                tarea=self.tarea,
                tipo=DocumentoTarea.Tipo.INFORME,
                formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
                usuario=self.usuario,
                url="https://example.com/foto.jpg",
            )
