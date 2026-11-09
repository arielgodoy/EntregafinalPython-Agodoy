# Modelo de datos propuesto Fase 1.6

**Estado**: las migraciones G02/T176-T179 existentes en el árbol de trabajo no se
presumen aplicadas a bases persistentes. La rectificación del 2026-11-09 define
un esquema SQL MySQL nuevo para los tres maestros dentro de `BASE_TAREAS`; no se
crean modelos ORM ni migraciones Django para esas tablas.
Referencias: [spec](spec.md), [consistencia](contracts/consistencia.md).
Los nombres de entidades nuevas son propuestas tecnicas locales; no agregan roles
ni permisos de negocio.

## Rectificación arquitectónica definitiva — 2026-11-09

Los tres maestros se materializan exclusivamente como tablas SQL MySQL en
`BASE_TAREAS`. El DDL es versionado mediante el mecanismo existente de
`tareas/services/base_tareas_schema.py` y scripts bajo `tareas/sql/`. No se
generan modelos ORM, migraciones Django ni tablas equivalentes en `default`.

El esquema target debe contener:

| Maestro | Columnas y reglas mínimas |
|---|---|
| Proveedores | `id` BIGINT preservado; campos actuales de identidad/contacto; `rut` normalizado UNIQUE global; `activo`; timestamps |
| Locales | `id` BIGINT preservado; `empresa_id`; `codigo`; `nombre`; `legacy_code`; `activo`; `source`; timestamps; UNIQUE (`empresa_id`,`codigo`) |
| Departamentos | `id` BIGINT preservado; `empresa_id`; `codigo`; `nombre`; `activo`; `source`; timestamps; UNIQUE (`empresa_id`,`codigo`) |

Las tres tablas serán InnoDB. No tendrán FK físicas hacia CORE ni hacia otras
bases. `source=ERP` será inmutable para Locales; `source=LOCAL` permitirá las
mutaciones autorizadas. En Departamentos, código, Empresa y source son inmutables
después del alta y nombre es editable. Las operaciones de mutación deben
conservar actor, UUID, motivo, antes/después y timestamps mediante el mecanismo
de auditoría operativa aprobado, sin crear una auditoría paralela.

La evolución será por manifiestos DDL SQL versionados, preflight idempotente,
verificación de InnoDB/índices/unicidades, dry-run y recuperación documentada.
No se ejecutará DDL productivo automáticamente ni se usarán `DROP`, `TRUNCATE`
o migraciones Django para estos maestros.

## Registro técnico de operaciones — diseño aprobado para T216

Las mutaciones futuras de los tres maestros requieren un registro técnico
durable en `BASE_TAREAS`. Sus columnas conceptuales mínimas son:

| Campo | Regla |
|---|---|
| `operation_id` | UUID único, obligatorio |
| `entity_type` / `action` | Entidad y operación normalizadas |
| `empresa_id` | Empresa activa validada; nullable solo para scope físico global, no para autorización |
| `actor_id` | Actor autenticado |
| `payload_hash` | Hash canónico de todos los parámetros mutables |
| `status` | `PENDING`, `COMMITTED`, `FAILED` o `UNKNOWN` |
| `result_id` / `result_payload` | Resultado mínimo replayable |
| `audit_status` | `PENDING`, `CONFIRMED` o `ERROR` |
| `audit_event_id` / `audit_error_code` | Proyección central y error sanitizado |
| `created_at` / `updated_at` | Trazabilidad técnica |

`operation_id` tendrá unicidad física. La fila se bloqueará con la misma
conexión de la mutación para detectar replay, payload conflictivo y resultado
incierto. El registro y la mutación se confirman o revierten en una única
transacción InnoDB. La proyección posterior utiliza
`AuditoriaService.log_event_idempotent()` y nunca se trata como una transacción
distribuida ni como una segunda auditoría.

Esta sección define el contrato de diseño de T216; la tabla y su DDL no se han
creado en esta Fase A.

## Diseño físico T213 — `base_tareas_maestros_v001.sql`

El artefacto [base_tareas_maestros_v001.sql](../../tareas/sql/base_tareas_maestros_v001.sql)
usa los nombres físicos derivados de los `db_table` actuales para conservar
compatibilidad semántica con IDs y referencias históricas, pero las tablas target
residen exclusivamente en `BASE_TAREAS`; no modifica ni reutiliza las tablas de
los owners en `default`.

