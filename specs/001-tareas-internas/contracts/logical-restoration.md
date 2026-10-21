# Contract: L5 Logical Task Restoration

**Status**: Etapa 2 del servicio interno implementada y probada; HTTP/L4 siguen diferidos
**Feature**: [spec.md](../spec.md)
**Data model**: [data-model.md](../data-model.md)
**Web routes**: [web-urls.md](web-urls.md)

This document defines the L5 restoration service and deferred HTTP contract. Etapa 1 preparó
el ledger; Etapa 2 implementa solo preview, restauración interna transaccional y auditoría
post-commit. No registra rutas ni autoriza operaciones productivas. La campaña autorizada
del 2026-10-20 usó exclusivamente fixtures sintéticas en la base de desarrollo `tareas`.

## Boundary and invariants

- The operational source is the configured `BASE_TAREAS` role. The active company comes
  from the authenticated session and must equal the company on the deletion operation.
  Preserve the current L2 Base 00 restriction unless a separate contract expands it.
- The only restoration scope is the exact `tareas.tarea` manifest of one committed
  `LOGICALLY_DELETED` operation. Do not derive a new scope by traversing the current tree.
- Every manifest row must still exist, belong to the same company, and have all deletion
  markers tied to the source operation. One missing, mismatched, or conflicting row blocks
  the entire operation.
- Restore clears only `eliminada`, `eliminada_en`, `eliminada_por` and
  `eliminacion_operacion_id`. It does not change lifecycle state, dates, progress,
  responsibility, hierarchy, related records or files.
- The original deletion operation and manifest remain immutable. A restoration is a new
  operation with a new UUID and its own copy of the exact task-ID manifest.
- L4 remains GET-only. I on `Tareas - Tareas eliminadas` controls history visibility;
  S on `Tareas` controls restoration. Neither permission grants the other.

## Internal service interface

The APIs below are implemented in `tareas/services/logical_restoration.py`. They are not
HTTP endpoints and do not expose restoration through L4:

```text
build_logical_restoration_preview(
    actor, empresa_id, deletion_operation_id
) -> LogicalRestorationPreview

restore_logical_task_tree(
    actor, empresa_id, deletion_operation_id, restoration_operation_id,
    motivo, expected_fingerprint
) -> LogicalRestorationResult

reconcile_logical_restoration_audit(
    actor, empresa_id, restoration_operation_id
) -> LogicalRestorationResult
```

`LogicalRestorationPreview` contains the source deletion UUID, root ID/correlativo,
company, deletion actor/time/reason, exact ordered task manifest, retained hierarchy and
related-record summaries, document/file references, current row/marker consistency,
warnings, blockers, backend identity/configuration version, and a fingerprint. The signed
HTTP token additionally binds the current actor, active company, source operation,
new restoration UUID and fingerprint. The service preview itself is read-only.

`LogicalRestorationResult` identifies the new operation UUID, source deletion UUID,
restored task IDs, operational result (`COMMITTED`), audit status and whether the request
was an idempotent replay. A replay with the same UUID and identical actor/company/source
operation/reason/manifest/backend payload returns the existing operation. Reuse of that
UUID with different data is a conflict. A new UUID cannot restore a deletion operation
that already has a committed restoration.

The service revalidates authenticated/active user membership, S on `Tareas`, active
company and operation ownership. The L4-origin HTTP flow separately revalidates I on
`Tareas - Tareas eliminadas`; in that flow both permissions are required, for their
independent purposes.

## Implemented ledger extension (Etapa 1)

The extension reuses `TareaEliminacionOperacion` and `TareaEliminacionElemento`, preserving
all existing deletion rows and their L2/L4 readers:

- The nullable `reverses_operation` foreign key produces the physical column
  `reverses_operation_id`. It is protected and unique. Its model/database constraints
  allow either no reverse link, a pending restoration with empty `result_code`, or a
  committed restoration with `result_code=LOGICALLY_RESTORED`.
- `RestorationOperationInput`, `create_restoration_pending()` and
  `get_restoration_operation()` prepare/read the new operation in both ledger adapters.
  Registration validates that the source is a committed logical deletion in the same
  company/backend, checks its task-only manifest and rejects a different existing restore.
  It persists a pending row only; it does not modify task markers or commit a restoration.
- The original deletion row, including UUID, state, result, motive, actor, dates, company
  and manifest, is never updated. The common operation table PK enforces distinct UUIDs
  across deletion and restoration rows; the unique reverse link enforces at most one
  pending-or-committed restoration per deletion.
- Store the exact restored task IDs in `TareaEliminacionElemento` under the new operation
  ID. The set must exactly equal the source operation's task manifest; no non-task item is
  accepted.
- Keep the L1 deletion-motive constraint unchanged; add independent checks for restoration
  linkage/state and required motive. No file-cleanup rows are created.

