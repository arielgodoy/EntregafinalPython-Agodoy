from django.contrib.auth.models import User

from access_control.models import Empresa, Permiso, UsuarioPerfilEmpresa, Vista


ICMEAS_FIELDS = (
    "ingresar",
    "crear",
    "modificar",
    "eliminar",
    "autorizar",
    "supervisor",
)

VICMEAS_FIELDS = ("ver",) + ICMEAS_FIELDS

SIDEBAR_MENU = (
    {
        "key": "control_acceso",
        "label_key": "menu.access_control",
        "label": "Control de Acceso",
        "icon": "ri-lock-line",
        "children": (
            {
                "key": "usuarios",
                "label_key": "menu.access_control.users",
                "label": "Usuarios",
                "children": (
                    {
                        "key": "access_invite",
                        "label_key": "menu.access_control.invite_user",
                        "label": "Invitar Usuario",
                        "route_name": "access_control:usuario_invitar",
                        "vista": "Control de Acceso - Invitar Usuario",
                    },
                    {
                        "key": "access_invitations",
                        "label_key": "menu.access_control.invitations",
                        "label": "Invitaciones",
                        "route_name": "access_control:invitaciones_lista",
                        "vista": "Control de Acceso - Invitaciones",
                    },
                    {
                        "key": "access_users",
                        "label_key": "menu.access_control.master_users",
                        "label": "Maestro Usuarios",
                        "route_name": "access_control:usuarios_lista",
                        "vista": "Control de Acceso - Maestro Usuarios",
                    },
                ),
            },
            {
                "key": "access_companies",
                "label_key": "menu.access_control.master_companies",
                "label": "Maestro Empresas",
                "route_name": "access_control:empresas_lista",
                "vista": "Control de Acceso - Maestro Empresas",
            },
            {
                "key": "permisos",
                "label_key": "menu.access_control.permissions",
                "label": "Permisos",
                "children": (
                    {
                        "key": "access_views",
                        "label_key": "menu.access_control.master_views",
                        "label": "Maestro Vistas",
                        "route_name": "access_control:vistas_lista",
                        "vista": "Control de Acceso - Maestro Vistas",
                    },
                    {
                        "key": "access_permissions",
                        "label_key": "menu.access_control.master_permissions",
                        "label": "Maestro Permisos",
                        "route_name": "access_control:permisos_lista",
                        "vista": "Control de Acceso - Maestro Permisos",
                    },
                    {
                        "key": "access_filtered_permissions",
                        "label_key": "menu.access_control.filtered_permissions",
                        "label": "Permisos Filtrados",
                        "route_name": "access_control:permisos_filtrados",
                        "vista": "Control de Acceso - Permisos Filtrados",
                    },
                    {
                        "key": "access_view_permissions",
                        "label_key": "menu.access_control.view_permissions",
                        "label": "Permisos por Vista",
                        "route_name": "access_control:permisos_por_vista",
                        "vista": "Control de Acceso - Permisos por Vista",
                    },
                    {
                        "key": "access_utility",
                        "label_key": "menu.access_control.access_utility",
                        "label": "Utilitario de Acceso",
                        "route_name": "access_control:utilitario_acceso",
                        "vista": "Control de Acceso - Utilitario de Acceso",
                    },
                ),
            },
        ),
    },
    {
        "key": "database_manager",
        "label_key": "database_manager.dashboard.heading",
        "label": "Gestión de Bases del Sistema",
        "icon": "ri-database-2-line",
        "children": (
            {
                "key": "database_manager_dashboard",
                "label_key": "control_operacional.dashboard.title",
                "label": "Dashboard",
                "route_name": "database_manager:dashboard",
                "vista": "Gestión de Bases - Dashboard",
            },
            {
                "key": "database_manager_compare",
                "label_key": "database_manager.dashboard.compare",
                "label": "Comparar bases",
                "route_name": "database_manager:compare",
                "vista": "Gestión de Bases - Comparar",
            },
            {
                "key": "database_manager_preflight",
                "label_key": "database_manager.preflight.title",
                "label": "Preflight",
                "route_name": "database_manager:preflight",
                "vista": "Gestión de Bases - Preflight",
            },
        ),
    },
)


