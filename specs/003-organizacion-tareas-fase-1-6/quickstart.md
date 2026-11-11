# Validacion prevista Fase 1.6

**NO EJECUTADA en la consolidacion documental.** No ejecutar ahora tests, migraciones,
servidores, requests a entornos con datos ni comandos que inicialicen bases.

## Rectificación SQL — preflight futuro

La certificación futura debe ejecutarse contra una instancia MySQL aislada con el
rol configurable `BASE_TAREAS`, nunca contra `default`. Antes de habilitar CRUD se
verificará DDL versionado e idempotente, tablas InnoDB, PK preservadas, índices y
unicidades (RUT global; Empresa+código), `source`/`activo` y timestamps, ausencia
de FK/JOIN cross-database, permisos ICMEAS, Empresa activa, locks y rollback
transaccional. El dry-run reconciliará conteos, IDs, códigos y referencias
históricas; cualquier discrepancia bloquea el corte. Se probarán baja/reactivación,
protección ERP, replay idempotente y fallos entre `BASE_TAREAS` y `default` sin
afirmar 2PC. No se ejecuta nada de esto en esta rectificación documental.

## Prerrequisitos para una futura ejecucion autorizada

Esta guia complementa, no sustituye, el
[quickstart maestro](../001-tareas-internas/quickstart.md).
La [matriz de sincronizacion](synchronization.md) separa la evidencia historica
T170/T172-T175 de la certificacion de la arquitectura C. Los 42 escenarios de
aceptacion integral incluyen los nuevos maestros y sus gates. Tests en SQLite
temporal no certifican el rol MySQL `BASE_TAREAS`.

Implementacion de las tareas correspondientes, capacidad de auditoria organizacional,
schema en bases temporales, catalogos i18n autorizados y gates de concurrencia.
Fixtures sinteticas: Empresas A/B; dos Departamentos activos y uno inactivo en A,
uno en B; Local A; usuarios activos/inactivos con acceso y permisos controlados;
tareas LOCAL/DEPARTAMENTO/sin ambito, borrador/abiertas/cerradas/anuladas/eliminadas,
arbol padre-hija-nieta. No copiar datos productivos.

Separar escenarios de dominio con mocks de pruebas de exclusion con conexiones
reales independientes. MySQL legacy y SMTP externos mockeados salvo autorizacion
expresa de un backend temporal seguro. Registrar motor/version/capacidad real;
SQLite secuencial no certifica PostgreSQL/MySQL ni locks entre procesos.

## Escenarios de aceptacion (Given / When / Then condensados)

