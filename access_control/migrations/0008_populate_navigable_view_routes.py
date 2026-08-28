from django.db import migrations


ROUTES = {
    "Control de Acceso - Maestro Usuarios": "access_control:usuarios_lista",
    "Control de Acceso - Maestro Empresas": "access_control:empresas_lista",
    "Control de Acceso - Maestro Vistas": "access_control:vistas_lista",
    "Control de Acceso - Maestro Permisos": "access_control:permisos_lista",
    "Settings - Configuración del Sistema": "access_control:system_config",
    "Settings - Configuracion de Empresa": "access_control:company_config_list",
    "Settings - Emails Acounts": "access_control:email_accounts_list",
    "Biblioteca - Listar Propiedades": "biblioteca:listar_propiedades",
    "Biblioteca - Listar Propietarios": "biblioteca:listar_propietarios",
    "Biblioteca - Listar Tipos Documentos": "biblioteca:listar_tipos_documentos",
    "Biblioteca - Listar Documentos": "biblioteca:listado_documentos",
    "Chat - Bandeja de entrada": "chat_inbox",
    "Chat - Centro de mensajes": "centro_mensajes",
    "Control Operacional - Dashboard": "control_operacional:dashboard",
    "Control Operacional - Alertas": "control_operacional:alertas_operacionales",
    "Notificaciones - Mis Notificaciones": "notificaciones:mis_notificaciones",
    "Notificaciones - Centro de Alertas": "notificaciones:centro_alertas",
}


def populate_routes(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Vista = apps.get_model("access_control", "Vista")
    for nombre, route_name in ROUTES.items():
        Vista.objects.using(db_alias).filter(nombre=nombre).update(route_name=route_name)


def clear_routes(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Vista = apps.get_model("access_control", "Vista")
    for nombre, route_name in ROUTES.items():
        Vista.objects.using(db_alias).filter(
            nombre=nombre,
            route_name=route_name,
        ).update(route_name=None)


class Migration(migrations.Migration):

    dependencies = [
        ("access_control", "0007_populate_initial_view_routes"),
    ]

    operations = [
        migrations.RunPython(populate_routes, clear_routes),
    ]
