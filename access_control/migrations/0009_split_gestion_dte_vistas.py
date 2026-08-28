from django.db import migrations


CONTROL_NAME = "Gestión DTE - Control de Cesiones"
DASHBOARD_NAME = "Gestión DTE - Dashboard DTE-SII-RPETC"
LECTURA_NAME = "Gestión DTE - Lectura Automática de Cesiones"
CERTIFICADOS_NAME = "Gestión DTE - Certificados PFX-DTE"

VIEWS = {
    DASHBOARD_NAME: "gestion_dte:index",
    CONTROL_NAME: "gestion_dte:cesiones",
    LECTURA_NAME: "gestion_dte:lectura_automatica_cesiones",
    CERTIFICADOS_NAME: "gestion_dte:certificados",
}

PERMISSION_FLAGS = (
    "ingresar", "crear", "modificar", "eliminar", "autorizar", "supervisor",
)


def forwards(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Vista = apps.get_model("access_control", "Vista")
    Permiso = apps.get_model("access_control", "Permiso")

    vistas = {}
    for nombre, route_name in VIEWS.items():
        vista, _created = Vista.objects.using(db_alias).get_or_create(nombre=nombre)
        if vista.route_name != route_name:
            vista.route_name = route_name
            vista.save(using=db_alias, update_fields=["route_name"])
        vistas[nombre] = vista

    control_vista = vistas[CONTROL_NAME]
    for permiso in Permiso.objects.using(db_alias).filter(vista=control_vista):
        flags = {flag: getattr(permiso, flag) for flag in PERMISSION_FLAGS}
        for vista in (vistas[DASHBOARD_NAME], vistas[LECTURA_NAME]):
            Permiso.objects.using(db_alias).get_or_create(
                usuario_id=permiso.usuario_id,
                empresa_id=permiso.empresa_id,
                vista=vista,
                defaults=flags,
            )

class Migration(migrations.Migration):
    dependencies = [("access_control", "0008_populate_navigable_view_routes")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]