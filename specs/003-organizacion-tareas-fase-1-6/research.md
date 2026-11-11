# Research y registro de decisiones Fase 1.6

## Corrección de internacionalización de maestros — 2026-11-10

Se autorizaron y agregaron en `static/lang/sp.json` y
`static/lang/en.json` las claves compartidas y específicas de Proveedores y
Locales usadas por la plantilla `tareas/maestros/catalogo.html`. El registro
explícito `_GENERIC_MASTER_KEYS`/`_GENERIC_MASTER_LABELS` de `tareas.views` se
verifica mediante `tareas/tests/test_i18n.py`; las claves dinámicas no pueden
ocultar identificadores sin traducción. No se modificó el motor i18n,
`static/js/app.js`, vendor, themes ni navegación global.

La paridad de los 26 identificadores de esta superficie quedó cubierta en
ambos idiomas. Las 39 claves de Departamentos existentes mantienen su paridad.
La autorización de las claves no implica cierre de G05 ni registro automático
de identidades VICMEAS.

La auditoría completa detectó además que las rutas nuevas no pertenecían a la
jerarquía de mixins que el guard de `tareas` exige en dispatch. Proveedores,
Locales y Departamentos ahora usan `TareasLoginVerificarPermisoMixin` y
declaran explícitamente que su catálogo multiempresa no requiere Empresa Base
00; la Empresa activa y VICMEAS siguen siendo obligatorios. La regresión quedó
cubierta por `test_empresa_base00_guard`.

## Implementación integral de superficies HTTP — 2026-11-10

Se añadieron superficies protegidas en `tareas` para listar y consultar
Proveedores y Locales, detalle JSON controlado para los tres maestros y rutas
POST preparadas para crear, editar y cambiar estado. Las rutas mutantes de
Proveedores, Locales y Departamentos permanecen bloqueadas explícitamente por
G17, G18 y G19/T201; ningún botón de escritura se presenta habilitado mientras
esos gates sigan abiertos. Los formularios de Proveedores y Locales validan la
forma contractual, pero no se ejecutan mientras la certificación de fuente
única no exista.

La nueva plantilla de Proveedores/Locales usa un registro explícito de claves
`data-key` compartidas y específicas, ya incorporadas con paridad en los
catálogos globales. La integración VICMEAS global y el registro de identidades
siguen condicionados por G05.

La certificación de lectura de `BASE_TAREAS` posterior a la corrección del
parser confirmó como `COMPATIBLE` las tablas `proveedores_proveedor`,
`organizacion_local`, `organizacion_departamento` y
`tareas_master_operation`. No se ejecutaron DDL, DML, migraciones, bootstrap
real, reconciliación real, commit ni push.

## Implementación postauditoría autorizada — 2026-11-10

Se aplicaron las decisiones A, B y C sin ejecutar DDL, migraciones,
reconciliación real, bootstrap real, pruebas opt-in de MariaDB, commit ni push.

- **F-01/F-02:** un commit incierto descarta la conexión original y consulta el
  registro T229 con una conexión nueva. Solo un registro durable `COMMITTED` se
  recupera automáticamente; `PENDING`, `UNKNOWN`, ausencia de fila o evidencia
  contradictoria se mantienen para revisión manual. Un `PENDING` durable puede
  pasar a `UNKNOWN` para hacer visible la incertidumbre, nunca a `FAILED` por
  antigüedad. No se repite la mutación ni se sustituye el UUID.
- **F-03:** las rutas propias conservan `CONFIRMED` como terminal mediante
  bloqueo y actualización SQL condicional. Esto no protege a escritores SQL con
  privilegios equivalentes que ignoren el servicio; la certificación de
  privilegios queda pendiente.
- **F-05:** el preflight lee, parsea y compara también
  `base_tareas_maestros_v001.sql` y `base_tareas_master_operations_v001.sql`.
  La lectura no ejecuta DDL; la instalación explícita conserva su flujo
  existente y no se ejecutó en esta intervención. El comparador existente no
  inspecciona todavía `SHOW GRANTS` ni valida todas las expresiones `CHECK`;
  esos límites quedan reportados para una ampliación posterior antes de
  certificación.
