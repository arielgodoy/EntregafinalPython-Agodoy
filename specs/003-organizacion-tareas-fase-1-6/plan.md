# Plan tecnico: Fase 1.6

**Rama real**: `main` | **Fecha**: 2026-10-30 | **Spec**: [spec.md](spec.md).
**Estado**: preparado para revision e implementacion parcial condicionada;
ninguna tarea de codigo autorizada por esta entrega.

## Resumen

Extender organizacion existente con membresias/historia y API publica de dominio.
Tareas consume esa API para Opcion B y coordina revision, regularizacion y baja de
Departamentos sin que organizacion importe tareas. Reutilizar adapters/locks,
VICMEAS, auditoria y notificaciones vigentes; no agregar infraestructura paralela.

## Contexto tecnico

- Python/Django existentes (documentacion vigente comprueba Django 5.1.3 y Python
  3.11.4 local; no se ejecuta interpreter ni se infiere version productiva).
- Aplicacion web Django modular; templates server-side, Bootstrap, vanilla JS.
- Organizacion/SYSTEM en default; tareas en BASE_TAREAS configurable Django/MySQL.
  PostgreSQL/SQLite se evaluan segun alias desplegado, no se presume capacidad
  transaccional/locking de motores legacy.
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
| III/VII: ownership | Conforme documental: escritura solo specs; futura implementacion por owner y tareas separadas para externos |
| Connection Roles | Conforme: resolver privado de tareas; organizacion no es router compartido; ids canónicos sin copia |
| IV: vendor | Conforme: sin cambios ni plan de uso de app.js |
| V-VI: Empresa/VICMEAS | Conforme: sesion, APIs oficiales, identidad madre y capacidades existentes; no permisos por rol organizacional |
| VIII: cambios focales | Conforme: no renombrados de dominio ni estados nuevos |
| IX: validacion | Conforme a excepcion documental expresa: diff/enlaces/trazabilidad; pruebas solo planificadas |
| X-XI: que/como/trazabilidad | Spec separada del diseno; matriz completa y tareas con aceptacion |
| Capacidad externa de auditoria | CONDICIONAL F16-G02: no generar reemplazo local ni afirmar capacidad inexistente |
| Concurrencia multi-base | CONDICIONAL F16-G01/G07: protocolo propuesto, requiere prueba antes de habilitar |
| Precision funcional | BLOQUEOS ACOTADOS F16-G03/G04; no ocultarlos ni inventar reglas |

No hay exencion concedida para violar la constitucion. Los gates condicionales
impiden sus bloques de implementacion/habilitacion; no invalidan la documentacion
ni impiden trabajar en persistencia/consultas independientes autorizadas.

## Artefactos y estructura

Este directorio contiene spec, research, data-model, plan, tasks, quickstart,
traceability y contracts de organizacion, tareas y consistencia.
No se mueve ni reestructura `specs/001-tareas-internas/`.

Rutas de implementacion **previstas**, no creadas por esta entrega:

- `organizacion/models.py`, migraciones nuevas, `admin.py`, pruebas propias;
  nuevos servicios de membresias/coordinacion/historia en `organizacion/services/`.
- `tareas/services/authorization.py`, `participant_storage.py`, storages por
  familia y servicios nuevos de elegibilidad/regularizacion/afectaciones.
- `tareas/models.py`, migraciones y SQL operacional incrementales propios;
  views/forms/urls/templates/static propios para la superficie aprobada.
- Externos solo mediante tareas separadas/autorizadas: auditoria, navegacion,
  registro global o catalogos i18n cuando realmente sean necesarios.

La infraestructura central no se modifica "porque lo requiere el plan".

## Etapas y orden real

La maestra [reconoce FR-P06](../001-tareas-internas/spec.md) y mantiene su
[plan general](../001-tareas-internas/plan.md). Este plan es complementario,
no una nueva autorizacion de fases implementadas.

Orden conceptual solicitado para el desarrollo: persistencia -> servicios publicos
de membresias -> administracion -> elegibilidad -> suspension/recuperacion ->
regularizacion individual -> masiva -> baja departamental -> pruebas -> validacion.
**SYNC-C01**: T200 depende actualmente de T199, por lo que la secuencia tecnica
existente prepara el ejecutor masivo antes del individual. Se conserva esa
dependencia, los IDs y las 42 tareas por la prohibicion de eliminarlas en esta
sincronizacion. No afirmar que ese bloque satisface ya el orden solicitado:
su ajuste acotado queda pendiente de autorizacion, sin bloquear persistencia/
consultas. Detalle y criterio de salida en [synchronization.md](synchronization.md).

| Bloque | Objetivo | Tareas | Dependencias y salida |
|---|---|---:|---|
| Preparacion | Scope, capacidades y decisiones ausentes | 2 (T170-T171) | T170 habilita trabajo independiente; T171 bloquea solo G03/G04 |
| 1 / US1 | Persistencia, unicidad, historia, selectors, fence y tests organizacionales | 8 (T172-T179) | T170; mutaciones completas requieren G02; no exige UI de tareas |
| 2 / US2 | Maestro autorizado, JEFE, preparacion baja/reactivacion, UX | 7 (T180-T186) | Servicios US1; G05 para UI completa; finalizacion de baja depende T201 |
| 3 / US3 | Opcion B, inventario de operaciones, revision, suspension/recuperacion | 7 (T187-T193) | API US1; eventos organizacionales completos dependen T171 |
| 4 / US4 | Ledger, preview, individual/lote, baja coordinada, auditoria/notificacion | 12 (T194-T205) | Elegibilidad/fence; schema y G01/G07; roles G03 no habilitados hasta cierre |
| 5 / US5 | Aislamiento, concurrencia, historia, regresion y despliegue | 6 (T206-T211) | Bloques implementados y autorizaciones de entorno; no confundir mocks con certificacion |

Total **42 tareas**, todas pendientes. Tareas nuevas T170-T211, sin reutilizar
T001-T165 de la maestra ni IDs VICMEAS.

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

Primer bloque recomendado: T170 y T172-T175, bajo autorizacion futura exclusiva
de organizacion, preservando Local/Departamento. Probar schema/consultas sin activar
el gate de tareas ni modificar datos reales. Preparar G02 antes de habilitar cambios
organizacionales productivos.

Seguir con servicios/locks, superficie, integracion y lotes. No activar Opcion B
globalmente hasta tener inventario de usuarios sin membresia y alta explicita
autorizada; no inferir membresias ni eximir permanentemente datos legacy.
No se agrega un feature flag nuevo por suposicion: el despliegue debe definir una
activacion controlada con las herramientas existentes o autorizacion especifica.

Completar escenarios de [quickstart](quickstart.md) y pruebas por backend.
Un backend sin guarantee suficiente queda bloqueado explicitamente; no introducir
fallback a default ni fragmentar un lote. Cierre documental no implica cierre de
F16-G01 a G09 ni implementacion/produccion terminadas.

## Complejidad justificada

Historial de membresia y ledger de lote preservan hechos y reintentos, no son
auditoria transversal duplicada. Fence organizacional es coordinacion de dominio
para una exigencia de concurrencia concreta, no locks globales SYSTEM.
La alternativa mas simple (lectura doble y llamadas individuales) no cumple el
contrato. No se propone 2PC, broker, infraestructura nueva ni dependencia externa
sin demostrar necesidad y obtener autorizacion separada.
