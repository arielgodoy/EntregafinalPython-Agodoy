from django.db import migrations, models


def backfill_ver_from_ingresar(apps, schema_editor):
    Permiso = apps.get_model("access_control", "Permiso")
    PerfilAccesoDetalle = apps.get_model("access_control", "PerfilAccesoDetalle")

    Permiso.objects.using(schema_editor.connection.alias).update(ver=models.F("ingresar"))
    PerfilAccesoDetalle.objects.using(schema_editor.connection.alias).update(ver=models.F("ingresar"))


class Migration(migrations.Migration):
    dependencies = [
        ("access_control", "0012_rename_settings_vistas_merge_permisos"),
    ]

    operations = [
        migrations.AddField(
            model_name="permiso",
            name="ver",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="perfilaccesodetalle",
            name="ver",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(backfill_ver_from_ingresar, migrations.RunPython.noop),
    ]
