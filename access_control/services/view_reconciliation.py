from dataclasses import dataclass

from django.db import transaction

from access_control.models import AccessRequest, Permiso, PerfilAccesoDetalle, Vista
from access_control.services.empresa_activa import get_navigable_vistas
from core_search.models import SearchPageIndex
from settings.models import UserPreferences


class ReconciliationError(RuntimeError):
    pass


class ReconciliationPreconditionError(ReconciliationError):
    pass


class ReconciliationInvariantError(ReconciliationError):
    pass


@dataclass(frozen=True)
class RouteExpectation:
    vista_id: int
    nombre: str
    current_route_name: str | None
    target_route_name: str | None


@dataclass(frozen=True)
class ReconciliationPlan:
    release_routes: tuple[RouteExpectation, ...]
    assign_routes: tuple[RouteExpectation, ...]

    @property
    def all_expectations(self):
        return self.release_routes + self.assign_routes


@dataclass(frozen=True)
class ViewUsageSnapshot:
    view_rows: tuple
    permission_rows: tuple
    profile_rows: tuple
    preference_rows: tuple
    search_rows: tuple
    access_request_rows: tuple


@dataclass(frozen=True)
class ReconciliationResult:
    mode: str
    changed: int
    would_clear: tuple[tuple[int, str, str], ...]
    would_set: tuple[tuple[int, str, str], ...]
    snapshot: ViewUsageSnapshot
    navigation_before: tuple[tuple[int, str], ...]
    navigation_after: tuple[tuple[int, str], ...]
    conflicts: tuple[str, ...]
    invariants: tuple[tuple[str, bool], ...]
    permission_changes: int = 0
    deleted_views: int = 0


def _expectation(vista_id, nombre, current_route_name, target_route_name):
    return RouteExpectation(vista_id, nombre, current_route_name, target_route_name)


TASKS_LEGACY_ROUTE_SPECS = (
    ("Tareas - Listado", "tareas:listar_tareas"),
    ("Tareas - Publicar tarea", "tareas:publicar_tarea"),
)
TASKS_CANONICAL_ROUTE_NAMES = {
    "Tareas": "tareas:listar_tareas",
    "Tareas - Ciclo de vida": "tareas:publicar_tarea",
}


def _resolve_vista(nombre, current_route_name):
    rows = Vista.objects.filter(nombre=nombre)
    if rows.count() != 1:
        raise ReconciliationPreconditionError(
            f"El nombre no existe exactamente una vez: {nombre}."
        )
    vista = rows.get()
    if vista.route_name != current_route_name:
        raise ReconciliationPreconditionError(
            f"La Vista {nombre} tiene route_name inesperado: {vista.route_name}."
        )
    return vista


def build_tasks_reconciliation_plan():
    """Build the route plan from current database identities, never fixed PKs."""
    from tareas.vicmeas import TASKS_VIEW_DEFINITIONS

    definitions_by_name = {
        definition.nombre: definition
        for definition in TASKS_VIEW_DEFINITIONS
    }
    release_routes = []
    for nombre, route_name in TASKS_LEGACY_ROUTE_SPECS:
        vista = _resolve_vista(nombre, route_name)
        release_routes.append(_expectation(vista.id, nombre, route_name, None))

    assign_routes = []
    for nombre, route_name in TASKS_CANONICAL_ROUTE_NAMES.items():
        definition = definitions_by_name.get(nombre)
        if definition is None or definition.route_name != route_name:
            raise ReconciliationPreconditionError(
                f"La definición canónica no coincide para {nombre}."
            )
        vista = _resolve_vista(nombre, None)
        assign_routes.append(_expectation(vista.id, nombre, None, route_name))

    return ReconciliationPlan(
        release_routes=tuple(release_routes),
        assign_routes=tuple(assign_routes),
    )


def _resolved_plan(plan):
    return build_tasks_reconciliation_plan() if plan is None else plan


def _model_rows(model, **filters):
    field_names = [field.attname for field in model._meta.concrete_fields]
    return tuple(
        model.objects.filter(**filters).order_by("pk").values_list(*field_names)
    )


