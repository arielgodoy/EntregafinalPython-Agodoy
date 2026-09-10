from os.path import splitext
from urllib.parse import urlparse

from django.db import migrations, models


FORMATS = {
    "pdf": "PDF",
    "jpg": "JPG",
    "jpeg": "JPEG",
    "png": "PNG",
    "doc": "DOC",
    "docx": "DOCX",
    "xls": "XLS",
    "xlsx": "XLSX",
}


def _format_for_document(document):
    source = document.archivo.name if document.archivo else urlparse(document.url).path
    extension = splitext(source)[1].lower().lstrip(".")
    if not extension:
        return None
    return FORMATS.get(extension)


def backfill_file_formats(apps, schema_editor):
    DocumentoTarea = apps.get_model("tareas", "DocumentoTarea")
    unresolved = []
    for documento in DocumentoTarea.objects.order_by("pk"):
        formato = _format_for_document(documento)
        if formato is None:
            unresolved.append(documento.pk)
            continue
        documento.formato_archivo = formato
        documento.save(update_fields=["formato_archivo"])
    if unresolved:
        raise RuntimeError(
            "FORMAT_BACKFILL_DECISION_REQUIRED: DocumentoTarea sin formato "
            + ", ".join(str(pk) for pk in unresolved)
        )


def reverse_file_formats(apps, schema_editor):
    DocumentoTarea = apps.get_model("tareas", "DocumentoTarea")
    DocumentoTarea.objects.update(formato_archivo=None)


class Migration(migrations.Migration):
    dependencies = [
        ("tareas", "0014_hito_responsable_historial"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentotarea",
            name="formato_archivo",
            field=models.CharField(
                blank=True,
                choices=[
                    ("PDF", "PDF"),
                    ("JPG", "JPG"),
                    ("JPEG", "JPEG"),
                    ("PNG", "PNG"),
                    ("DOC", "DOC"),
                    ("DOCX", "DOCX"),
                    ("XLS", "XLS"),
                    ("XLSX", "XLSX"),
                ],
                max_length=4,
                null=True,
            ),
        ),
        migrations.RunPython(backfill_file_formats, reverse_file_formats),
        migrations.AlterField(
            model_name="documentotarea",
            name="formato_archivo",
            field=models.CharField(
                choices=[
                    ("PDF", "PDF"),
                    ("JPG", "JPG"),
                    ("JPEG", "JPEG"),
                    ("PNG", "PNG"),
                    ("DOC", "DOC"),
                    ("DOCX", "DOCX"),
                    ("XLS", "XLS"),
                    ("XLSX", "XLSX"),
                ],
                max_length=4,
            ),
        ),
    ]
