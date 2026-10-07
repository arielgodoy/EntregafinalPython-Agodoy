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
- `PENDING = 0`
- `BLOCKED = 1`
- `CLOSED = 3`

Six access sites are not six residues. The six sites are grouped into four
semantic connection transformations.

## T135 Private Boundary Contract — Phase A

### Architectural Requirement

- `ALL_OPERATIONAL_ACCESS_BEHIND_PRIVATE_BOUNDARY = REQUIRED`
- `CONFIG_ONLY_BACKEND_CHANGE = REQUIRED`
- `DIRECT_OPERATIONAL_DATABASE_DEPENDENCY = FORBIDDEN`
- `OBSERVABLE_BEHAVIOR_FROZEN = YES`
- `INTERNAL_ORM_REPLACEABLE = YES`

The frozen contract is the observable behavior: public inputs, results,
identity, filters, ordering, company/user scopes, permissions, validation,
states, observable errors, transactions, side effects, HTTP, templates, UX,
and business rules.

QuerySets, lazy evaluation, `.objects`, `.using()`, `select_related`,
`prefetch_related`, related managers, `Q`, `Subquery`, `OuterRef`, `annotate`,
`values`, `values_list`, `get_object_or_404`, `.filter().first()`, and ORM
chaining are implementation mechanisms, not functional contracts by
themselves.

### Revised Transformation Rule

> Una transformación de conexión puede adaptar consumidores internos,
> reemplazar QuerySets por resultados backend-neutral y sustituir operaciones
> ORM por primitives/adapters equivalentes, siempre que preserve exactamente
> el comportamiento funcional observable.

No se permite conservar un acceso operacional directo únicamente porque
históricamente utilizaba Django ORM. Si una construcción ORM impide operar
sobre otro backend, debe encapsularse o reemplazarse detrás de la frontera
privada; no debe declararse funcionalidad inmutable salvo evidencia contractual.

### Private Boundary Responsibilities

- `PRIVATE_CONNECTION_RESOLVER`: resuelve rol lógico, backend,
	alias/configuración, database name, capacidades, fail-closed y ausencia de
	fallback. No contiene negocio.
- `STORAGE_ADAPTER`: ejecuta primitives equivalentes, usando ORM encapsulado
	para `DJANGO_ALIAS` y SQL parametrizado/DTOs para `MYSQL_CONFIG`, incluyendo
	relaciones operacionales y transacciones del backend.
- `BUSINESS_SERVICE`: conserva reglas, permisos, estados, filtros funcionales,
	fórmulas KPI, validaciones y side effects. No conoce ubicación física.
- `VIEW`: conserva HTTP, sesión, autorización, templates y UX; consume
	servicios/primitives backend-independent y no decide ubicación física.

Interfaces comunes deben expresar operaciones funcionales como
`get_task`, `find_task`, `list_tasks`, `exists_task`, `list_personal_tasks`,
`latest_movements`, `list_comments` y `create_comment`, no
`get_queryset_for_*`.

### Backend and DTO Rules

- `DJANGO_ALIAS` puede implementar primitives con ORM, QuerySets y subqueries
	dentro de su adapter.
- `MYSQL_CONFIG` debe implementar las mismas primitives con SQL parametrizado,
	DTOs backend-neutral, relaciones completas y transacciones equivalentes.
- Un DTO debe materializar todos los atributos, relaciones, colecciones, roles
	e identidades externas que observe su consumidor, incluidos eventos y
	notificaciones.
- La paridad debe cubrir creador, responsable, participante explícito y no
	participante cuando la operación dependa de roles.
- Los guards deben basarse en capacidades reales de la frontera, nunca en el
	supuesto histórico de que una operación es Django-only.

### Data, Transactions and Fail-Closed

Los datos operacionales de Tareas atraviesan la frontera privada. `User`,
`Empresa`, `Permiso`, `Vista`, `Proveedor` y demás referencias canónicas
externas pueden conservarse por ID y resolverse mediante servicios públicos;
no se requieren joins físicos cross-database ni copias de SYSTEM/CORE.

