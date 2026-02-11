from django.db import migrations


def _infer_empresa_id(conversacion, permiso_model):
    participant_ids = list(conversacion.participantes.values_list('id', flat=True))
    if not participant_ids:
        return None

    shared_empresas = None
    for user_id in participant_ids:
        user_empresas = set(
            permiso_model.objects.filter(usuario_id=user_id).values_list('empresa_id', flat=True)
        )
        if not user_empresas:
            return None
        if shared_empresas is None:
            shared_empresas = user_empresas
        else:
            shared_empresas &= user_empresas
        if not shared_empresas:
            return None

    if len(shared_empresas) == 1:
        return next(iter(shared_empresas))
    return None


def set_empresa_for_conversaciones(apps, schema_editor):
    Conversacion = apps.get_model('chat', 'Conversacion')
    Empresa = apps.get_model('access_control', 'Empresa')
    Permiso = apps.get_model('access_control', 'Permiso')

    fallback_empresa = Empresa.objects.order_by('id').first()

    for conversacion in Conversacion.objects.filter(empresa__isnull=True).iterator():
        inferred_id = _infer_empresa_id(conversacion, Permiso)
        if inferred_id:
            conversacion.empresa_id = inferred_id
        elif fallback_empresa:
            # Fallback: asigna la primera Empresa disponible si no se puede inferir.
            conversacion.empresa_id = fallback_empresa.id
        else:
            continue
        conversacion.save(update_fields=['empresa'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0002_conversacion_empresa'),
        ('access_control', '0002_perfilacceso_perfilaccesodetalle_and_more'),
    ]

    operations = [
        migrations.RunPython(set_empresa_for_conversaciones, noop_reverse),
    ]
