from django.db import migrations, models
import django.db.models.deletion


def backfill_evidence_requirement(apps, schema_editor):
    Tarea = apps.get_model("tareas", "Tarea")
    EvidenciaCierre = apps.get_model("tareas", "EvidenciaCierre")
    requeridas_por_tarea = {}
    for tarea_id, requerida in EvidenciaCierre.objects.order_by("pk").values_list(
        "tarea_id", "requerida"
    ):
        anterior = requeridas_por_tarea.get(tarea_id)
        if anterior is not None and anterior != bool(requerida):
            raise RuntimeError(
                "T079_REQUERIDA_CONFLICT: valores contradictorios para Tarea "
                + str(tarea_id)
            )
        requeridas_por_tarea[tarea_id] = bool(requerida)

    for tarea in Tarea.objects.order_by("pk"):
        tarea.requiere_evidencia_cierre = requeridas_por_tarea.get(tarea.pk, False)
        tarea.save(update_fields=["requiere_evidencia_cierre"])


def reverse_evidence_requirement(apps, schema_editor):
    Tarea = apps.get_model("tareas", "Tarea")
    EvidenciaCierre = apps.get_model("tareas", "EvidenciaCierre")
    for evidencia in EvidenciaCierre.objects.order_by("pk"):
        evidencia.requerida = Tarea.objects.get(
            pk=evidencia.tarea_id
        ).requiere_evidencia_cierre
        evidencia.save(update_fields=["requerida"])


class Migration(migrations.Migration):
    dependencies = [
        ("tareas", "0016_evidenciacierre_direct_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="tarea",
            name="requiere_evidencia_cierre",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(backfill_evidence_requirement, reverse_evidence_requirement),
        migrations.AlterField(
            model_name="evidenciacierre",
            name="tarea",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="evidencias_cierre",
                to="tareas.tarea",
            ),
        ),
        migrations.RemoveIndex(
            model_name="evidenciacierre",
            name="tareas_evid_tarea_i_412f46_idx",
        ),
        migrations.RemoveField(
            model_name="evidenciacierre",
            name="requerida",
        ),
        migrations.AddIndex(
            model_name="evidenciacierre",
            index=models.Index(
                fields=["tarea", "fecha"],
                name="tareas_evid_tarea_fecha_idx",
            ),
        ),
        migrations.AlterModelOptions(
            name="evidenciacierre",
            options={"ordering": ["-fecha", "-pk"]},
        ),
    ]