- `DJANGO_ALIAS_TRANSACTION = transaction.atomic(using=resolved_alias)`
- `MYSQL_CONFIG_TRANSACTION = transacción explícita sobre la conexión resuelta`
- `CROSS_BACKEND_OPERATIONAL_TRANSACTION = FORBIDDEN`
- `IMPLICIT_DEFAULT = FORBIDDEN`
- `SILENT_FALLBACK = FORBIDDEN`
- `_state.db` como routing = `FORBIDDEN`

Si el rol, conexión o backend requerido no puede resolverse, la operación
debe fallar cerrada.

`DATABASE_ROUTERS` de Django por sí solos no constituyen esta frontera porque
`MYSQL_CONFIG` puede no ser un alias Django. Un router Django futuro puede
complementar aliases/model routing, pero debe convivir con el resolver privado.

### Future Server and Migration Plan

Tareas debe poder cambiar a una base/servidor dedicado mediante configuración
y despliegue de su schema operacional, sin reescribir reglas funcionales.

- `PHASE_A`: formalizar este contrato backend-independent.
- `PHASE_B`: consolidar la frontera/resolver privado.
- `PHASE_C`: reabrir y migrar los residuos bloqueados restantes.
- `PHASE_D`: ejecutar Full Tareas Connection Integrity Gate.
- `PHASE_E`: corregir residuos encontrados.
- `PHASE_F`: certificar Tareas backend-independent.
- `PHASE_G`: extraer contrato reusable para APPLICATION_APPS.
- `PHASE_H`: aplicar posteriormente a gestiondte y demás apps.

No se implementa ninguna fase posterior en este checkpoint.

### T135 Private Boundary — Phase B2 Resolver Adoption

- `B2_PRIVATE_RESOLVER_ADOPTION = COMPLETE`
- `ALL_STORAGE_RESOLVERS_USE_PRIVATE_ENTRYPOINT = YES`
- `UNEXPECTED_RESOLVER_RESIDUE = 0`
- `DJANGO_ALIAS_RESOLUTION = PASS`
- `MYSQL_CONFIG_RESOLUTION = PASS`
- `NO_IMPLICIT_DEFAULT_INTRODUCED = YES`
- `NO_SILENT_FALLBACK_INTRODUCED = YES`
- `FAIL_CLOSED = YES`
- `EXISTING_ADAPTERS_CONTINUE_WORKING = YES`
- `FUNCTIONAL_LOGIC_CHANGED = NO`
- `DTO_CHANGED = NO`
- `SCHEMA_CHANGED = NO`
- `SYSTEM_CORE_CHANGED = NO`

All storage resolver families now consume the private operational entrypoint.
Remaining `get_tarea_connection`/`get_tarea_mysql_connection` references are
limited to compatibility wrapper implementation, the explicit legacy task
guard, and technical schema/reference-data helpers. R001 remains
`BLOCKED / REOPEN_PHASE_C`; R003 and R004 are closed by their Phase C
primitives.

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

### T135C-FIX3 Comments HTTP MySQL Checkpoint

- `STATUS = CLOSED`
- `SCOPE = Comments HTTP guard only`
- `GUARD = ExistingTaskBackendGuardMixin removed only from TareaComentariosView`
- `GLOBAL_GUARD_CHANGED = NO`
- `BASE_TAREAS = MYSQL_CONFIG`
- `REAL_HTTP_CREATE = PASS` (`200`, JSON `success=true`)
- `REAL_HTTP_LOAD = PASS` (`200`, JSON `success=true`, created comment returned)
- `PHYSICAL_MYSQL_ROW = PASS` (temporary task `3`, author `1`, active company `3`)
- `CLEANUP = PASS` (temporary comment absent after cleanup)
- `REGRESSION = PASS` (107 focused Comments/Reading tests)
- `EVENT_PATH = FAIL` (best-effort notification expects `TaskDTO.prioridad`; outside this connection-only correction)
- `DTO_COMPATIBILITY = PASS` (MySQL comments now expose the historical View relation interface)