| ID | Preparacion y accion | Resultado verificable |
|---|---|---|
| F16-AC01 | Usuario activo con acceso A, membresia efectiva y permiso/rol; opera tarea A | Accion permitida solo si estado/reglas existentes permiten; no nuevos permisos |
| F16-AC02 | Mismo usuario sin membresias; intenta gestion y luego lectura autorizada | Gestion rechazada; participaciones/historia intactas y lectura permitida |
| F16-AC03 | Usuario en dos Departamentos A; se suspende uno | Conserva elegibilidad por el otro; no se reasignan tareas |
| F16-AC04 | Usuario tiene membresia solo en B, intenta tarea A; luego obtiene membresias A/B | B no habilita A; permisos y operaciones permanecen aislados por sesion |
| F16-AC05 | Unica membresia SUSPENDIDA, BAJA o Departamento inactivo | No efectiva; una fila historica no basta; historial aun consultable con permiso |
| F16-AC06 | Recupera membresia y tiene o no los demas requisitos | Facultad vuelve solo cuando todos cumplen; no revierte sustituciones previas; evento registrado |
| F16-AC07 | Designar JEFE con anterior activo: sin resolucion/motivo y con cada opcion valida | Primer intento falla; SUPERVISOR/STAFF/BAJA explicitos generan dos eventos en una transaccion, sin roles de tareas cambiados |
| F16-AC08 | Dos conexiones designan JEFE simultaneamente en Departamento sin JEFE | Como maximo uno ACTIVA; conflicto controlado en perdedor; nunca dos ni historia parcial |
| F16-AC09 | Tarea LOCAL A, usuario con membresia en cualquier Departamento A | Puede operar con demas condiciones; no se inventa relacion Local-Departamento |
| F16-AC10 | Tarea Departamento A1, usuario miembro solo de A2 | Puede operar por Opcion B; no se exige A1 |
| F16-AC11 | Tarea historica sin ambito A | Opcion B exigida; no se agrega ambito/backfill |
| F16-AC12 | Trasladar usuario A1->A2, con tareas abiertas y roles diversos | Lista de revision, membresias auditadas; responsable/participantes/roles de tareas no cambian automaticamente |
| F16-AC13 | Baja Departamento con tareas abiertas o anuladas bloqueantes | Preview las muestra; no finaliza hasta traslado/resolucion autorizada; no evadir lifecycle |
| F16-AC14 | Baja Departamento sin tareas abiertas bajo lock, concurrente con nueva asociacion | Baja solo tras chequeo final protegido; nueva asociacion no puede dejar tarea abierta en Departamento ya inactivo |
| F16-AC15 | Baja/transferencias con tarea cerrada y arbol con distintos Departamentos | Cerrada conserva ambito; Empresa, parentesco, XOR y reglas de rama intactos |
| F16-AC16 | Lote valido con dos o mas tareas, mismo origen/destino/rol/motivo | Todas cambian juntas, detalles por tarea y UUID comun; nada fuera de seleccion cambia |
| F16-AC17 | Una tarea del lote cerrada, eliminada, ajena, anulada o sin rol de origen | Todo rechazado; cero cambios en las demas y cero eventos de exito |
| F16-AC18 | Reemplazante inactivo/sin acceso/sin membresia; origen pierde esos requisitos | Reemplazante bloquea; origen inelegible no bloquea sustitucion autorizada por ese solo hecho |
| F16-AC19 | Revocar permiso tras preview, antes de confirmar | Confirmacion 403/denegacion oficial segun superficie; ninguna mutacion |
| F16-AC20 | Suspender ultima membresia mientras lote confirma en otra base | Serializacion conforme contrato: cambio primero invalida preview o espera hasta commit del lote; topologia sin garantia queda bloqueada |
| F16-AC21 | Inyectar error al mutar primera, intermedia y ultima tarea antes del commit | Rollback completo en cada caso, incluyendo ledger nuevo/detalles y cursores nuevos |
| F16-AC22 | Inyectar error al guardar auditoria funcional individual dentro del lote | Ningun cambio de tareas confirmado; no "exito parcial" |
| F16-AC23 | Lote confirmado, fallo posterior al proyectar auditoria central | Datos/evidencia local persisten, proyeccion pendiente visible y reconciliable sin repetir sustitucion |
| F16-AC24 | Instrumentar callbacks/canales con commit y rollback | Cero envios antes del commit o en rollback; tras exito, destinatarios exactos sin duplicados |
| F16-AC25 | Error de email tras commit y tarea CRITICA | Operacion aplicada; error sanitizado; usa cuenta sistema Empresa/purpose, no SMTP actor |
| F16-AC26 | Cambiar motivo/seleccion/actor/Empresa/rol/backend/revision tras preview | Confirmacion obsoleta o manipulada rechazada; preview nuevo necesario; GET/preview sin escrituras |
| F16-AC27 | Perder respuesta de commit, reenviar mismo UUID y despues payload distinto | Resolver resultado sin aplicar dos veces; replay identico sin reemitir todo; payload distinto en conflicto |
| F16-AC28 | Perder membresia de creador/responsable/participante/Hito/MiniTarea | Solo gestion suspendida; participacion historica y lectura autorizada no desaparecen; no ampliar privilegios |
| F16-AC29 | JEFE sin M/C/E intenta administrar; usuario con V y sin I accede | Rol organizacional no autoriza; menu no filtra por I y acceso denegado usa 403 oficial |
| F16-AC30 | Resolver existente `tareas` para BASE_TAREAS falla o apunta a un backend invalido | Error controlado sin fallback ni resolver alternativo; cero escrituras en default; sin FK/JOIN remoto |
| F16-AC31 | Reactivar Departamento con conflictos JEFE y membresias SUSPENDIDA/BAJA | Conflicto impide activacion; no levanta decisiones independientes ni restaura participantes sustituidos |
| F16-AC32 | Confirmar transferencias y fallar la baja del maestro en BASE_TAREAS | Departamento no se declara inactivo; transferencias confirmadas conservadas/auditadas; reintento revisa sin duplicar |
| F16-AC33 | Lote con varios roles, origen=destino, duplicados, motivo vacio o rol G03 no aprobado | Bloqueo explicito del lote; no degradar roles, fusionar filas ni escribir autoria historica |
| F16-AC34 | Sustitucion individual, lecturas previas y sustitucion masiva equivalente | Mismas validaciones/motivo, cursores existentes intactos, historial saliente preservado, auditoria individual |
| F16-AC35 | Arranque con usuarios legacy sin membresia, antes/despues de altas autorizadas | Inventario previo; sin alta inferida desde permisos/tareas; gate solo se activa con preparacion aprobada |
| F16-AC36 | Abrir maestro/preview/errores en ES/EN, acceder sin permiso y operar formularios | Layout/modal propios, sin claves crudas, CSRF efectivo, vendor intacto, no confirm() ni nuevas dependencias |
| F16-AC37 | Consultar/crear/editar Proveedor desde Empresas A y B con RUT normalizado | Solo tras G17 y corte autorizado: catalogo global unico en BASE_TAREAS; writer previo desactivado por via autorizada; antes, writer Tareas bloqueado; sin modelo espejo ni FK/filtro Empresa; una identidad VICMEAS |
| F16-AC38 | Crear/editar Local source=LOCAL y modificar manualmente source=ERP | Solo tras G18/corte: aislamiento por Empresa; ERP rechazado; LOCAL conserva codigo/legacy_code/origen/ID; ICMEAS por accion; baja/reactivacion no se expone hasta T227; sin dual writer |
| F16-AC39 | Crear/editar Departamento y solicitar cambio de codigo/Empresa/source/activo | Solo tras G19: codigo, Empresa y source inmutables; solo nombre editable; ICMEAS por accion; sin ORM/modelo espejo; baja/reactivacion solo T183 tras T201/G07; sin dual writer |
| F16-AC40 | Resolver `BASE_TAREAS` desde `tareas` con config invalida o alias variable | Reutiliza resolver existente; no alias fijo, resolver por owner ni fallback a default; error controlado y sin writer alternativo |
| F16-AC41 | Transicionar datos maestros usando APIs publicas y referencias de Tareas/Reuniones/Cotizaciones | PKs/IDs estables; sin lectura ORM privada, FK fisica cross-database, modelo espejo ni dos writers activos; bloqueado si no hay export/corte publico autorizado |
| F16-AC42 | Confirmar una mutacion maestra, perder respuesta y fallar proyeccion central | Sin ledger/outbox seleccionado por anticipado; hasta tener contrato durable autorizado no se habilita el writer; una vez resuelto el gate, replay/conflicto y reconciliacion no duplican efectos |

