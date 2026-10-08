# GESTIONDTE CANONICAL CONNECTION INVENTORY

- **Version:** 1.1
- **Status:** FROZEN BASELINE + POST-FREEZE RECONCILIATION
- **Phase:** A3 — canonical inventory freeze; post-freeze discovery reconciled
- **Phase A:** COMPLETE (static baseline)
- **Audit mode:** Static / read-only
- **Baseline commit:** `09283ac13ba54d3c35ae31855deb9f68718cf993`
- **Classification source:** [`AppDocs/app_classification.py`](../AppDocs/app_classification.py)

**Scope:** `gestiondte/`; SYSTEM/CORE and external canonical systems are classified as dependencies, not transformation scope.

This inventory freezes the known access surface for a future connection
transformation. It does **not** freeze internal ORM details as functional
contracts. The observable behavior of GestionDTE must remain unchanged.

> No estamos transformando funcionalidades. Estamos transformando conexiones.

The application must preserve its observable behavior. The following internal
mechanisms may change if the functional contract is preserved:

- connection selection mechanism;
- backend adapter;
- internal ORM or SQL adapter;
- DTO/materialization approach;
- internal boundaries needed for backend independence.

This inventory preserves the 139-site baseline and records the completed
GDTE-B1 connection-path transformation for A015-A018. The separately verified
post-freeze command access is appended as GDTE-A140; no later batch is
authorized by this inventory.

## 1. Classification model

Every row has exactly one `PRIMARY_CLASSIFICATION`, one productive status, one
data ownership, and one connection-path compliance value. Only
`PRIMARY_CLASSIFICATION` participates in the `TOTAL_ACCESS_SITES` sum.

### Primary classification

`CONTROL_PLANE`, `BACKEND_ADAPTER`, `OPERATIONAL_BYPASS`,
`LEGACY_CONNECTION_BYPASS`, `EXTERNAL_ACCESS`, `SYSTEM_CORE_ACCESS`,
`FILE_STORAGE`, `EXTERNAL_API`, `TEST_ONLY`, `MIGRATION_ONLY`,
`DEAD_CONFIRMED`, `UNKNOWN`.

### Dimension codes

| Dimension | Code | Meaning |
|---|---|---|
| `PRODUCTIVE_STATUS` | `PRODUCTIVE` | Productive code path identified |
|  | `PUBLIC_NOT_PRODUCTIVE` | Public service/API without a productive caller found |
|  | `NON_PRODUCTIVE` | Non-production path, such as a historical migration |
| `DATA_OWNERSHIP` | `GESTIONDTE_DATA_PLANE` | Operational data owned by GestionDTE |
|  | `GESTIONDTE_CONTROL_PLANE` | GestionDTE routing/control configuration |
|  | `SYSTEM_CORE` | System/Core-owned identity, permission, or configuration data |
|  | `EXTERNAL_CANONICAL` | Canonical data owned by Contabilidad |
|  | `EXTERNAL_SYSTEM` | SII or RPETC external service |
|  | `FILE_STORAGE` | Certificate file storage |
| `CONNECTION_PATH_COMPLIANCE` | `PRIVATE_ROUTER` | Goes through GestionDTE's private connection boundary |
|  | `CONTROL_PLANE` | Legitimate Control Plane access |
|  | `LEGACY_BYPASS` | Legacy connection selection/opening bypasses the private resolver |
|  | `IMPLICIT_DEFAULT` | Operational ORM access uses the implicit default connection |
|  | `NOT_APPLICABLE` | No database connection path applies |
| `TRANSACTION_RELEVANT` | `YES` / `NO` | Site participates in or defines a transaction |
| `MULTIEMPRESA_RELEVANT` | `YES` / `NO` | Site has company-scoped or cross-company implications |

## 2. Architecture boundary

```text
APPLICATION = gestiondte (APPLICATION_APP)
PRIVATE_ROUTER_MODULE = gestiondte.services.connection_roles
LOGICAL_ROLES = serverbasedte, servercontabilidad
PRIVATE_ROUTER_SCOPE = GLOBAL_PER_APPLICATION
CONTROL_PLANE_SCOPE = GLOBAL_PER_APPLICATION
MULTIEMPRESA_ISOLATION = PRESERVE_EXISTING_BEHAVIOR
PHYSICAL_CONNECTION_CATALOG = settings.SettingsMySQLConnection
CONTROL_PLANE = GestionDTEConnectionRole and required Settings catalog metadata
DATA_PLANE = GestionDTE operational models and tables
EXTERNAL_CANONICAL = Contabilidad
```

The Control Plane may reside on `default` when it is needed to discover the
Data Plane destination. That is not an operational bypass. Identity references
to SYSTEM/CORE do not by themselves prove a physical cross-database join:

```text
IDENTITY_REFERENCE != PHYSICAL_CROSS_DATABASE_JOIN
```

In particular, A084 uses `select_related('empresa')`. Any physical separation
must analyze this and other relations from GestionDTE Data Plane models to
SYSTEM/CORE. Do not infer that an FK identity must move with the Data Plane.

## 3. Frozen access-site inventory

`File / symbol` identifies the source location at module/symbol granularity;
line numbers are deliberately omitted because they are not stable identifiers.
The operation and target column distinguishes the read/write or external
effect represented by each ID.

