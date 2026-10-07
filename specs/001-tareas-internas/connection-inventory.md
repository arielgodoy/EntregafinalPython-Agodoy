# T135 Connection Transformation Inventory

## Principle

> No estamos transformando funcionalidades.
> Estamos transformando conexiones.
>
> La aplicación debe hacer exactamente lo mismo antes y después;
> únicamente debe cambiar el origen físico/configurable de sus datos
> operacionales.

## Baseline

- `BASELINE_COMMIT = e37e337cd02c0846eff62762b8ad289aec6febe5`
- `TOTAL_ACCESS_SITES_REVIEWED = 47`
- `SAFE_ALREADY_ADAPTED = 19`
- `ALREADY_CLOSED = 8`
- `CANONICAL_EXTERNAL_REFERENCE = 14`
- `ACTIONABLE_ACCESS_SITES = 6`
- `MANUAL = 0`
- `CANONICAL_PENDING_RESIDUES = 4`
- `CANONICAL_RESIDUES = 4`
- `PENDING = 2`
- `BLOCKED = 1`
- `CLOSED = 1`

Six access sites are not six residues. The six sites are grouped into four
semantic connection transformations.

## Closed History

| Block | Commit | Status |
|---|---|---|
| T135B | `9a4d37a2f7570de54c9b67da2acd2479c853f405` | CLOSED |
| T135C | `1839b80a3fd0986d9f3f03e2939ef99c540b138f` | CLOSED |
| T135D | `db45c9309f8c21149ffdd89f25440f2f007335b8` | CLOSED |
| T135E | `2c92e71d62f0ee2a2caa26a9a0204a4654e04d5e` | CLOSED |
| T135F | `74326e6cdc361c8c950786626ef38e59d842c2ec` | CLOSED |
| T135G | `2775eeb8aef734ddfd46c953e9f58725f1dc7726` | CLOSED |
| T135H | `e37e337cd02c0846eff62762b8ad289aec6febe5` | CLOSED |

These blocks are not pending and must not be reinterpreted.

## Pending Inventory

### T135-R001

- `STATUS = BLOCKED`
- `PRIORITY = P1`
- `FAMILY = Views/list/detail compatibility`
- `FILE = tareas/views.py`
- `FUNCTION = TareaEmpresaQuerysetMixin.get_queryset`
- `ACCESS_SITES = 1`
- `CURRENT_ACCESS = Direct Tarea.objects`
- `EXPECTED_FRONTIER = Existing task/detail/list storage`
- `COMPLEXITY = EXTENDED`
- `BLOCKED_AT_COMMIT = 17eb1852e3c7000881c9d728923d876140532b62`
- `BLOCKER = Historical consumers require a real lazy Django QuerySet while the MYSQL_CONFIG task frontier exposes backend-neutral TaskListResult.`
- `CONNECTION_ONLY_TRANSFORMATION_FEASIBLE = NO`
- `FUNCTIONAL_CONTRACT_FROZEN = YES`
- `REVISIT = Post-Tareas connection architecture/private-router contract design.`

### T135-R002

- `STATUS = CLOSED`
- `PRIORITY = P1`
- `FAMILY = Hierarchy`
- `FILE = tareas/services/hierarchy.py`
- `FUNCTIONS = get_parent, get_children`
- `ACCESS_SITES = 2`
- `CURRENT_ACCESS = Implicit ORM/default`
- `EXPECTED_FRONTIER = Hierarchy storage`
- `COMPLEXITY = EXTENDED`
- `CLOSED_AT_COMMIT = PENDING_FINAL_COMMIT`
- `EVIDENCE = Django alias path validated; MYSQL_CONFIG real validation PASS; parent/child identity preserved by Tarea.pk; children ordered by id ASC; no implicit default; no _state.db; no silent fallback; cleanup PASS; one historical View failure confirmed preexisting.`

### T135-R003

- `STATUS = PENDING`
- `PRIORITY = P1`
- `FAMILY = KPI/dashboard`
- `FILE = tareas/services/kpi.py`
- `FUNCTION = _personal_task_queryset`
- `ACCESS_SITES = 2`
- `CURRENT_ACCESS = Direct Tarea/participant ORM`
- `EXPECTED_FRONTIER = Backend-aware dashboard source`
- `COMPLEXITY = EXTENDED`

### T135-R004

- `STATUS = PENDING`
- `PRIORITY = P1`
- `FAMILY = KPI/dashboard`
- `FILE = tareas/services/kpi.py`
- `FUNCTION = _movement_queryset`
- `ACCESS_SITES = 1`
- `CURRENT_ACCESS = Django Subquery/OuterRef`
- `EXPECTED_FRONTIER = Backend-aware movement queries`
- `COMPLEXITY = EXTENDED`

## Accounting Rule

`PENDING_RESIDUES` decreases only when a residue completes:

1. contract and identity diagnostic;
2. connection transformation;
3. regression/isolation tests;
4. real backend validation when applicable;
5. final checkpoint;
6. commit and push.

Allowed statuses are `PENDING`, `IN_PROGRESS`, `BLOCKED`, and `CLOSED`.
Rows are never deleted; only status and evidence may change.

## Next

- `NEXT_RESIDUE = T135-R003`

No implementation of R001 is included in this inventory checkpoint.

## Final Tareas Connection Gate

Before T135/Tareas can be declared fully complete, perform a final
connection-only audit of the entire `tareas/` app.

The gate must inspect for operational Tareas access that bypasses the
approved configurable architecture, including implicit default ORM,
unscoped saves/deletes/refreshes, transactions without an operational
backend, related managers resolving through default, `_state.db` backend
selection, direct SQL outside approved adapters, silent default fallback,
missing `MYSQL_CONFIG` paths, and legacy connection mechanisms superseded
by the final private Tareas router architecture.

Canonical external references such as `User`, `Empresa`, `Permiso`, `Vista`,
`SettingsMySQLConnection`, `Proveedor`, and `Avatar` remain external and
must not be classified as operational Tareas residues merely because they
use SYSTEM/CORE storage.

This is a future closure gate only. It does not authorize implementation,
router design, reopening closed residues, or a new audit in this checkpoint.
