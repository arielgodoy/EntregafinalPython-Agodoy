# Reusable APPLICATION_APP Operational Connection Audit Specification

**Purpose:** reusable execution specification for auditing and, only under a
separate explicit authorization, transforming one `APPLICATION_APP`.

**Normative contract:** `COPILOT/OPERATIONAL_CONNECTION_TRANSFORMATION_CONTRACT.md`
**Checklist:** `COPILOT/APPLICATION_CONNECTION_AUDIT_CHECKLIST.md`
**Inventory artifact:** `COPILOT/APPLICATION_CONNECTION_INVENTORY_TEMPLATE.md`

## 1. Scope declaration

Before work, fill in:

```text
APPLICATION =
CLASSIFICATION_SOURCE = AppDocs/app_classification.py
APPLICATION_CLASSIFICATION =
AUDIT_MODE = READ_ONLY | AUTHORIZED_TRANSFORMATION
WRITABLE_ROOT =
PRODUCTION_STATUS = UNKNOWN | DEV_ONLY | PRODUCTION | MIXED
ACTIVE_DATA_PLANE =
CONTROL_PLANE =
REQUESTED_SCOPE =
EXPLICITLY_EXCLUDED =
```

This specification applies only to the selected application. Do not audit
another application opportunistically and do not edit SYSTEM/CORE,
infrastructure, migrations, global settings or another app. An initial
connection audit is read-only. An authorized transformation is a distinct
task with its own file scope and explicit gates.

## 2. READ-ONLY audit procedure

### Phase A — Architecture and evidence

1. Read the required repository instructions and relevant current
   architecture documentation.
2. Confirm the selected app is an `APPLICATION_APP` from the classification
   source; do not reproduce the application list as a competing source.
3. Read the app's current connection contracts, inventories, tests and prior
   checkpoints. Treat initial certification as a hypothesis; include later
   corrective and physical-isolation evidence.
4. Separate known facts, historical assertions, current reproduction and
   unknowns. Record conflicts rather than silently choosing one status.

### Phase B — Ownership and boundary

Identify the app-owned private router/resolver, logical roles and scope,
storage/adapters, physical catalog/API consumed from Settings, and actual
Control Plane/Data Plane tables. Verify no dependency on another
APPLICATION_APP's private router. Do not infer ownership from Python app
labels or table prefixes alone.

### Phase C — Complete static inventory

Search the whole application, not just views/services/models. Include forms,
admin, signals, management commands, APIs/serializers, jobs, reports,
exports/imports, document generation, helpers, templatetags, tests and
wrappers. Search the patterns in the contract and inventory template.

Trace each candidate from public entry point/callers to its query/write and
physical backend. Classify each as one of:

```text
CONTROL_PLANE
EXTERNAL_CANONICAL
BACKEND_ADAPTER
PRODUCTIVE
PUBLIC_BUT_NOT_PRODUCTIVE
TEST_ONLY
DEAD_CONFIRMED
OPERATIONAL_BYPASS
UNKNOWN
```

Do not call a site dead because a local caller was not found. No credentials,
secrets, connection strings or sensitive row values belong in the inventory.

### Phase D — Contract snapshot

Capture observable inputs/results, IDs, filters/order, company and permission
scope, validation/messages, states/transitions, relationships, transactions,
events/recipients, HTTP/API and UX. Record identity independent of ORM/backend.
Do not freeze ORM implementation details as behavior.

### Phase E — Risk and result

Report missing evidence and classify suspected bypasses. The read-only audit
does not fix code, run migrations, mutate rows, isolate/drop tables or edit
configuration. Produce inventory, boundary diagram, candidate plan, risks,
stop conditions and requested decisions. The audit ends at a human review
checkpoint.

## 3. Authorized transformation procedure

Begin only after an explicit separate instruction approving this selected
application and scope.

1. Reconfirm a cleanly understood baseline without discarding WIP; capture
   public behavior, identity, status and relevant tests.