| ID | File / symbol | Operation / target | PRIMARY_CLASSIFICATION | PRODUCTIVE_STATUS | DATA_OWNERSHIP | CONNECTION_PATH_COMPLIANCE | TRANSACTION_RELEVANT | MULTIEMPRESA_RELEVANT | Notes |
|---|---|---|---|---|---|---|---|---|---|
| GDTE-A001 | `services/connection_roles.py::get_gestiondte_connection` | Read logical role from `GestionDTEConnectionRole` | CONTROL_PLANE | PRODUCTIVE | GESTIONDTE_CONTROL_PLANE | CONTROL_PLANE | NO | YES | Control Plane lookup required for routing |
| GDTE-A002 | `services/connection_roles.py::get_gestiondte_mysql_connection` | Read physical connection metadata from Settings | CONTROL_PLANE | PRODUCTIVE | SYSTEM_CORE | CONTROL_PLANE | NO | YES | Does not itself open a physical connection |
| GDTE-A003 | `services/connection_roles.py::get_active_mysql_connection_catalog` | Read active Settings connection catalog for role form | CONTROL_PLANE | PRODUCTIVE | SYSTEM_CORE | CONTROL_PLANE | NO | YES | Configuration catalog |
| GDTE-A004 | `connection_views.py::GestionDTEConnectionRoleView._role_instances` | Read role rows and related MySQL connection | CONTROL_PLANE | PRODUCTIVE | GESTIONDTE_CONTROL_PLANE | CONTROL_PLANE | NO | YES | Configuration UI |
| GDTE-A005 | `connection_views.py::GestionDTEConnectionRoleView.post` | Validate/save role configuration in transaction | CONTROL_PLANE | PRODUCTIVE | GESTIONDTE_CONTROL_PLANE | CONTROL_PLANE | YES | YES | Control Plane write |
| GDTE-A006 | `repositories/certificados.py::CertificadoSIIRepository.__init__` | Resolve `serverbasedte` | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_CONTROL_PLANE | PRIVATE_ROUTER | NO | YES | Private boundary |
| GDTE-A007 | `repositories/certificados.py::CertificadoSIIRepository._mysql_connection` | Look up Settings connection by configured ID | BACKEND_ADAPTER | PRODUCTIVE | SYSTEM_CORE | CONTROL_PLANE | NO | YES | Connection metadata |
| GDTE-A008 | `repositories/certificados.py::CertificadoSIIRepository.list_by_empresa` | Read certificates using resolved backend | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | Alias or MYSQL_CONFIG branch |
| GDTE-A009 | `repositories/certificados.py::CertificadoSIIRepository.create` | Save certificate PFX file | FILE_STORAGE | PRODUCTIVE | FILE_STORAGE | NOT_APPLICABLE | NO | YES | `default_storage` |
| GDTE-A010 | `models.py::CertificadoSII.save` | Implicit ORM save and deactivate other certificates | OPERATIONAL_BYPASS | PUBLIC_NOT_PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Public model fallback; inspected upload view uses repository |
| GDTE-A011 | `services/rpetc_importer.py::importar_resultado_rpetc` | Import transaction boundary | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Wraps operational persistence |
| GDTE-A012 | `services/rpetc_importer.py::importar_resultado_rpetc` | Upsert `TareaRPETC` | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Same source `update_or_create` is also referenced by A058; retained as supplied |
| GDTE-A013 | `services/rpetc_importer.py::importar_resultado_rpetc` | Lookup `CesionRPETC` by identity | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Same source lookup is also referenced by A059; retained as supplied |
| GDTE-A014 | `services/rpetc_importer.py::importar_resultado_rpetc` | Insert/update `CesionRPETC` | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Within A011 |
| GDTE-A015 | `services/rpetc_contabilidad.py::_mysql_connection_config` | Resolve `servercontabilidad` through GestionDTE private resolver | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_CONTROL_PLANE | PRIVATE_ROUTER | NO | YES | PRE_B1=LEGACY_CONNECTION_BYPASS; legacy selector removed and replaced by private resolver |
| GDTE-A016 | `services/rpetc_contabilidad.py::registrar_cesiones_contabilidad` | SELECT/INSERT/UPDATE Contabilidad RCV events through Settings opener | EXTERNAL_ACCESS | PRODUCTIVE | EXTERNAL_CANONICAL | PRIVATE_ROUTER | YES | YES | PRE_B1=LEGACY_CONNECTION_BYPASS; PyMySQL retains explicit `commit()`; Django alias uses its transaction boundary |
| GDTE-A017 | `services/rpetc_contabilidad.py::_query_movimientos` | SELECT accounting movements through Settings opener | EXTERNAL_ACCESS | PRODUCTIVE | EXTERNAL_CANONICAL | PRIVATE_ROUTER | NO | YES | PRE_B1=LEGACY_CONNECTION_BYPASS |
| GDTE-A018 | `services/rpetc_contabilidad.py::_query_factoring_glosa_candidates` | SELECT factoring/glosa candidates through Settings opener | EXTERNAL_ACCESS | PRODUCTIVE | EXTERNAL_CANONICAL | PRIVATE_ROUTER | NO | YES | PRE_B1=LEGACY_CONNECTION_BYPASS |
| GDTE-A019 | `utils/maestro.py::get_maestroempresa_by_codigo` | Resolve `servercontabilidad` | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_CONTROL_PLANE | PRIVATE_ROUTER | NO | YES | Existing private resolver reference |
| GDTE-A020 | `utils/maestro.py::get_maestroempresa_by_codigo` | Read canonical company master through Django alias | EXTERNAL_ACCESS | PRODUCTIVE | EXTERNAL_CANONICAL | PRIVATE_ROUTER | NO | YES | Canonical Contabilidad data |
| GDTE-A021 | `utils/maestro.py::get_maestroempresa_by_codigo` | Read canonical company master through MYSQL_CONFIG | EXTERNAL_ACCESS | PRODUCTIVE | EXTERNAL_CANONICAL | PRIVATE_ROUTER | NO | YES | Opens configured connection |
| GDTE-A022 | `services/lectura_automatica.py::ejecutar_lote` | Lock/configuration/creation transaction for execution batch | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Parent transaction site; detailed operations A066-A069 |
| GDTE-A023 | `services/estado_contable_cesiones.py::actualizar_estados_contables_cesiones` | Read and persist accounting-state snapshots | OPERATIONAL_BYPASS | PUBLIC_NOT_PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | No productive caller found; not classified dead |
| GDTE-A024 | `admin.py::CertificadoSIIAdmin` | Read-only certificate changelist/queryset | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Admin read-only does not change connection path |
| GDTE-A025 | `admin.py::TareaRPETCAdmin` | Read-only RPETC task changelist/queryset | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Related fields may be read |
| GDTE-A026 | `admin.py::CesionRPETCAdmin` | Read-only assignment changelist/queryset | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Related fields may be read |
| GDTE-A027 | `admin.py::LecturaAutomaticaConfigAdmin` | Read-only automatic-reading configuration changelist | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES |  |
| GDTE-A028 | `admin.py::LecturaAutomaticaEjecucionAdmin` | Read-only execution changelist, including company reference | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES |  |
| GDTE-A029 | `admin.py::EstadoContableCesionAdmin` | Read-only accounting-state snapshot changelist | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Related fields may be read |
| GDTE-A030 | `admin.py::TareaCesionRPETCAdmin` | Read-only task-assignment changelist | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Related task/assignment data |
| GDTE-A031 | `admin.py::CesionRPETCHistorialAdmin` | Read-only assignment history changelist | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Related assignment/task data |
| GDTE-A032 | `forms.py::CertificadoUploadForm.save` | Save ModelForm instance through implicit model save | OPERATIONAL_BYPASS | PUBLIC_NOT_PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Inspected upload view uses `commit=False`, then repository |
| GDTE-A033 | `forms.py::CertificadoUploadForm.clean_empresa_codigo` | Look up company master | EXTERNAL_ACCESS | PRODUCTIVE | EXTERNAL_CANONICAL | PRIVATE_ROUTER | NO | YES | Uses maestro helper |
| GDTE-A034 | `repositories/certificados.py::CertificadoSIIRepository._mysql_connection` | Open physical MySQL connection for certificate Data Plane | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | Uses configured `serverbasedte` connection |
| GDTE-A035 | `repositories/certificados.py::CertificadoSIIRepository.create` | Deactivate existing certificates before MySQL insert | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | Separate SQL update |
| GDTE-A036 | `repositories/certificados.py::CertificadoSIIRepository.create` | Insert certificate using MySQL branch | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | Parameterized SQL |
| GDTE-A037 | `repositories/certificados.py::CertificadoSIIRepository.create` | Read back inserted MySQL certificate | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | Post-insert verification |
| GDTE-A038 | `repositories/certificados.py::CertificadoSIIRepository.create` | Save certificate using Django alias branch | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES |  |
| GDTE-A039 | `repositories/certificados.py::CertificadoSIIRepository.create` | Deactivate prior certificates using Django alias | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES |  |
| GDTE-A040 | `repositories/certificados.py::CertificadoSIIRepository.update_active` | Update active flag using Django alias | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES |  |
| GDTE-A041 | `repositories/certificados.py::CertificadoSIIRepository.update_active` | Deactivate other active certificates using Django alias | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES |  |
| GDTE-A042 | `repositories/certificados.py::CertificadoSIIRepository.delete` | Transaction and delete certificate using Django alias | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | YES | YES | Django branch |
| GDTE-A043 | `repositories/certificados.py::CertificadoSIIRepository.update_active` | Update active flag using MySQL SQL branch | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | Parameterized SQL |
| GDTE-A044 | `repositories/certificados.py::CertificadoSIIRepository.delete` | Delete certificate using MySQL SQL branch | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | Parameterized SQL |
| GDTE-A045 | `repositories/certificados.py::CertificadoSIIRepository.create` | Remove stored file if database write fails | FILE_STORAGE | PRODUCTIVE | FILE_STORAGE | NOT_APPLICABLE | NO | YES | Best-effort compensation |
| GDTE-A046 | `services/sii_auth.py` | Read PFX bytes from file storage for authentication | FILE_STORAGE | PRODUCTIVE | FILE_STORAGE | NOT_APPLICABLE | NO | YES | File dependency separate from database |
| GDTE-A047 | `services/sii_auth.py` | Submit authentication/token request | EXTERNAL_API | PRODUCTIVE | EXTERNAL_SYSTEM | NOT_APPLICABLE | NO | YES | SII |
| GDTE-A048 | `services/rpetc.py::RPETCClient` | Create RPETC task | EXTERNAL_API | PRODUCTIVE | EXTERNAL_SYSTEM | NOT_APPLICABLE | NO | YES | RPETC |
| GDTE-A049 | `services/rpetc.py::RPETCClient.consultar_estado_tarea` | Poll RPETC task state | EXTERNAL_API | PRODUCTIVE | EXTERNAL_SYSTEM | NOT_APPLICABLE | NO | YES | RPETC |
| GDTE-A050 | `services/rpetc.py::RPETCClient.descargar_resultado_tarea` | Download RPETC task result | EXTERNAL_API | PRODUCTIVE | EXTERNAL_SYSTEM | NOT_APPLICABLE | NO | YES | RPETC |
| GDTE-A051 | `services/lectura_automatica.py::_certificado_elegible` | Check certificate file existence in storage | FILE_STORAGE | PRODUCTIVE | FILE_STORAGE | NOT_APPLICABLE | NO | YES | Eligibility check |
| GDTE-A052 | `migrations/0007_revisioncesioncomentario.py` | Read historical `RevisionCesionRPETC` rows | MIGRATION_ONLY | NON_PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Historical migration path only |
| GDTE-A053 | `migrations/0007_revisioncesioncomentario.py` | Bulk insert migrated comments | MIGRATION_ONLY | NON_PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Historical migration path only |
| GDTE-A054 | `migrations/0007_revisioncesioncomentario.py` | Delete comments when reversing migration | MIGRATION_ONLY | NON_PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Reverse operation only |
| GDTE-A055 | `services/connection_roles.py::get_gestiondte_connection_status` | Read configured roles and status metadata | CONTROL_PLANE | PRODUCTIVE | GESTIONDTE_CONTROL_PLANE | CONTROL_PLANE | NO | YES | Control Plane status |
| GDTE-A056 | `services/base_dte_schema.py::install_base_dte_schema` | Open physical MySQL connection | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | `serverbasedte` |
| GDTE-A057 | `services/base_dte_schema.py::install_base_dte_schema` | Execute `CREATE TABLE IF NOT EXISTS` for Base DTE | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | Explicit schema installer |
| GDTE-A058 | `services/rpetc_importer.py::importar_resultado_rpetc` | Upsert `TareaRPETC` inside import transaction | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Same source `update_or_create` as A012; retained as supplied, not an additional SQL statement |
| GDTE-A059 | `services/rpetc_importer.py::importar_resultado_rpetc` | Lookup `CesionRPETC` inside import transaction | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Same source lookup as A013; retained as supplied, not an additional SQL statement |
| GDTE-A060 | `services/rpetc_importer.py::importar_resultado_rpetc` | Insert new `CesionRPETC` | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Inside A011 |
| GDTE-A061 | `services/rpetc_importer.py::importar_resultado_rpetc` | Update existing `CesionRPETC` | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Inside A011 |
| GDTE-A062 | `services/rpetc_importer.py::importar_resultado_rpetc` | Insert state history row | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Inside A011 |
| GDTE-A063 | `services/rpetc_importer.py::importar_resultado_rpetc` | Get/create task-cession relation | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Inside A011 |
| GDTE-A064 | `services/lectura_automatica.py::empresas_elegibles` | Read all company identities | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | `Empresa.objects.all()` |
| GDTE-A065 | `services/lectura_automatica.py::empresas_elegibles` | Look up company by code | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Resolves company identity |
| GDTE-A066 | `services/lectura_automatica.py::ejecutar_lote` | Get/create automatic-reading configuration | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Within A022 |
| GDTE-A067 | `services/lectura_automatica.py::ejecutar_lote` | Lock configuration row with `select_for_update` | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Within A022 |
| GDTE-A068 | `services/lectura_automatica.py::ejecutar_lote` | Check for pending/in-progress executions | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Within A022 |
| GDTE-A069 | `services/lectura_automatica.py::ejecutar_lote` | Create execution rows | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | YES | YES | Within A022 |
| GDTE-A070 | `services/lectura_automatica.py::ejecutar_lote` | Update execution status/progress/result | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | After the initial atomic block |
| GDTE-A071 | `services/lectura_automatica.py::ejecutar_lote` | Update configuration's next/last execution | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Implicit ORM |
| GDTE-A072 | `services/lectura_automatica.py::estado_lote` | Read ordered executions with `select_related('empresa')` | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Related company identity |
| GDTE-A073 | `services/estado_contable_cesiones.py::_persistir` | Bulk-create accounting-state snapshots | OPERATIONAL_BYPASS | PUBLIC_NOT_PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Public service; no productive caller found |
| GDTE-A074 | `services/estado_contable_cesiones.py::_persistir` | Bulk-update accounting-state snapshots | OPERATIONAL_BYPASS | PUBLIC_NOT_PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Public service; no productive caller found |
| GDTE-A075 | `services/estado_contable_cesiones.py::_persistir` | Read existing snapshots | OPERATIONAL_BYPASS | PUBLIC_NOT_PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Public service; no productive caller found; related to A023 |
| GDTE-A076 | `views.py::_cesiones_rpetc_context` | Query company-scoped cessions | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Operational list/context |
| GDTE-A077 | `views.py::_cesiones_rpetc_context` | Query latest RPETC task | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Separate model/query from cessions |
| GDTE-A078 | `views.py::_rpetc_filtered_queryset` | Query/filter cessions | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Operational filters |
| GDTE-A079 | `views.py::_rpetc_annotated_queryset` | Subquery for review/comment existence | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | `Exists` over review/comment data |
| GDTE-A080 | `views.py::_rpetc_apply_payment_filters` | Filter cessions using payment-state batches | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Operational query |
| GDTE-A081 | `views.py::cesiones` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session `empresa_id` |
| GDTE-A082 | `views.py::cesiones` | Look up permission `Vista` | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Permission/control lookup |
| GDTE-A083 | `views.py::cesiones` | Look up `Permiso` scoped to active company | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Permission/control lookup |
| GDTE-A084 | `views.py::_lectura_automatica_filas` | Read executions with `select_related('empresa')` | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Potential Data Plane–SYSTEM/CORE join after physical separation |
| GDTE-A085 | `views.py::lectura_automatica_cesiones` | Get/create reading configuration | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | View-side access |
| GDTE-A086 | `views.py::ejecutar_lectura_automatica_cesiones` | Save automatic-reading configuration | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | POST action |
| GDTE-A087 | `views.py::cesiones_data` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session `empresa_id` |
| GDTE-A088 | `views.py::cesiones_data` | Query/filter/aggregate cessions for DataTables | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Includes totals and paginated page |
| GDTE-A089 | `views.py::exportar_cesiones_excel` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session `empresa_id` |
| GDTE-A090 | `views.py::exportar_cesiones_excel` | Query filtered cessions for workbook | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Excel export |
| GDTE-A091 | `views.py::detalle_contable_cesion` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session `empresa_id` |
| GDTE-A092 | `views.py::detalle_contable_cesion` | Read cession scoped to company | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Related task/company filter |
| GDTE-A093 | `views.py::_revision_empresa` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session `empresa_id` |
| GDTE-A094 | `views.py::_revision_cesion` | Read company-scoped cession | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Traverses task/company relation |
| GDTE-A095 | `views.py::_revision_permisos` | Look up access-control `Vista` | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | ICMEAS control lookup |
| GDTE-A096 | `views.py::_revision_permisos` | Look up `Permiso` for user/company/view | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | ICMEAS control lookup |
| GDTE-A097 | `views.py::revision_cesion` | Read review for company/cession | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Review data |
| GDTE-A098 | `views.py::_revision_json` | Load related comments | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Related manager |
| GDTE-A099 | `views.py::_revision_json` | Dereference comment author username | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | User identity reference; not proof of physical join |
| GDTE-A100 | `views.py::_revision_con_permisos` | Read review before create/edit operations | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Shared helper |
| GDTE-A101 | `views.py::crear_comentario_revision` | Get/create review row | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Review model |
| GDTE-A102 | `views.py::crear_comentario_revision` | Insert review comment | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Comment model |
| GDTE-A103 | `views.py::_comentario_autorizado` | Read comment with ownership/scope filters | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Review/company/cession |
| GDTE-A104 | `views.py::editar_comentario_revision` | Save comment change | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Comment model |
| GDTE-A105 | `views.py::eliminar_comentario_revision` | Delete comment | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Comment model |
| GDTE-A106 | `views.py::eliminar_comentario_revision` | Check remaining comments | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Related manager |
| GDTE-A107 | `views.py::eliminar_comentario_revision` | Delete empty review | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Review model |
| GDTE-A108 | `views.py::crear_revision_cesion` | Get/create review | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Review model |
| GDTE-A109 | `views.py::crear_revision_cesion` | Insert initial comment | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Comment model |
| GDTE-A110 | `views.py::editar_revision_cesion` | Read review | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Review model |
| GDTE-A111 | `views.py::editar_revision_cesion` | Save review change | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Review model |
| GDTE-A112 | `views.py::eliminar_revision_cesion` | Read review before deletion | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Read then delete |
| GDTE-A113 | `views.py::eliminar_revision_cesion` | Delete review | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Review model |
| GDTE-A114 | `views.py::sincronizar_cesiones_rpetc` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session `empresa_id` |
| GDTE-A115 | `views.py::sincronizar_cesiones_rpetc` | Check for RPETC task in progress | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Avoids duplicate period sync |
| GDTE-A116 | `views.py::sincronizar_cesiones_rpetc` | Read cessions related to task | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Accounting registration input |
| GDTE-A117 | `views.py::_dashboard_resumen` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session/company scope |
| GDTE-A118 | `views.py::_dashboard_resumen` | Aggregate company-scoped cessions | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Dashboard metrics |
| GDTE-A119 | `views.py::index` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Dashboard |
| GDTE-A120 | `views.py::dashboard_resumen` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session/company scope |
| GDTE-A121 | `views.py::dashboard_resumen` | Query/aggregate cessions | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Data Plane |
| GDTE-A122 | `views.py::certificados_list` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session `empresa_id` |
| GDTE-A123 | `views.py::certificados_list` | Look up access-control `Vista` | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Permission lookup |
| GDTE-A124 | `views.py::certificados_list` | Look up `Permiso` for active company | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | ICMEAS scope |
| GDTE-A125 | `views.py::certificados_list` | Check create permission across companies | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Explicit cross-company query |
| GDTE-A126 | `views.py::certificados_eliminar` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session `empresa_id` |
| GDTE-A127 | `views.py::certificados_eliminar` | Delete certificate through repository | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | Delegated database operation |
| GDTE-A128 | `views.py::certificados_eliminar` | Delete certificate file from storage | FILE_STORAGE | PRODUCTIVE | FILE_STORAGE | NOT_APPLICABLE | NO | YES | After row deletion |
| GDTE-A129 | `views.py::certificados_cargar` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session `empresa_id` |
| GDTE-A130 | `views.py::certificados_detail` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session `empresa_id` |
| GDTE-A131 | `views.py::certificados_detail` | Read company certificates through repository | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | Company-scoped |
| GDTE-A132 | `views.py::certificados_list` / `certificados_detail` / `certificados_cargar` | Read company master through helper | EXTERNAL_ACCESS | PRODUCTIVE | EXTERNAL_CANONICAL | PRIVATE_ROUTER | NO | YES | Uses maestro helper |
| GDTE-A133 | `views.py::certificados_toggle_active` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session `empresa_id` |
| GDTE-A134 | `views.py::certificados_toggle_active` | Repository lookup of certificate | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | Before update |
| GDTE-A135 | `views.py::certificados_toggle_active` | Repository update of active state | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | Django or MySQL branch |
| GDTE-A136 | `views.py::certificados_probar_conexion` | Read active company from session identity | SYSTEM_CORE_ACCESS | PRODUCTIVE | SYSTEM_CORE | IMPLICIT_DEFAULT | NO | YES | Session `empresa_id` |
| GDTE-A137 | `views.py::certificados_probar_conexion` | Repository lookup of certificate | BACKEND_ADAPTER | PRODUCTIVE | GESTIONDTE_DATA_PLANE | PRIVATE_ROUTER | NO | YES | Certificate scoped to company |
| GDTE-A138 | `views.py::certificados_probar_conexion` | Read company master through helper | EXTERNAL_ACCESS | PRODUCTIVE | EXTERNAL_CANONICAL | PRIVATE_ROUTER | NO | YES | Contabilidad helper |
| GDTE-A139 | `views.py::certificados_probar_conexion` / `services/sii_auth.py` | Submit SII authentication/token request | EXTERNAL_API | PRODUCTIVE | EXTERNAL_SYSTEM | NOT_APPLICABLE | NO | YES | SII test/auth flow |
| GDTE-A140 | `management/commands/ejecutar_lectura_automatica_cesiones.py::Command.handle` | Read `LecturaAutomaticaConfig` by singleton `pk=1` before deciding whether to run | OPERATIONAL_BYPASS | PRODUCTIVE | GESTIONDTE_DATA_PLANE | IMPLICIT_DEFAULT | NO | YES | Post-freeze discovery; direct `.objects.filter(pk=1).first()` at line 12. Independent of Admin A027 and service/view A066/A085; pending adaptation in B2-2. |

