from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from PIL import TiffImagePlugin

from proveedores.models import Proveedor
from tareas.models import (
    Cotizacion,
    DocumentoCotizacion,
    DocumentoTarea,
    EvidenciaCierre,
    Hito,
    HitoEvidencia,
    RondaCotizacion,
    Tarea,
)
from tareas.services.comments import create_comment
from tareas.services.documents import create_document, register_closure_evidence
from tareas.services.image_processing import optimize_uploaded_image
from tareas.services.progress import complete_milestone
from tareas.services.quotations import add_quotation_document, create_quotation, create_quotation_round
from tareas.tests.factories import assign_permission, configure_task_storage, create_empresa, create_tarea, create_user


def upload_image(name, image_format, image, **save_kwargs):
    buffer = BytesIO()
    image.save(buffer, format=image_format, **save_kwargs)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f"image/{image_format.lower()}")


def read_uploaded_file(uploaded_file):
    uploaded_file.seek(0)
    return uploaded_file.read()


class ImageProcessingTests(TestCase):
    def test_large_jpeg_is_resized_and_smaller(self):
        image = Image.effect_noise((2400, 1800), 90).convert("RGB")
        source = upload_image("large.jpg", "JPEG", image, quality=95)
        original_size = len(read_uploaded_file(source))

        result = optimize_uploaded_image(source, DocumentoTarea.FormatoArchivo.JPG)

        with Image.open(BytesIO(read_uploaded_file(result))) as processed:
            self.assertEqual(processed.format, "JPEG")
            self.assertLessEqual(max(processed.size), 1600)
            self.assertLess(len(read_uploaded_file(result)), original_size)

    def test_small_jpeg_is_not_upscaled_and_exif_is_removed(self):
        image = Image.new("RGB", (80, 40), "red")
        exif = image.getexif()
        exif[274] = 6
        exif[34853] = {
            1: "N",
            2: (
                TiffImagePlugin.IFDRational(33, 1),
                TiffImagePlugin.IFDRational(26, 1),
                TiffImagePlugin.IFDRational(0, 1),
            ),
        }
        source = upload_image("small.jpg", "JPEG", image, exif=exif)

        result = optimize_uploaded_image(source, DocumentoTarea.FormatoArchivo.JPG)

        with Image.open(BytesIO(read_uploaded_file(result))) as processed:
            self.assertEqual(processed.size, (40, 80))
            self.assertEqual(dict(processed.getexif()), {})
            self.assertNotIn(34853, processed.getexif())

    def test_png_preserves_alpha_and_resizes_without_conversion(self):
        image = Image.new("RGBA", (2400, 1200), (10, 20, 30, 90))
        source = upload_image("large.png", "PNG", image)

        result = optimize_uploaded_image(source, DocumentoTarea.FormatoArchivo.PNG)

        with Image.open(BytesIO(read_uploaded_file(result))) as processed:
            self.assertEqual(processed.format, "PNG")
            self.assertEqual(processed.mode, "RGBA")
            self.assertEqual(processed.getpixel((0, 0))[3], 90)
            self.assertEqual(processed.size, (1600, 800))

    def test_small_png_is_not_upscaled(self):
        source = upload_image("small.png", "PNG", Image.new("RGB", (40, 20), "blue"))

        result = optimize_uploaded_image(source, DocumentoTarea.FormatoArchivo.PNG)

        with Image.open(BytesIO(read_uploaded_file(result))) as processed:
            self.assertEqual(processed.size, (40, 20))

    def test_fake_jpeg_and_png_are_rejected(self):
        for name, formato in (("fake.jpg", DocumentoTarea.FormatoArchivo.JPG), ("fake.png", DocumentoTarea.FormatoArchivo.PNG)):
            with self.subTest(name=name):
                source = SimpleUploadedFile(name, b"not an image", content_type="image/jpeg")
                with self.assertRaises(ValidationError):
                    optimize_uploaded_image(source, formato)

    def test_corrupt_image_is_rejected(self):
        source = SimpleUploadedFile("corrupt.jpg", b"\xff\xd8\xff\xd9", content_type="image/jpeg")

        with self.assertRaises(ValidationError):
            optimize_uploaded_image(source, DocumentoTarea.FormatoArchivo.JPG)

    def test_images_over_sixty_megapixels_are_rejected(self):
        class FakeImage:
            format = "JPEG"
            size = (8001, 7500)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def verify(self):
                return None

            def load(self):
                return None

            def close(self):
                return None

        fake_image = FakeImage()
        source = SimpleUploadedFile("huge.jpg", b"image", content_type="image/jpeg")

        with patch("tareas.services.image_processing.Image.open", return_value=fake_image):
            with self.assertRaises(ValidationError):
                optimize_uploaded_image(source, DocumentoTarea.FormatoArchivo.JPG)

    def test_decompression_bomb_is_rejected(self):
        source = SimpleUploadedFile("bomb.jpg", b"image", content_type="image/jpeg")

        with patch(
            "tareas.services.image_processing.Image.open",
            side_effect=Image.DecompressionBombError("too many pixels"),
        ):
            with self.assertRaises(ValidationError):
                optimize_uploaded_image(source, DocumentoTarea.FormatoArchivo.JPG)

    def test_non_image_bytes_are_returned_unchanged(self):
        for name, formato, content in (
            ("document.pdf", DocumentoTarea.FormatoArchivo.PDF, b"%PDF-1.7\r\nnot processed"),
            ("document.docx", DocumentoTarea.FormatoArchivo.DOCX, b"docx-bytes"),
            ("spreadsheet.xlsx", DocumentoTarea.FormatoArchivo.XLSX, b"xlsx-bytes"),
        ):
            with self.subTest(name=name):
                source = SimpleUploadedFile(name, content, content_type="application/octet-stream")
                result = optimize_uploaded_image(source, formato)
                self.assertEqual(read_uploaded_file(result), content)


class ImagePersistenceIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        configure_task_storage()
        cls.empresa = create_empresa(codigo="IMG")
        cls.usuario = create_user(username="image-user")
        assign_permission(cls.usuario, cls.empresa, "Tareas - Hitos", ingresar=True, crear=True, modificar=True)
        cls.tarea = create_tarea(cls.empresa, cls.usuario, responsable=cls.usuario)
        cls.tarea.estado = Tarea.Estado.ACTIVA
        cls.tarea.fecha_publicacion = timezone.now()
        cls.tarea.save(update_fields=["estado", "fecha_publicacion"])
        cls.proveedor = Proveedor.objects.create(nombre="Image provider")
        assign_permission(
            cls.usuario,
            cls.empresa,
            "Tareas",
            ingresar=True,
            crear=True,
            modificar=True,
        )

    def _jpeg(self, name="foto.jpg"):
        return upload_image(name, "JPEG", Image.effect_noise((2200, 1400), 90).convert("RGB"), quality=95)

    def test_document_tarea_uses_optimized_image(self):
        documento = create_document(
            tarea=self.tarea,
            tipo=DocumentoTarea.Tipo.FOTOGRAFIA,
            formato_archivo=DocumentoTarea.FormatoArchivo.JPG,
            usuario=self.usuario,
            archivo=self._jpeg(),
        )

        with Image.open(documento.archivo) as processed:
            self.assertLessEqual(max(processed.size), 1600)

    def test_hito_evidencia_uses_optimized_image(self):
        hito = Hito.objects.create(
            tarea=self.tarea,
            nombre="Evidencia visual",
            responsable=self.usuario,
            peso=Decimal("100"),
        )
        complete_milestone(
            hito,
            self.usuario,
            resena_cierre="Completado",
            formato_archivo=DocumentoTarea.FormatoArchivo.JPG,
            archivo=self._jpeg(),
        )
        evidencia = HitoEvidencia.objects.get(hito=hito)

        with Image.open(evidencia.archivo) as processed:
            self.assertLessEqual(max(processed.size), 1600)

    def test_closure_evidence_uses_optimized_image(self):
        evidencia = register_closure_evidence(
            tarea=self.tarea,
            usuario=self.usuario,
            formato_archivo=DocumentoTarea.FormatoArchivo.JPG,
            archivo=self._jpeg(),
        )

        with Image.open(evidencia.archivo) as processed:
            self.assertLessEqual(max(processed.size), 1600)

    def test_quotation_document_uses_optimized_image(self):
        ronda = create_quotation_round(tarea=self.tarea)
        cotizacion = create_quotation(
            ronda=ronda,
            proveedor=self.proveedor,
            version=1,
            monto=Decimal("100"),
            fecha_cotizacion=date(2026, 10, 1),
        )
        documento = add_quotation_document(
            cotizacion=cotizacion,
            formato_archivo=DocumentoTarea.FormatoArchivo.JPG,
            usuario=self.usuario,
            archivo=self._jpeg(),
        )

        with Image.open(documento.archivo) as processed:
            self.assertLessEqual(max(processed.size), 1600)

    def test_comment_attachment_keeps_single_document_relation(self):
        comentario = create_comment(
            tarea=self.tarea,
            usuario=self.usuario,
            contenido="",
            documentos_nuevos=[
                {
                    "tipo": DocumentoTarea.Tipo.FOTOGRAFIA,
                    "formato_archivo": DocumentoTarea.FormatoArchivo.JPG,
                    "archivo": self._jpeg(),
                }
            ],
        )

        self.assertEqual(comentario.adjuntos.count(), 1)
        self.assertEqual(comentario.versiones.first().documentos.count(), 1)