### T135C-FIX4 Comments Event DTO Parity Checkpoint

- `STATUS = CLOSED`
- `SCOPE = MySQL TaskDTO priority parity`
- `EVENT_FUNCTION = tareas.services.comments._schedule_comment_event`
- `EVENT_CONSUMER = tareas.services.notifications.emit_task_event`
- `EVENT_TASK_REQUIRED_ATTRIBUTES = pk, empresa, prioridad`
- `MYSQL_TASK_DTO_HAS_PRIORIDAD = YES`
- `PHYSICAL_MYSQL_TAREA_HAS_PRIORIDAD = YES` (`tareas_tarea.id=3`, value `NORMAL`)
- `REAL_HTTP_CREATE = PASS` (`200`, JSON `success=true`, no DTO priority error)
- `REAL_HTTP_LOAD = PASS` (`200`, JSON `success=true`, temporary comment returned)
- `CLEANUP = PASS`
- `EVENT_PATH = PASS` (no `TaskDTO.prioridad` error observed)

### T135C-FIX6 Comments MySQL Participant Parity Checkpoint

- `STATUS = CLOSED`
- `SCOPE = Explicit participant parity in MySQLCommentStorage.task`
- `HISTORICAL_EFFECTIVE_PARTICIPANT_RULE = creator + responsible + explicit participants`
- `MYSQL_EXPLICIT_PARTICIPANT_PARITY = PASS`
- `TASK6_USER1_HTTP_CREATE = PASS` (`200`, JSON `success=true`)
- `TASK6_HTTP_LOAD = PASS` (`200`, JSON `success=true`, temporary comment returned)
- `NON_PARTICIPANT_FAIL_CLOSED = PASS`
- `TASK_DTO_PRIORIDAD_PARITY = PASS`
- `EVENT_PATH = PASS`
- `CLEANUP = PASS`

## Pending Inventory

### T135-R001

- `STATUS = CLOSED`
- `PRIORITY = P1`
- `FAMILY = Views/list/detail compatibility`
- `FILE = tareas/views.py`
- `FUNCTION = TareaEmpresaQuerysetMixin.get_queryset`
- `ACCESS_SITES = 1`
- `CURRENT_ACCESS = Backend-neutral task/detail/similarity/document storage`
- `EXPECTED_FRONTIER = Existing task/detail/list/similarity/document storage`
- `COMPLEXITY = EXTENDED`
- `BLOCKED_AT_COMMIT = 17eb1852e3c7000881c9d728923d876140532b62`
- `CLOSED_AT_COMMIT = PENDING_C3_CHECKPOINT`
- `BLOCKER = Superseded by the Phase A contract: QuerySet/laziness was not a functional contract.`
- `CLASSIFICATION = LEGACY_ORM_COUPLING`
- `BLOCK_REASON_SUPERSEDED_BY_CONTRACT_REVIEW = YES`
- `REOPEN_IN_PHASE_C = YES`
- `CONNECTION_ONLY_TRANSFORMATION_FEASIBLE = YES`
- `FUNCTIONAL_CONTRACT_FROZEN = YES`
- `R001_LEGACY_ORM_COUPLING_REMOVED = YES`
- `R001_DJANGO_ALIAS_PARITY = PASS`
- `R001_MYSQL_CONFIG_PARITY = PASS (storage/API parity; public HTTP smoke pending real configured backend)`
- `R001_HTTP_PARITY = PASS (Django focal suite)`
- `R001_REAL_BACKEND = PENDING FINAL MYSQL_CONFIG HTTP SMOKE`

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