### Inventory reconciliation

The primary-classification baseline supplied for this freeze is:

| Primary classification | Sites |
|---|---:|
| `CONTROL_PLANE` | 6 |
| `BACKEND_ADAPTER` | 23 |
| `OPERATIONAL_BYPASS` | 65 |
| `LEGACY_CONNECTION_BYPASS` | 0 |
| `EXTERNAL_ACCESS` | 8 |
| `SYSTEM_CORE_ACCESS` | 25 |
| `FILE_STORAGE` | 5 |
| `EXTERNAL_API` | 5 |
| `TEST_ONLY` | 0 |
| `MIGRATION_ONLY` | 3 |
| `DEAD_CONFIRMED` | 0 |
| `UNKNOWN` | 0 |
| **TOTAL_ACCESS_SITES** | **140** |

```text
BASELINE_ACCESS_SITES = 139
POST_FREEZE_NEW_ACCESS_SITES = 1
PENDING_BASELINE_IDS = 64
PENDING_BASELINE_UNIQUE_SITES = 62
PENDING_ACCESS_IDS = 65
UNIQUE_PENDING_ACCESS_SITES = 63
DOCUMENTAL_OVERLAP_PAIRS = 2 (A012/A058; A013/A059)
SUM_PRIMARY_CLASSIFICATIONS_MATCH = YES
UNCLASSIFIED_RELEVANT_MATCHES = 0
```