def _view_rows():
    return tuple(
        Vista.objects.order_by("pk").values_list(
            "id", "nombre", "descripcion", "route_name"
        )
    )


def snapshot_view_usage(plan=None):
    plan = _resolved_plan(plan)
    view_ids = tuple(expectation.vista_id for expectation in plan.all_expectations)
    view_names = tuple(expectation.nombre for expectation in plan.all_expectations)
    return ViewUsageSnapshot(
        view_rows=_view_rows(),
        permission_rows=_model_rows(Permiso, vista_id__in=view_ids),
        profile_rows=_model_rows(PerfilAccesoDetalle, vista_id__in=view_ids),
        preference_rows=_model_rows(UserPreferences, vista_inicial_id__in=view_ids),
        search_rows=_model_rows(SearchPageIndex, vista_id__in=view_ids),
        access_request_rows=_model_rows(
            AccessRequest,
            vista_nombre__in=view_names,
        ),
    )


def _validate_preconditions(plan):
    ids = [item.vista_id for item in plan.all_expectations]
    if len(set(ids)) != len(ids):
        raise ReconciliationPreconditionError("El plan contiene IDs de Vista duplicados.")

    for expectation in plan.all_expectations:
        rows = Vista.objects.filter(pk=expectation.vista_id)
        if rows.count() != 1:
            raise ReconciliationPreconditionError(
                f"La Vista ID {expectation.vista_id} no existe exactamente una vez."
            )
        if Vista.objects.filter(nombre=expectation.nombre).count() != 1:
            raise ReconciliationPreconditionError(
                f"El nombre no existe exactamente una vez: {expectation.nombre}."
            )
        vista = rows.get()
        if vista.nombre != expectation.nombre:
            raise ReconciliationPreconditionError(
                f"La Vista ID {expectation.vista_id} tiene nombre inesperado: {vista.nombre}."
            )
        if vista.route_name != expectation.current_route_name:
            raise ReconciliationPreconditionError(
                f"La Vista {expectation.nombre} tiene route_name inesperado: {vista.route_name}."
            )

    legacy_ids = [item.vista_id for item in plan.release_routes]
    if UserPreferences.objects.filter(vista_inicial_id__in=legacy_ids).exists():
        raise ReconciliationPreconditionError(
            "Una Vista legacy está asignada como vista inicial; no se reasignará automáticamente."
        )


def _navigation_rows(route_overrides=None):
    return tuple(
        (vista.id, vista.nombre)
        for vista in get_navigable_vistas(route_overrides=route_overrides)
    )


def _route_conflicts(plan, route_overrides=None):
    route_overrides = route_overrides or {}
    target_routes = {
        item.target_route_name
        for item in plan.assign_routes
        if item.target_route_name
    }
    planned_ids = {item.vista_id for item in plan.all_expectations}
    conflicts = []
    for vista in Vista.objects.exclude(pk__in=planned_ids):
        route_name = route_overrides.get(vista.id, vista.route_name)
        if route_name in target_routes:
            conflicts.append(f"{route_name} pertenece a {vista.nombre} (ID {vista.id}).")
    return tuple(conflicts)


def _planned_routes(plan):
    return {
        item.vista_id: item.target_route_name
        for item in plan.all_expectations
    }


def _expected_route_changes(plan):
    return (
        tuple(
            (item.vista_id, item.nombre, item.current_route_name)
            for item in plan.release_routes
        ),
        tuple(
            (item.vista_id, item.nombre, item.target_route_name)
            for item in plan.assign_routes
        ),
    )


def _invariant_map(before, after, plan):
    expected_routes = _planned_routes(plan)
    before_identity = tuple((row[0], row[1], row[2]) for row in before.view_rows)
    after_identity = tuple((row[0], row[1], row[2]) for row in after.view_rows)
    route_changes = {
        (before_row[0], after_row[3])
        for before_row, after_row in zip(before.view_rows, after.view_rows)
        if before_row[3] != after_row[3]
    }
    return {
        "view_count": len(before.view_rows) == len(after.view_rows),
        "view_identity": before_identity == after_identity,
        "only_planned_routes_changed": route_changes
        == set(expected_routes.items()),
        "permissions_identical": before.permission_rows == after.permission_rows,
        "profiles_identical": before.profile_rows == after.profile_rows,
        "preferences_identical": before.preference_rows == after.preference_rows,
        "search_identical": before.search_rows == after.search_rows,
        "access_requests_identical": before.access_request_rows
        == after.access_request_rows,
        "permission_changes_zero": before.permission_rows == after.permission_rows,
        "deleted_views_zero": len(before.view_rows) == len(after.view_rows),
    }