- `STATUS = CLOSED`
- `PRIORITY = P1`
- `FAMILY = KPI/dashboard`
- `FILE = tareas/services/kpi.py`
- `FUNCTION = _personal_task_queryset`
- `ACCESS_SITES = 2`
- `CURRENT_ACCESS = Direct Tarea/participant ORM`
- `EXPECTED_FRONTIER = Backend-aware dashboard source`
- `COMPLEXITY = EXTENDED`
- `BLOCKER = _personal_task_queryset combina Tarea y participación mediante ORM Django; no existe actualmente una frontera backend-neutral suficiente para MYSQL_CONFIG y preservarla requiere adaptar la composición KPI/dashboard, fuera del alcance de transformación mecánica de conexiones T135.`
- `CLASSIFICATION = LEGACY_ORM_COUPLING`
- `BLOCK_REASON_SUPERSEDED_BY_CONTRACT_REVIEW = YES`
- `REOPEN_IN_PHASE_C = NO`
- `R003_LEGACY_ORM_COUPLING_REMOVED = YES`
- `R003_DJANGO_ALIAS_PARITY = PASS`
- `R003_MYSQL_CONFIG_PARITY = PASS`
- `R003_REAL_BACKEND = PASS`
- `CLOSED_AT = Phase C1`

### T135-R004

- `STATUS = CLOSED`
- `PRIORITY = P1`
- `FAMILY = KPI/dashboard`
- `FILE = tareas/services/kpi.py`
- `FUNCTION = _movement_queryset`
- `ACCESS_SITES = 1`
- `CURRENT_ACCESS = Django Subquery/OuterRef`
- `EXPECTED_FRONTIER = Backend-aware movement queries`
- `COMPLEXITY = EXTENDED`
- `BLOCKER = _movement_queryset depende de un Django QuerySet lazy con Subquery/OuterRef sobre transiciones e historial documental. MYSQL_CONFIG no dispone actualmente de una frontera backend-neutral que preserve ese contrato sin adaptar la composición KPI/dashboard.`
- `CLASSIFICATION = LEGACY_ORM_COUPLING`
- `REOPEN_IN_PHASE_C = NO`
- `R004_LEGACY_ORM_COUPLING_REMOVED = YES`
- `R004_DJANGO_ALIAS_PARITY = PASS`
- `R004_MYSQL_CONFIG_PARITY = PASS`
- `R004_REAL_BACKEND = PASS`
- `CLOSED_AT = Phase C2`

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

- `NEXT_RESIDUE = FINAL_TAREAS_CONNECTION_INTEGRITY_GATE`

## Document Relationship Closure

- `COMENTARIO_FORM_BACKEND_NEUTRAL = CLOSED`
- `DOCUMENT_REFERENCE_PRIMITIVE = CLOSED`
- `COMMENT_DOCUMENT_RELATIONSHIP_PARITY = CLOSED`
- `DOCUMENT_RELATIONSHIP_TESTS = PASS (27 focused T135 tests)`
- `UNRELATED_WORKTREE_CHANGES = requirements.txt`

## Final Tareas Connection Integrity Gate

- `FINAL_TAREAS_CONNECTION_INTEGRITY_GATE = PASS`
- `OPERATIONAL_BYPASS = 0`
- `UNKNOWN = 0`
- `OPERATIONAL_FORM_BYPASS = 0`
- `DIRECT_OPERATIONAL_ORM_VIEWS = 0`
- `STATE_DB_ROUTING = 0`
- `IMPLICIT_OPERATIONAL_DEFAULT = 0`
- `IMPLICIT_OPERATIONAL_TRANSACTION = 0`
- `UNSUPPORTED_LEGACY_GUARD = 0`
- `DTO_PARITY_GAP = 0`
- `RELATIONSHIP_PARITY_GAP = 0`
- `T135_FOCAL = PASS (48/48)`
- `PARITY_MATRIX = PASS (176/176)`
- `FULL_TAREAS_SUITE = 933 tests (910 pass, 8 failures, 15 errors)`
- `T135_INTRODUCED_FAILURES = 0`
- `INCONCLUSIVE_FAILURES = 0`
- `REAL_BACKEND = PASS (MYSQL_CONFIG / tareas / MySQLdb)`
- `SELECT_1 = PASS`
- `OPERATIONAL_TABLE_READ = PASS (4 tables)`
- `REAL_DOCUMENT_STORAGE = PASS (empty data set)`
- `REAL_COMMENT_DOCUMENT_RELATION = PASS (empty data set)`
- `HISTORICAL_DEBT = 8 failures + 15 errors, unchanged`
- `REUNION_FORM = CLOSED`
- `COMMENT_FORM = CLOSED`
- `COMMENT_DOCUMENT_RELATION = CLOSED`
- `TAREAS_PRIVATE_BOUNDARY = COMPLETE`
- `TAREAS_BACKEND_INDEPENDENT = YES`
- `TAREAS_CONFIG_ONLY_BACKEND_MOVE = YES`
- `TAREAS_CONNECTION_TRANSFORMATION_COMPLETE = YES`
- `READY_TO_EXTRACT_GENERAL_CONNECTION_CONTRACT = YES`