The A012/A058 and A013/A059 notes preserve the supplied IDs but flag that the
current source contains one `update_or_create` statement and one cession lookup
statement, respectively. They must not be interpreted as additional SQL
statements. The frozen baseline retains IDs A001-A139. GDTE-A140 is one independently
verified post-freeze access, not a renumbering or a change to the historical
baseline. The command read is operational scheduling configuration, not
connection-routing Control Plane. The 65 pending IDs represent 63 unique
pending sites after subtracting only the two documented duplicate-reference
pairs.

## 4. Frozen cross-cutting findings

| Finding | Classification / status | Evidence and constraint |
|---|---|---|
| GDTE-R001 | `CLOSED_BY_HUMAN_DECISION` | `PRIVATE_ROUTER_SCOPE=GLOBAL_PER_APPLICATION`; `CONTROL_PLANE_SCOPE=GLOBAL_PER_APPLICATION`. Preserve existing company data isolation, permissions, filters, identities and process behavior. No per-company role, model, schema, permission, Settings or UI change. |
| GDTE-R002 | `SYSTEM_CORE_FINDING` | External to this application transformation; do not modify. |
| GDTE-R003 | `SYSTEM_CORE_FINDING` | External to this application transformation; do not modify. |
| GDTE-R004 | Operational ORM bypass | Operational ORM access remains implicit-default in the listed sites. |
| GDTE-R005 | `RESOLVED_BY_GDTE_B1` | A015-A018 now resolve/open through the private `servercontabilidad` role and Settings opener; SQL schema coupling remains unchanged. |
| GDTE-R006 | Residual / latent | `CertificadoSII.save()` retains an implicit ORM fallback at A010. |
| GDTE-R007 | Adapter/side-effect risk | Certificate database writes and file-storage operations do not share a distributed transaction. |
| GDTE-R008 | `CLOSED_BY_HUMAN_DECISION` / functional policy frozen | Preserve exactly the current Admin visibility for A024-A031. Do not add/remove company filters or change permissions. Their connection adaptation remains pending. |