| Tabla target | Campo | Tipo MySQL | Null/default | Restricción o índice | Origen/justificación |
|---|---|---|---|---|---|
| `proveedores_proveedor` | `id` | `BIGINT` | No / `AUTO_INCREMENT` | PK estable | `Proveedor` usa BigAutoField implícito; acepta IDs explícitos durante transición |
| `proveedores_proveedor` | `rut` | `VARCHAR(12)` | Sí / NULL | UNIQUE global | `CharField(max_length=12, null=True)`; la mutación queda bloqueada hasta disponer de una interfaz pública autorizada de validación |
| `proveedores_proveedor` | `nombre` | `VARCHAR(255)` | No | índice de búsqueda con prefijo 191 | `CharField(max_length=255)` |
| `proveedores_proveedor` | `direccion`, `comuna`, `ciudad` | `VARCHAR(255/100/100)` | No / `''` | — | Campos existentes con `blank=True, default=''` |
| `proveedores_proveedor` | `fono1`, `fono2`, `fax` | `VARCHAR(30)` | No / `''` | — | Campos de contacto existentes |
| `proveedores_proveedor` | `contacto` | `VARCHAR(150)` | No / `''` | — | Campo existente |
| `proveedores_proveedor` | `email1`, `email2` | `VARCHAR(254)` | No / `''` | — | `EmailField` Django con longitud efectiva 254 |
| `proveedores_proveedor` | `activo` | `TINYINT(1)` | No / `1` | índice activo+nombre | `BooleanField(default=True)` |
| `proveedores_proveedor` | `created_at`, `updated_at` | `DATETIME(6)` | No / servicio | — | `DateTimeField(auto_now_add/auto_now)`; el servicio aporta UTC |
| `organizacion_local` | `id` | `BIGINT` | No / `AUTO_INCREMENT` | PK estable | BigAutoField implícito; permite preservar IDs explícitos |
| `organizacion_local` | `empresa_id` | `BIGINT` | No | parte de UNIQUE e índices | FK lógica a CORE; no FK física cross-database |
| `organizacion_local` | `codigo` | `VARCHAR(100)` | No | UNIQUE (`empresa_id`,`codigo`) | `CharField(max_length=100)` |
| `organizacion_local` | `nombre` | `VARCHAR(255)` | No | — | `CharField(max_length=255)` |
| `organizacion_local` | `legacy_code` | `VARCHAR(100)` | Sí / NULL | — | `CharField(max_length=100, null=True, blank=True)` |
| `organizacion_local` | `activo` | `TINYINT(1)` | No / `1` | índice Empresa+activo | `BooleanField(default=True)` |
| `organizacion_local` | `source` | `VARCHAR(5)` | No / servicio | índice Empresa+source | `OrganizationalSource`: `ERP`/`LOCAL`; validación de dominio en servicio |
| `organizacion_local` | `created_at`, `updated_at` | `DATETIME(6)` | No / servicio | — | Campos Django existentes; el servicio aporta UTC |
| `organizacion_departamento` | `id` | `BIGINT` | No / `AUTO_INCREMENT` | PK estable | BigAutoField implícito; permite preservar IDs explícitos |
| `organizacion_departamento` | `empresa_id` | `BIGINT` | No | parte de UNIQUE e índices | FK lógica a CORE; no FK física cross-database |
| `organizacion_departamento` | `codigo` | `VARCHAR(100)` | No | UNIQUE (`empresa_id`,`codigo`) | `CharField(max_length=100)`; inmutable tras alta por servicio |
| `organizacion_departamento` | `nombre` | `VARCHAR(255)` | No | — | `CharField(max_length=255)`; único campo editable |
| `organizacion_departamento` | `activo` | `TINYINT(1)` | No / `1` | índice Empresa+activo | `BooleanField(default=True)`; lifecycle queda en T183/T201/G07 |
| `organizacion_departamento` | `source` | `VARCHAR(5)` | No / servicio | índice Empresa+source | Mismo `OrganizationalSource`; inmutable por servicio |
| `organizacion_departamento` | `created_at`, `updated_at` | `DATETIME(6)` | No / servicio | — | Campos Django existentes; el servicio aporta UTC |