F16-AC06/12/28 prueban efectos de dominio; la audiencia/canal completos de eventos
organizacionales se verifican solo al cerrar F16-G04, no se inventan en fixtures.
F16-AC20 incluye perdida de conexion del fence; si no se demuestra exclusion,
el resultado correcto de disponibilidad es bloqueo de la ejecucion masiva, no
declarar superada la prueba con una doble lectura.

## Comandos futuros, no ejecutados ahora

Solo despues de autorizacion, implementacion y preparacion aislada:

```powershell
python manage.py test organizacion.tests tareas.tests.test_organizational_eligibility tareas.tests.test_organizational_regularization tareas.tests.test_organizational_regularization_views --settings=AppDocs.settings_test
python manage.py check --settings=AppDocs.settings_test
```

Los modulos nuevos de ese comando se crean en tasks; hoy no se presume que existan.
La configuracion test debe revisarse antes de ejecutar para garantizar bases
temporales. No agregar `--keepdb` contra una base desconocida ni hacer conexiones
reales por defaults. Regresion posterior focal: assignment/participant storage,
lifecycle/hierarchy, comentarios/lecturas, hitos/MiniTareas, notificaciones y L4/L5
solo en los puntos de contacto, sin ampliar a una auditoria general.

## Evidencia a conservar en la futura validacion

Para cada AC: backend/version, fixture sintetica, resultado esperado/obtenido,
filas antes/despues por owner, eventos/notificaciones y ausencia cross-company.
Para concurrencia: dos conexiones/procesos, barreras reproducibles, orden de locks,
timeout, commit/rollback y comportamiento ante perdida de conexion.
Separar PASS, FAIL e INCONCLUSIVE. Un mock verde no cierra un gate fisico.

Para rollout: inventario por Empresa de usuarios sin membresia, aprobacion de altas,
schema y capabilities, activacion controlada, responsable de reconciliacion y
restauracion del servicio sin borrar historial ni deshacer reasignaciones aprobadas.
No ejecutar ese inventario contra datos reales en esta entrega.

## Validación de CRUD e idempotencia — 2026-11-10

Comandos focalizados ejecutados en el entorno local:

```powershell
.\.venv\Scripts\python.exe manage.py test --settings=AppDocs.settings_test tareas.tests.test_department_views tareas.tests.test_master_catalog_services tareas.tests.test_master_operation_service tareas.tests.test_master_operation_store tareas.tests.test_task_mutation_locks
.\.venv\Scripts\python.exe manage.py check --settings=AppDocs.settings_test
node --check tareas\static\tareas\js\master_departments.js
```

Resultado: 46 pruebas PASS; `check` PASS con el warning preexistente `ckeditor.W001`;
compilación Python y sintaxis JavaScript PASS. Las pruebas Django usaron una base
temporal que se eliminó al terminar.

No ejecutar `RUN_TAREAS_MYSQL_TESTS=1` sin autorización específica y verificación
operativa de `SELECT DATABASE() = 'tareas'`. Esta intervención no aplicó DDL ni
DML persistente, no ejecutó la reconciliación real y no certificó visualmente las
pantallas en navegador. El comando
`py manage.py reconcile_master_catalog_audit --limit 100` está implementado para
una ejecución manual autorizada; hace escrituras de estado/proyección y debe
usarse solo después de cerrar G02.

El listado y alta/edición de Departamentos existen parcialmente en Tareas. La
navegación VICMEAS y las claves de traducción faltantes siguen pendientes; las
interfaces HTTP/UI de Proveedores y Locales no se habilitan hasta resolver G05.