### Contabilidad

```text
ACCOUNTING_ROLE_INTERNAL_KEY = servercontabilidad
ACCOUNTING_LEGACY_BYPASS_IDS = NONE
ACCOUNTING_PRE_B1_LEGACY_BYPASS_IDS = GDTE-A015, GDTE-A016, GDTE-A017, GDTE-A018
ACCOUNTING_CONNECTION_PATH_POST_B1 = PRIVATE_ROUTER
CONNECTION_SELECTION_COUPLING = REMOVED
SQL_SCHEMA_COUPLING = PRESENT_UNCHANGED
ACCOUNTING_AUDIT_ROLE_INTERNAL_KEY = serverauditoriacontabilidad
ACCOUNTING_AUDIT_ACCESS_SITE_IDS = NONE FOUND
ACCOUNTING_AUDIT_LEGACY_BYPASS_IDS = NONE FOUND
```

The validated B1 connection path is:

```text
GestionDTE
  -> private resolver
  -> servercontabilidad
  -> Settings physical connection catalog
  -> Settings public connection opener
  -> physical connection
  -> Contabilidad
```

Keep schema-name coupling separate from connection selection. Current code
contains `eltit_conta` and `eltit_conta{codigo}` references. This phase does not
change those names, convert them into configuration, or conclude that they
should be removed.

