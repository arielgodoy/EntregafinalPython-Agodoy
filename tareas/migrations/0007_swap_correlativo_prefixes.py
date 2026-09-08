import re

from django.db import migrations


CORRELATIVO_RE = re.compile(r"^[AB][0-9]{7}$")


def _target_prefix(estado):
    return "B" if estado == "BORRADOR" else "A"


def _remap_prefixes(apps, schema_editor, reverse=False):
    Tarea = apps.get_model("tareas", "Tarea")
    db_alias = schema_editor.connection.alias

    tareas = list(Tarea.objects.using(db_alias).order_by("empresa_id", "id"))
    targets = {}
    updates = []
    for tarea in tareas:
        correlativo = tarea.correlativo or ""
        if not CORRELATIVO_RE.fullmatch(correlativo):
            raise RuntimeError(
                "Migración abortada: correlativo inválido para "
                f"empresa {tarea.empresa_id}, tarea {tarea.pk}."
            )

        expected_prefix = _target_prefix(tarea.estado)
        if reverse:
            expected_prefix = "A" if tarea.estado == "BORRADOR" else "B"
        target = f"{expected_prefix}{correlativo[1:]}"
        key = (tarea.empresa_id, target)
        previous = targets.get(key)
        if previous is not None and previous != tarea.pk:
            raise RuntimeError(
                "Migración abortada: colisión de correlativo para "
                f"empresa {tarea.empresa_id}, valor {target}."
            )
        targets[key] = tarea.pk
        updates.append((tarea, target))

    for tarea, _target in updates:
        tarea.correlativo = f"X{tarea.correlativo}"
    Tarea.objects.using(db_alias).bulk_update(
        [tarea for tarea, _target in updates], ["correlativo"]
    )

    for tarea, target in updates:
        tarea.correlativo = target
    Tarea.objects.using(db_alias).bulk_update(
        [tarea for tarea, _target in updates], ["correlativo"]
    )


def forwards(apps, schema_editor):
    _remap_prefixes(apps, schema_editor)


def backwards(apps, schema_editor):
    _remap_prefixes(apps, schema_editor, reverse=True)


class Migration(migrations.Migration):
    dependencies = [
        ("tareas", "0006_tarearelacion"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]