El DDL usa `utf8mb4_unicode_ci`, consistente con la inspección estática del
schema/servicios MySQL existentes. La elección debe confirmarse contra la versión
real de `BASE_TAREAS` durante el preflight; si el servidor no soporta esa
codificación, el gate queda bloqueado y no se sustituye silenciosamente por otra.
No se añaden `CHECK`, triggers ni procedimientos: en versiones MySQL antiguas los
checks no son una garantía fiable y la inmutabilidad de `source`, `empresa_id`,
`codigo` y la protección de `source=ERP` deben aplicarse en los servicios SQL
autorizados, dentro de la transacción y con la fila releída bajo lock.

## Servicios SQL target preparados

Se añadieron servicios tipados bajo `tareas/services/` sin modelos ORM ni
endpoints:

- `providers.py`: lectura global y contratos de mutación de Proveedores. Las
  mutaciones permanecen bloqueadas porque consumir directamente
  `proveedores.services.rut` cruzaría la APPLICATION BOUNDARY y no existe aún
  una interfaz pública autorizada; no se duplica el algoritmo RUT.
- `locals.py`: lectura aislada por `CompanyContext`, alta y edición de Locales
  `LOCAL`. Las escrituras `ERP` y la baja/reactivación permanecen bloqueadas.
- `department_catalog.py`: lectura aislada por Empresa, alta de Departamentos
  `LOCAL` y edición exclusiva del nombre. Código, Empresa, `source` y lifecycle
  permanecen inmutables o bloqueados.
- `master_catalog_common.py`: resolución única de `BASE_TAREAS`, verificación
  efectiva de `SELECT DATABASE() = 'tareas'`, transacciones InnoDB, espera de
  locks y errores de dominio.

Toda mutación exige `MutationMetadata` con actor, UUID de operación y motivo.
El resultado declara `audit_status=PENDING_G02`: la auditoría central está fuera
de `BASE_TAREAS` y todavía no existe un contrato que garantice atomicidad
distribuida ni idempotencia durable para estos catálogos. Por ello no se creó
ledger, outbox ni almacenamiento paralelo, y los servicios no deben habilitarse
como writers productivos hasta cerrar G02/T216 y la transición T224-T226.
Las bajas/reactivaciones y las escrituras ERP no se presentan como disponibles
antes de T227/T183/T201/G07.

## Certificación de servicios — 2026-11-09

La certificación focal verificó:

- resolución `BASE_TAREAS` como `MYSQL_CONFIG` y rechazo de cualquier base física
  distinta de `tareas`;
- SQL parametrizado, errores de base sanitizados, transacciones InnoDB y
  propagación correcta de conflictos de unicidad;
- aislamiento por `empresa_id` en Locales y Departamentos;
- protección de registros ERP y bloqueo explícito de lifecycle no certificado;
- concurrencia real de dos conexiones independientes para el índice único
  (`organizacion_local_empresa_codigo_uniq`), con una sola alta confirmada y
  rollback del duplicado;
- ausencia de registros residuales de las pruebas reales.

No se cerraron G17-G19, T216, T218, T219 ni T220. La validación de Empresa en
`CompanyContext` comprueba forma y rango, pero la pertenencia del actor a la
Empresa debe acreditarse antes de invocar el servicio mediante la interfaz
ICMEAS/CORE correspondiente; por ello estos servicios no son una superficie HTTP
autorizada por sí mismos. La auditoría central e idempotencia durable continúan
pendientes de G02/T216.

`CREATE TABLE IF NOT EXISTS` solo evita un error de existencia. El preflight de
T213 debe consultar `information_schema.tables`, `columns`, `statistics` y
`table_constraints`, comparar tipos, nulabilidad, collation, motor, PK,
unicidades e índices con este manifiesto, y detenerse ante cualquier estructura
preexistente incompatible. No debe ejecutar DDL correctivo ni hacer `ALTER`,
`DROP`, `TRUNCATE` o migración automática.

La instalación futura será un paso explícitamente autorizado del mecanismo de
schema de `tareas`, usando el resolver `BASE_TAREAS`; este archivo no se importa
desde módulos ni se ejecuta automáticamente. Las evoluciones posteriores deberán
crear nuevos manifiestos versionados y pasar el mismo preflight. La recuperación
requiere backup verificable, dry-run, reconciliación de conteos/IDs/códigos y
rollback operacional documentado; no se copia información desde `default` en T213.