```text
SQL_SCHEMA_COUPLING = PRESENT
CAN_MOVE_CONTABILIDAD_BY_CONFIGURATION = NO
```

There are no identified consumers for `serverauditoriacontabilidad`; do not
invent one.

### Data Plane classification

```text
OPERATIONAL_BYPASS_IDS =
GDTE-A010-GDTE-A014, GDTE-A022-GDTE-A032, GDTE-A058-GDTE-A063,
GDTE-A066-GDTE-A075, GDTE-A076-GDTE-A080, GDTE-A084-GDTE-A086,
GDTE-A088, GDTE-A090, GDTE-A092, GDTE-A094, GDTE-A097-GDTE-A098,
GDTE-A100-GDTE-A113, GDTE-A115-GDTE-A116, GDTE-A118, GDTE-A121, GDTE-A140

LEGACY_CONNECTION_BYPASS_IDS = NONE
```

Families:

- `CERTIFICADOS`: A010, A024, A032, A034-A045, A127, A131, A134-A135, A137.
- `RPETC_IMPORT`: A011-A014, A058-A063.
- `RPETC_QUERY`: A076-A080, A088, A090, A092, A094, A118, A121.
- `RPETC_REVIEW`: A097-A113.
- `RPETC_AUTOMATIC_READING`: A022, A066-A072, A084-A086, A115, A140.
- `ADMIN_READ_ONLY`: A024-A031, including A027-A028; all retain their existing
  visibility and remain pending connection adaptation.
