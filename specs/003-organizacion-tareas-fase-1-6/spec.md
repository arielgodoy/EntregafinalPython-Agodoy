# Fase 1.6: organizacion e integracion con tareas

**Fecha**: 2026-10-30. **Estado**: consolidacion documental para revision; NO implementada.
**Rama inspeccionada**: `main`. **HEAD**: `196658dfb4d77b3942bde1603e1affa00fc112d2`.
**Fuente de decisiones**: prompt del propietario "Consolidacion y cierre de Fase 1.6",
compartido el 2026-10-30, especialmente secciones 3 a 10 y 13.

## Objetivo, alcance y precedencia

Completar el contrato de membresias departamentales y su consumo operativo por
`tareas`, y formalizar la ubicacion autoritativa compartida de los maestros en
`BASE_TAREAS`, con toda nueva funcionalidad en `tareas`. Los modelos/servicios
existentes de `proveedores` y `organizacion` se preservan sin modificarlos ni
duplicarlos. Complementa
[SPEC MAESTRA](../001-tareas-internas/spec.md), especialmente FR-A03, FR-D05 a
FR-D17, FR-E01 a FR-E11, FR-K y T054; no reemplaza esos documentos.
Los identificadores `F16-FRxx` son nuevos y exclusivos de este complemento.

**Sincronizacion 2026-10-30**: FR-P06 de la maestra reconoce Opcion B y remite a
este contrato para su detalle. La maestra conserva roles, lifecycle, participacion,
jerarquia, evidencias y reglas generales; Fase 1.6 especializa membresias,
elegibilidad y regularizacion organizacional. El numero 003 no implica reemplazo
de 001. Ver [matriz de sincronizacion](synchronization.md) para relaciones
Complementa/Restringe/Depende de/No afecta y contradicciones pendientes.

Incluye membresias, historial, administracion autorizada, elegibilidad, efectos de
cambios organizacionales, revision de afectaciones y regularizacion individual/masiva.
Local y Departamento ya existen. No se crea una nueva app.

Fuera de alcance: ERP/sincronizacion, nuevas APIs externas, roles funcionales nuevos,
estados de tareas nuevos, aprobaciones/cierres/subtareas nuevos, autenticacion,
sesiones, VICMEAS, correo base, router, infraestructura o backfill automatico.
La presente entrega solo escribe documentacion dentro de `specs/`.

El contrato aprobado describe el resultado futuro; el codigo describe lo implementado.
Las diferencias se clasifican en [research.md](research.md), nunca se resuelven
declarando que una funcionalidad ausente ya existe.

## Addendum de autonomía de `tareas` — 2026-11-09

## Addendum de cierre postauditoría — 2026-11-10

La operación durable de los maestros distingue confirmación recuperable de
incertidumbre: solo `COMMITTED` con resultado válido puede proyectarse
automáticamente después de un commit incierto. `PENDING`, `UNKNOWN`, ausencia
de fila y evidencia contradictoria no autorizan replay ni rollback inferido.
La salida de reconciliación es administrativa y no fuerza estados.

El preflight de `BASE_TAREAS` incluye los dos manifiestos SQL versionados de
maestros y operaciones sin ejecutar DDL en esta entrega. Las traducciones
aprobadas y el bootstrap VICMEAS explícito fueron preparados; el bootstrap no
se ejecutó contra ninguna base real. G02, G05, G07, G17, G18 y G19 permanecen
abiertos.

**F16-FR34 — Autonomía de aplicación.** La aplicación `tareas` es la propietaria de la nueva gestión de Proveedores,
Locales y Departamentos para su dominio. Puede consumir interfaces públicas de
SYSTEM/CORE, pero no puede depender directamente de modelos, servicios,
formularios, vistas, migraciones ni tablas administradas por otra
`APPLICATION_APP`. Los modelos y servicios existentes de `proveedores` y
`organizacion` permanecen intactos y no se convierten en dependencias de
ejecución del target.

