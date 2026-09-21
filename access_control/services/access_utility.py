from collections import defaultdict
from dataclasses import dataclass

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction

from access_control.models import Permiso, UsuarioPerfilEmpresa, Vista
from access_control.services.permissions import (
    SIDEBAR_GLOBAL_ITEMS,
    SIDEBAR_GROUPS,
    SIDEBAR_SCOPE_ALIASES,
    SIDEBAR_VIEW_NAMES,
    VICMEAS_FIELDS,
    get_descendant_sidebar_keys,
    get_sidebar_node,
)


ACCESS_UTILITY_VISTA_NAME = "Control de Acceso - Utilitario de Acceso"
SENSITIVE_FIELDS = frozenset(("autorizar", "supervisor"))

ACCESS_UTILITY_SCOPE_VIEWS = {
    "tasks": (
        "Tareas",
        "Tareas - Ciclo de vida",
        "Tareas - Hitos",
        "Tareas - Documentos y evidencia",
        "Tareas - Dashboard personal",
    ),
    "control_de_proyectos": (
        "Control de Proyectos - Proyectos",
        "Control de Proyectos - Tareas",
        "Control de Proyectos - Clientes",
        "Control de Proyectos - Profesionales",
        "Control de Proyectos - Documentos de Tarea",
    ),
}


@dataclass(frozen=True)
class ScopeResolution:
    requested_leaf_names: tuple
    vistas: tuple
    missing_names: tuple
    conflicts: tuple = ()


@dataclass(frozen=True)
class ScopeConflict:
    code: str
    nombre: str
    detail: str


def get_access_utility_vista():
    return Vista.objects.filter(nombre=ACCESS_UTILITY_VISTA_NAME).first()


def _get_scope_item_keys(scope):
    global_names = {
        SIDEBAR_VIEW_NAMES[item_key]
        for item_key in SIDEBAR_GLOBAL_ITEMS
        if item_key in SIDEBAR_VIEW_NAMES
    }
    if scope == "all":
        item_keys = [
            item_key
            for group in SIDEBAR_GROUPS.values()
            for item_key in group
            if item_key not in SIDEBAR_GLOBAL_ITEMS
            and SIDEBAR_VIEW_NAMES[item_key] not in global_names
        ]
    elif get_sidebar_node(scope) is not None:
        item_keys = [
            item_key
            for item_key in get_descendant_sidebar_keys(scope)
            if item_key not in SIDEBAR_GLOBAL_ITEMS
        ]
    elif scope in SIDEBAR_SCOPE_ALIASES:
        item_keys = [
            item_key
            for item_key in SIDEBAR_SCOPE_ALIASES[scope]
            if item_key not in SIDEBAR_GLOBAL_ITEMS
        ]
    elif scope in SIDEBAR_GROUPS:
        item_keys = [
            item_key
            for item_key in SIDEBAR_GROUPS[scope]
            if item_key not in SIDEBAR_GLOBAL_ITEMS
            and SIDEBAR_VIEW_NAMES[item_key] not in global_names
        ]
    else:
        raise ValidationError("El alcance seleccionado no es válido.")

    return list(dict.fromkeys(item_keys))


def _registry_definitions_for_scope(scope, group=None):
    from importlib import import_module

    from access_control.services.view_registry import (
        VistaDefinition,
        definitions_for_app,
        register_app_definitions,
    )
    from access_control.services.view_registry_audit import APP_DEFINITION_MODULES

    expected_group = group or scope
    candidate_apps = (scope,) if scope in APP_DEFINITION_MODULES else APP_DEFINITION_MODULES
    for app in candidate_apps:
        module_path = APP_DEFINITION_MODULES.get(app)
        if module_path is None:
            continue
        module = import_module(module_path)
        declared_definitions = tuple(
            definition
            for value in vars(module).values()
            for definition in (value if isinstance(value, (tuple, list)) else (value,))
            if isinstance(definition, VistaDefinition)
        )
        if declared_definitions:
            register_app_definitions(app, declared_definitions)
        definitions = tuple(
            definition
            for definition in definitions_for_app(app)
            if definition.access_utility and definition.group == expected_group
        )
        if definitions:
            return definitions
    return None