- `RPETC_ACCOUNTING`: A015-A018; external canonical access through the private
  router. PRE_B1, all four sites were `LEGACY_CONNECTION_BYPASS`.

A073-A075 are explicitly public/no-productive-caller-found. Their status is
not `DEAD_CONFIRMED`.

### Independence status

```text
CAN_MOVE_GESTIONDTE_DATA_PLANE_BY_CONFIGURATION = NO
CAN_MOVE_CONTABILIDAD_BY_CONFIGURATION = NO
```

The frozen baseline attributed this to 64 operational bypasses and 4 legacy
connection bypasses. B1 removed the four legacy connection-selection bypasses.
Post-freeze discovery adds the independently confirmed A140, so 65 operational
ORM bypasses remain pending.

### Certificates

```text
REFERENCE_IMPLEMENTATION = YES
NOT_FULLY_CLEAN = YES
RESIDUAL_IDS = GDTE-A010, GDTE-A024, GDTE-A032
```

The primary repository path is a positive reference, but those residuals mean
the entire certificate family is not certified.

## 5. Proposed transformation sequence

GDTE-B1 is validated as recorded below. B2-1 through B2-8 remain proposals
and are not authorized by this inventory.

| Batch | Pending sites | Scope | Rationale / dependency |
|---|---|---|---|
| GDTE-B1 | A015-A018 | Contabilidad connection path | VALIDATED_NOT_COMMITTED. Private resolver and `servercontabilidad` role; current SQL/schema and transaction/commit behavior preserved. |
| B2-1 | A011-A014, A058-A063 | RPETC importer | Preserve compound persistence, task/cession identity, history, links and the existing transaction boundary. |
| B2-2 | A022, A066-A072, A084-A086, A140 | Automatic reading | Preserve scheduling, singleton config, lock/state lifecycle and company identity. Calls the B2-1 importer. |
| B2-3 | A076-A080, A088, A090, A092, A115-A116 | RPETC queries and synchronization | Preserve company filtering, payment-state results, filters, pagination, exports and B1 Contabilidad boundary. A115 also calls the B2-1 importer. |
| B2-4 | A094, A097-A098, A100-A113 | Reviews and comments | Preserve authorization, company/author scope, relations and response contracts. |
| B2-5 | A118, A121 | Dashboard | Read-only aggregation. Reuse of a B2-3 query adapter is optional, not a functional dependency. |
| B2-6 | A010, A032 | Certificate model/form fallbacks | Keep pending as `CONTRACT_NOT_PROVEN`; preserve public behavior unless reachability/contract evidence proves otherwise. |
| B2-7 | A024-A031 | Admin read-only | Preserve GDTE-R008 visibility exactly; connection adaptation remains pending. |
| B2-8 | A023, A073-A075 | Accounting-state snapshots | Keep pending as `CONTRACT_NOT_PROVEN`; no productive caller was found. Do not declare dead or alter behavior without evidence. |

