# APPLICATION_APP Operational Connection Audit and Certification Checklist

Use this checklist with
`COPILOT/APPLICATION_CONNECTION_AUDIT_SPEC.md`. Mark `N/A` only with a
reason. An unknown item is not a pass.

## A. Precheck and boundary

- [ ] Read the current COPILOT index and only applicable architecture rules.
- [ ] Confirm the app classification from `AppDocs/app_classification.py`.
- [ ] Declare the exact app, writable root, mode, production status and scope.
- [ ] Capture git status and preserve all existing worktree/index changes.
- [ ] Keep read-only audit non-mutating: no edits, migrations, row writes,
      configuration change, table creation/drop/truncate or staging.
- [ ] Read prior specs, connection inventories, corrections, tests and
      checkpoint evidence; reconcile conflicting status assertions.
- [ ] Confirm whether physical backend testing is safe and authorized.

## B. Ownership and architecture

- [ ] Identify the application-owned private resolver/router and its public
      entrypoints.
- [ ] Inventory the app's logical roles, role scope and allowed source types.
- [ ] Confirm app does not import/consume another APPLICATION_APP's private
      router.
- [ ] Identify Settings public connection/catalog API used by the app.
- [ ] Confirm physical credentials/catalog/opening logic are not duplicated.
- [ ] Classify Control Plane and Data Plane by responsibility and table.
- [ ] Preserve SYSTEM/CORE and external canonical references.
- [ ] Confirm `DATABASE_ROUTERS` is not treated as the app's private boundary.

## C. Static inventory coverage

- [ ] Models and custom managers/querysets
- [ ] Services, storage/adapters, repositories and helper/wrapper modules
- [ ] Views, APIs, serializers, URLs and public service callers
- [ ] Forms, admin, `clean()`, `full_clean()`, `save()`, `save_m2m()`
- [ ] Signals and receiver call paths
- [ ] Management commands, tasks/jobs and background work
- [ ] Reports, exports/imports and document generation
- [ ] Templatetags and helpers that execute data access
- [ ] Tests that encode observable behavior and backend parity
- [ ] Search direct and indirect access: `.objects`, `.using`, raw/cursor SQL,
      connections, transaction/on_commit, `_state.db`, save/delete/bulk,
      related managers, choice querysets, storage aliases, connection drivers
      and credential/configuration references.
- [ ] Trace wrappers and call chains; don't infer a site's status from syntax.
- [ ] Record file/line, symbol, caller, table/model, operation, backend and
      evidence in the inventory template.
- [ ] Redact credentials, DSNs, tokens, personal/sensitive values.

## D. Classification and static gate

- [ ] Assign exactly one canonical classification to every candidate:
      `CONTROL_PLANE`, `EXTERNAL_CANONICAL`, `BACKEND_ADAPTER`, `PRODUCTIVE`,
      `PUBLIC_BUT_NOT_PRODUCTIVE`, `TEST_ONLY`, `DEAD_CONFIRMED`,
      `OPERATIONAL_BYPASS` or `UNKNOWN`.
- [ ] Justify every `DEAD_CONFIRMED` using reachability/public-surface evidence.
- [ ] Distinguish allowed Control Plane/default access from operational reads.
- [ ] Confirm operational access always enters the app-owned private boundary.
- [ ] Confirm resolution fails closed; no fallback to default or another
      unconfigured source.
- [ ] `OPERATIONAL_BYPASS = 0`
- [ ] `UNKNOWN = 0`

## E. Frozen functional contract and parity

- [ ] Snapshot public inputs, output, identity/PK and observable ordering.
- [ ] Preserve multi-company scoping and ICMEAS/VICMEAS permissions.
- [ ] Cover validations, messages, states, transitions and error behavior.
- [ ] Cover relations, FKs-as-IDs, N:M, participants/roles and references.
- [ ] Cover DTO attributes, relations, collections and consumer expectations.
- [ ] Cover ModelForm/choices and any query hidden by validation or rendering.
- [ ] Cover operations composed across services/storage boundaries.
- [ ] Cover API/HTTP, templates and UX where they are public behavior.
- [ ] Cover events, recipients, notifications, signals and callbacks.
- [ ] Cover correlated identifiers/counters without assuming cleanup rewinds
      sequences.
- [ ] Treat ORM mechanics as replaceable, not as functional contract.

## F. Transactions and side effects

- [ ] Confirm Django alias transactions explicitly use the resolved alias.
- [ ] Confirm MYSQL_CONFIG transaction uses the resolved physical connection.
- [ ] Verify nested transaction, commit, rollback and partial-failure behavior.
- [ ] Verify `on_commit` is tied to the intended transaction boundary.
- [ ] Verify callbacks see committed data and fire at the expected time.
- [ ] Verify backend adapters reproduce required signal/side-effect behavior.
- [ ] Verify no side effect occurs on failed storage operations.
- [ ] Document limits for filesystem/external service atomicity and cleanup.

## G. Automated and real-backend verification

- [ ] Run focused tests for changed access sites and the app's parity matrix.
- [ ] Include fail-closed tests and prove no operational query on `default`.
- [ ] Exercise each supported backend path relevant to the app.
- [ ] Classify failures as `HISTORICAL`, `INTRODUCED` or `INCONCLUSIVE`.
- [ ] `INTRODUCED = 0`
- [ ] `INCONCLUSIVE = 0`
- [ ] If safe and authorized, verify real backend INSERT/UPDATE/DELETE,
      relations, state, counters and rollback as applicable.
- [ ] Check physical persisted rows/relationships; HTTP status alone is not
      sufficient evidence.
- [ ] Clean only known temporary fixtures after checking identity and
      dependencies; verify zero leftovers.
- [ ] Do not manually reverse sequences/counters without evidence and approval.
- [ ] If real-backend checks are unsafe/unavailable, record `NOT_RUN`, reason,
      and do not assert complete certification.

## H. Physical Isolation Gate

- [ ] Is the environment DEV/non-production and the gate explicitly authorized?
- [ ] Inventory tables and classify before any isolation operation.
- [ ] Preserve SYSTEM/CORE, Control Plane and external canonical data.
- [ ] Prove the private resolver reaches the intended backend before isolating.
- [ ] Ensure operational tables on `default` are not serving as fallback.
- [ ] During each scenario monitor SQL on `default` and classify by table.
- [ ] Interpret `no such table` / operational SQL on `default` as bypass evidence.
- [ ] Never restore operational tables to hide a bypass.
- [ ] Do not DROP/TRUNCATE production data as part of initial diagnosis.
- [ ] Verify the physical state and fixture cleanup after the matrix.

## I. Final certification and handoff

- [ ] `PRIVATE_ROUTER_OWNED_BY_APP = YES`
- [ ] `SETTINGS_PHYSICAL_CATALOG_REUSED = YES`
- [ ] `PHYSICAL_CREDENTIAL_DUPLICATION = NO`
- [ ] `OTHER_APP_PRIVATE_ROUTER_DEPENDENCY = NO`
- [ ] `FUNCTIONAL_CONTRACT_PRESERVED = YES`
- [ ] `CAN_MOVE_DATA_PLANE_BY_CONFIGURATION = YES`
- [ ] `OPERATIONAL_BYPASS = 0`
- [ ] `UNKNOWN = 0`
- [ ] `INTRODUCED = 0`
- [ ] `INCONCLUSIVE = 0`
- [ ] Diff/scope and documentation reviewed; migrations/schema changes listed.
- [ ] Report blockers, unavailable evidence, open decisions and exact next step.
- [ ] Stage, commit and push only under separate explicit authorization.