- **F-04:** se incorporaron exactamente 39 claves
  `tareas.master_catalog.department.*` en `en.json` y `sp.json`, con paridad
  verificada. No se modificó el motor i18n ni `app.js`.
- **F-06:** se preparó `bootstrap_master_catalog_views`, de inspección por
  defecto y con `--apply` explícito. Registra solo las tres identidades
  aprobadas, no asigna permisos ni crea Empresas, y no fue ejecutado contra
  datos reales.

El reconciliador ahora enumera `COMMITTED` para proyección, `ERROR` recuperable,
`UNKNOWN` y `PENDING`; los dos últimos producen una salida administrativa
sanitizada de revisión y nunca ejecutan nuevamente la mutación. La evidencia
aislada de una entidad de catálogo o la antigüedad de una fila no confirma el
resultado.

Pruebas aisladas añadidas: recuperación de `COMMITTED` durable sin replay,
revisión de `PENDING/UNKNOWN`, contrato de manifiestos, paridad de traducciones y
bootstrap idempotente simulado. Los gates G02/G05/G07/G17/G18/G19 permanecen
abiertos.

## Implementación correctiva controlada — 2026-11-10

El precheck de esta intervención fue `main`, HEAD `918ffd4c52c1adc2ce7538bf8fe56e14ddc5100f`.
El worktree ya contenía cambios locales dentro y fuera de `tareas`; todos se
preservaron. Las correcciones de esta intervención se limitaron a `tareas/` y
a los artefactos de Fase 1.6 indicados en el informe. No se modificaron
SYSTEM/APPLICATION_APPS ajenas, traducciones globales, navegación ni vendor.

Decisiones formalizadas: D01 fija `Tareas - Maestro de locales`; D02 vincula
el usuario Django activo a la auditoría central cuando existe y conserva
`actor_id` en `meta`; D03 mantiene las operaciones `UNKNOWN` bloqueadas salvo
evidencia durable concluyente y no repite mutaciones por heurística.

Se integró el registro existente T229 con mutaciones SQL mediante un coordinador
que reserva UUID/hash, ejecuta la mutación y persiste el resultado usando una sola
conexión/transacción `BASE_TAREAS`. La proyección posterior utiliza el adaptador
de `AuditoriaService.log_event_idempotent()`. Los errores de auditoría quedan
marcados como reintentables o permanentes; `reconcile_master_operations()` procesa
un lote acotado y el comando propio `reconcile_master_catalog_audit` no programa
reintentos automáticos. Los errores de commit/rollback inciertos requieren el
mismo UUID; no se repite una escritura en la misma solicitud.

Los servicios SQL de Proveedores, Locales y Departamentos consumen el coordinador.
El catálogo de Departamentos tiene además listado, detalle, alta y edición de
nombre con ICMEAS y fetch/CSRF. No se habilitaron bajas/reactivaciones de Local o
Departamento. No se crearon vistas/menús de Proveedores o Locales: T221 conserva
el literal aprobado `Proveedores - Maestro`, pero G17/fuente única sigue abierta.
La identidad aprobada de Locales es `Tareas - Maestro de locales`; G05 continúa
abierto hasta verificar su integración. La identidad aprobada de Departamento se
reutiliza, pero el registro global, navegación e i18n siguen fuera del scope
autorizado.

La normalización RUT conserva los ceros iniciales conforme al contrato T228. Por
ejemplo, `1-9` y `01-9` son RUT matemáticamente válidos y permanecen como cadenas
canónicas distintas; el índice UNIQUE global solo impide repetir la misma cadena
normalizada. No se colapsan cuerpos numéricamente equivalentes sin una decisión
contractual expresa.

Validación ejecutada: 46 pruebas focalizadas PASS, `manage.py check` PASS con el
warning preexistente `ckeditor.W001`, compilación Python y `node --check` PASS.
No se ejecutaron DDL/DML contra bases persistentes, pruebas opt-in MySQL ni
validación visual en navegador; por tanto no se certifican T218-T220/T230 ni se
cierran G02/G17/G18/G19.

