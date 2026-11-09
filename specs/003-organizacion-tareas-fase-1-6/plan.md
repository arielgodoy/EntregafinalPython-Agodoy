# Plan tecnico: Fase 1.6

**Rama real**: `main` | **Fecha**: 2026-10-30 | **Spec**: [spec.md](spec.md).
**Estado**: preparado para revision e implementacion parcial condicionada;
ninguna tarea de codigo autorizada por esta entrega.
**Actualizacion 2026-11-09**: rectificacion arquitectonica definitiva. Todo nuevo
codigo funcional y todo DDL versionado de Proveedores, Locales y Departamentos
reside en `tareas`; los tres maestros son tablas SQL MySQL del rol configurable
`BASE_TAREAS`. No se usan modelos ORM ni migraciones Django para estos maestros.
La ausencia de APIs owner ya no bloquea la creacion SQL, pero mantiene separados
los gates de transicion, preservacion de IDs, desactivacion de writers antiguos,
adaptacion de consumidores, auditoria y concurrencia.

## Resumen

Implementar en `tareas` las pantallas, servicios SQL y DDL versionado de los tres
maestros, con persistencia en el rol configurable `BASE_TAREAS`. Los modelos y
migraciones existentes de `proveedores` y `organizacion` no se modifican ni se
usan como esquema target. CORE, Empresa, Usuario, autenticacion/permisos y la
historia organizacional en `default` conservan sus responsabilidades. El target
SQL no es un modelo espejo: es la fuente autoritativa futura, con preservacion de
IDs y un corte controlado que debe cerrar los writers antiguos antes de habilitar
escrituras productivas.

## Contexto tecnico

- Python/Django existentes (documentacion vigente comprueba Django 5.1.3 y Python
  3.11.4 local; no se ejecuta interpreter ni se infiere version productiva).
- Aplicacion web Django modular; templates server-side, Bootstrap, vanilla JS.
- El objetivo de almacenamiento de los tres maestros es exclusivamente MySQL en el
  rol configurable `BASE_TAREAS`; el rol puede resolverse por la infraestructura
  existente y no es un alias fijo.
- El DDL se versiona mediante el mecanismo de `tareas/services/base_tareas_schema.py`
  y scripts SQL bajo `tareas/sql/`. No se generan modelos ORM, migraciones Django
  ni tablas equivalentes en `default` para estos maestros.
- Los modelos/servicios existentes de `proveedores` y `organizacion` permanecen
  intactos como fuentes históricas/callers durante la transición. La ausencia de
  una API pública owner no bloquea el DDL ni los servicios SQL de `tareas`, pero sí
  bloquea la transición y cualquier consumidor que todavía dependa de la fuente
  anterior hasta definir un corte autorizado.
- CORE, Empresa, Usuario, autenticacion/permisos y membresias/eventos/control
  organizacionales que permanezcan en `default` no se mueven por inferencia.
  Toda referencia entre esos stores es por ID/DTO, sin FK fisica ni JOIN remoto.
- PostgreSQL/SQLite se evaluan segun alias desplegado, no se presume capacidad
  transaccional/locking de motores legacy. El fence T177 de `default` no certifica
  escritores MySQL.
- Sin nuevas dependencias, cambios router/settings, APIs externas ni SMTP.
- Pruebas futuras con `AppDocs.settings_test`, bases temporales y conectores
  externos mockeados; concurrencia real solo en entorno aislado autorizado.
- No existe SLA numerico aprobado ni volumen maximo de lote aprobado. No inventar
  un limite funcional; medir tiempo/contencion con volumen representativo acordado.
  Timeouts deben devolver conflicto controlado, nunca commit por fragmentos.

## Constitution Check (antes y despues del diseno)

| Principio/gate | Evaluacion |
|---|---|
| I-II: arquitectura/contexto | Conforme: se conserva estado implementado y contratos; sin nueva auditoria general |
| III/VII: ownership | Conforme: DDL, servicios y UI de maestros quedan físicamente en tareas; proveedores/organizacion no se modifican; la transición requiere gates separados |
| Connection Roles | Conforme al contrato de `tareas`: reutilizar su resolver existente y APIs publicas SYSTEM; no crear resolvers/infraestructura por owner, credenciales duplicadas ni modificar router |
| IV: vendor | Conforme: sin cambios ni plan de uso de app.js |
| V-VI: Empresa/VICMEAS | Conforme: sesion, APIs oficiales, identidad madre y capacidades existentes; no permisos por rol organizacional |
| VIII: cambios focales | Conforme: no renombrados de dominio ni estados nuevos |
| IX: validacion | Conforme a excepcion documental expresa: diff/enlaces/trazabilidad; pruebas solo planificadas |
| X-XI: que/como/trazabilidad | Spec separada del diseno; matriz completa y tareas con aceptacion |
| Capacidad externa de auditoria | CONDICIONAL F16-G02: consumir auditoria central existente; bloquear habilitación si no cubre el writer SQL |
| Concurrencia multi-base | CONDICIONAL F16-G01/G07: protocolo propuesto, requiere prueba antes de habilitar |
| Precision funcional | BLOQUEOS ACOTADOS F16-G03/G04; no ocultarlos ni inventar reglas |