Implementation order for B2-1 through B2-8 follows the detailed plan. A023
and A073-A075 remain a public/no-productive-caller-found service to review;
they are not human-decision blockers. B2-2 and B2-3 have hard runtime call
dependencies on B2-1; B2-5 may optionally reuse B2-3's adapter; B2-3 has no
call dependency on B2-8. Reassess runtime gates before authorizing each batch.
Do not transform
SYSTEM/CORE data sites A002-A003, A007, A033, A055, A064-A065, A081-A083,
A087, A089, A091, A093, A095-A096, A099, A114, A117, A119-A120,
A122-A126, A129-A130, A133, A136, or external canonical ownership. A015 remains
the app-owned historical connection-selection site, now resolved through the
private router; Settings itself remains out of scope.

### B1 preservation contract and validation

B1 preserved:

- current SQL and tables;
- current schemas and parameters;
- result shapes;
- commit/rollback semantics;
- company scoping;
- side effects;
- HTTP/service behavior.

Only the way the connection is resolved/opened changed. B1 passed its focused
suite and the 70-test B1 relational subset; the two synchronization tests
passed after their test fixture supplied the pre-existing
`servercontabilidad` dependency. The unrelated `DB_sistema` selector test
remains excluded because `settings_test` exposes `default` and `system_test`,
not `DB_sistema`.

```text
GDTE_B1_STATUS = VALIDATED_NOT_COMMITTED
LEGACY_CONNECTION_BYPASS_BEFORE = 4
LEGACY_CONNECTION_BYPASS_AFTER = 0
TOTAL_ACCESS_SITES = 139
UNKNOWN = 0
CONNECTION_SELECTION_COUPLING = REMOVED
SQL_SCHEMA_COUPLING = PRESENT_UNCHANGED
READY_FOR_REAL_BACKEND_GATE = YES
```

## 6. Freeze rules and scope

- IDs `GDTE-A001` through `GDTE-A139` are the unchanged frozen baseline; never
  renumber or reuse them.
- The confirmed post-freeze site is GDTE-A140. A genuinely new site found later
  receives `GDTE-A141` and so
  on, with `POST_FREEZE_DISCOVERY = YES`, `DISCOVERY_PHASE`, and
  `REASON_NOT_CAPTURED`.
- This freeze does not assert runtime physical-backend validation or complete
  application certification.
- No ORM implementation detail is made an immutable functional contract.
- Do not modify Settings, access control, accounts, API, other SYSTEM/CORE
  apps, external canonical schemas, or GestionDTE data as part of this
  inventory.
- No credentials, passwords, tokens, DSNs, connection strings, or sensitive
  row values are included.

```text
INVENTORY_COMPLETE = YES (140 statically classified sites; runtime gates pending)
BASELINE_ACCESS_SITES = 139
TOTAL_ACCESS_SITES = 140
PENDING_ACCESS_IDS = 65
UNIQUE_PENDING_ACCESS_SITES = 63
READY_TO_FREEZE_CANONICAL_INVENTORY = YES
READY_TO_IMPLEMENT = NO
```

## 7. Audit safety record

```text
BASELINE_FILES_CHANGED_BEFORE_FREEZE = NO
POST_FREEZE_RECONCILIATION_FILES = connection-inventory.md, connection-transformation-plan.md
PYTHON_FILES_MODIFIED = NO
TEST_FILES_MODIFIED = NO
DATABASE_OR_EXTERNAL_CONNECTIONS_USED = NO
MIGRATIONS_RUN = NO
SCHEMA_OR_DATA_CHANGED = NO
TESTS_EXECUTED = NO
DJANGO_COMMANDS_EXECUTED = NO
GIT_STAGE = NO
GIT_COMMIT = NO
GIT_PUSH = NO
```
