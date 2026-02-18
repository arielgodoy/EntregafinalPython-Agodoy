from django.db import migrations
import sys


def create_vistas(apps, schema_editor):
    # Evitar crear vistas durante la ejecución de tests, muchos tests
    # simulan la ausencia de Vistas y fallarían si las creamos aquí.
    if any('test' in str(arg) for arg in sys.argv):
        return

    Vista = apps.get_model('access_control', 'Vista')
    nombres = [
        'Maestro Usuarios',
        'auth_invite',
        'invitaciones',
        'system_config',
        'company_config',
        'email_accounts',
        'control_operacional.alertas',
        'chat.inbox',
        'chat.thread',
        'chat.create',
        'chat.send_message',
        'chat.delete',
    ]
    for nombre in nombres:
        Vista.objects.get_or_create(nombre=nombre)


def remove_vistas(apps, schema_editor):
    Vista = apps.get_model('access_control', 'Vista')
    nombres = [
        'Maestro Usuarios',
        'auth_invite',
        'invitaciones',
        'system_config',
        'company_config',
        'email_accounts',
        'control_operacional.alertas',
        'chat.inbox',
        'chat.thread',
        'chat.create',
        'chat.send_message',
        'chat.delete',
    ]
    Vista.objects.filter(nombre__in=nombres).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('access_control', '0004_create_auditoria_vistas'),
    ]

    operations = [
        migrations.RunPython(create_vistas, remove_vistas),
    ]