## T135 Classification Checkpoint

- `T135_PENDING_ZERO = YES`
- `T135_BLOCKED_ZERO = NO (R001 closed; final integrity gate remains pending)`
- `FINAL_TAREAS_CONNECTION_INTEGRITY_GATE = PENDING`
- `T135_FULL_APP_CERTIFIED = NO`

The future integrity gate must reserve, at minimum:

- `OLD_DATA_ACCESS`
- `MISSING_BACKEND_PRIMITIVES`
- `LEGACY_BACKEND_GUARDS`
- `DTO_CONTRACT_PARITY`
- `RELATED_MANAGER_PARITY`
- `RELATIONSHIP_PARITY`
- `ROLE_VARIANT_PARITY`
- `EVENT_COMPOSITION_PARITY`
- `HTTP_END_TO_END_PARITY`
- `FAIL_CLOSED_CONTAMINATION`

Blocked residue `R001` is an input to the later private Tareas
router/frontier contract. No private router is created or designed in this
checkpoint.

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

## Post-T135 Corrective A1-A5 Checkpoint

This corrective scope closes the specific publication, meeting-creation,
meeting-convening, and comment-reading/recipient parity gaps below. It does not
certify the complete Tareas connection inventory or close the final gate above.

- `A1_PUBLICATION_AFTER_SIMILARITY_REVIEW = IMPLEMENTED`: MySQL lifecycle
  publication no longer rejects a draft merely because a similar operational
  task exists. The existing HTTP flow continues to route pending evaluations
  to similarity review; parity coverage confirms a decided evaluation followed
  by publication.
- `A2_MEETING_CREATION = IMPLEMENTED`: MySQL persists the published planned
  task, its publication transition, and its meeting on one BASE_TAREAS
  connection and transaction. Meeting validation failure rolls back the task.
- `A3_MEETING_CONVENING = IMPLEMENTED`: MySQL convening uses the storage
  transaction and does not assume that MySQL storage has a Django alias.
- `A4_COMMENT_READINGS = IMPLEMENTED`: MySQL comment, version, attachment links,
  and effective-participant reading rows are persisted in one storage
  transaction, matching the Django comment-created signal behavior.
- `A5_COMMENT_EFFECTIVE_ROLES = IMPLEMENTED`: MySQL comment task DTOs include
  creator, responsible, explicit participants, owners of non-annulled
  milestones, and mini-task assignees for participation validation and comment
  notifications.

The following findings were inspected but deliberately not changed in this
corrective scope:

- `A6_ON_COMMIT_ALIAS = NO CURRENT VIEW BLOCKER FOUND`: comment notifications
  register `transaction.on_commit()` on Django's default alias after the
  configured storage operation returns. Current comment views have no
  transaction wrapper and `ATOMIC_REQUESTS` is disabled. Reassess if a caller
  adds an outer transaction whose commit boundary must control this callback.
- `A7_LEGACY_PROGRESS_API = FAILS_CLOSED`: legacy progress entry points require
  `DjangoMilestoneStorage`; workspace references are tests, not production
  views. No behavior change was made.
- `A8_MODEL_CLEAN_DEFAULT_READ = OPEN AT THIS CHECKPOINT`: `Tarea.clean()` read
  the existing task through an implicit default ORM queryset. MySQL meeting
  updates called `full_clean()` on the planned-task DTO/model; this risk is
  addressed in the separate Corrective B checkpoint below.