def _validate_after_apply(before, after, plan):
    invariants = _invariant_map(before, after, plan)
    failed = [name for name, passed in invariants.items() if not passed]
    if failed:
        raise ReconciliationInvariantError(
            "Fallaron invariantes de reconciliación: " + ", ".join(failed)
        )
    conflicts = _route_conflicts(plan)
    if conflicts:
        raise ReconciliationInvariantError(
            "Persisten conflictos de route_name: " + "; ".join(conflicts)
        )
    return invariants


def _baseline_mismatch(snapshot, expected_snapshot):
    if expected_snapshot is None:
        return ()
    mismatches = []
    for field_name in (
        "permission_rows",
        "profile_rows",
        "preference_rows",
        "search_rows",
        "access_request_rows",
    ):
        if getattr(snapshot, field_name) != getattr(expected_snapshot, field_name):
            mismatches.append(field_name)
    return tuple(mismatches)


def preview_reconciliation(
    *, plan=None, expected_snapshot=None
):
    plan = _resolved_plan(plan)
    _validate_preconditions(plan)
    snapshot = snapshot_view_usage(plan)
    mismatches = _baseline_mismatch(snapshot, expected_snapshot)
    if mismatches:
        raise ReconciliationPreconditionError(
            "El snapshot actual difiere del snapshot esperado: "
            + ", ".join(mismatches)
        )

    route_overrides = _planned_routes(plan)
    conflicts = _route_conflicts(plan, route_overrides)
    if conflicts:
        raise ReconciliationPreconditionError(
            "El plan produciría conflictos de route_name: " + "; ".join(conflicts)
        )
    return ReconciliationResult(
        mode="PREVIEW",
        changed=0,
        would_clear=_expected_route_changes(plan)[0],
        would_set=_expected_route_changes(plan)[1],
        snapshot=snapshot,
        navigation_before=_navigation_rows(),
        navigation_after=_navigation_rows(route_overrides),
        conflicts=(),
        invariants=(
            ("preview_no_writes", True),
            ("permission_changes_zero", True),
            ("deleted_views_zero", True),
        ),
    )


def apply_reconciliation(
    *, plan=None, expected_snapshot=None
):
    plan = _resolved_plan(plan)
    with transaction.atomic():
        _validate_preconditions(plan)
        locked = tuple(
            Vista.objects.select_for_update()
            .filter(pk__in=[item.vista_id for item in plan.all_expectations])
            .order_by("pk")
        )
        if len(locked) != len(plan.all_expectations):
            raise ReconciliationPreconditionError(
                "No se pudieron bloquear las cuatro Vistas."
            )
        _validate_preconditions(plan)
        before = snapshot_view_usage(plan)
        mismatches = _baseline_mismatch(before, expected_snapshot)
        if mismatches:
            raise ReconciliationPreconditionError(
                "El snapshot actual difiere del snapshot esperado: "
                + ", ".join(mismatches)
            )

        for item in plan.release_routes + plan.assign_routes:
            Vista.objects.filter(pk=item.vista_id).update(
                route_name=item.target_route_name
            )

        after = snapshot_view_usage(plan)
        invariants = _validate_after_apply(before, after, plan)
        return ReconciliationResult(
            mode="APPLY",
            changed=len(plan.all_expectations),
            would_clear=_expected_route_changes(plan)[0],
            would_set=_expected_route_changes(plan)[1],
            snapshot=before,
            navigation_before=_navigation_rows(),
            navigation_after=_navigation_rows(),
            conflicts=(),
            invariants=tuple(invariants.items()),
        )