## Resultado de ejecución T213 — desarrollo

La resolución de `BASE_TAREAS` se verificó mediante
`tareas.services.connection_roles` y `open_mysql_connection`. La conexión efectiva
devolvió `SELECT DATABASE() = 'tareas'`; no se utilizó otra conexión ni se alteró
la configuración global.

| Dato verificado | Resultado |
|---|---|
| Servidor | MariaDB `10.11.13-MariaDB-ubu2004` |
| Base física | `tareas` |
| Charset de la base | `utf8mb4` |
| Collation de la base | `utf8mb4_general_ci` |
| Collation de las tablas | `utf8mb4_unicode_ci` |
| Motor | InnoDB en las tres tablas |
| Tablas creadas | `proveedores_proveedor`, `organizacion_local`, `organizacion_departamento` |
| Columnas | 15, 9 y 8 respectivamente |
| FKs cross-database | 0 |
| Filas residuales de prueba | 0 |

Pruebas reales ejecutadas únicamente en `tareas`: unicidad global de RUT,
aceptación de RUT `NULL`, unicidad de código por Empresa, aceptación del mismo
código en Empresas distintas, IDs explícitos, default `activo=1` y rollback
transaccional. Todas pasaron. Los registros de prueba fueron eliminados y la
inspección final confirmó cero filas en las tres tablas.

La instalación no modifica `base_tareas_schema.py`, `base_tareas_schema.sql`,
routers, modelos ni migraciones Django. La integración reproducible del nuevo
manifiesto con el instalador existente requiere una decisión técnica posterior;
T213 solo deja el DDL instalado y verificado en desarrollo.

## Entidades existentes y target de persistencia

Las referencias a los owners actuales son solo para identificar los modelos que
se preservan, no para autorizar su modificacion. La implementacion nueva, si se
desbloquea, pertenece a `tareas`. No se crean modelos espejo ni se activa una
segunda fuente mientras sigan vigentes las escrituras existentes.

| Entidad / modelo existente preservado | Meta de datos y restricciones |
|---|---|
| User / Django-acounts | Identidad canónica; actividad y acceso Empresa consultados por interfaces SYSTEM |
| Empresa / access_control | PK canónica, nunca se sustituye por Empresa enviada por formulario |
| `proveedores.Proveedor` | Owner histórico intacto. Target: tabla SQL global en `BASE_TAREAS`, sin Empresa; conservar PK/campos y RUT normalizado único. G17 condiciona transición y writer único, no el DDL/CRUD SQL target |
| `organizacion.Local` | Owner histórico intacto. Target: tabla SQL por Empresa en `BASE_TAREAS`; conservar PK/código/nombre/legacy_code/activo/source/fechas; ERP protegido y LOCAL manual. G18 condiciona transición y callers |
| `organizacion.Departamento` | Owner histórico intacto. Target: tabla SQL por Empresa en `BASE_TAREAS`; conservar PK/código/nombre/activo/source/fechas; código, Empresa y source inmutables; nombre editable; no FK a Local. G19 condiciona membresías/lifecycle y corte |
| Tarea / tareas | Identidad operacional en el rol `BASE_TAREAS`; `empresa_id`, `local_id` y `departamento_id` son referencias estables sin FK fisica cross-database; ambito LOCAL/DEPARTAMENTO o historico vacio; XOR e historia cerrada preservados |
| ReunionRevision / tareas | Referencias estables a Empresa/Local/Departamento/Tarea; no FK física a otro rol/owner; lectura target SQL requiere transición G18 para callers antiguos |
| Cotizacion / tareas | `proveedor_id` estable; validación target SQL en `BASE_TAREAS`; corte y adaptación de callers requieren G17; no FK física entre owners |
| TareaParticipante / tareas | Unico (tarea, usuario), rol historico; no contiene membresia organizacional |
| TareaReasignacion / tareas | Ledger existente para responsable; conservar filas e identidad saliente |

La ubicacion objetivo de los tres maestros es el rol configurable `BASE_TAREAS`,
resuelto por el mecanismo existente de `tareas`; puede ser alias Django o MySQL,
no un nombre fijo. La implementacion funcional nueva, incluidas superficies y
orquestacion, reside en `tareas`. Los modelos/servicios de `proveedores` y
`organizacion` no se eliminan, duplican, migran ni modifican bajo esta autorizacion.

