from django.db import migrations


def create_gestion_dte_auditoria_view(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Vista = apps.get_model("access_control", "Vista")
    Vista.objects.using(db_alias).get_or_create(
        nombre="Auditoría - Gestión DTE",
        defaults={"route_name": "auditoria:auditoria_gestiondte_list"},
    )


class Migration(migrations.Migration):
    dependencies = [("access_control", "0010_consolidate_biblioteca_auditoria")]
    operations = [migrations.RunPython(create_gestion_dte_auditoria_view, migrations.RunPython.noop)]