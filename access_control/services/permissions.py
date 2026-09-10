from django.contrib.auth.models import User

from access_control.models import Permiso, UsuarioPerfilEmpresa, Vista


ICMEAS_FIELDS = (
    "ingresar",
    "crear",
    "modificar",
    "eliminar",
    "autorizar",
    "supervisor",
)

VICMEAS_FIELDS = ("ver",) + ICMEAS_FIELDS

SIDEBAR_VIEW_NAMES = {
    "library_add_owner": "Biblioteca - Crear Propietario",
    "library_add_property": "Biblioteca - Crear Propiedad",
    "library_add_document_type": "Biblioteca - Crear Tipo Documento",
    "library_list_owners": "Biblioteca - Listar Propietarios",
    "library_list_properties": "Biblioteca - Listar Propiedades",
    "library_list_document_types": "Biblioteca - Listar Tipos Documentos",
    "library_list_documents": "Biblioteca - Listar Documentos",
    "gestion_dte_index": "Gestión DTE - Dashboard DTE-SII-RPETC",
    "gestion_dte_cesiones": "Gestión DTE - Control de Cesiones",
    "gestion_dte_lectura": "Gestión DTE - Lectura Automática de Cesiones",
    "gestion_dte_certificados": "Gestión DTE - Certificados PFX-DTE",
    "evaluaciones_import": "Evaluaciones - Importar Personas",
    "projects_list": "Control de Proyectos - Proyectos",
    "projects_create": "Control de Proyectos - Crear proyecto",
    "projects_clients": "Control de Proyectos - Clientes",
    "projects_create_client": "Control de Proyectos - Crear cliente",
    "projects_professionals": "Control de Proyectos - Profesionales",
    "projects_create_professional": "Control de Proyectos - Crear profesional",
    "operational_dashboard": "Control Operacional - Dashboard",
    "operational_alerts": "Control Operacional - Alertas",
    "tasks_list": "Tareas - Listado",
    "tasks_create": "Tareas - Crear tarea",
    "account_profile": "Accounts - Editar Perfil",
    "account_email": "Configuración - Cuentas de Correo",
    "chat_inbox": "Chat - Bandeja de entrada",
    "chat_center": "Chat - Centro de mensajes",
    "notifications_list": "Notificaciones - Mis Notificaciones",
    "notifications_alerts": "Notificaciones - Centro de Alertas",
    "notifications_force": "Forzar Notificaciones",
    "notifications_custom": "Notificaciones - Alerta Personalizada",
    "audit_library": "Auditoría - Biblioteca",
    "audit_gestion_dte": "Auditoría - Gestión DTE",
    "access_invite": "Control de Acceso - Invitar Usuario",
    "access_invitations": "Control de Acceso - Invitaciones",
    "access_users": "Control de Acceso - Maestro Usuarios",
    "access_companies": "Control de Acceso - Maestro Empresas",
    "access_views": "Control de Acceso - Maestro Vistas",
    "access_permissions": "Control de Acceso - Maestro Permisos",
    "access_filtered_permissions": "Control de Acceso - Permisos Filtrados",
    "access_view_permissions": "Control de Acceso - Permisos por Vista",
    "api_home": "APIs - Inicio",
    "settings_system": "Configuración - Configuración del Sistema",
    "settings_company": "Configuración - Configuracion de Empresa",
    "settings_email": "Configuración - Cuentas de Correo",
    "settings_mysql": "Configuración - Conexiones MySQL",
}

SIDEBAR_GROUPS = {
    "library": ("library_add_owner", "library_add_property", "library_add_document_type", "library_list_owners", "library_list_properties", "library_list_document_types", "library_list_documents"),
    "gestion_dte": ("gestion_dte_index", "gestion_dte_cesiones", "gestion_dte_lectura", "gestion_dte_certificados"),
    "evaluaciones": ("evaluaciones_import",),
    "projects": ("projects_list", "projects_create", "projects_clients", "projects_create_client", "projects_professionals", "projects_create_professional"),
    "operational": ("operational_dashboard", "operational_alerts"),
    "tasks": ("tasks_list", "tasks_create"),
    "account": ("account_profile", "account_email"),
    "chat": ("chat_inbox", "chat_center"),
    "notifications": ("notifications_list", "notifications_alerts", "notifications_force", "notifications_custom"),
    "audit": ("audit_library", "audit_gestion_dte"),
    "access": ("access_invite", "access_invitations", "access_users", "access_companies", "access_views", "access_permissions", "access_filtered_permissions", "access_view_permissions"),
    "apis": ("api_home",),
    "settings": ("settings_system", "settings_company", "settings_email", "settings_mysql"),
}

SIDEBAR_GLOBAL_ITEMS = {"account_email"}


def get_sidebar_visible_items(user, empresa_id):
    if not getattr(user, "is_authenticated", False) or not empresa_id:
        return set(SIDEBAR_GLOBAL_ITEMS) if getattr(user, "is_authenticated", False) else set()
    if user.is_superuser:
        visible_items = set(SIDEBAR_VIEW_NAMES)
        for group, children in SIDEBAR_GROUPS.items():
            if any(child in visible_items for child in children):
                visible_items.add(group)
        return visible_items | SIDEBAR_GLOBAL_ITEMS

    visible_names = set(
        Permiso.objects.filter(
            usuario=user,
            empresa_id=empresa_id,
            ver=True,
            vista__nombre__in=SIDEBAR_VIEW_NAMES.values(),
        ).values_list("vista__nombre", flat=True)
    )
    visible_items = {
        item_key
        for item_key, vista_nombre in SIDEBAR_VIEW_NAMES.items()
        if vista_nombre in visible_names
    }
    for group, children in SIDEBAR_GROUPS.items():
        if any(child in visible_items for child in children):
            visible_items.add(group)
    return visible_items | SIDEBAR_GLOBAL_ITEMS


def get_valid_users_for_empresa(empresa):
    """Return the compatibility union of assigned and permission-bearing users."""
    assigned_user_ids = UsuarioPerfilEmpresa.objects.filter(empresa=empresa).values("usuario_id")
    permission_user_ids = Permiso.objects.filter(empresa=empresa).values("usuario_id")
    return User.objects.filter(id__in=assigned_user_ids.union(permission_user_ids)).order_by("username")


def user_has_permission_for_empresa(*, user, empresa, vista_nombre, accion):
    """Check an existing ICMEAS permission for an explicit company without side effects."""
    return user_has_permission(
        user=user,
        empresa=empresa,
        vista=vista_nombre,
        accion=accion,
    )


def user_has_permission(*, user, empresa, vista, accion):
    if accion not in ICMEAS_FIELDS:
        raise ValueError("Acción ICMEAS no válida.")

    if isinstance(vista, str):
        vista = Vista.objects.filter(nombre=vista).first()
    if vista is None:
        return False

    permiso = Permiso.objects.filter(
        usuario=user,
        empresa=empresa,
        vista=vista,
    ).first()
    if permiso is None:
        return False

    if permiso.supervisor:
        return True
    return bool(getattr(permiso, accion, False))
