from django.conf import settings
from django.db import migrations, models
from django.utils import timezone
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("tareas", "0017_tarea_evidencia_configuracion"),
    ]

    operations = [
        migrations.AddField(
            model_name="hito",
            name="completado",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="hito",
            name="completado_por",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="hitos_completados",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="hito",
            name="fecha_completado",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hito",
            name="resena_cierre",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.CreateModel(
            name="HitoEvidencia",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "formato_archivo",
                    models.CharField(
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
                (
                    "archivo",
                    models.FileField(
                        blank=True,
                        default="",
                        upload_to="tareas/hitos/evidencias/",
                    ),
                ),
                ("url", models.URLField(blank=True, default="")),
                ("fecha", models.DateTimeField(default=timezone.now)),
                (
                    "hito",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="evidencias",
                        to="tareas.hito",
                    ),
                ),
                (
                    "usuario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="evidencias_hitos_registradas",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-fecha", "-pk"],
                "indexes": [
                    models.Index(
                        fields=["hito", "fecha"],
                        name="tareas_he_hito_fecha_idx",
                    )
                ],
            },
        ),
        migrations.AlterField(
            model_name="hitohistorial",
            name="tipo_evento",
            field=models.CharField(
                choices=[
                    ("CREACION", "Creación"),
                    ("CAMBIO_NOMBRE", "Cambio de nombre"),
                    ("CAMBIO_CUMPLIMIENTO", "Cambio de cumplimiento"),
                    ("CAMBIO_PESO", "Cambio de peso"),
                    ("REASIGNACION", "Reasignación"),
                    ("ANULACION", "Anulación"),
                    ("REACTIVACION", "Reactivación"),
                    ("ELIMINACION_FISICA", "Eliminación física"),
                    ("COMPLETADO", "Completado"),
                ],
                max_length=32,
            ),
        ),
    ]
