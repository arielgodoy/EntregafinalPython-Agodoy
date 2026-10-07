# <APPLICATION> Operational Connection Inventory

**Audit ID:**
**Date / commit:**
**Classification source:** `AppDocs/app_classification.py`
**Audit mode:** `READ_ONLY` | `AUTHORIZED_TRANSFORMATION`
**Production status:**
**Scope / exclusions:**
**WIP preserved:** YES | NO
**Evidence references:**

> Do not include passwords, credentials, tokens, DSNs, connection strings,
> sensitive row values or unnecessary personal data.

## 1. Architecture boundary

```text
APPLICATION =
PRIVATE_ROUTER_MODULE =
LOGICAL_ROLES_AND_SCOPE =
SETTINGS_PUBLIC_CATALOG/API =
CONTROL_PLANE_TABLES =
DATA_PLANE_TABLES =
EXTERNAL_CANONICAL_REFERENCES =
DEFAULT_ROLE =
SUPPORTED_BACKENDS =
```

| Property | Evidence | Result / open question |
|---|---|---|
| App is an `APPLICATION_APP` |  |  |
| Private resolver is owned by this app |  |  |
| Physical catalog/API comes from Settings |  |  |
| No other app's private router is consumed |  |  |
| Configuration-only Data Plane move is possible |  |  |

## 2. Access-site inventory

One row per distinct access site/call path. Split a row when backend, caller,
table class or behavior differs.

| ID | File:line / symbol | Caller / call chain | Model/table | Operation | Source syntax | Runtime backend | Expected backend | Classification | Evidence / test | Result / risk |
|---|---|---|---|---|---|---|---|---|---|---|
| A-001 |  |  |  |  |  |  |  |  |  |  |

Allowed classifications:

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

### SQL evidence

Record only sanitized SQL shape, table and caller. Replace values with
`<redacted>`; never copy bound secrets or personal data.

| Capture ID | Stage | Connection/alias | Sanitized SQL shape | Table(s) | Caller file:line | Classification |
|---|---|---|---|---|---|---|
| SQL-001 |  |  |  |  |  |  |

## 3. Functional contract / identity snapshot

| Surface / operation | Inputs and scope | Observable result/order | Identity | Validation/state | Relations | Events/side effects | HTTP/UX |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

## 4. Forms, transactions and indirect access

| Site | Query/persist mechanism | Hidden query risk | Transaction / callback boundary | Backend evidence | Classification / finding |
|---|---|---|---|---|---|
|  | `ModelForm` / choice / clean / save / manager / signal / helper |  |  |  |  |

## 5. Evidence and gates

```text
PRIVATE_ROUTER_EXISTS =
PRIVATE_ROUTER_OWNED_BY_APP =
SETTINGS_PHYSICAL_CATALOG_REUSED =
PHYSICAL_CREDENTIAL_DUPLICATION =
OTHER_APP_ROUTER_DEPENDENCY =
DIRECT_OPERATIONAL_BYPASS =
LEGACY_CONNECTION_RESIDUES =
UNKNOWN_CONNECTION_SITES =
FUNCTIONAL_CONTRACT_PRESERVED =
REAL_BACKEND_VALIDATION =
PHYSICAL_ISOLATION_GATE =
CAN_MOVE_DATA_PLANE_BY_CONFIGURATION =
```

| Gate/test | Command or scenario | Backend | Result | Failure classification | Evidence |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

## 6. Findings and decisions

| Finding | Classification | Severity / confidence | Exact evidence | Required decision / stop condition |
|---|---|---|---|---|
|  |  |  |  |  |

```text
MISSING_SYSTEM_CAPABILITY =
CONFLICTS_WITH_EXISTING_ARCHITECTURE =
OPEN_DECISIONS =
UNSAFE_OR_UNAVAILABLE_TESTS =
```

## 7. Final handoff

```text
OPERATIONAL_BYPASS_COUNT =
UNKNOWN_COUNT =
INTRODUCED_FAILURES =
INCONCLUSIVE_FAILURES =
FILES_CHANGED =
SCHEMA_OR_MIGRATIONS =
STAGE =
COMMIT =
PUSH =
CERTIFICATION = PASS | FAIL | NOT_CERTIFIED
NEXT_ACTION =
```