def _resolve_registry_scope_vistas(scope, definitions):
    definitions_by_key = {}
    definitions_by_name = {}
    conflicts = []
    for definition in definitions:
        previous_key = definitions_by_key.get(definition.key)
        if previous_key is not None and previous_key != definition:
            conflicts.append(
                ScopeConflict(
                    code="duplicate_definition_key",
                    nombre=definition.nombre,
                    detail=f"La key {definition.key} tiene metadatos incompatibles.",
                )
            )
            continue
        previous_name = definitions_by_name.get(definition.nombre)
        if previous_name is not None and previous_name != definition:
            conflicts.append(
                ScopeConflict(
                    code="duplicate_definition_name",
                    nombre=definition.nombre,
                    detail="El nombre canónico pertenece a definiciones incompatibles.",
                )
            )
            continue
        definitions_by_key[definition.key] = definition
        definitions_by_name[definition.nombre] = definition

    requested_names = tuple(definition.nombre for definition in definitions_by_key.values())
    rows_by_name = {}
    duplicate_names = set()
    for vista in Vista.objects.filter(nombre__in=requested_names).order_by("id"):
        if vista.nombre in rows_by_name:
            duplicate_names.add(vista.nombre)
            continue
        rows_by_name[vista.nombre] = vista

    for nombre in sorted(duplicate_names):
        conflicts.append(
            ScopeConflict(
                code="duplicate_persistent_name",
                nombre=nombre,
                detail="Existen varias filas Vista con el mismo nombre canónico.",
            )
        )

    missing_names = tuple(
        nombre
        for nombre in requested_names
        if nombre not in rows_by_name
    )
    return ScopeResolution(
        requested_leaf_names=requested_names,
        vistas=tuple(
            rows_by_name[nombre]
            for nombre in requested_names
            if nombre in rows_by_name and nombre not in duplicate_names
        ),
        missing_names=missing_names,
        conflicts=tuple(conflicts),
    )


def _resolve_named_scope_vistas(requested_names):
    vistas_by_name = {}
    for vista in Vista.objects.filter(nombre__in=requested_names).order_by("id"):
        vistas_by_name.setdefault(vista.nombre, vista)
    missing_names = tuple(name for name in requested_names if name not in vistas_by_name)
    resolved_names = tuple(dict.fromkeys(requested_names))
    return ScopeResolution(
        requested_leaf_names=requested_names,
        vistas=tuple(vistas_by_name[name] for name in resolved_names if name in vistas_by_name),
        missing_names=missing_names,
    )


def _resolve_legacy_scope_vistas(scope, *, excluded_groups=()):
    item_keys = _get_scope_item_keys(scope)
    excluded_groups = set(excluded_groups)
    if scope == "all":
        item_keys = [
            item_key
            for item_key in item_keys
            if not any(
                item_key in group_items
                for group, group_items in SIDEBAR_GROUPS.items()
                if group in excluded_groups
            )
        ]
    requested_names = tuple(SIDEBAR_VIEW_NAMES[item_key] for item_key in item_keys)
    return _resolve_named_scope_vistas(requested_names)


def resolve_scope_vistas(scope, *, group=None):
    from access_control.services.view_registry_audit import APP_DEFINITION_MODULES

    explicit_names = ACCESS_UTILITY_SCOPE_VIEWS.get(scope)
    if explicit_names is not None:
        return _resolve_named_scope_vistas(explicit_names)

    if scope == "all":
        registry_groups = tuple(
            app for app in APP_DEFINITION_MODULES if app in SIDEBAR_GROUPS
        )
        registry_resolutions = [
            _resolve_registry_scope_vistas(
                app,
                _registry_definitions_for_scope(app),
            )
            for app in registry_groups
        ]
        legacy_resolution = _resolve_legacy_scope_vistas(
            scope,
            excluded_groups=registry_groups,
        )
        requested_names = tuple(
            dict.fromkeys(
                name
                for resolution in (*registry_resolutions, legacy_resolution)
                for name in resolution.requested_leaf_names
            )
        )
        resolved_vistas = []
        seen_ids = set()
        missing_names = []
        conflicts = []
        for resolution in (*registry_resolutions, legacy_resolution):
            for vista in resolution.vistas:
                if vista.id not in seen_ids:
                    seen_ids.add(vista.id)
                    resolved_vistas.append(vista)
            missing_names.extend(resolution.missing_names)
            conflicts.extend(resolution.conflicts)
        return ScopeResolution(
            requested_leaf_names=requested_names,
            vistas=tuple(resolved_vistas),
            missing_names=tuple(dict.fromkeys(missing_names)),
            conflicts=tuple(conflicts),
        )

    registry_definitions = _registry_definitions_for_scope(scope, group=group)
    if registry_definitions is not None:
        return _resolve_registry_scope_vistas(scope, registry_definitions)
    return _resolve_legacy_scope_vistas(scope)


