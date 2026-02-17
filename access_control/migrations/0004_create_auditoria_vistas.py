from django.db import migrations


def create_auditoria_vistas(apps, schema_editor):
    Vista = apps.get_model('access_control', 'Vista')
    Vista.objects.get_or_create(nombre='Auditoría - Listar', defaults={'descripcion': 'Vista para listar eventos de auditoría'})
    Vista.objects.get_or_create(nombre='Auditoría - Detalle', defaults={'descripcion': 'Vista para ver detalle de eventos de auditoría'})


class Migration(migrations.Migration):

    dependencies = [
        ('access_control', '0003_accessrequest'),
    ]

    operations = [
        migrations.RunPython(create_auditoria_vistas, migrations.RunPython.noop),
    ]