def _menu_leaves(nodes):
    for node in nodes:
        children = node.get("children", ())
        if children:
            yield from _menu_leaves(children)
        else:
            yield node


def _menu_nodes(nodes):
    for node in nodes:
        yield node
        yield from _menu_nodes(node.get("children", ()))


_SIDEBAR_MENU_NODES = {node["key"]: node for node in _menu_nodes(SIDEBAR_MENU)}
_SIDEBAR_MENU_LEAVES = tuple(_menu_leaves(SIDEBAR_MENU))

_ACCESS_VIEW_NAMES = {
    node["key"]: node["vista"]
    for node in _SIDEBAR_MENU_LEAVES
    if not node.get("global")
}

SIDEBAR_VIEW_NAMES = {
    "library_add_owner": "Biblioteca - Propietarios",
    "library_add_property": "Biblioteca - Propiedades",
    "library_add_document_type": "Biblioteca - Tipos de Documento",
    "library_list_owners": "Biblioteca - Propietarios",
    "library_list_properties": "Biblioteca - Propiedades",
    "library_list_document_types": "Biblioteca - Tipos de Documento",
    "library_list_documents": "Biblioteca - Documentos",
    "suppliers_master": "Maestros - Proveedores",
    "gestion_dte_index": "Gestión DTE - Dashboard DTE-SII-RPETC",
    "gestion_dte_cesiones": "Gestión DTE - Control de Cesiones",
    "gestion_dte_lectura": "Gestión DTE - Lectura Automática de Cesiones",
    "gestion_dte_certificados": "Gestión DTE - Certificados PFX-DTE",
    "evaluaciones_import": "Evaluaciones - Importar Personas",
    "projects_list": "Control de Proyectos - Proyectos",
    "projects_create": "Control de Proyectos - Proyectos",
    "projects_clients": "Control de Proyectos - Clientes",
    "projects_create_client": "Control de Proyectos - Clientes",
    "projects_professionals": "Control de Proyectos - Profesionales",
    "projects_create_professional": "Control de Proyectos - Profesionales",
    "operational_dashboard": "Control Operacional - Dashboard",
    "operational_alerts": "Control Operacional - Alertas",
    "tasks_list": "Tareas - Listado",
    "tasks_create": "Tareas - Crear tarea",
    "tasks_dashboard": "Tareas - Dashboard personal",
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
    **_ACCESS_VIEW_NAMES,
    "api_home": "APIs - Inicio",
    "settings_system": "Configuración - Configuración del Sistema",
    "settings_company": "Configuración - Configuracion de Empresa",
    "settings_email": "Configuración - Cuentas de Correo",
    "settings_mysql": "Configuración - Conexiones MySQL",
    "database_manager_dashboard": "Gestión de Bases - Dashboard",
    "database_manager_compare": "Gestión de Bases - Comparar",
    "database_manager_preflight": "Gestión de Bases - Preflight",
}

SIDEBAR_DEFINITION_KEYS = {
    "tasks_list": "tareas.tasks",
    "tasks_create": "tareas.tasks",
    "tasks_dashboard": "tareas.personal_dashboard",
    "operational_dashboard": "control_operacional.dashboard",
    "operational_alerts": "control_operacional.alertas",
}