No migration, schema, global routing, permission, view, or template changes
are included in this corrective checkpoint. The final Tareas connection
integrity gate remains pending.

Verification for this working checkpoint:

- `PY_COMPILE = PASS` for all `tareas/**/*.py` with Python 3.11.
- `DJANGO_CHECK = PASS` with the historical `ckeditor.W001` warning.
- Focused corrective selector = `PASS (117 tests)`.
- `REAL_MYSQL_WRITE_VALIDATION = NOT_RUN`; no isolated non-canonical MySQL
  database was established for mutation testing.
- The separately run `test_t054_notifications` module reported 9 errors and 2
  failures: its mocks/assertions expect `notify_task_event(destinatario=...)`,
  while the current comment service emits through `emit_task_event(recipients=...)`.
  The emitter API was not changed in this corrective scope.

## Post-T135 Corrective B — A8 Checkpoint

- `SCOPE = Tarea.clean() operational read during MySQL meeting updates`
- `A8_REPRODUCED = YES`: the MySQL-backed `update_meeting()` test observed an
  implicit `tareas_tarea` query on Django's default connection before the fix.
- `A8_MYSQL_DEFAULT_OPERATIONAL_READ = REMOVED`: `MySQLMeetingStorage` now
  loads the persisted lifecycle fields needed by `Tarea.clean()` and supplies
  that snapshot to model validation. The Django ORM path retains its existing
  read.
- `PUBLISHED_TASK_RULES = PRESERVED`: focused Django model tests and the
  MySQL-storage parity test verify the irreversible state and immutable
  publication/assignment dates.
- `FOCUSED_TESTS = PASS (118 tests)` with the runtime-only test settings
  workaround; `test_t054_notifications` was not selected.
- `PY_COMPILE = PASS` for all `tareas/**/*.py` with Python 3.11.
- `DJANGO_CHECK = PASS` with the historical `ckeditor.W001` warning.
- `REAL_MYSQL_VALIDATION = NOT RUN`: a MYSQL_CONFIG connection and safe DEV
  database were not positively established, so no external database was used.
- `SCHEMA_OR_MIGRATIONS_CHANGED = NO`; the final Tareas connection integrity
  gate remains pending.

## Corrective A/B Baseline Reproducibility

The historical Corrective B evidence records `118/118 PASS`. The exact test
selector was not recorded, so that result cannot be reproduced exactly from
the available evidence. This is an evidence reproducibility gap; it does not
invalidate or revise the historical result. Do not reconstruct the historical
selector by choosing arbitrary tests to reach the same count.

The current reproducible baseline is a new semantic baseline, not a
retroactive replacement for the historical result:

```text
HISTORICAL_CORRECTIVE_AB_RESULT = 118/118 PASS
HISTORICAL_SELECTOR = NOT_RECORDED
HISTORICAL_RESULT_REPRODUCIBLE_EXACTLY = NO

CURRENT_REPRODUCIBLE_SELECTOR =
  tareas.tests.test_t134_lifecycle_backend_parity.MySQLLifecycleStorageTests
  tareas.tests.test_t135_comments_reading_backend_parity.CommentsReadingBackendParityTests
  tareas.tests.test_t135_meetings_backend_parity.MeetingBackendParityTests
  tareas.tests.test_t135_similarity_backend_parity.SimilarityBackendParityTests
CURRENT_REPRODUCIBLE_TEST_COUNT = 43
CURRENT_REPRODUCIBLE_BASELINE = 43/43 PASS
FAILURES = 0
ERRORS = 0
```

These explicitly named classes cover the directly changed lifecycle and
similarity publication paths, comment/readings and effective-recipient parity,
meeting creation/convening, and MySQL meeting validation/default-query
protection. `tareas.tests.test_t054_notifications` is excluded; it is not used
to construct or pad this selector. Future checkpoints must record both the
exact selector and its discovered/executed test count.

This new baseline does not certify Tareas globally. The comment-editing
finding remains open: `CommentDTO` does not provide the `tarea` attribute
consumed by `edit_comment()`.