**Estado contractual actualizado**: T216/T229 seleccionan el registro técnico
SQL de operaciones en `BASE_TAREAS`; no es un ledger de negocio ni una segunda
auditoría. G02 continúa abierto por falta de certificación real de la proyección
desde `BASE_TAREAS`, y T230 permanece abierta hasta certificar el flujo.

## Precheck y metodo

Fecha 2026-10-30; rama `main`; HEAD `196658dfb4d77b3942bde1603e1affa00fc112d2`.
`git diff` y `git diff --cached` iniciales vacios. Unico untracked inicial:
`db.sqlite3.bak_pre_L4_20261019`, preservado sin abrir ni modificar.
Solo comandos Git de lectura; no fetch/pull/checkout/commit/push, pruebas,
consultas a bases, migraciones ni instalaciones.

## Rectificación arquitectónica definitiva — 2026-11-09

La decisión final permite avanzar con DDL SQL MySQL, servicios SQL y pantallas
futuras de Proveedores, Locales y Departamentos dentro de `tareas`, usando el rol
configurable `BASE_TAREAS` y los resolvers existentes. No se usarán modelos ORM,
migraciones Django ni modelos espejo.

La falta de APIs públicas en `proveedores` u `organizacion` deja de ser un bloqueo
de implementación SQL. Se conserva como bloqueo de transición y habilitación:
inventariar y adaptar consumidores, preservar PK/IDs y referencias históricas,
definir cómo se desactivan los writers antiguos, cerrar auditoría/idempotencia y
certificar consistencia entre MySQL y `default`. Hasta entonces `BASE_TAREAS`
puede validarse en entorno aislado, pero no puede ser un segundo writer productivo.

La separación normativa es: (1) esquema DDL versionado y preflight; (2) servicios
SQL y transacciones; (3) integración con conexiones, ICMEAS, auditoría y
notificaciones; (4) transición y callers; (5) UI CRUD; (6) certificación y corte.

## Certificación de servicios SQL — 2026-11-09

La revisión de `tareas/services/master_catalog_common.py`,
`providers.py`, `locals.py` y `department_catalog.py` encontró y corrigió un
defecto de propagación: el helper de espera de locks clasificaba un duplicado
SQL como conflicto genérico de mutación y ocultaba `MasterCatalogConflict`.
La capa común ahora conserva los errores de dominio presentes en la cadena causal
y solo sanitiza fallos de base no clasificados.

Se eliminó además la importación directa de `proveedores.services.rut` desde
`tareas`, porque ambas son APPLICATION_APPS y la APPLICATION BOUNDARY prohíbe
consumir servicios de otra aplicación sin contrato público. No se duplicó el
algoritmo RUT. Las lecturas de Proveedores permanecen disponibles; sus
mutaciones están bloqueadas hasta una interfaz pública autorizada.

La prueba real opt-in de MySQL (`master_catalog_mysql_checks.py`) verificó
aislamiento por Empresa, commit de Local/Departamento, limpieza y dos altas
concurrentes del mismo código. Cada hilo resolvió y comprobó `SELECT DATABASE()`
antes de escribir; el resultado fue una sola fila confirmada y un conflicto
controlado. La prueba se ejecuta fuera del runner Django porque el resolver
`BASE_TAREAS` debe consultar su configuración en la base de desarrollo, no en
una base de pruebas sustituida.

Persisten estos bloqueos:

1. `CompanyContext` no demuestra pertenencia del actor a la Empresa; el caller
   debe aportar un contexto ya validado por ICMEAS/CORE antes de usarlo.
2. `MutationMetadata.operation_id` valida un UUID, pero no existe persistencia de
   idempotencia para la mutación SQL; UUID no se declara como replay seguro.
3. `AuditoriaService.log_event_idempotent` escribe en la auditoría central y no
   comparte transacción con `BASE_TAREAS`; el resultado continúa
   `PENDING_G02`.
4. ERP, lifecycle, membresías, JEFE y transición de callers siguen bloqueados
   por T227/T182/T183/T201/T212/T224-T226/G17-G19.