def get_scope_vistas(scope, *, require_all=True):
    resolution = resolve_scope_vistas(scope)
    if require_all and (resolution.missing_names or resolution.conflicts):
        messages = []
        if resolution.missing_names:
            messages.append("Faltan Vistas catalogadas: " + ", ".join(resolution.missing_names))
        if resolution.conflicts:
            messages.append(
                "Conflictos de Vistas: "
                + "; ".join(conflict.detail for conflict in resolution.conflicts)
            )
        raise ValidationError(" ".join(messages))
    return list(resolution.vistas)


def get_hideable_sidebar_vistas():
    """Resolve the unique, non-global leaf views controlled by the sidebar."""
    vistas = get_scope_vistas("all", require_all=False)
    unique_vistas = {}
    for vista in vistas:
        unique_vistas.setdefault(vista.id, vista)
    return list(unique_vistas.values())


def get_descendant_vistas(node_key, *, require_all=False):
    """Resolve a hierarchical sidebar node to its ordered leaf Vistas."""
    item_keys = get_descendant_sidebar_keys(node_key)
    expected_names = [SIDEBAR_VIEW_NAMES[item_key] for item_key in item_keys]
    vistas_by_name = {}
    for vista in Vista.objects.filter(nombre__in=expected_names).order_by("id"):
        vistas_by_name.setdefault(vista.nombre, vista)
    missing_names = [name for name in expected_names if name not in vistas_by_name]
    if missing_names and require_all:
        raise ValidationError("Faltan Vistas catalogadas: " + ", ".join(missing_names))
    return [vistas_by_name[name] for name in expected_names if name in vistas_by_name]


def get_hideable_sidebar_vista(vista):
    allowed_vistas = get_hideable_sidebar_vistas()
    allowed_by_id = {allowed_vista.id: allowed_vista for allowed_vista in allowed_vistas}
    if vista.id not in allowed_by_id:
        raise ValidationError("La Vista seleccionada no es una opción navegable del sidebar.")
    return allowed_by_id[vista.id]


def get_access_utility_user_options(empresas):
    empresa_ids = [empresa.id for empresa in empresas]
    assigned_rows = UsuarioPerfilEmpresa.objects.filter(
        empresa_id__in=empresa_ids,
        usuario__is_active=True,
    ).values_list("usuario_id", "empresa_id")
    permission_rows = Permiso.objects.filter(
        empresa_id__in=empresa_ids,
        usuario__is_active=True,
    ).values_list("usuario_id", "empresa_id")
    empresa_ids_by_user = defaultdict(set)
    for user_id, empresa_id in [*assigned_rows, *permission_rows]:
        empresa_ids_by_user[user_id].add(empresa_id)

    users = User.objects.filter(
        id__in=empresa_ids_by_user,
        is_active=True,
    ).order_by("username")
    return [
        {
            "user": user,
            "empresa_ids": sorted(empresa_ids_by_user[user.id]),
        }
        for user in users
    ]


def has_explicit_permission(*, user, empresa, vista, accion):
    if accion not in VICMEAS_FIELDS:
        raise ValueError("Acción VICMEAS no válida.")
    return Permiso.objects.filter(
        usuario=user,
        empresa=empresa,
        vista=vista,
        **{accion: True},
    ).exists()


def validate_operation_authorization(*, executor, empresa, vista, selected_fields):
    if not has_explicit_permission(
        user=executor,
        empresa=empresa,
        vista=vista,
        accion="modificar",
    ):
        raise PermissionError("No tienes modificar en el Utilitario de Acceso para la empresa objetivo.")
    if SENSITIVE_FIELDS.intersection(selected_fields) and not has_explicit_permission(
        user=executor,
        empresa=empresa,
        vista=vista,
        accion="supervisor",
    ):
        raise PermissionError("Se requiere supervisor para asignar permisos sensibles.")