The Django migration `0034_logical_restoration_ledger.py` is generated, and the frozen
ledger DDL plus additive `logical_restoration_schema.sql` contract are updated. The
read-only `preview_logical_restoration_schema()` checks the configured backend and, for
MYSQL_CONFIG, reports the server version and checks the exact selected database, column,
unique index and source FK. It does not certify server-version compatibility or CHECK
enforcement. The additive L5 SQL contract was applied by direct SQL to the owner-authorized
development database `tareas` on 2026-10-20; the L5 preflight is `CURRENT`. No Django
migration was applied to the operational database, and this test authorization does not
extend to production. The Django migration router allows migrations to SYSTEM aliases;
deployers must explicitly target the configured `BASE_TAREAS` Django alias, not migrate an
unrelated `default` database.

The service locks the company, exact manifest task rows, retained relation/document rows,
the source operation and its manifest. It creates or resumes the matching pending row,
copies the exact manifest, clears only the four logical-deletion markers, and transitions
the new ledger operation to `COMMITTED/LOGICALLY_RESTORED` in the same `BASE_TAREAS`
transaction. A pre-commit failure rolls back both task markers and new ledger data. A commit
with uncertain acknowledgement is resolved by the same new UUID; it is never reused for a
different request. No cross-database transaction with audit or filesystem is claimed.

For `MYSQL_CONFIG`, resolve through the existing Tareas role and public Settings
connection API, use parameterized SQL, check `SELECT DATABASE()` equals exactly `tareas`,
and verify the affected tables are transactional before writing. Do not fall back to
`default`, change `DATABASES`, or alter a global router. The schema change remains
unapplied until a separate implementation and deployment authorization.

The SQL `CHECK` constraints are supplementary: older MySQL versions may parse but not
enforce them. Ledger input validation and transactional source/manifest checks remain
authoritative; this stage does not claim CHECK enforcement on a physical server.

## Operation and audit states

| Source deletion | Restoration operation | Task projection | Meaning |
|---|---|---|---|
| `COMMITTED / LOGICALLY_DELETED`, no committed restore | none | `CURRENTLY_DELETED` if all markers match | Eligible for preview |
| `COMMITTED / LOGICALLY_DELETED` | `PENDING`, empty result, linked to source | pending registration; callers must keep it in the same transaction | Prepared ledger row, not a restoration |
| `COMMITTED / LOGICALLY_DELETED` | `COMMITTED / LOGICALLY_RESTORED` | `RESTORED` relative to this deletion | Historical deletion remains queryable |
| Any deletion | committed restore points to it, but task markers conflict | `INCONSISTENT` | Fail closed; do not repair automatically |
| Manifest includes a missing task row | no committed restoration | `PHYSICALLY_ABSENT` | Reject whole restoration; retain history |
| Any committed operation | `audit_status=PENDING/ERROR` | operation result remains distinct from audit | Reconcile with the same restoration UUID |

After several cycles, a prior deletion can remain historically `RESTORED` while the same
task is currently deleted by a later operation. L4 must show both facts without conflating
the old operation outcome with the task's present state.

The central audit event is written post-commit through
`AuditoriaService.log_event_idempotent` using the restoration UUID as its own key. Lookup
and reconciliation use the existing public API. A confirmed operation with pending audit
must be reported as operationally committed/audit-pending, not as audit-confirmed or as a
transaction failure. A transaction that did not commit must never be recorded as a
successful restoration.

Etapa 1 does not create audit events, reconcile them, or set a restoration to `COMMITTED`.
The original deletion's pending audit policy and durable logging of failed attempts remain
open decisions for subsequent stages.

## Controlled errors

Service errors map to controlled response keys; never return raw DB, SQL or filesystem
exceptions.

| Error code | Condition | Expected behavior |
|---|---|---|
| `RESTORATION_INVALID_REQUEST` | Invalid UUID, reason or input | Reject without writes |
| `RESTORATION_UNAUTHORIZED` | Missing active user or explicit S | 403 |
| `RESTORATION_HISTORY_ACCESS_REQUIRED` | L4 I missing in L4-origin flow | 403 without history disclosure |
| `RESTORATION_NOT_FOUND` | Source operation is absent or outside active company | 404 |
| `RESTORATION_NOT_ELIGIBLE` | Source is not committed logical deletion | 409 |
| `RESTORATION_ALREADY_COMPLETED` | Source deletion already has a committed restore | 409; no second mutation |
| `RESTORATION_MANIFEST_INCOMPLETE` | Manifest is empty, partial, mixed-type or mismatched | 409; rollback |
| `RESTORATION_TASK_MISSING` | A manifest task row is physically absent | 409; rollback; no reconstruction |
| `RESTORATION_STATE_CONFLICT` | Deletion markers do not all match the source UUID | 409; rollback |
| `RESTORATION_HIERARCHY_CONFLICT` | Retained relations fail company/root/manifest checks | 409; rollback |
| `RESTORATION_PREVIEW_STALE` | Actor/company/backend/manifest fingerprint changed | 409; require new preview |
| `RESTORATION_OPERATION_ID_CONFLICT` | UUID reused with a different payload | 409 |
| `RESTORATION_COMMIT_UNCERTAIN` | Commit outcome cannot yet be determined | Controlled pending response; reconcile by UUID |
| `RESTORATION_AUDIT_PENDING` | Operational commit succeeded, central audit is unresolved | Warning/pending; reconcile idempotently |
| `RESTORATION_AUDIT_CONFLICT` | Existing audit event does not match the operation | Controlled conflict; do not overwrite |
| `RESTORATION_BACKEND_UNAVAILABLE` | Resolver, schema or connection validation fails | 503; fail closed |

