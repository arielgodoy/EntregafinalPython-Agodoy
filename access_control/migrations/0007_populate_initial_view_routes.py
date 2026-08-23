from django.db import migrations


GESTION_CESIONES_NAME = "Gestión DTE - Control de Cesiones"
GESTION_CESIONES_ROUTE = "gestion_dte:cesiones"


def populate_routes(apps, schema_editor):
    Vista = apps.get_model("access_control", "Vista")
    Vista.objects.filter(nombre=GESTION_CESIONES_NAME).update(
        route_name=GESTION_CESIONES_ROUTE,
    )


def clear_routes(apps, schema_editor):
    Vista = apps.get_model("access_control", "Vista")
    Vista.objects.filter(
        nombre=GESTION_CESIONES_NAME,
        route_name=GESTION_CESIONES_ROUTE,
    ).update(route_name=None)


class Migration(migrations.Migration):

    dependencies = [
        ("access_control", "0006_vista_route_name"),
    ]

    operations = [
        migrations.RunPython(populate_routes, clear_routes),
    ]
