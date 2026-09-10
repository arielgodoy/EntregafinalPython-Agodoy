from collections import defaultdict

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction

from access_control.models import Permiso, UsuarioPerfilEmpresa, Vista
from access_control.services.permissions import (
    SIDEBAR_GLOBAL_ITEMS,
    SIDEBAR_GROUPS,
    SIDEBAR_VIEW_NAMES,
    VICMEAS_FIELDS,
)


ACCESS_UTILITY_VISTA_NAME = "Control de Acceso - Utilitario de Acceso"
SENSITIVE_FIELDS = frozenset(("autorizar", "supervisor"))


def get_access_utility_vista():
    return Vista.objects.filter(nombre=ACCESS_UTILITY_VISTA_NAME).first()


def get_scope_vistas(scope, *, require_all=True):
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
    elif scope in SIDEBAR_GROUPS:
        item_keys = [
            item_key
            for item_key in SIDEBAR_GROUPS[scope]
            if item_key not in SIDEBAR_GLOBAL_ITEMS
            and SIDEBAR_VIEW_NAMES[item_key] not in global_names
        ]
    else:
        raise ValidationError("El alcance seleccionado no es válido.")

    item_keys = list(dict.fromkeys(item_keys))
    expected_names = [SIDEBAR_VIEW_NAMES[item_key] for item_key in item_keys]
    vistas_by_name = {}
    for vista in Vista.objects.filter(nombre__in=expected_names).order_by("id"):
        vistas_by_name.setdefault(vista.nombre, vista)
    missing_names = [name for name in expected_names if name not in vistas_by_name]
    if missing_names and require_all:
        raise ValidationError("Faltan Vistas catalogadas: " + ", ".join(missing_names))
    return [vistas_by_name[name] for name in expected_names if name in vistas_by_name]


def get_hideable_sidebar_vistas():
    """Resolve the unique, non-global leaf views controlled by the sidebar."""
    return get_scope_vistas("all", require_all=False)


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


def build_preview(*, usuario, empresa, vistas, selected_fields):
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