**Actualizacion documental 2026-11-03**: precheck en `main`, HEAD
`9ca3a693471cd8ed76acbe39143596fb1a9a3b96`, con cambios locales G02/T176-T181/T212
ya presentes y preservados. La edicion autorizada se limita a este directorio;
no se consultan bases persistentes, no se ejecutan pruebas/migraciones y no se
modifica la SPEC MAESTRA ni la constitucion.

Se reutiliza la auditoria de cierre aportada por el propietario, resultado
**SI, CON CONDICIONES**, sobre el mismo HEAD. No se localizo un informe adicional
en `specs/` ni en la consulta de historial reciente; no se atribuyen a ese informe
detalles distintos de los aportados. Se contrastaron solo sus puntos pertinentes,
no una nueva auditoria general ni una certificacion productiva.

Instrucciones consultadas: AGENTS, AI_CONTEXT, ARCHITECTURE_MAP, AI_TASK_PATTERNS,
COPILOT_PROMPTS, instrucciones globales, indice COPILOT, arquitectura de apps,
estado actual, vendor, contrato operacional de conexiones y constitucion 1.5.0.
Contratos consultados: bloques A/D/E/K de la SPEC MAESTRA, clarificaciones de
participacion y jerarquia, data-model organizacional, conexiones, URLs, L5 y
spec VICMEAS. La clasificacion real procede de
[app_classification.py](../../AppDocs/app_classification.py).

## Evidencia del antecedente en HEAD

| Hallazgo anterior | Contraste focal actual | Clasificacion |
|---|---|---|
| organizacion existe | [models.py](../../organizacion/models.py), admin read-only, migracion 0001 y clasificacion APPLICATION | Implementado; frase "futura app" es historica |
| Local/Departamento existen | Empresa PROTECT, codigo unico por Empresa, activo/source/fechas; solo Local tiene legacy_code | Implementado, sin relacion Local -> Departamento |
| tareas tiene ambitos basicos | [models.py](../../tareas/models.py), `tipo_ambito`, local/departamento, XOR y validacion de Empresa; T092/T093 completadas | Implementado, no implica membresias |
| Membresias incompletas | organizacion solo contiene ambos maestros; sin servicios, modelos de membresia ni vista departamental | Ausente, no parcialmente habilitada |
| Regularizacion masiva ausente | [participant_storage.py](../../tareas/services/participant_storage.py) recibe un task_id por comando; busqueda de regularizacion masiva sin coincidencias | Ausente |
| Atomicidad individual | Django `_execute` abre atomic por comando; MySQL abre conexion/transaccion y notifica al salir | Implementado por tarea, insuficiente para lote |
| Decisiones fuera de specs | Opcion B, roles organizacionales, sustitucion JEFE y lote aportados por prompt | Aprobadas, incorporadas en este complemento |
| No redisenar roles/estados | FR-D13..D17, `PUBLIC_ROLES`, `TareaParticipante.Rol` y restricciones de lifecycle | Vigente; no contradiccion que obligue a rediseno |

No se inspecciono la DB: no se afirma que exista o no una fila manual `Vista` en
un entorno. Lo verificado es ausencia de rutas/metadatos/contrato previo con el
literal `Tareas - Maestro de departamentos` en los archivos buscados.

## Decisiones consolidadas