Los tres maestros se almacenan exclusivamente en el rol configurable
`BASE_TAREAS`. Los nombres físicos históricos de las tablas no implican
dependencia con sus aplicaciones originales. No se crean modelos ORM espejo,
migraciones Django, routers, resolvers alternativos ni una segunda fuente de
verdad. La transición de consumidores y el cierre de writers antiguos son
gates separados y no se consideran resueltos por la existencia del esquema SQL.

**F16-FR35 — Validación interna de RUT.** La validación de RUT será una capacidad interna de `tareas`, ubicada en
`tareas/utils/rut.py`, con limpieza, normalización, módulo 11, soporte de `K`,
DV `0`, valores vacíos según contrato y formato canónico. La validación del
servidor es obligatoria; `static/js/funciones.js` solo es una ayuda de interfaz.
No se importará `proveedores.services.rut` ni se copiará su algoritmo desde otra
`APPLICATION_APP`.

**F16-FR36 — Operación durable.** G02/T216 seleccionan un registro técnico de operaciones dentro de MySQL
`BASE_TAREAS`. El registro no es una segunda auditoría central: persiste UUID,
hash canónico, entidad, acción, Empresa, actor, resultado, estado de operación y
estado de proyección de auditoría. La mutación del maestro y el registro técnico
participan de la misma transacción InnoDB. La auditoría central continúa usando
exclusivamente `AuditoriaService.log_event_idempotent()`, después del commit y
con reconciliación de estados pendientes o inciertos.

La selección de este diseño no habilita todavía mutaciones productivas. G02,
G17, G18, G19, T224, T225 y T226 continúan siendo puertas de auditoría,
certificación, autorización, adaptación de callers, fuente única y corte.

## Actores e historias

| Historia | Prioridad | Actor y resultado | Prueba independiente |
|---|---|---|---|
| US1 | P1 | Administrador autorizado mantiene membresias e historial en organizacion | Alta, suspension, baja, recuperacion y unicidad sin usar tareas |
| US2 | P1 | Administrador de la superficie aprobada gestiona departamentos y sustitucion de JEFE | Permisos, motivo y dos designaciones concurrentes |
| US3 | P1 | Usuario de tareas opera solo si es elegible, sin perder lectura historica autorizada | Opcion B en los tres ambitos y recuperacion sin reasignar |
| US4 | P1 | Gestor de tareas revisa afectaciones y sustituye participantes individualmente o en lote | Preview sin escritura; una tarea invalida revierte todo |
| US5 | P1 | Responsable de validacion demuestra aislamiento, paridad, concurrencia e historia | Matriz integrada en bases temporales, tras autorizacion |
| US6 | P1 | Administradores mantienen Proveedores, Locales y Departamentos desde una pantalla por maestro dentro de `tareas` | Reglas de alcance, origen, permisos, referencias estables y almacenamiento objetivo en BASE_TAREAS; bloquear una operacion si falta API publica y no duplicar modelos/catalogos |

JEFE/SUPERVISOR/STAFF son roles organizacionales. Creador, responsable lider,
supervisor, autorizador, participante e invitado/observador son roles funcionales
ya definidos por tareas. El permiso VICMEAS `supervisor` es una tercera dimension
distinta. Ninguna de estas dimensiones se convierte automaticamente en otra.

## Requisitos funcionales

### Organizacion y administracion

- **F16-FR01**: Empresa es el aislamiento superior; Local y Departamento pertenecen
  directamente a ella. Conservar PK, codigo unico por Empresa, source, timestamps,
  baja logica y `Local.legacy_code`; no agregar jerarquia Local -> Departamento.
  Los catalogos viven en `BASE_TAREAS`; `empresa_id` es referencia estable a CORE,
  no FK fisica entre bases.