SIDEBAR_GROUPS = {
    "library": ("library_add_owner", "library_add_property", "library_add_document_type", "library_list_owners", "library_list_properties", "library_list_document_types", "library_list_documents"),
    "master_files": ("suppliers_master",),
    "gestion_dte": ("gestion_dte_index", "gestion_dte_cesiones", "gestion_dte_lectura", "gestion_dte_certificados"),
    "evaluaciones": ("evaluaciones_import",),
    "projects": ("projects_list", "projects_create", "projects_clients", "projects_create_client", "projects_professionals", "projects_create_professional"),
    "operational": ("operational_dashboard", "operational_alerts"),
    "tasks": ("tasks_list", "tasks_create", "tasks_dashboard"),
    "account": ("account_profile", "account_email"),
    "chat": ("chat_inbox", "chat_center"),
    "notifications": ("notifications_list", "notifications_alerts", "notifications_force", "notifications_custom"),
    "audit": ("audit_library", "audit_gestion_dte"),
    "access": tuple(_ACCESS_VIEW_NAMES),
    "apis": ("api_home",),
    "settings": ("settings_system", "settings_company", "settings_email", "settings_mysql"),
    "database_manager": (
        "database_manager_dashboard",
        "database_manager_compare",
        "database_manager_preflight",
    ),
}

SIDEBAR_GROUP_LABELS = {
    "library": "Biblioteca Digital",
    "master_files": "Archivos Maestros",
    "gestion_dte": "Gestión DTE",
    "evaluaciones": "Evaluaciones",
    "projects": "Gestión de Proyectos",
    "operational": "Control Operacional",
    "tasks": "Tareas",
    "account": "Cuenta de Usuario",
    "chat": "Mensajería",
    "notifications": "Notificaciones",
    "audit": "Auditoría",
    "access": "Control de Acceso",
    "apis": "APIs",
    "settings": "Settings",
    "database_manager": "Gestión de Bases del Sistema",
}

SIDEBAR_GLOBAL_ITEMS = {"account_email"}


def get_sidebar_group_options():
    return [
        ("all", "Todo"),
        ("control_acceso", "Control de Acceso"),
        ("usuarios", "Usuarios"),
        ("permisos", "Permisos"),
    ] + [
        (group, SIDEBAR_GROUP_LABELS[group])
        for group in SIDEBAR_GROUPS
    ]


def filter_sidebar_tree(nodes, visible_leaf_keys, *, current_route_name=None):
    def filter_nodes(current_nodes, ancestors=()):
        filtered = []
        for node in current_nodes:
            children = node.get("children", ())
            if children:
                filtered_children = filter_nodes(children, ancestors + (node["key"],))
                if not filtered_children:
                    continue
                filtered_node = dict(node)
                filtered_node["children"] = tuple(filtered_children)
                filtered.append(filtered_node)
                continue

            if not (node.get("global") or node["key"] in visible_leaf_keys):
                continue
            filtered_node = dict(node)
            filtered_node["active"] = node.get("route_name") == current_route_name
            filtered_node["open"] = filtered_node["active"]
            filtered_node["collapse_id"] = None
            filtered.append(filtered_node)

        for node in filtered:
            if node.get("children"):
                node["open"] = any(child.get("open") for child in node["children"])
                node["active"] = node["open"]
                node["collapse_id"] = "sidebar-" + node["key"].replace("_", "-")
        return filtered

    return tuple(filter_nodes(nodes))


def get_sidebar_access_tree(visible_items, current_route_name=None):
    visible_leaf_keys = set(visible_items).intersection(_ACCESS_VIEW_NAMES)
    return filter_sidebar_tree(
        SIDEBAR_MENU,
        visible_leaf_keys,
        current_route_name=current_route_name,
    )


def get_sidebar_node(node_key):
    return _SIDEBAR_MENU_NODES.get(node_key)


def get_descendant_sidebar_keys(node_key):
    node = get_sidebar_node(node_key)
    if node is None:
        raise KeyError(node_key)
    return tuple(leaf["key"] for leaf in _menu_leaves((node,)))


def ensure_sidebar_permissions(user, empresa_id):
    return ensure_user_view_permissions(
        user,
        empresa_id,
        view_names=_sidebar_permission_view_names(),
    )