| ID | Decision y fundamento | Alternativa descartada |
|---|---|---|
| F16-D01 | Conservar maestros canónicos; evidencia T092/T093 y prompt 4.1 | Duplicar Local/Departamento o inventar padre Local |
| F16-D02 | Membresia actual unica mas historial append-only; roles JEFE/SUPERVISOR/STAFF, maximo un JEFE | Borrar anterior o mezclar roles VICMEAS/tarea |
| F16-D03 | Sustitucion JEFE explicita y atomica en organizacion, motivo obligatorio | Degradacion automatica o reemplazo silencioso |
| F16-D04 | Opcion B transversal a LOCAL/DEPARTAMENTO/sin ambito, validaciones acumulativas | Exigir mismo Departamento o eximir tareas sin ambito |
| F16-D05 | Traslado/perdida/recuperacion no alteran asignaciones existentes; elegibilidad se deriva | Cascadas de borrado/reasignacion o privilegios congelados |
| F16-D06 | Baja logica departamental con revision y bloqueo por tareas pendientes; historia cerrada intacta | Borrar Departamento o trasladar historico |
| F16-D07 | Lote explicito origen/destino/rol/tareas/motivo, preview + confirmacion | Sustitucion global implicita, commit parcial |
| F16-D08 | Evidencia individual y UUID comun dentro de BASE_TAREAS; efectos despues de commit | Secuencia de servicios individuales que notifica/commitea por tarea |
| F16-D09 | Tareas consume APIs publicas de organizacion y conserva su resolver operacional propio; sin ciclo inverso | JOIN remoto, resolver importado de otra app, nuevo router o copia de maestros |
| F16-D10 | Fence organizacional mantenido hasta commit operacional; certificacion por backend | Doble lectura/version sin lock como supuesta garantia |
| F16-D11 | Reutilizar auditoria/notificaciones base y separar dominio de proyeccion central | SMTP propio, auditoria transversal paralela, atomicidad distribuida ficticia |
| F16-D12 | UI/permisos actuales y dependencias externas explicitas; arranque sin backfill inferido | Crear permisos por rol, editar CORE/catalogos sin autorizacion |

F16-D01 a D09, D11 y D12 consolidan reglas aprobadas y restricciones vigentes.
F16-D10 y la forma de persistencia son **diseno tecnico propuesto**, no evidencia
de implementacion ni nueva decision de negocio.

## Rectificacion de ownership — 2026-11-03

Se conserva el objetivo de que los tres maestros tengan su fuente autoritativa en
el rol configurable `BASE_TAREAS`, pero la instruccion vigente coloca toda nueva
funcionalidad en `tareas`. Los modelos/servicios existentes de `proveedores` y
`organizacion` no se eliminan, duplican, migran ni modifican bajo esta autorizacion.
No se crea un modelo espejo ni se habilita un segundo writer en `tareas`.

| Opcion | Dictamen rectificado |
|---|---|
| A. Trasladar directamente los modelos actuales | No autorizada ni ejecutable en esta tarea: exige cambiar owners/modelos/FKs fuera de `tareas` y migrar datos. |
| B. Crear catálogos nuevos en `tareas` y sincronizarlos con los actuales | Descartada: duplicaria modelos/datos y crearia dos fuentes activas, prohibido por el requerimiento. |
| C. Nueva interfaz en `tareas`, datos objetivo en `BASE_TAREAS`, APIs públicas para dependencias | Es el objetivo documental. DDL y servicios SQL target avanzan sin APIs owner; transición, callers y habilitación quedan bloqueados donde faltan contratos. No se resuelve con ORM privado, SQL de bypass o modelos espejo. |

Decisiones consolidadas y preservadas:

| ID | Decision |
|---|---|
| F16-D13 | `BASE_TAREAS` sigue siendo el rol objetivo, no un alias fijo; el resolver de `tareas` existente es el unico a reutilizar para la nueva funcionalidad. |
| F16-D14 | Proveedores es global, sin Empresa, con RUT normalizado/unico e identidad `Proveedores - Maestro`; una pantalla modal/AJAX bajo `tareas`. |
| F16-D15 | Locales por Empresa; ERP protegido y LOCAL editable autorizado; identidad `Tareas - Maestro de locales`; campos/IDs preservados; baja/reactivacion condicionada por T227; pantalla nueva en `tareas`. |
| F16-D16 | Departamentos por Empresa; codigo/Empresa/source inmutables, nombre editable; baja T183 tras T201/G07; membresias T176 y JEFE T182; pantalla `Tareas - Maestro de departamentos`. |
| F16-D17 | APIs publicas e IDs estables, sin FK/JOIN cross-database ni catalogos/modelos espejo. |
| F16-D18 | Registro técnico de operaciones en `BASE_TAREAS`, combinado con idempotencia durable y estado de proyección de auditoría; no asumir atomicidad distribuida. |
| F16-D19 | Todo nuevo codigo funcional de estos maestros reside en `tareas`; las apps existentes permanecen intactas. |
| F16-D20 | Si un API publico necesario para cruzar dominios no existe, la operacion se bloquea y se solicita autorizacion independiente; los maestros target permanecen internos de `tareas`. |
| F16-D21 | La validación canónica de RUT pertenece a `tareas/utils/rut.py`; no se importa ni se duplica el algoritmo de otra APPLICATION_APP. |
| F16-D22 | T216 selecciona un registro técnico SQL en `BASE_TAREAS` para UUID/hash/replay/reconciliación; no es una segunda auditoría central ni un 2PC. |