def validate_cross_company_authorization(
    *, executor, active_empresa, target_empresa, vista, selected_fields=()
):
    if not has_explicit_permission(
        user=executor,
        empresa=active_empresa,
        vista=vista,
        accion="modificar",
    ):
        raise PermissionError("No tienes modificar en la herramienta administrativa.")

    requires_supervisor = (
        active_empresa.pk != target_empresa.pk
        or SENSITIVE_FIELDS.intersection(selected_fields)
    )
    if requires_supervisor and not has_explicit_permission(
        user=executor,
        empresa=active_empresa,
        vista=vista,
        accion="supervisor",
    ):
        raise PermissionError("Se requiere supervisor para operar otra empresa.")


def build_preview(*, usuario, empresa, vistas, selected_fields, scope_resolution=None):
    existing = {
        permiso.vista_id: permiso
        for permiso in Permiso.objects.filter(
            usuario=usuario,
            empresa=empresa,
            vista_id__in=[vista.id for vista in vistas],
        ).select_related("vista")
    }
    created = 0
    updated = 0
    unchanged = 0
    for vista in vistas:
        permiso = existing.get(vista.id)
        if permiso is None:
            created += 1
            continue
        if any(not getattr(permiso, field_name) for field_name in selected_fields):
            updated += 1
        else:
            unchanged += 1
    return {
        "usuario": usuario,
        "empresa": empresa,
        "vistas": vistas,
        "selected_fields": selected_fields,
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "processed": len(vistas),
        "requested": len(scope_resolution.requested_leaf_names) if scope_resolution else len(vistas),
        "missing_names": scope_resolution.missing_names if scope_resolution else (),
    }


def apply_additive_permissions(*, usuario, empresa, vistas, selected_fields):
    selected_fields = tuple(selected_fields)
    with transaction.atomic():
        existing = {
            permiso.vista_id: permiso
            for permiso in Permiso.objects.select_for_update().filter(
                usuario=usuario,
                empresa=empresa,
                vista_id__in=[vista.id for vista in vistas],
            )
        }
        created = 0
        updated = 0
        unchanged = 0
        for vista in vistas:
            permiso = existing.get(vista.id)
            if permiso is None:
                Permiso.objects.create(
                    usuario=usuario,
                    empresa=empresa,
                    vista=vista,
                    **{field_name: field_name in selected_fields for field_name in VICMEAS_FIELDS},
                )
                created += 1
                continue

            changed_fields = [
                field_name
                for field_name in selected_fields
                if not getattr(permiso, field_name)
            ]
            if changed_fields:
                for field_name in changed_fields:
                    setattr(permiso, field_name, True)
                permiso.save(update_fields=changed_fields)
                updated += 1
            else:
                unchanged += 1

    return {
        "processed": len(vistas),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "deleted": 0,
        "selected_fields": selected_fields,
    }


def validate_hide_view_authorization(*, executor, empresa, vista):
    if not has_explicit_permission(
        user=executor,
        empresa=empresa,
        vista=vista,
        accion="modificar",
    ):
        raise PermissionError("No tienes modificar en el Utilitario de Acceso para la empresa objetivo.")


def build_hide_view_preview(*, empresa, vista):
    affected_permissions = list(
        Permiso.objects.filter(
            empresa=empresa,
            vista=vista,
            ver=True,
        ).select_related("usuario").order_by("usuario__username", "usuario_id")
    )
    return {
        "empresa": empresa,
        "vista": vista,
        "affected_permissions": affected_permissions,
        "affected_users": [permiso.usuario for permiso in affected_permissions],
        "affected_count": len(affected_permissions),
        "processed": 1,
    }


def hide_view_from_sidebar(*, empresa, vista):
    with transaction.atomic():
        affected_permissions = Permiso.objects.select_for_update().filter(
            empresa=empresa,
            vista=vista,
            ver=True,
        )
        updated = affected_permissions.count()
        if updated:
            affected_permissions.update(ver=False)

    return {
        "processed": 1,
        "updated": updated,
        "v_disabled": updated,
        "created": 0,
        "deleted": 0,
        "icmeas_modified": 0,
    }