def _sidebar_definition_names():
    from importlib import import_module

    from access_control.services.view_registry import definitions_for_app
    from access_control.services.view_registry_audit import APP_DEFINITION_MODULES

    definitions_by_key = {}
    for definition_key in SIDEBAR_DEFINITION_KEYS.values():
        app = definition_key.split(".", 1)[0]
        module_path = APP_DEFINITION_MODULES.get(app)
        if module_path is None:
            continue
        try:
            import_module(module_path)
        except (ImportError, ValueError):
            continue
        definitions_by_key.update(
            {
                definition.key: definition.nombre
                for definition in definitions_for_app(app)
            }
        )
    return {
        item_key: definitions_by_key[definition_key]
        for item_key, definition_key in SIDEBAR_DEFINITION_KEYS.items()
        if definition_key in definitions_by_key
    }


def _sidebar_permission_view_names():
    definition_names = _sidebar_definition_names()
    legacy_names = {
        vista_nombre
        for item_key, vista_nombre in SIDEBAR_VIEW_NAMES.items()
        if item_key not in SIDEBAR_DEFINITION_KEYS
    }
    return legacy_names | set(definition_names.values())


def ensure_user_view_permissions(user, empresa_id, *, view_names=None):
    """Materialize empty VICMEAS rows for one user and one company."""
    if not getattr(user, "is_authenticated", False) or not empresa_id:
        return 0

    if not Empresa.objects.filter(pk=empresa_id).exists():
        return 0

    if view_names is None:
        from access_control.services.view_catalog import discover_protected_views

        vista_names = {
            definition.vista_nombre
            for definition in discover_protected_views()
        }
    else:
        vista_names = set(view_names)
    vistas = list(Vista.objects.filter(nombre__in=vista_names).only("id"))
    vista_ids = {vista.id for vista in vistas}
    if not vista_ids:
        return 0

    existing_ids = set(
        Permiso.objects.filter(
            usuario=user,
            empresa_id=empresa_id,
            vista_id__in=vista_ids,
        ).values_list("vista_id", flat=True)
    )
    missing_ids = vista_ids - existing_ids
    if not missing_ids:
        return 0

    Permiso.objects.bulk_create(
        [
            Permiso(
                usuario=user,
                empresa_id=empresa_id,
                vista_id=vista_id,
            )
            for vista_id in missing_ids
        ],
        ignore_conflicts=True,
    )
    return len(missing_ids)


def get_sidebar_visible_items(user, empresa_id, *, materialize_permissions=True):
    if not getattr(user, "is_authenticated", False) or not empresa_id:
        return set(SIDEBAR_GLOBAL_ITEMS) if getattr(user, "is_authenticated", False) else set()

    if materialize_permissions:
        ensure_sidebar_permissions(user, empresa_id)

    definition_names = _sidebar_definition_names()
    visible_names = set(
        Permiso.objects.filter(
            usuario=user,
            empresa_id=empresa_id,
            ver=True,
            vista__nombre__in=_sidebar_permission_view_names(),
        ).values_list("vista__nombre", flat=True)
    )
    visible_items = {
        item_key
        for item_key, vista_nombre in SIDEBAR_VIEW_NAMES.items()
        if item_key not in SIDEBAR_DEFINITION_KEYS
        if vista_nombre in visible_names
    }
    visible_items.update(
        item_key
        for item_key, vista_nombre in definition_names.items()
        if vista_nombre in visible_names
    )
    for group, children in SIDEBAR_GROUPS.items():
        if any(child in visible_items for child in children):
            visible_items.add(group)
    return visible_items | SIDEBAR_GLOBAL_ITEMS


def get_valid_users_for_empresa(empresa, *, active_only=False):
    """Return the compatibility union of assigned and permission-bearing users."""
    assigned_user_ids = UsuarioPerfilEmpresa.objects.filter(empresa=empresa).values("usuario_id")
    permission_user_ids = Permiso.objects.filter(empresa=empresa).values("usuario_id")
    queryset = User.objects.filter(id__in=assigned_user_ids.union(permission_user_ids))
    if active_only:
        queryset = queryset.filter(is_active=True)
    return queryset.order_by("username")


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