No hay exencion concedida para violar la constitucion. Los gates condicionales
impiden sus bloques de implementacion/habilitacion; no invalidan la documentacion
ni impiden trabajar en persistencia/consultas independientes autorizadas.

## Artefactos y estructura

Este directorio contiene spec, research, data-model, plan, tasks, quickstart,
traceability y contracts de organizacion, tareas y consistencia.
No se mueve ni reestructura `specs/001-tareas-internas/`.

Rutas de implementacion **previstas dentro de `tareas/`**, no creadas por esta entrega:

- `tareas/forms.py`, `views.py`, `urls.py`, templates y static propios para las
  pantallas y orquestacion de los maestros.
- `tareas/services/` y storage SQL propio para los maestros, sin modelos ORM:
  servicios parametrizados por `BASE_TAREAS`, validaciones de dominio, transacciones
  MySQL y DDL versionado. No crear auditoría, permisos, conexiones, locks ni una
  auditoría paralela que duplique SYSTEM; el registro técnico de operaciones
  aprobado por T216 pertenece al dominio SQL de `tareas`.
- Los modelos y servicios de `proveedores/` y `organizacion/` permanecen intactos.
  Los datos origen no se migran ni se desactivan en esta autorizacion documental.
- Menu e i18n globales requieren una autorizacion especifica G05 separada.

La infraestructura central no se modifica "porque lo requiere el plan".

### Autonomía de `tareas` y operación durable

El scope writable de esta iniciativa es `tareas/` y sus manifiestos SQL
autorizados para `BASE_TAREAS`. `tareas` solo consume APIs públicas de
SYSTEM/CORE; no importa ni modifica otras `APPLICATION_APPS`. La validación
canónica de RUT se implementará como utilidad Python interna en
`tareas/utils/rut.py`, sin depender de `proveedores/services/rut.py`.

La operación durable se implementará como registro técnico SQL dentro de
`BASE_TAREAS`, en la misma transacción InnoDB que la mutación del maestro. El
registro conservará UUID, hash de payload, actor, Empresa, entidad, acción,
resultado y estado de auditoría. La auditoría transversal seguirá siendo
responsabilidad de `AuditoriaService.log_event_idempotent()`; el registro técnico
solo permitirá replay y reconciliación. No se implementa 2PC ni se modifica
`auditoria`, `access_control`, `proveedores` u `organizacion`.

La existencia de esta decisión habilita el diseño y la implementación aislada,
pero no cierra los gates de transición, fuente única, adaptación de callers,
auditoría certificada ni writers productivos.

## Etapas y orden real

La maestra [reconoce FR-P06](../001-tareas-internas/spec.md) y mantiene su
[plan general](../001-tareas-internas/plan.md). Este plan es complementario,
no una nueva autorizacion de fases implementadas.

Orden conceptual solicitado para el desarrollo: persistencia -> servicios publicos
de membresias -> administracion -> elegibilidad -> suspension/recuperacion ->
regularizacion individual -> masiva -> baja departamental -> pruebas -> validacion.
**SYNC-C01**: T200 depende actualmente de T199, por lo que la secuencia tecnica
existente prepara el ejecutor masivo antes del individual. Se conserva esa
dependencia, los IDs/estados de las 43 tareas existentes y se agregan 15 tareas
US6; no se elimina ni renumera trabajo por esta actualizacion. No afirmar que ese
bloque satisface ya el orden solicitado:
su ajuste acotado queda pendiente de autorizacion, sin bloquear persistencia/
consultas. Detalle y criterio de salida en [synchronization.md](synchronization.md).