- **F16-FR02**: Un usuario puede tener membresias en varios departamentos y Empresas
  autorizadas, con un unico registro vigente/rol por Usuario + Empresa + Departamento.
  Acceso a una Empresa no concede acceso a otra.
- **F16-FR03**: Roles organizacionales cerrados: JEFE, SUPERVISOR, STAFF. Como maximo
  un JEFE activo por Departamento; multiples SUPERVISORES/STAFF. Cero JEFE o cero
  SUPERVISOR no produce advertencia automatica ni impide operar por si solo.
  Esto precisa FR-D06, no impone un JEFE obligatorio en todo Departamento.
- **F16-FR04**: Activar, suspender, dar de baja logicamente y recuperar membresias
  conserva historia inmutable de autor, fecha, motivo, operacion y valores anteriores/
  posteriores. No borrar registros para resolver conflictos.
- **F16-FR05**: Designar un nuevo JEFE cuando existe otro activo requiere resolver
  expresamente al anterior como SUPERVISOR, STAFF o baja de membresia, con justificacion,
  auditoria y transaccion unica en la base propietaria. Una carrera no puede dejar dos
  JEFES. No cambiar roles de tareas por este hecho.
- **F16-FR06**: La administracion usa VICMEAS y la identidad aprobada
  `Tareas - Maestro de departamentos`. No conceder administracion por ser JEFE o
  SUPERVISOR organizacional. Metadatos de permisos segun
  [contrato organizacional](contracts/organizacion.md); no inventar codigos ni
  presentar esa Vista como ya registrada.

### Opcion B y continuidad funcional

- **F16-FR07**: Para ejercer funciones operativas en cualquier tarea se exige al menos
  una membresia efectiva en un Departamento activo de la misma Empresa, sea la tarea
  de LOCAL, DEPARTAMENTO o sin ambito. No exigir el Departamento de la tarea.
- **F16-FR08**: Acumular usuario activo, acceso vigente a Empresa por el helper oficial,
  membresia efectiva, permisos VICMEAS aplicables, rol/participacion funcional y estado/
  restricciones de la operacion. Ningun requisito sustituye a otro ni crea bypass `S`.
- **F16-FR09**: La falta de membresia suspende facultades operativas, no borra
  participaciones ni bloquea lectura historica ya autorizada. No aplicar el gate al
  login, sesiones, administracion general de usuarios ni otras aplicaciones.
  No usar el gate de tareas para impedir al administrador autorizado crear la primera
  membresia en el maestro organizacional.
- **F16-FR10**: Trasladar a un usuario actualiza solo membresias segun la decision
  autorizada, conserva participaciones y genera lista de tareas abiertas a revisar.
  No reasignar automaticamente. Otra membresia efectiva permite seguir operando
  si se mantienen los demas requisitos.
- **F16-FR11**: Perder todas las membresias efectivas no elimina participaciones de
  tareas publicadas, ni responsables/supervisores, ni historia. Identificar afectaciones,
  suspender facultades dependientes y emitir los eventos de notificacion aplicables.
- **F16-FR12**: Recuperar una membresia efectiva reevalua automaticamente las demas
  condiciones y devuelve solo las facultades que aun correspondan. No restaura
  asignaciones sustituidas. Registrar y notificar al afectado conforme al contrato.

### Departamentos e historia

- **F16-FR13**: Desactivar un Departamento es una baja logica. Revisar todas sus tareas
  abiertas; trasladar las que correspondan a Departamentos activos de la misma Empresa.
  No finalizar la desactivacion con bloqueos pendientes. No modificar Empresa ni
  reinterpretar el ambito de tareas cerradas.
- **F16-FR14**: Mantener padre -> hija -> nieta, XOR Local/Departamento y reglas de
  anulación efectiva/eliminacion/restauracion existentes. No convertir ramas LOCAL
  ni sin ambito a DEPARTAMENTO para facilitar la baja. Una tarea bloqueada no puede
  ser trasladada evadiendo su lifecycle; obliga a resolver el bloqueo previamente.
