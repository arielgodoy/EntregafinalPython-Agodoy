# Fase 1.6: organizacion e integracion con tareas

**Fecha**: 2026-10-30. **Estado**: consolidacion documental para revision; NO implementada.
**Rama inspeccionada**: `main`. **HEAD**: `196658dfb4d77b3942bde1603e1affa00fc112d2`.
**Fuente de decisiones**: prompt del propietario "Consolidacion y cierre de Fase 1.6",
compartido el 2026-10-30, especialmente secciones 3 a 10 y 13.

## Objetivo, alcance y precedencia

Completar el contrato de membresias departamentales y su consumo operativo por
`tareas`, sin duplicar maestros ni redisenar el dominio existente. Complementa
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

## Actores e historias

| Historia | Prioridad | Actor y resultado | Prueba independiente |
|---|---|---|---|
| US1 | P1 | Administrador autorizado mantiene membresias e historial en organizacion | Alta, suspension, baja, recuperacion y unicidad sin usar tareas |
| US2 | P1 | Administrador de la superficie aprobada gestiona departamentos y sustitucion de JEFE | Permisos, motivo y dos designaciones concurrentes |
| US3 | P1 | Usuario de tareas opera solo si es elegible, sin perder lectura historica autorizada | Opcion B en los tres ambitos y recuperacion sin reasignar |
| US4 | P1 | Gestor de tareas revisa afectaciones y sustituye participantes individualmente o en lote | Preview sin escritura; una tarea invalida revierte todo |
| US5 | P1 | Responsable de validacion demuestra aislamiento, paridad, concurrencia e historia | Matriz integrada en bases temporales, tras autorizacion |

JEFE/SUPERVISOR/STAFF son roles organizacionales. Creador, responsable lider,
supervisor, autorizador, participante e invitado/observador son roles funcionales
ya definidos por tareas. El permiso VICMEAS `supervisor` es una tercera dimension
distinta. Ninguna de estas dimensiones se convierte automaticamente en otra.

## Requisitos funcionales

### Organizacion y administracion

- **F16-FR01**: Empresa es el aislamiento superior; Local y Departamento pertenecen
  directamente a ella. Conservar PK, codigo unico por Empresa, source, timestamps,
  baja logica y `Local.legacy_code`; no agregar jerarquia Local -> Departamento.
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

- **F16-FR23**: Separar `default` (organizacion/SYSTEM) del storage configurable
  `BASE_TAREAS`. IDs/DTOs y consultas al propietario, no FKs fisicas cross-database,
  JOIN entre servidores, copias de maestros ni nuevo router/global storage.
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
F16-AC36. Cobertura requisito -> decision -> contrato -> tarea -> prueba:
[traceability.md](traceability.md).