2. Resolve contract questions before edits. If work requires a SYSTEM/CORE
   capability, schema change, functional change, or cross-app boundary
   change, stop with `MISSING_SYSTEM_CAPABILITY` or a scoped architectural
   blocker.
3. Adapt only the selected app's connection boundary/storage. Keep the
   service/view/form observable contract. Do not copy another app's router.
4. Add backend parity and isolation tests for the exact access sites and
   relations changed. Test rollback, transaction ownership, `on_commit`,
   callbacks/signals and side effects as applicable.
5. Validate against the configured physical backend when safe and authorized;
   verify persisted rows/relations, not only HTTP results.
6. Run a Physical Isolation Gate only when separately approved and safe for
   the environment. Production applications require a conservative plan,
   explicit authorization, and approved window; no destructive gate during
   initial diagnosis.
7. Classify test failures `HISTORICAL`, `INTRODUCED` or `INCONCLUSIVE`.
   Certification requires introduced and inconclusive failures to be zero.
8. Review scope, full diff, docs, schema/migrations, test evidence and git
   state. Stage/commit/push only if the user explicitly authorizes it.

## 4. Evidence required for certification

Certification requires all gates in the checklist and:

```text
PRIVATE_ROUTER_OWNED_BY_APP = YES
SETTINGS_PHYSICAL_CATALOG_REUSED = YES
PHYSICAL_CREDENTIAL_DUPLICATION = NO
OTHER_APP_PRIVATE_ROUTER_DEPENDENCY = NO
OPERATIONAL_BYPASS = 0
UNKNOWN = 0
INTRODUCED_TEST_FAILURES = 0
INCONCLUSIVE_TEST_FAILURES = 0
FUNCTIONAL_CONTRACT_PRESERVED = YES
CAN_MOVE_DATA_PLANE_BY_CONFIGURATION = YES
```

Real-backend checks and physical isolation are mandatory where safe and
applicable; if unsafe/unavailable, record `NOT_RUN` plus the reason and do not
claim complete certification.

## 5. Stop conditions

Stop without fixing inside the audit when:

- a query's ownership, table class, caller or runtime backend is unknown;
- a candidate reaches `default` for operational data;
- a service resolves correctly but later composes through ORM/default;
- an external canonical entity would need to move or a cross-server join is
  assumed;
- a required Settings interface is missing;
- behavior, schema, permission or public contract must change;
- safe physical testing or fixture cleanup cannot be guaranteed.

Report exact file/symbol/line, evidence, classification and minimum next
decision. Never resolve a bypass by recreating operational tables on
`default`.

## 6. Next phase: GestionDTE read-only audit

This is a preparation contract only; it is not the audit and makes no
certification claims. Validate, do not assume, the currently known hypotheses:

- GestionDTE is classified as an APPLICATION_APP;
- it owns a private router/frontier;
- the Certificates view uses that private router;
- Certificates is a positive reference but is itself included in the audit;
- legacy/direct access sites may remain elsewhere.

The initial GestionDTE task must be `GESTIONDTE CONNECTION AUDIT — READ ONLY`.
It must inventory the entire app and answer:

```text
PRIVATE_ROUTER_EXISTS =
PRIVATE_ROUTER_OWNED_BY_GESTIONDTE =
USES_SETTINGS_CONNECTION_CATALOG =
CERTIFICADOS_USES_PRIVATE_ROUTER =
DUPLICATES_PHYSICAL_CREDENTIALS =
USES_OTHER_APP_ROUTER =
DIRECT_OPERATIONAL_CONNECTION_BYPASS =
LEGACY_CONNECTION_RESIDUES =
UNKNOWN_CONNECTION_SITES =
CAN_MOVE_DATA_PLANE_BY_CONFIGURATION =
```

Inspect Certificates and all legacy/direct paths. Classify each access and
identify Control Plane/Data Plane. The initial audit prohibits code changes,
migrations, schema/data changes, DROP/TRUNCATE, recreation of tables and
destructive isolation. Deliver the inventory and plan first; defer fixes and
physical isolation to separately authorized work.