### Evidencia T228

`tareas/utils/rut.py` implementa la limpieza de separadores permitidos, la
normalización canónica `cuerpo-DV`, el cálculo módulo 11 y la validación de
`K` y `0`, sin importar otras APPLICATION_APPS, ORM ni conexiones SQL. La
política certificada para esta utilidad convierte `None` y entradas vacías en
ausencia, mientras preserva los ceros iniciales del cuerpo. La evidencia es
`tareas/tests/test_rut.py`: 11 pruebas focalizadas PASS; `manage.py check`
también PASS con el warning preexistente de CKEditor. T228 no habilita por sí
sola las mutaciones de Proveedores ni cierra T229/T230.

### Evidencia T229

El manifiesto `tareas/sql/base_tareas_master_operations_v001.sql` crea
`tareas_master_operation` únicamente en `BASE_TAREAS`, con motor InnoDB, UUID
como PK, hash SHA-256 ASCII, estados `PENDING`/`COMMITTED`/`FAILED`/`UNKNOWN`,
estado de auditoría, resultado JSON, índices de consulta y checks de contrato.
El preflight confirmó `SELECT DATABASE() = 'tareas'`, la tabla no existía y
quedó verificada con 14 columnas; las pruebas limpiaron sus propios UUID y la
tabla terminó con cero filas de certificación.

`tareas/services/master_operation_store.py` expone serialización/hash
deterministas, reserva con `SELECT ... FOR UPDATE`, replay, conflicto de
payload/identidad, resultado durable, estados de fallo/UNKNOWN, estados de
auditoría y consulta de reconciliación. La transacción reutiliza el timeout de
locks y la transacción InnoDB existentes de `tareas`; la conexión verificada
reutiliza el resolver `BASE_TAREAS` y comprueba la base física `tareas`.

La evidencia es `tareas/tests/test_master_operation_store.py` (5 pruebas
unitarias PASS), `tareas/tests/master_operation_mysql_checks.py` (4 checks
MariaDB PASS: replay/conflicto, resultado durable, rollback, concurrencia,
reapertura y reconciliación) y `manage.py check` PASS con el warning
preexistente de CKEditor. La incertidumbre de commit no puede persistir
`UNKNOWN` después de perder la conexión; el registro permite marcarlo durante
la recuperación y el protocolo de captura/proyección pertenece a T230.

## Capacidades existentes y limites

| Capacidad | Interfaz publica reutilizable | Limite relevante |
|---|---|---|
| Autenticacion/sesion/Empresa | `request.user`, `session['empresa_id']`, helpers oficiales de `access_control` | No duplicar seleccion de Empresa, acceso ni autenticacion |
| VICMEAS/ICMEAS | `VerificarPermisoMixin`, `verificar_permiso`, `user_has_permission_for_empresa` | Una identidad madre; sin permisos locales ni bypass |
| Auditoria | `AuditoriaService` y APIs centrales existentes | G02: verificar capacidades para el nuevo writer Tareas; no es atomica con BASE_TAREAS ni equivale a idempotencia |
| Conexiones | `tareas.services.connection_roles` existente y APIs publicas de `settings` | Reutilizar, no crear resolver nuevo ni modificar `DATABASES`/router |
| Notificaciones | APIs publicas de `notificaciones` y correo de sistema `acounts` | Consumir segun contrato; no crear cola/SMTP local |
| Menu e i18n | Recursos globales protegidos | Solo excepciones G05 con autorizacion especifica; no editar en esta tarea |