| Bloque | Objetivo | Tareas | Dependencias y salida |
|---|---|---:|---|
| Preparacion | Scope, capacidades y decisiones ausentes | 2 (T170-T171) | T170 habilita trabajo independiente; T171 bloquea solo G03/G04 |
| 1 / US1 | Persistencia, unicidad, historia, selectors, fence y tests organizacionales | 8 (T172-T179) | T170; mutaciones completas requieren G02; no exige UI de tareas |
| 2 / US2 | Maestro autorizado, JEFE, preparacion de Departamento y membresias, UX | 8 (T180,T212,T181-T186) | Tareas consume APIs publicas; T212/T182/T183 se bloquean si faltan; G05 para UI completa; baja depende T201/G07 |
| 3 / US3 | Opcion B, inventario de operaciones, revision, suspension/recuperacion | 7 (T187-T193) | API US1; eventos organizacionales completos dependen T171 |
| 4 / US4 | Ledger, preview, individual/lote, baja coordinada, auditoria/notificacion | 12 (T194-T205) | Elegibilidad/fence; schema y G01/G07; roles G03 no habilitados hasta cierre |
| 5 / US5 | Aislamiento, concurrencia, historia, regresion y despliegue | 6 (T206-T211) | Bloques implementados y autorizaciones de entorno; no confundir mocks con certificacion |
| 6 / US6 | DDL SQL, servicios, referencias, pantallas, transición y certificación de los tres maestros | 18 (T213-T230) | Nuevo código solo en tareas; DDL/servicios pueden avanzar sin APIs owner; habilitación/corte requiere G01/G02/G05/G06/G07/G17-G19/T201 |

Total **61 tareas**: 11 completadas (10 históricas más T216 documental) y 50 pendientes. El estado se
conserva en `tasks.md`; T170-T227 no reutiliza T001-T165 de la maestra ni IDs
VICMEAS. T176/T177 siguen completadas en su alcance historico sobre `default`,
pero no certifican la nueva topologia.

## Rectificación arquitectónica definitiva — 2026-11-09

La fuente autoritativa futura de Proveedores, Locales y Departamentos será el
esquema SQL MySQL de `BASE_TAREAS`. La ausencia de servicios públicos en los
owners anteriores no autoriza imports ORM, pero tampoco impide crear el esquema
ni sus servicios SQL dentro de `tareas`.

La implementación queda dividida en cinco capas:

1. DDL SQL versionado y preflight de esquema.
2. Servicios SQL de lectura/escritura, validación, transacción, concurrencia,
   baja lógica, reactivación e idempotencia.
3. Integración con resolver de conexión, ICMEAS/VICMEAS, auditoría y notificaciones.
4. Transición: inventario, preservación de IDs, adaptación de callers y
   deshabilitación autorizada de writers antiguos.
5. UI CRUD y certificación de consistencia/concurrencia.

Mientras no exista corte autorizado, el esquema y los servicios pueden diseñarse
y probarse en entornos aislados, pero no se habilita un segundo writer productivo.
No se declara resuelto G17, G18 ni G19 hasta cerrar sus criterios de aceptación
de transición y certificación.

El orden numerico no oculta dependencias: T184 prepara UI/protocolo de baja, pero
solo T201 puede finalizarla con la integracion de tareas. US2 no se declara completa
antes de T201. T171 puede seguir bloqueada mientras avanza US1; no se pide otra vez
aprobacion de Opcion B, roles organizacionales o todo-o-nada.

## Estrategia incremental y salida

Las dependencias protegidas se clasifican en
[synchronization.md](synchronization.md): interfaz existente, capacidad faltante,
autorizacion externa requerida y exclusion del scope de tareas. T170 identifica
la necesidad; no autoriza ejecutar cambios SYSTEM. Una decision funcional pendiente
(G03/G04) no equivale a una capacidad tecnica ausente (G02).

La cadena T170/T172-T175 y T176/T177 se conserva como evidencia historica del
diseno previo y de membresias en `default`; no es certificacion de maestros en
`BASE_TAREAS`. La transicion documental inicia con T213/T214 y el inventario de
APIs publicas. T212/T182/T183 y CRUD de Proveedores/Locales se detienen ante G17-G19;
no se sustituyen esas APIs con acceso privado desde `tareas`.

Seguir con servicios/locks, superficie, integracion y lotes. No activar Opcion B
globalmente hasta tener inventario de usuarios sin membresia y alta explicita
autorizada; no inferir membresias ni eximir permanentemente datos legacy.
No se agrega un feature flag nuevo por suposicion: el despliegue debe definir una
activacion controlada con las herramientas existentes o autorizacion especifica.

Completar escenarios F16-AC01 a F16-AC42 de [quickstart](quickstart.md) y pruebas
por owner/backend. Un resolver o backend no certificado queda bloqueado; no
introducir fallback a `default`, FK cross-database ni commits parciales. Cierre
documental no implica cierre de F16-G01 a G09 ni implementacion/produccion terminadas.

## Complejidad justificada

Historial de membresia y ledger de lote preservan hechos y reintentos, no son
auditoria transversal duplicada. Fence organizacional es coordinacion de dominio
para una exigencia de concurrencia concreta, no locks globales SYSTEM.
La alternativa mas simple (lectura doble y llamadas individuales) no cumple el
contrato. No se propone 2PC, broker, infraestructura nueva ni dependencia externa
sin demostrar necesidad y obtener autorizacion separada.