- **F16-FR15**: Reactivar Departamento/membresia revalida Empresa, acceso, rol y
  conflictos de JEFE; conserva historia, no reactiva membresias dadas de baja o
  suspendidas por una decision independiente, ni participaciones sustituidas.
  Las membresias ACTIVA que solo eran inefectivas por Departamento inactivo se
  reevaluan sin crear altas ficticias.

### Regularizacion de tareas

- **F16-FR16**: Tareas conserva propiedad de participantes y sustituciones.
  Regularizacion individual exige actor autorizado, reemplazante elegible, motivo,
  auditoria y notificaciones. El participante saliente puede carecer de membresia/
  acceso/actividad; no exigirle elegibilidad para permitir su reemplazo.
- **F16-FR17**: Cada lote tiene una Empresa, un origen, un reemplazante distinto,
  un unico rol funcional, tareas expresamente seleccionadas y una justificacion
  unica no vacia. No mutar roles, hitos, MiniTareas o participaciones no seleccionados.
- **F16-FR18**: Preview de solo lectura con Empresa, origen/reemplazante, rol,
  IDs/correlativos, estados, validaciones por tarea, justificacion y bloqueos/
  advertencias. Cualquier bloqueo impide confirmar el lote completo.
- **F16-FR19**: Confirmacion explicita, protegida y ligada al actor/Empresa/contenido
  del preview. Revalidar en servidor permisos, membresias, tareas, roles, jerarquia y
  backend. Preview nunca es una autorizacion permanente.
- **F16-FR20**: Todas las modificaciones de tareas y su evidencia individual ocurren
  en una sola transaccion de BASE_TAREAS. Cualquier fallo previo al commit revierte
  todo el lote. Prohibido encadenar servicios que confirmen cada tarea por separado.
- **F16-FR21**: Cada tarea conserva origen, destino, rol, motivo, autor, fecha, Empresa
  y un identificador comun de operacion. Mantener identidad historica y lecturas;
  no sobrescribir autores pasados ni borrar historia para resolver duplicados.
- **F16-FR22**: Notificar solo despues del exito completo, deduplicando por evento,
  usuario y canal. Un rechazo/rollback nunca genera una notificacion de exito.
  Fallo de comunicacion posterior no convierte un commit confirmado en rollback.

### Contratos tecnicos y compatibilidad

- **F16-FR23**: La fuente autoritativa target de Proveedores, Locales y Departamentos
  es el rol configurable `BASE_TAREAS`, mediante tablas MySQL InnoDB creadas por
  DDL SQL versionado. Toda nueva superficie, servicio y codigo funcional se
  implementa dentro de `tareas`; no se usan modelos ORM, migraciones Django,
  imports privados, escrituras ORM cruzadas ni modelos/catalogos espejo. La falta
  de API owner no bloquea DDL/servicios SQL, pero bloquea transición, callers,
  writers antiguos y habilitación productiva. CORE conserva sus responsabilidades;
  no se mantienen dos fuentes autoritativas, FKs físicas ni JOINs entre bases.
  `BASE_TAREAS` no se presume alias Django fijo.
- **F16-FR24**: Proteger cambios concurrentes de membresia mientras se confirma el
  lote: no basta consultar dos veces. Cumplir
  [consistencia](contracts/consistencia.md), o bloquear el backend no certificado;
  no prometer atomicidad distribuida ni degradar a exitos parciales.
- **F16-FR25**: Separar historia organizacional, evidencia transaccional de tareas y
  auditoria central. Consumir interfaces publicas existentes; una capacidad ausente
  es dependencia explicita, no infraestructura paralela.
- **F16-FR26**: Conservar compatibilidad de datos existentes sin membresias inventadas,
  backfill automatico, borrado de participaciones ni cambios a tareas cerradas.
  Preparar asignaciones autorizadas antes de activar la exigencia operativa.
