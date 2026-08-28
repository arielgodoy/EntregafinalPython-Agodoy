from django.db import migrations


TARGET_NAME = "Auditoría - Biblioteca"
SOURCE_NAMES = (
    "Auditoría - Listar",
    "Auditoría - Detalle",
    "Auditoría - Biblioteca Detalle",
)
PERMISSION_FLAGS = (
    "ingresar",
    "crear",
    "modificar",
    "eliminar",
    "autorizar",
    "supervisor",
)


def forwards(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Vista = apps.get_model("access_control", "Vista")
    Permiso = apps.get_model("access_control", "Permiso")

    target, _created = Vista.objects.using(db_alias).get_or_create(nombre=TARGET_NAME)
    source_vistas = Vista.objects.using(db_alias).filter(nombre__in=SOURCE_NAMES)

    for source in source_vistas:
        for source_permission in Permiso.objects.using(db_alias).filter(vista=source):
            target_permission, _created = Permiso.objects.using(db_alias).get_or_create(
                usuario_id=source_permission.usuario_id,
                empresa_id=source_permission.empresa_id,
                vista=target,
                defaults={flag: getattr(source_permission, flag) for flag in PERMISSION_FLAGS},
            )
            updates = {
                flag: getattr(target_permission, flag) or getattr(source_permission, flag)
                for flag in PERMISSION_FLAGS
            }
            changed = [
                flag for flag in PERMISSION_FLAGS
                if getattr(target_permission, flag) != updates[flag]
            ]
            if changed:
                for flag in changed:
                    setattr(target_permission, flag, updates[flag])
                target_permission.save(using=db_alias, update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [("access_control", "0009_split_gestion_dte_vistas")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]