El estado actual no se considera migrado: los modelos existentes y sus superficies
siguen siendo fuentes/callers preexistentes. No activar escritores en `tareas`
hasta que exista una fuente unica y una transicion/corte autorizados. No acceder a
los modelos fuente mediante ORM privado ni crear modelos espejo. La forma tecnica
de materializar el schema target en `BASE_TAREAS` no queda bloqueada por la ausencia
de APIs owner; la transición queda bloqueada si requiere
duplicacion de modelos; resolver G17-G19 antes del corte, no antes del DDL o de
los servicios SQL target aislados.

Empresa, Usuario, autenticacion/permisos y la coordinacion/historia organizacional
que permanezca en `default` no se trasladan por inferencia. Cuando una relacion
cruza owners o bases, se conserva la identidad como ID estable y se valida mediante
el servicio publico del owner. No se crean FK fisicas ni JOINs cross-database.
La migracion debe conservar IDs existentes y retirar la fuente activa de `default`
solo tras reconciliar todas las referencias; backups de transicion no son catalogos
autoritativos.

La creación de Departamento usa el source local vigente (`LOCAL`) y activo inicial.
La edición ordinaria solo puede modificar `nombre`; no permite cambiar `codigo`,
Empresa, `source` ni `activo`. No se introduce unicidad para `nombre`.

## MembresiaDepartamental (organizacion/default)

| Campo conceptual | Regla |
|---|---|
| id | PK interna estable |
| empresa, usuario | FKs protegidas a identidades canonicas de CORE en `default` |
| departamento_id | Meta: ID estable externo a `BASE_TAREAS`, sin FK fisica. El modelo actual conserva su FK a Departamento; cambiarlo requiere autorizacion fuera del alcance. Sin API/representacion compatible, membresias que dependen de la migracion quedan bloqueadas por G19 |
| rol | JEFE, SUPERVISOR o STAFF, exactamente uno |
| estado | ACTIVA, SUSPENDIDA o BAJA; estado de membresia, no de tarea |
| version | Revision monotona para detectar preview obsoleto; no reemplaza locks |
| created_at, updated_at | Fechas aware UTC |

Unica `(usuario, empresa, departamento)` aun cuando este suspendida/de baja; una
reactivacion reutiliza esa identidad y crea nuevo evento. No se borra y recrea.
La unicidad de la triple combinacion es mas simple que multiples filas temporales
solapadas; los intervalos historicos se reconstruyen desde eventos.

Como maximo una fila `rol=JEFE AND estado=ACTIVA` por Departamento. En los backends
propietarios que lo soporten, constraint condicional mas validacion de servicio.
Bloquear la fila Departamento para serializar dos altas cuando aun no existe JEFE;
la consulta de una fila inexistente por si sola no evita una carrera. No confiar
en `full_clean()` como barrera concurrente. Certificar restricciones por backend.
La inactividad de Departamento no habilita dos JEFES ACTIVA latentes.

**Efectiva** = membresia ACTIVA + Departamento activo + coherencia Empresa +
usuario activo y acceso Empresa vigente. `estado` no se modifica al perder acceso
SYSTEM o al desactivar un Departamento. No persistir un booleano duplicado de
elegibilidad ni derivar permisos VICMEAS de esta tabla.

Transiciones autorizadas: alta -> ACTIVA; ACTIVA -> SUSPENDIDA/BAJA;
SUSPENDIDA -> ACTIVA/BAJA; BAJA -> ACTIVA mediante recuperacion explicita.
Cambio de rol conserva identidad y genera evento. Toda mutacion exige motivo
no vacio y autor; una solicitud repetida con mismo UUID/payload no duplica historia.

## EventoMembresia (nuevo historial de dominio, organizacion/default)

PK; membresia_id; empresa_id; usuario_afectado_id; departamento_id (ID estable externo);
autor_id;
fecha; operacion_id UUID; tipo; motivo; rol/estado/version antes y despues.
Sin FK fisica a Departamento en `BASE_TAREAS`; sin borrado ni edicion del evento. UUID + secuencia de evento
identifica de forma unica cada efecto; sustituir JEFE produce dos eventos ligados
al mismo UUID en una transaccion. Una revision autorizada de datos historicos seria
otro evento, no UPDATE del anterior.