- **F16-FR27**: Errores sanitizados y controlados, sin secretos ni exito aparente ante
  indisponibilidad. Resolver resultado de commit incierto por ID de operacion antes
  de reintentar o notificar; no repetir una mutacion ya confirmada.
- **F16-FR28**: Consumir notificaciones in-app y correo de sistema por Empresa/
  `purpose="notifications"`; nunca SMTP personal para eventos automaticos.
  No cambiar servicios base ni la politica T054 de canales/destinatarios.
- **F16-FR29**: Reutilizar layouts, modal Bootstrap, CSRF, POST y fetch solo donde
  corresponda; no `confirm()` ni nueva UI framework. Textos con `data-key`/
  `message_key`. Claves faltantes se reportan, no se editan catalogos globales sin
  autorizacion. Visibilidad no depende de `ingresar`; el acceso sin permiso responde
  403 oficial, sin redisenar `ver` ni su materializacion.
- **F16-FR30**: Demostrar trazabilidad, aislamiento, paridad y regresiones con escenarios
  verificables. Esta entrega no ejecuta pruebas ni migra datos; todas las tareas de
  implementacion permanecen pendientes.
- **F16-FR31**: Proveedores es un catalogo global compartido entre Empresas, sin FK
  a Empresa. Conservar RUT normalizado y unicidad global. Una sola pantalla con CRUD
  por modales Bootstrap/AJAX, incluida baja logica/reactivacion, CSRF y respuestas
  controladas sobre SQL `BASE_TAREAS`; conservar la identidad VICMEAS existente
  `Proveedores - Maestro` y permisos ICMEAS segun accion. G17 solo bloquea corte
  y writer único mientras no se adapten callers y writers antiguos.
- **F16-FR32**: Locales se aislan por Empresa y conservan codigo, `legacy_code`,
  origen e identificadores en SQL `BASE_TAREAS`. Los registros `source=ERP` son protegidos contra edicion
  manual; los `source=LOCAL` admiten alta/edicion autorizadas. Una sola pantalla con
  listado/busqueda y modales/AJAX. Baja/reactivacion manual solo despues del contrato
  de integridad pendiente; no exponer esas acciones antes.   Una identidad VICMEAS y capacidades ICMEAS existentes se aplican por accion; V
  no sustituye autorizacion. G18 queda como gate de transición y callers antiguos.
- **F16-FR33**: Departamentos se aislan por Empresa; el codigo, Empresa y origen
  son inmutables despues del alta, y el nombre es editable. Baja/reactivacion solo
  mediante T183 y tras T201/G07; membresias y sustitucion de JEFE siguen T176/T182.
  Una sola pantalla SQL con modales/AJAX y la identidad VICMEAS
  `Tareas - Maestro de departamentos`; no crear una Vista por boton. Las capacidades
  ICMEAS existentes se aplican por accion; V no sustituye autorizacion. G19 bloquea
  solo integración de membresías/lifecycle y el corte hasta cerrar sus contratos.

## Excepciones, dependencias y aceptacion

No se amplian permisos para sustituir CREADOR, SUPERVISOR o AUTORIZADOR historicos
porque existan esos valores en el modelo. El alcance permitido y la dependencia
de decision se registran en [contrato de tareas](contracts/tareas.md).
Hitos/MiniTareas pueden aparecer en la revision, pero no se convierten en el rol
principal del lote ni cambian de propietario por inferencia.

Las precisiones funcionales no encontradas y los gates tecnicos figuran en
[research.md](research.md). Las partes independientes pueden implementarse una vez
autorizadas, sin presentar los bloques pendientes como cerrados.

Criterios verificables: [quickstart.md](quickstart.md), escenarios F16-AC01 a
F16-AC42. Cobertura requisito -> decision -> contrato -> tarea -> prueba:
[traceability.md](traceability.md).
