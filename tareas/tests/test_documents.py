from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from tareas.models import DocumentoHistorial, DocumentoTarea, EvidenciaCierre
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
        documento = create_document(
            tarea=self.tarea,
            tipo=DocumentoTarea.Tipo.INFORME,
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
            usuario=self.usuario,
            archivo="tareas/documentos/foto.jpg",
        )
        self.assertEqual(archivo.archivo.name, "tareas/documentos/foto.jpg")
        with self.assertRaises(ValidationError):
            create_document(
                tarea=self.tarea,
                tipo=DocumentoTarea.Tipo.INFORME,
                usuario=self.usuario,
                archivo="tareas/documentos/informe.pdf",
                url="https://example.com/informe",
            )

    def test_document_history_is_recorded_on_create_and_update(self):
        documento = create_document(
            tarea=self.tarea,
            tipo=DocumentoTarea.Tipo.INFORME,
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
            requerida=True,
        )
        documento = create_document(
            tarea=self.tarea,
            tipo=DocumentoTarea.Tipo.CERTIFICADO,
            usuario=self.usuario,
            url="https://example.com/certificado",
        )
        registrada = register_closure_evidence(
            tarea=self.tarea,
            documento=documento,
            usuario=self.usuario,
        )

        self.assertIsInstance(configurada, EvidenciaCierre)
        self.assertEqual(registrada.documento, documento)
        self.assertTrue(registrada.requerida)

    def test_document_and_evidence_reject_other_company_context(self):
        otra_empresa = create_empresa(codigo="02")
        otro_usuario = create_user(username="other-documents-user")
        otra_tarea = create_tarea(otra_empresa, otro_usuario)
        assign_permission(otro_usuario, otra_empresa, "Tareas - Listado", ingresar=True)

        with self.assertRaises(ValidationError):
            create_document(
                tarea=self.tarea,
                tipo=DocumentoTarea.Tipo.OTRO,
                usuario=otro_usuario,
                url="https://example.com/otro",
            )

        documento = create_document(
            tarea=otra_tarea,
            tipo=DocumentoTarea.Tipo.OTRO,
            usuario=otro_usuario,
            url="https://example.com/otro",
        )
        with self.assertRaises(ValidationError):
            register_closure_evidence(
                tarea=self.tarea,
                documento=documento,
                usuario=self.usuario,
            )