from dataclasses import dataclass

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.urls import get_resolver

from AppDocs.app_classification import APPLICATION_APPS, SYSTEM_APPS
from access_control.models import Empresa, Permiso, Vista
from access_control.services.permissions import SIDEBAR_GROUPS, SIDEBAR_VIEW_NAMES, VICMEAS_FIELDS


BASE_COMPANY_CODE = "00"
BASE_COMPANY_DESCRIPTION = "empresa base"
BASE_VIEW_KEYS = tuple(SIDEBAR_GROUPS["access"])
SYSTEM_APP_NAMES = frozenset(app.rsplit(".", 1)[-1] for app in SYSTEM_APPS)
APPLICATION_APP_NAMES = frozenset(app.rsplit(".", 1)[-1] for app in APPLICATION_APPS)


class BootstrapInconsistency(Exception):
    """Raised when bootstrap cannot safely choose an existing record."""


@dataclass
class BootstrapSummary:
    empresa_created: bool = False
    empresa_reused: bool = False
    user_created: bool = False
    user_reused: bool = False
    views_processed: int = 0
    views_created: int = 0
    views_existing: int = 0
    permissions_processed: int = 0
    permissions_created: int = 0
    permissions_updated: int = 0
    permissions_unchanged: int = 0
    access_views_count: int = 0
    system_views_count: int = 0
    application_views_excluded: int = 0
    ambiguous_views_count: int = 0
    bootstrap_view_names: tuple = ()
    application_view_names: tuple = ()
    ambiguous_view_names: tuple = ()


def _sidebar_leaves(nodes=None):
    if nodes is None:
        from access_control.services.permissions import SIDEBAR_MENU

        nodes = SIDEBAR_MENU
    for node in nodes:
        children = node.get("children", ())
        if children:
            yield from _sidebar_leaves(children)
        else:
            yield node


def _base_view_definitions():
    leaves = {node["key"]: node for node in _sidebar_leaves()}
    return tuple(
        (SIDEBAR_VIEW_NAMES[key], leaves[key].get("route_name"))
        for key in BASE_VIEW_KEYS
    )


def _route_namespace(route_name):
    route_name = (route_name or "").strip()
    return route_name.split(":", 1)[0] if ":" in route_name else None


def _url_namespace_apps():
    namespace_apps = {}

    def visit(patterns):
        for pattern in patterns:
            urlconf_module = getattr(pattern, "urlconf_module", None)
            if urlconf_module is not None:
                module_name = getattr(urlconf_module, "__name__", "")
                app_name = module_name.split(".", 1)[0]
                namespace = getattr(pattern, "namespace", None)
                if namespace:
                    namespace_apps[namespace] = app_name
                visit(getattr(pattern, "url_patterns", ()))

    visit(get_resolver().url_patterns)
    return namespace_apps


def _classified_route_app(route_name):
    namespace = _route_namespace(route_name)
    if namespace is None:
        return None
    return _url_namespace_apps().get(namespace, namespace)


def get_bootstrap_system_vistas(*, summary=None, required_vistas=()):
    """Select existing system views; only the access catalog may be created."""
    access_names = {name for name, _ in _base_view_definitions()}
    access_vistas = []
    for name in access_names:
        vista = Vista.objects.filter(nombre=name).order_by("id").first()
        if vista is None:
            vista = next((item for item in required_vistas if item.nombre == name), None)
        if vista is not None:
            access_vistas.append(vista)

    system_vistas = []
    application_names = []
    ambiguous_names = []
    for vista in Vista.objects.exclude(nombre__in=access_names).order_by("id"):
        app_name = _classified_route_app(vista.route_name)
        if app_name in SYSTEM_APP_NAMES:
            system_vistas.append(vista)
        elif app_name in APPLICATION_APP_NAMES:
            application_names.append(vista.nombre)
        else:
            ambiguous_names.append(vista.nombre)

    selected = access_vistas + system_vistas
    if summary:
        summary.access_views_count = len(access_vistas)
        summary.system_views_count = len(system_vistas)
        summary.application_views_excluded = len(application_names)
        summary.ambiguous_views_count = len(ambiguous_names)
        summary.application_view_names = tuple(application_names)
        summary.ambiguous_view_names = tuple(ambiguous_names)
        summary.bootstrap_view_names = tuple(vista.nombre for vista in selected)
    return selected


