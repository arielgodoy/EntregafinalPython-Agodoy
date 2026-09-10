from django.db import migrations, models


FORMATO_CHOICES = [
    ("PDF", "PDF"),
    ("JPG", "JPG"),
    ("JPEG", "JPEG"),
    ("PNG", "PNG"),
    ("DOC", "DOC"),
    ("DOCX", "DOCX"),
    ("XLS", "XLS"),
    ("XLSX", "XLSX"),
]


def copy_historical_evidence(apps, schema_editor):
    EvidenciaCierre = apps.get_model("tareas", "EvidenciaCierre")
    unresolved = []
    for evidencia in EvidenciaCierre.objects.select_related("documento").order_by("pk"):
        documento = evidencia.documento
        if documento is None:
            continue
        archivo = documento.archivo.name if documento.archivo else ""
        url = documento.url or ""
        formato = documento.formato_archivo or ""
        if not formato or bool(archivo) == bool(url):
            unresolved.append(evidencia.pk)
            continue
        evidencia.formato_archivo = formato
        evidencia.archivo = archivo
        evidencia.url = url
        evidencia.save(update_fields=["formato_archivo", "archivo", "url"])
    if unresolved:
        raise RuntimeError(
            "EVIDENCE_MIGRATION_DECISION_REQUIRED: EvidenciaCierre ambigua "
            + ", ".join(str(pk) for pk in unresolved)
        )


class Migration(migrations.Migration):
    dependencies = [
        ("tareas", "0015_documentotarea_formato_archivo"),
    ]

    operations = [
        migrations.AddField(
            model_name="evidenciacierre",
            name="formato_archivo",
            field=models.CharField(
                blank=True,
                choices=FORMATO_CHOICES,
                default="",
                max_length=4,
            ),
        ),
        migrations.AddField(
            model_name="evidenciacierre",
            name="archivo",
            field=models.FileField(
                blank=True,
                default="",
                upload_to="tareas/evidencias/",
            ),
        ),
        migrations.AddField(
            model_name="evidenciacierre",
            name="url",
            field=models.URLField(blank=True, default=""),
        ),
        migrations.RunPython(copy_historical_evidence, migrations.RunPython.noop),
    ]