| Gate | API/capacidad ausente | Efecto |
|---|---|---|
| F16-G17 | Proveedores tiene CRUD existente basado en ORM directo, pero no servicio publico owner necesario para la transición | T218/T221 pueden implementar el target SQL interno de `tareas`; transición, callers y writer productivo siguen bloqueados |
| F16-G18 | No se identifico API publica de Locales | T219/T222/T224/T227 bloqueadas para operaciones que requieren datos; no importar `Local` ni modificar organizacion |
| F16-G19 | `list_active_departments` existe pero no acredita lectura desde BASE_TAREAS; tampoco hay API publica confirmada para create/update, reemplazo atomico JEFE o prepare/finalize/activo. `change_membership` no sustituye esas operaciones | T220 no puede leer el target como si la API actual lo sirviera; T212/T182/T183/T201/T223 bloqueadas para lectura/escritura faltante |

Los modelos actuales siguen siendo fuentes/callers preexistentes mientras no haya
una transicion autorizada. El CRUD existente de Proveedores continua fuera de este
scope; Tareas no puede desactivarlo ni asegurar exclusividad de writer sin una
dependencia adicional. Por tanto, ninguna pantalla nueva puede habilitar escritura
hasta demostrar una fuente unica, APIs publicas suficientes y un corte autorizado.
T176/T177 se conservan historicamente en `organizacion/default`; no certifican
MySQL, ni autorizan imports privados desde Tareas. No se consultaron datos persistentes.

## Reconciliacion documental acotada

| Discrepancia | Resolucion para esta fase |
|---|---|
| ARQUITECTURA_APPS/data-model dicen "organizacion aun no existe" | Etiqueta historica de etapa anterior; T092/T093 y codigo prevalecen para estado real; no editar documentos fuera de alcance |
| FR-D06 dice "cuando corresponda" un jefe | Maximo un JEFE activo y cero sin warning, conforme al prompt; no exigir cobertura obligatoria |
| SPEC/URLs antiguas hablan de bypass visual superuser | Codigo actual y spec 002 separan V/ICMEAS sin bypass visual; no usar ese texto historico para crear privilegios |
| URLs antiguas separan Vistas de detalle/editar | Metadata actual usa `Tareas` para la superficie principal; no crear Vistas desde tablas historicas |
| Regla generica ForeignKey Empresa frente a storage externo | Maestros en BASE_TAREAS usan empresa_id estable sin FK fisica a CORE; datos de dominio que permanezcan en default pueden conservar FK local |
| Connection Roles y ownership | `tareas` reutiliza su resolver existente; no importa resolvers/modelos privados de otras APPLICATION_APPS. APIs faltantes quedan bloqueadas |
| Contrato de conexiones dice runtime pendiente | Los adapters actuales existen; no declarar pendientes todos los storages ni certificar todos sus backends por ese hecho |
| "Auditoria individual" frente a deuda de participantes FR-D17 | Nuevo historial de dominio transaccional para regularizacion; proyeccion central separada. No declarar saldada toda deuda historica |

La actualizacion autorizada modifica solo los artefactos de Fase 1.6 en este
directorio. No se reescribe la SPEC MAESTRA, la constitucion, CORE ni los resolvers
globales. Tareas reutiliza su resolver y las APIs publicas disponibles; no crea
infraestructura para suplir G17-G19.

## Dependencias, riesgos y decisiones realmente ausentes