An external file confirmed missing is reported as unavailable metadata; the restoration
does not recreate it and does not fail solely because no physical file cleanup is needed.
The mechanism for authoritative file-existence checks remains pending.

## Proposed HTTP routes

These routes are **DEFERRED** and must not be registered until L5 implementation is
separately authorized:

| Method | Proposed route | Name | Permission and behavior |
|---|---|---|---|
| GET | `/tareas/eliminadas/operacion/<uuid:operation_id>/restaurar/` | `restauracion_logica` | Read-only preview; require L4 I and S on `Tareas` separately |
| POST | `/tareas/eliminadas/operacion/<uuid:operation_id>/restaurar/` | `restauracion_logica` | CSRF, reason, signed preview; revalidate L4 I and S on `Tareas`; commit through service |

GET never mutates. The confirmation is a traditional POST with CSRF and explicit reason;
the response is controlled and does not expose raw exceptions. The existing L4 list,
task-detail and operation-detail paths remain GET-only. The restore action is visible
from L4 only when S is also present; no sidebar permission or new VICMEAS View is created
by this contract.

## Etapa 1 actual

Implementados el campo/link de ledger, constraints de unicidad/consistencia, la migración
Django `0034_logical_restoration_ledger.py`, las primitivas internas
`create_restoration_pending()`/`get_restoration_operation()` y el preflight
`preview_logical_restoration_schema()`. El contrato MySQL actualizado para una base
existente está en `tareas/sql/logical_restoration_schema.sql`; el schema de ledger inicial
incluye también la columna. Los SELECT de L2 SQL-direct conservan su lista de columnas
previa, y el preflight L1 de eliminación no exige el campo L5.

La etapa solo registra filas de ledger `PENDING` y su manifiesto exacto dentro del UOW
existente. No cambia marcas de `Tarea`, no escribe `LOGICALLY_RESTORED`, no marca una
operación como exitosa, no emite auditoría ni instala DDL. La migración se ejecutó
únicamente en la base temporal creada por el test runner; el SQL MySQL se validó con
conexiones simuladas. La ejecución focalizada combinada registró 163 PASS, 0 FAIL y
0 SKIP para persistencia/schema L5 y regresiones L2/L3/L4. La carrera concurrente se
probó en SQLite aislada; MariaDB real sigue pendiente.

## Etapa 2 actual

Implementados `build_logical_restoration_preview()`, `restore_logical_task_tree()` y
`reconcile_logical_restoration_audit()` en `tareas/services/logical_restoration.py`, además
de las transiciones y locks de ledger requeridos en los adaptadores existentes. El preview
es de solo lectura e incluye el manifiesto, filas/estados, relaciones retenidas, documentos,
referencias no expuestas de archivos, advertencias y bloqueos. La confirmación vuelve a
calcular su fingerprint bajo locks; las filas ausentes o inconsistentes bloquean todo el
manifiesto. No cambia estados de negocio, relaciones, documentos ni archivos.

Se permite continuar cuando la auditoría de la eliminación original sigue pendiente o con
error; el preview lo informa y cada operación de auditoría se concilia independientemente.
Las referencias externas de origen se informan como advertencia y no bloquean, según la
decisión del propietario. La disponibilidad física de archivos no se comprueba.

La auditoría de restauración se entrega después del commit mediante
`AuditoriaService.log_event_idempotent()` y se reconcilia por el UUID de restauración. El
servicio no agrega rutas, vistas, tokens HTTP ni cambia la proyección L4. El guard de raíz
L2 permanece intacto: los ciclos posteriores de eliminación/restauración todavía no están
habilitados. El 2026-10-20 se ejecutó una campaña con fixtures sintéticas en MariaDB
10.11.13: T01–T12 y T14 pasaron; T13 quedó parcial, T15 usó un doble de auditoría central
en memoria y T16 permanece pendiente. Las conexiones operacionales de la campaña verificaron
`DATABASE() = tareas`; se limpiaron las fixtures y no se tocaron archivos físicos ni otras
bases. La regresión focal de `AppDocs.settings_test` registró 153 PASS.

## Open decisions

- Whether exact parent-child edge snapshots are required to detect direct SQL changes
  outside official L3 writers.
- The authoritative, non-destructive way to confirm an external file is missing.
- The response to replaying an old deletion UUID after its task was restored; it must never
  execute another deletion.
- Whether failed, rolled-back restoration attempts require a durable history row separate
  from committed restoration operations.
- Repeated cycles remain blocked by the unchanged L2 root guard and require separate
  authorization before that guard can be changed.
- New Spanish/English UI keys, if needed, require separate authorization for global
  translation files outside `tareas/`.