Guardar referencias estables, no reconstruir al autor pasado desde el JEFE actual.
Estado/rol anteriores documentan el hecho; cambios futuros del nombre de usuario
no alteran identidad. No copiar datos personales innecesarios.
Este historial prueba vigencia del dominio, no sustituye al servicio de auditoria
transversal. F16-G02 gobierna su proyeccion central.

## ControlOrganizacionEmpresa (coordinacion tecnica propuesta)

Una fila por Empresa, propia de organizacion en `default`: empresa_id unico, version
y metadata de coordinacion estrictamente necesaria. Es un fence para mutaciones y
consultas de elegibilidad, no otro sistema de permisos. T177 implementa el fence
en su alcance historico sobre `default`; no protege por si solo escritores MySQL.
Su compatibilidad con el catalogo en `BASE_TAREAS` requiere T217/G01/G07.
Creacion inicial serializada; no admitir ausencia del fence como "sin bloqueo".

La revision de `ControlOrganizacionEmpresa` no es por si sola un ledger de
operaciones idempotentes. Una operación departamental reiniciable necesita poder
resolver durablemente UUID, Departamento, actor, motivo, fase técnica y resultado
sin convertir `Departamento.activo` en un nuevo lifecycle de negocio. La fase
"preparada" no significa Departamento desactivado; la finalizacion cambia
`activo=False` solo tras comprobar los bloqueos. Ver protocolo en consistencia.
Si el replay no puede apoyarse en un mecanismo público ya autorizado, cualquier
registro/esquema adicional requiere autorización separada.

## RegularizacionOperacion / RegularizacionDetalle (nuevas, tareas/BASE_TAREAS)

| Entidad | Campos conceptuales e invariantes |
|---|---|
| Operacion | UUID unico; empresa_id; actor_id; origen_id; reemplazante_id; rol; motivo; manifiesto ordenado de IDs; huella del contenido/backend; fecha commit; resultado confirmado |
| Detalle | operacion_id FK interna; tarea_id FK interna; rol; identidad origen/destino; cambio antes/despues; fecha; referencia al ledger de responsable si aplica |

Unico `(operacion_id, tarea_id, rol)`; lote con una Empresa/un rol. IDs de usuario/
Empresa son referencias externas, no FKs remotas. Detalles, cambios y confirmacion
de operacion se guardan en la MISMA transaccion operacional. Fallo antes de commit
no deja detalles de exito. Se puede persistir una reserva tecnica de operacion
antes, pero no confundirla con aplicacion parcial ni notificarla.

No reutilizar el ledger de eliminacion/restauracion para regularizaciones:
sus invariantes y manifiestos tienen otra semantica. Reutilizar patrones de UUID,
fingerprint y replay, no tablas ajenas al dominio.

La sustitucion explicita de un participante puede retirar su vinculo operacional
segun FR-D15, pero primero conserva el hecho anterior en Detalle dentro de la misma
transaccion. La perdida de membresia por si sola nunca ejecuta esa retirada.
No reasignar comentarios, documentos, lecturas ni eventos al reemplazante.

## Compatibilidad y evolucion

- No crear membresias desde tareas historicas, roles VICMEAS, creador o responsable.
- Tareas sin ambito permanecen sin ambito; Opcion B tambien se aplica a ellas.
- No borrar maestros ni historia; admin de nuevas entidades debe ser read-only
  o canalizar mutaciones por el servicio protegido, nunca `save()` directo que
  evada motivo, locks o permisos.
- Cualquier herramienta de migracion de maestros se alojaria en `tareas/` y
  consumiria exportacion publica autorizada; no modifica/migra automaticamente
  modelos fuente de otros owners. El schema, DDL y corte requieren autorizacion y
  gates G17-G19. Nada de DDL ni migraciones en esta entrega.
- Para BASE_TAREAS remoto, extension SQL/versionado/preflight propios y paridad
  con Django; no ejecutar `migrate` implicitamente contra default.
- Constraints no soportados por un motor antiguo no se presumen efectivos.
  F16-G01/G06 exigen alternativa equivalente certificada o bloqueo controlado,
  no degradacion silenciosa.