def ensure_base_company(*, dry_run=False, summary=None):
    matches = Empresa.objects.filter(codigo=BASE_COMPANY_CODE)
    if matches.count() > 1:
        raise BootstrapInconsistency(
            f"Se encontraron múltiples empresas con código {BASE_COMPANY_CODE}."
        )
    empresa = matches.first()
    if empresa:
        if summary:
            summary.empresa_reused = True
        return empresa
    if summary:
        summary.empresa_created = True
    return Empresa(codigo=BASE_COMPANY_CODE, descripcion=BASE_COMPANY_DESCRIPTION)


def ensure_system_vistas(*, dry_run=False, summary=None):
    vistas = []
    for nombre, route_name in _base_view_definitions():
        vista = Vista.objects.filter(nombre=nombre).order_by("id").first()
        if vista is None:
            vista = Vista(nombre=nombre, route_name=route_name)
            if not dry_run:
                vista.save()
            if summary:
                summary.views_created += 1
        else:
            if route_name and vista.route_name != route_name and not dry_run:
                vista.route_name = route_name
                vista.save(update_fields=["route_name"])
            if summary:
                summary.views_existing += 1
        vistas.append(vista)
    selected = get_bootstrap_system_vistas(summary=summary, required_vistas=vistas)
    if summary:
        summary.views_processed = len(selected)
        summary.views_existing = len(selected) - summary.views_created
    return selected


def ensure_initial_superuser(*, username, email="", first_name="", last_name="", password=None, dry_run=False, summary=None):
    user = User.objects.filter(username=username).first()
    if user:
        if not user.is_superuser:
            raise BootstrapInconsistency(f"El usuario {username} ya existe y no es superusuario.")
        if not user.is_staff:
            raise BootstrapInconsistency(
                f"El usuario {username} es superusuario pero no tiene is_staff activo."
            )
        if summary:
            summary.user_reused = True
        return user
    if not dry_run:
        if password is None:
            raise ValueError("Se requiere password para crear el usuario.")
        validate_password(password)
        user = User.objects.create_superuser(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
    else:
        user = User(username=username, email=email, first_name=first_name, last_name=last_name)
    if summary:
        summary.user_created = True
    return user


def ensure_initial_permissions(*, user, empresa, vistas, dry_run=False, summary=None):
    for vista in vistas:
        if summary:
            summary.permissions_processed += 1
        if dry_run:
            permiso = None
            if user.pk and empresa.pk and vista.pk:
                permiso = Permiso.objects.filter(usuario=user, empresa=empresa, vista=vista).first()
            if permiso is None:
                if summary:
                    summary.permissions_created += 1
            elif any(not getattr(permiso, field) for field in VICMEAS_FIELDS):
                if summary:
                    summary.permissions_updated += 1
            elif summary:
                summary.permissions_unchanged += 1
            continue

        permiso, created = Permiso.objects.get_or_create(
            usuario=user,
            empresa=empresa,
            vista=vista,
            defaults={field: True for field in VICMEAS_FIELDS},
        )
        if created:
            if summary:
                summary.permissions_created += 1
            continue
        changed_fields = [field for field in VICMEAS_FIELDS if not getattr(permiso, field)]
        if changed_fields:
            for field in changed_fields:
                setattr(permiso, field, True)
            permiso.save(update_fields=changed_fields)
            if summary:
                summary.permissions_updated += 1
        elif summary:
            summary.permissions_unchanged += 1


def initialize_system_for_user(*, username, email="", first_name="", last_name="", password=None, dry_run=False):
    summary = BootstrapSummary()
    if dry_run:
        empresa = ensure_base_company(dry_run=True, summary=summary)
        vistas = ensure_system_vistas(dry_run=True, summary=summary)
        user = ensure_initial_superuser(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            dry_run=True,
            summary=summary,
        )
        ensure_initial_permissions(
            user=user, empresa=empresa, vistas=vistas, dry_run=True, summary=summary
        )
        return summary

    with transaction.atomic():
        empresa = ensure_base_company(summary=summary)
        if empresa.pk is None:
            empresa.save()
        vistas = ensure_system_vistas(summary=summary)
        ensure_initial_superuser(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password,
            summary=summary,
        )
        user = User.objects.get(username=username)
        ensure_initial_permissions(
            user=user, empresa=empresa, vistas=vistas, summary=summary
        )
    return summary