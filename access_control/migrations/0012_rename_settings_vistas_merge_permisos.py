from django.db import migrations


# Renames autorizados (nombres canonicos en espanol). Cada entrada:
# (nombre_antiguo, nombre_nuevo, route_name_canonico)
# El route_name canonico se asigna a la Vista nueva porque el menu
# (access_control.services.empresa_activa) solo muestra vistas con route_name
# no nulo; el codigo productivo actual de cada pantalla usa el nombre nuevo.
RENAMES = [
    (
        "Settings - Emails Acounts",
        "Configuración - Cuentas de Correo",
        "access_control:email_accounts_list",
    ),
    (
        "Settings - Configuracion de Empresa",
        "Configuración - Configuracion de Empresa",
        "access_control:company_config_list",
    ),
    (
        "Settings - Configuración del Sistema",
        "Configuración - Configuración del Sistema",
        "access_control:system_config",
    ),
]

ICMEAS_FIELDS = ("ingresar", "crear", "modificar", "eliminar", "autorizar", "supervisor")


def merge_vistas(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Vista = apps.get_model("access_control", "Vista")
    Permiso = apps.get_model("access_control", "Permiso")

    for old_name, new_name, canonical_route in RENAMES:
        old = Vista.objects.using(db_alias).filter(nombre=old_name).first()
        new = Vista.objects.using(db_alias).filter(nombre=new_name).first()

        # Crear la Vista nueva si aun no existe (idempotente, safe si ya existe).
        if new is None:
            new = Vista.objects.using(db_alias).create(
                nombre=new_name,
                descripcion=(old.descripcion if old else "") or "",
                route_name=None,
            )

        # Metadata: solo rellenar campos vacios de NEW con valores validos de OLD.
        if old is not None:
            updated_fields = []
            if not (new.descripcion or "").strip() and (old.descripcion or "").strip():
                new.descripcion = old.descripcion
                updated_fields.append("descripcion")
            if updated_fields:
                new.save(using=db_alias, update_fields=updated_fields)

        # route_name canonico: solo asignar si NEW no tiene uno (no pisar valor valido).
        if not (new.route_name or "").strip():
            new.route_name = canonical_route
            new.save(using=db_alias, update_fields=["route_name"])

        if old is None:
            continue

        # Migrar/fusionar permisos OLD -> NEW.
        for permiso in Permiso.objects.using(db_alias).filter(vista=old):
            existente = Permiso.objects.using(db_alias).filter(
                usuario_id=permiso.usuario_id,
                empresa_id=permiso.empresa_id,
                vista=new,
            ).first()
            if existente is None:
                # Mover: reutilizar el permiso antiguo apuntandolo a la nueva vista.
                permiso.vista = new
                permiso.save(using=db_alias, update_fields=["vista"])
            else:
                # Fusionar con OR logico; nunca reducir flags existentes.
                changed = False
                for field in ICMEAS_FIELDS:
                    if getattr(permiso, field) and not getattr(existente, field):
                        setattr(existente, field, True)
                        changed = True
                if changed:
                    existente.save(using=db_alias, update_fields=list(ICMEAS_FIELDS))
                permiso.delete(using=db_alias)

        # Eliminar OLD solo si ya no queda ningun Permiso apuntando a ella.
        if not Permiso.objects.using(db_alias).filter(vista=old).exists():
            old.delete(using=db_alias)


def reverse_noop(apps, schema_editor):
    # Reverse intencionalmente no-op: la fusion OR de flags es irreversible de
    # forma segura (no es posible reconstruir la distribucion previa de flags
    # sin perdida o invencion de informacion).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("access_control", "0011_create_gestion_dte_auditoria_view"),
    ]

    operations = [
        migrations.RunPython(merge_vistas, reverse_noop),
    ]