| ID | Nivel/tipo | Evidencia, impacto y condicion de salida |
|---|---|---|
| F16-G01 | Alto, tecnico | Fence entre default y BASE_TAREAS no existe. Certificar exclusión de escrituras de membresia/Departamento, incluso admin/commands, y orden global de locks; bloquear lote si backend no puede garantizarlo |
| F16-G02 | Bloqueante para mutaciones auditadas multi-base, dependencia externa | T216 selecciona el registro técnico y el worktree integra T230 con la API central idempotente; las pruebas unitarias no certifican el flujo físico `BASE_TAREAS` → auditoría central. Se requiere evidencia MySQL/auditoría autorizada antes de habilitar o cerrar G02; no modificar CORE ni crear auditoría shadow |
| F16-G03 | Bloqueante para roles no soportados, funcional | FR-D15 solo permite alta/cambio publico PARTICIPANTE/INVITADO_OBSERVADOR; responsable usa su campo. No consta autorizacion de sustitucion publica SUPERVISOR/AUTORIZADOR ni reemplazo CREADOR. Mantener bloqueo explicito por rol; cerrar politica antes de habilitarlos, sin redisenar roles |
| F16-G04 | Bloqueante para notificaciones organizacionales completas, funcional | El prompt exige notificar perdida/recuperacion, pero T054 solo detalla eventos de tareas. Falta precisar destinatarios/canal de traslado/suspension/perdida y si recuperacion notifica al propio actor. Recuperacion incluye al afectado por mandato expreso; no inventar alertas a todos los jefes o correos masivos |
| F16-G05 | Alto, autorizacion externa | Departamento reutiliza `Tareas - Maestro de departamentos`; su alta global/menu y sus 39 claves nuevas de traducción siguen pendientes. `Proveedores - Maestro` quedó seleccionado para T221 por el propietario, pero G17 bloquea habilitar su CRUD; Local permanece bloqueado hasta aprobar su literal. No se registraron Vistas ni se modificaron menús/SYSTEM |
| F16-G06 | Alto, tecnico | Schema incremental MySQL no se resuelve con migracion Django; disenar extension operacional/adapters y preflight sin ejecutar DDL ahora |
| F16-G07 | Alto, tecnico | Baja de Departamento cruza bases; no es una transaccion distribuida. Fence, protocolo reiniciable y revalidacion final; no finalizar ante bloqueo o estado incierto |
| F16-G08 | Alto, despliegue | Usuarios existentes sin membresias perderan operacion al activar Opcion B. Inventario/alta autorizada previa, sin inferir membresias de participaciones |
| F16-G09 | Medio, tecnico | Fallos tras commit, perdida de respuesta, auditoria o email fallidos; UUID y evidencia durable, reconciliacion controlada; exactamente-una-vez email no esta garantizado por infraestructura actual |
| F16-G10 | Bajo, documental | Etiquetas historicas desactualizadas fuera de specs y en maestra; quedan identificadas, no se corrigen por ampliacion de alcance |
| F16-G11 | Alto, tecnico | T213 debe documentar y reutilizar el resolver existente de `tareas` para `BASE_TAREAS`; no agregar resolver por owner, alias fijo ni cambio de CORE/router |
| F16-G12 | Alto, funcional/tecnico | T227 debe definir integridad y permisos de baja/reactivacion Local; hasta entonces no exponer esas acciones |
| F16-G13 | Alto, datos | T214/T215 deben especificar referencias estables, inventario autorizado, preservacion de IDs y recuperacion; no declarar migracion resuelta sin inspeccion autorizada |
| F16-G14 | Alto, seguridad/consistencia | T216 debe obtener contrato/autorizacion de auditoria, idempotencia durable y reconciliacion; ledger/outbox no seleccionado y no modificar CORE en esta tarea |
| F16-G15 | Alto, concurrencia | T217 debe demostrar protocolo compatible con MySQL; T177/SQLite no certifica escritores MySQL y no se asume atomicidad distribuida |
| F16-G16 | Alto, certificacion/corte | T225/T226 requieren SQLite temporal y MySQL aislado, rollback y responsable de reconciliacion antes de un corte controlado |

F16-G03/G04 no obligan a redisenar roles/estados/asignaciones. Son precisiones
ausentes que bloquean solo sus partes; no se reabre Opcion B ni ninguna decision
ya expresamente aprobada. No se declara "sin pendientes funcionales".

## Herramientas Spec Kit y limites de ejecucion

Se siguieron las estructuras de spec/plan/tasks y se leyo la constitucion.
`.specify/extensions.yml` no existe: hooks before/after plan/tasks no aplican.
No se ejecuta `setup-plan.ps1` ni `setup-tasks.ps1`: el helper compartido
`Get-FeaturePathsEnv` persiste `.specify/feature.json` al usar una nueva carpeta.
Eso excederia el permiso exclusivo `specs/`. Se crean los artefactos manualmente
sin cambiar estado Spec Kit, rama ni archivos globales. No se usan agentes de
investigacion externos ni se transmite codigo a terceros.
