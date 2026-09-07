# Feature Specification (SPEC MAESTRA): Tareas — App completa de gestión de tareas

**Feature Branch**: `001-tareas-internas`

**Created**: 2026-09-07

**Status**: Draft (Spec Maestra — dominio completo auditado)

**Input**: Dominio completo de `tareas` como app de gestión de tareas del sistema. Integra decisiones confirmadas de la iteración inicial y las decisiones de diseño funcional tomadas fuera del repositorio (22 grupos), sin perder comportamiento.

> **Alcance**: SPEC MAESTRA del dominio completo. La implementación se descompone en fases; la Fase 1 (borrador/publicada, ya implementada) sigue válida e integrada. LOCAL y PROVEEDOR legacy quedan como **`LEGACY API PENDIENTE`** (bloqueo explícito), sin cerrar contrato.

## Clarifications

### Session 2026-09-07

- Q: ¿Publicar con responsable desactivado/eliminado? → A: Bloquear la publicación e informar; el usuario debe asignar un responsable válido antes de publicar.
- Q: ¿Operaciones sobre una tarea ya publicada? → A: Edición libre de campos (manteniendo responsable válido); la tarea publicada no puede volver a borrador.

---

## Regla arquitectónica (vigente)

- Toda la lógica funcional nueva vive dentro de `tareas/` (app autocontenida; COPILOT/ARQUITECTURA_APPS.md).
- `tareas` REUTILIZA, no duplica: ICMEAS/access_control, sesión/usuario autenticado, seguridad, multiempresa, `notificaciones`, email (`acounts`/email_service).
- No se modifican otras apps ni archivos globales salvo integración técnica mínima con autorización expresa.
- Detención: si una necesidad no puede resolverse dentro de `tareas/`, se DETIENE y reporta (archivo, motivo, impacto, alternativa).

---

## A. Identidad, Correlativos y Contexto

- **FR-A01**: Todo borrador MUST tener correlativo de borrador tipo `A0000001`. Al publicar, el correlativo MUST convertirse a activo tipo `B0000001`. El borrador MUST transformarse, NO duplicarse.
- **FR-A02**: Un borrador MUST tener vida indefinida y ser visible inicialmente SOLO en el dashboard propio del creador.
- **FR-A03**: Toda tarea MUST pertenecer a una empresa (empresa activa al crearla) y MUST poder asociarse a local y a departamento/área.
- **FR-A04**: Una tarea MUST poder asociarse opcionalmente a un equipo/máquina/activo cuando corresponda.
- **FR-A05**: Toda tarea MUST registrar su creador (creada_por) automáticamente desde el usuario autenticado.
- **FR-A06**: El correlativo MUST ser único por empresa y legible.
- **FR-A07**: LOCAL es concepto legacy → **`LEGACY API PENDIENTE`**: no se define tabla/IDs/sincronización sin autorización y lectura del legacy.

**Key Entities — A**: Tarea (correlativo_borrador `A*`, correlativo_activo `B*`, empresa, local [LEGACY], departamento, equipo_activo [opcional], creada_por).

---

## B. Tipos y Clasificación

- **FR-B01**: La prioridad MUST ser SIMPLE, NORMAL, URGENTE o CRITICA; jerarquía CRITICA > URGENTE > NORMAL > SIMPLE; default NORMAL. NO existe prioridad "baja".
- **FR-B02**: La prioridad MUST poder cambiar dinámicamente durante la vida de la tarea.
- **FR-B03**: Una tarea MUST clasificarse como "trabajo en equipo" (múltiples participantes) o "tarea independiente por responsable".
- **FR-B04**: Las clasificaciones MUST ser utilizables como filtros en listados y dashboards.

**Key Entities — B**: Clasificación (prioridad, naturaleza_trabajo).

---

## C. Ciclo de Vida y Cierre

- **FR-C01**: Estados: borrador, publicación (transición), activa, gestión, 100% pendiente de aprobación, cierre aprobado, cierre rechazado, cerrada, cancelada/anulada, reactivada.
- **FR-C02**: Toda tarea nace como borrador (vida indefinida).
- **FR-C03**: Publicar exige responsable válido/activo, registra fecha de publicación, convierte correlativo A→B y es irreversible hacia borrador.
- **FR-C04**: El responsable puede llevar la tarea a 100%; entonces pasa a "en espera de aprobación de cierre".
- **FR-C05**: El creador o un perfil autorizado MUST aprobar el cierre.
- **FR-C06**: Si el cierre se rechaza, la tarea queda "cierre rechazado / vuelve a gestión" y MUST mantener el 100% aunque vuelva a gestión.
- **FR-C07**: MUST registrarse quién cerró/canceló y cuándo.
- **FR-C08**: Cada transición MUST registrar fecha y usuario (auditoría).

**Key Entities — C**: Estado, Transición (origen, destino, fecha, usuario), Cierre/Cancelación (por, fecha).

---

## D. Asignación, Responsables y Participantes

- **FR-D01**: La asignación base es tarea 1 a 1 (un responsable líder por tarea).
- **FR-D02**: Una tarea de "trabajo en equipo" MUST soportar múltiples participantes.
- **FR-D03**: Crear "tarea independiente por responsable" MUST clonar N tareas (una por responsable seleccionado).
- **FR-D04**: La asignación masiva MUST asignar a cada tarea un nombre propio (responsable) y una fecha común.
- **FR-D05**: Un usuario inactivo MUST NOT poder recibir ni publicar tareas.
- **FR-D06**: Cuando corresponda, MUST haber un jefe por departamento.
- **FR-D07**: Roles soportados: creador, responsable líder, supervisor, autorizador, participante, invitado/observador.
- **FR-D08**: MUST existir reasignación de responsable con registro (quién, cuándo).
- **FR-D09**: Permisos por rol integrados con ICMEAS (sin sistema paralelo).
- **FR-D10**: Confirmación de lectura para participantes/invitados cuando corresponda.

**Key Entities — D**: Asignación de rol, Reasignación, Confirmación de lectura.

---

## E. Jerarquía de Trabajo

- **FR-E01**: Una tarea MUST soportar padre → hijos → nietos, con máximo DOS niveles bajo el padre.
- **FR-E02**: Los descendientes MUST heredar las dimensiones base del padre, pero MUST poder cambiar el departamento.
- **FR-E03**: El padre MUST NOT cerrar mientras haya descendientes sin cerrar.
- **FR-E04**: MUST existir navegación vertical (padre ↔ descendientes).
- **FR-E05**: Anular un padre MUST anular hijos y nietos (cascada).
- **FR-E06**: Reactivar MUST restituir la estructura tal como estaba.
- **FR-E07**: Al reactivar, las fechas MUST reconfigurarse.
- **FR-E08**: Al anular/reactivar MUST notificarse a los participantes (ver K).
- **FR-E09**: MUST existir el concepto de subtarea y de mini-tarea (ver F).

**Key Entities — E**: Relación padre/hija (tarea_padre), Subtarea, Mini-tarea.

---

## F. Avance, Hitos y Mini-tareas

- **FR-F01**: Tarea simple con porcentaje de avance manual.
- **FR-F02**: Tarea ponderada: avance calculado por hitos.
- **FR-F03**: Cada hito MUST tener un peso; el avance ponderado MUST calcularse proporcionalmente.
- **FR-F04**: Agregar un nuevo hito MUST recalcular el avance (ej. conceptual: si se incorpora un nuevo 20%, el avance se redistribuye).
- **FR-F05**: Los hitos MUST mostrarse ordenados por fecha de creación; los hitos de la misma fecha se muestran juntos.
- **FR-F06**: La evidencia de cierre MUST ser configurable/requerida cuando corresponda.
- **FR-F07**: Las mini-tareas son ultra simples (checkbox hecho/no hecho), con UNA persona por mini-tarea, MUST NOT ponderar el avance y MUST impedir el cierre mientras estén pendientes.

**Key Entities — F**: Avance, Hito (peso, fecha_creacion), Evidencia, Mini-tarea (hecho/no hecho, persona).

---

## G. Fechas, Atrasos y Reprogramación

- **FR-G01**: El vencimiento MUST definirse por días desde la asignación.
- **FR-G02**: MUST calcularse días atrasados acumulados hasta el cierre.
- **FR-G03**: MUST soportar múltiples causas de atraso; la lista inicial incluye: imposibilidad técnica, atraso importación, permisos municipales, problemas de escrituras, causas internas, causas externas.
- **FR-G04**: La justificación MUST ser obligatoria para reprogramar.
- **FR-G05**: La reprogramación MUST ser trazable (registro de fecha anterior/nueva, justificación, usuario).

**Key Entities — G**: Fechas (asignación, vencimiento), Causa de atraso, Reprogramación.

---

## H. Documentos y Evidencias

- **FR-H01**: Tipos de documento predefinidos: Cotización, Fotografía, Informe, Orden de trabajo, Factura, Contrato, Plano, Certificado, Otro.
- **FR-H02**: Los documentos MUST soportar adjunto (archivo) o URL.
- **FR-H03**: Cada documento MUST registrar fecha de documento y fecha de vencimiento informativa.
- **FR-H04**: Sin control automático de vencimientos por ahora (vencimiento solo informativo; ver R).
- **FR-H05**: MUST existir evidencia de cierre.
- **FR-H06**: Los documentos MUST mantener historial.

**Key Entities — H**: Documento (tipo, archivo/url, fecha_documento, fecha_vencimiento), Evidencia de cierre, Historial.

---

## I. Cotizaciones

- **FR-I01**: Una tarea MUST poder requerir o no cotización; si la requiere, MUST existir un mínimo configurable por tarea (ejemplo posible: 3).
- **FR-I02**: MUST soportar un máximo sugerido de versiones por proveedor (según lo ya acordado).
- **FR-I03**: Las cotizaciones MUST organizarse por rondas; MUST existir histórico por ronda y MUST poder abrirse una nueva ronda.
- **FR-I04**: El mínimo de cotizaciones MUST poder cambiar en una nueva ronda.
- **FR-I05**: MUST existir una última cotización válida por proveedor.
- **FR-I06**: Estados de cotización por proveedor: "Participó cotizando" y "Proveedor seleccionado".
- **FR-I07**: El proveedor adjudicado MUST ser visible.
- **FR-I08**: El cierre MUST bloquearse si no se cumple el mínimo de cotizaciones cuando aplique.

**Key Entities — I**: Cotización (proveedor, ronda, versión, vigente, monto, estado), Adjudicación.

---

## J. Proveedores

- **FR-J01**: MUST existir un maestro de proveedores en Django.
- **FR-J02**: Evaluación manual 1–5 del proveedor: malo / deficiente / regular / normal / sobresaliente.
- **FR-J03**: Califica el responsable líder.
- **FR-J04**: MUST existir promedio global del proveedor.
- **FR-J05**: Vínculo con legacy mediante `rut_contable` → **`LEGACY API PENDIENTE`**: NO se define integración real (tabla/IDs/sincronización/contrato) sin revisar primero el legacy con el usuario.

**Key Entities — J**: Proveedor (datos maestros, rut_contable [LEGACY], evaluación 1–5, promedio global).

---

## K. Notificaciones y Email

- **FR-K01**: Notificación interna por: asignación, lectura, aceptación/rechazo (cuando aplique), comentarios, documentos, cambio de responsable, vencimientos, aprobaciones, rechazo de cierre, cierre, anulación, reactivación, cambios clave.
- **FR-K02**: Las tareas críticas MUST notificar por sistema Y por email.
- **FR-K03**: Las notificaciones MUST soportar leídas/no leídas.
- **FR-K04**: MUST reutilizar la infraestructura existente (`notificaciones`, email de `acounts`); MUST NOT crear un subsistema paralelo.

**Key Entities — K**: Notificación de tarea (tipo, leída/no leída), canal (sistema/email).

---

## L. Dashboards y KPI

- **FR-L01**: Dashboard Usuario: urgentes/por vencer arriba; acordeones por clasificación; tareas donde participa como Invitado; leído/no leído manual; vista Equipo para jefaturas; acumulación de trabajo.
- **FR-L02**: Dashboard Jefatura/General: tareas por responsable, atrasadas, sin movimiento, próximas a vencer, esperando aprobación, carga por persona, cumplimiento, tiempo promedio de cierre, detectar "sin gestión".
- **FR-L03**: Dimensiones con drill-down: General → Empresa → Local → Departamento → Usuario → Tarea; también por Proveedor.
- **FR-L04**: Los mismos KPI por dimensión.
- **FR-L05**: Presentación con DataTables, modal "Ver info de la tarea" y opción de abrir la tarea completa.
- **FR-L06**: Las dimensiones Local y Proveedor dependen de `LEGACY API PENDIENTE` (A y J).

**Key Entities — L**: Dashboard (dimensión), KPI, Drill-down.

---

## M. Reuniones de Revisión

- **FR-M01**: Debe existir un botón/acción "reunión de revisión".
- **FR-M02**: La reunión se convoca sobre un subconjunto homogéneo de tareas.
- **FR-M03**: Modalidad Zoom o presencial.
- **FR-M04**: Convocatoria por email.
- **FR-M05**: La reunión es una tarea planificada.
- **FR-M06**: La reunión tiene agenda por prioridades.
- **FR-M07**: El cierre de la reunión registra comentarios por tarea.

**Key Entities — M**: Reunión (modalidad, agenda, comentarios), Subconjunto de tareas.

---

## N. Origen, Derivación y Similitud

- **FR-N01**: Una tarea MUST poder provenir de otra (una sola tarea origen directa).
- **FR-N02**: El historial de origen MUST ser accesible en lectura.
- **FR-N03**: MUST NOT convertir una tarea antigua en la nueva: se crea una nueva y se referencia. Cadenas históricas permitidas.
- **FR-N04**: Al publicar, el sistema MUST advertir si parece un problema repetido con coincidencia aproximada desde el 80%.
- **FR-N05**: La evaluación de similitud MUST incluir también tareas cerradas.
- **FR-N06**: El usuario MUST confirmar "es el mismo problema nuevamente"; aun confirmando, la tarea es NUEVA.
- **FR-N07**: La nueva tarea MUST poder referenciar una o varias tareas antiguas si corresponde.
- **FR-N08**: Cambio de repuesto MUST NOT implicar automáticamente "mismo problema".

**Key Entities — N**: Origen/derivación, Relación de similitud, Cadena histórica, Umbral (80%).

---

## O. Equipos / Máquinas

- **FR-O01**: El código del equipo puede ser global.
- **FR-O02**: Local/departamento son características o ubicación del equipo.
- **FR-O03**: MUST permitir asignar herramienta/equipo incluso a una mantención.
- **FR-O04**: NO inventar integración legacy de equipos/activos (ver bloqueos).

**Key Entities — O**: Equipo/Máquina/Activo (código global, local, departamento).

---

## P. Seguridad, Multiempresa y Enlaces

- **FR-P01**: Toda operación MUST respetar empresa activa en sesión y aislamiento multiempresa (se mantiene FR-003 previo).
- **FR-P02**: Acceso controlado por ICMEAS (vista visible en menú, autorización al acceder, 403 con solicitud de acceso) — se mantiene FR-011 previo.
- **FR-P03**: Enlaces compartibles: enlace parametrizado a tarea/hito, solo para usuario autenticado del sistema, acceso en lectura cuando corresponda, registro de notificación/acceso, respetando ICMEAS y seguridad existente.
- **FR-P04**: Visibilidad según rol/participación del usuario.
- **FR-P05**: Sin usuarios externos por ahora (ver R).

**Key Entities — P**: (se apoya en access_control; enlace compartible parametrizado).

---

## Q. Reglas de Cierre (consolidación)

- **FR-Q01**: El cierre MUST exigir evidencia adjunta (cuando sea requerida, ver F06).
- **FR-Q02**: El cierre MUST estar bloqueado por mini-tareas pendientes y por descendientes sin cerrar.
- **FR-Q03**: Si la tarea requiere cotización, el cierre MUST exigir el mínimo configurable.
- **FR-Q04**: El cierre MUST requerir aprobación del creador o perfil autorizado.
- **FR-Q05**: Al cerrar una tarea con proveedor, el responsable líder MUST calificar al proveedor (1–5, ver J).
- **FR-Q06**: MUST registrarse quién cerró/canceló y cuándo.

**Key Entities — Q**: Regla de cierre, Evidencia, Cierre/Cancelación (por, fecha).

---

## R. Exclusiones Actuales

- **FR-R01**: Sin usuarios externos por ahora.
- **FR-R02**: Sin plantilla de hitos por ahora.
- **FR-R03**: Sin vencimiento automático de documentos (vencimiento informativo solamente).
- **FR-R04**: Sin prioridad "baja" (solo Simple/Normal/Urgente/Crítica).
- **FR-R05**: Integración real con legacy de LOCALES y PROVEEDORES fuera de alcance hasta revisión (`LEGACY API PENDIENTE`).
- **FR-R06**: Sin eliminación física de tareas (el ciclo usa cancelación/anulación).

---

## Requisitos previos integrados (iteración inicial, vigentes)

Mapeo de la Fase 1 (ya implementada) a los bloques:

- Crear con solo título, borrador indefinido → **FR-A02 / FR-C02**.
- Atributos base + creador → **FR-A05** + modelo.
- Empresa activa / aislamiento → **FR-P01**.
- Responsable opcional en borrador, obligatorio al publicar → **FR-C03 / FR-D05**.
- Publicación registra fecha, irreversible a borrador → **FR-C03**.
- Edición por formulario sin estado → **FR-C03** (estado no editable por formulario).
- Listar borrador/publicada → **FR-C01**.
- ICMEAS + menú + 403 → **FR-P02**.
- Eliminación fuera de alcance → **FR-R06**.

## Success Criteria

- **SC-001**: Crear borrador con solo título en < 1 minuto (vigente).
- **SC-002**: 100% de publicaciones sin responsable válido rechazadas con mensaje claro (vigente).
- **SC-003**: 100% de aislamiento por empresa activa (vigente).
- **SC-004**: Ciclo crear → editar → publicar en < 3 minutos (vigente).
- **SC-005**: Borradores sin límite de tiempo (vigente).
- **SC-006**: 100% de cierres bloqueados cuando falta evidencia, hay mini-tareas/descendientes pendientes o faltan cotizaciones mínimas.
- **SC-007**: 100% de notificaciones críticas por sistema y email.
- **SC-008**: Dashboards muestran los mismos KPI en todas las dimensiones con drill-down.
- **SC-009**: Advertencia de similitud al publicar cuando coincidencia ≥ 80%.
- **SC-010**: Correlativo borrador `A*` se convierte a activo `B*` al publicar, sin duplicar la tarea.

## Assumptions

- Se reutilizan usuarios, empresa activa, ICMEAS, notificaciones y email existentes; sin sistemas paralelos.
- Prioridad: SIMPLE/NORMAL/URGENTE/CRITICA, default NORMAL (sin "baja").
- Fechas: UTC almacenamiento, presentación en zona local configurada.
- App `tareas` autocontenida; integración externa mínima requiere autorización expresa.
- Implementación por fases; Fase 1 (borrador/publicada, aislamiento, ICMEAS) ya implementada y válida.

---

## BLOQUEOS LEGACY (explícitos, no supuestos)

- **LOCAL (A/G/L)**: **`LEGACY API PENDIENTE`**. No se define modelo, tabla, endpoint, ID ni sincronización. Se necesita leer del legacy: estructura/tabla de locales, clave de vínculo, disponibilidad por empresa. DETENIDO hasta autorización y revisión del legacy con el usuario.
- **PROVEEDOR (I/J/L)**: **`LEGACY API PENDIENTE`**. No se define tabla, API, `rut_contable`, sincronización ni contrato definitivo. Se necesita leer del legacy: maestro de proveedores, significado/unicidad de `rut_contable`, sincronización. DETENIDO hasta autorización y revisión del legacy con el usuario.
- **EQUIPOS/ACTIVOS (O)**: NO se inventa integración legacy de equipos/máquinas; solo se modela el concepto (código global, local, departamento) dentro de `tareas` sin vínculo legacy.

---

## PUNTOS NO RESUELTOS / PENDIENTES

- **P1 (LEGACY)**: Contrato de Local (A) — campos, IDs, sincronización. `LEGACY API PENDIENTE`.
- **P2 (LEGACY)**: Contrato de Proveedor (J) — `rut_contable`, datos maestros, sincronización. `LEGACY API PENDIENTE`.
- **P3**: Mínimo configurable de cotizaciones (valor por defecto; ejemplo sugerido 3) y máximo sugerido de versiones por proveedor (I) — confirmar valores.
- **P4**: Pesos/reglas exactas de hitos y criterio de "proporcional" en el recálculo (F04) — detallar en planificación.
- **P5**: Máquina de estados exacta de C (transiciones permitidas entre cada par de estados) — detallar en planificación.
- **P6**: Lista cerrada de KPI por dimensión (L) — definir métricas exactas.
- **P7**: Reglas de cascada en anulación/reactivación de jerarquía (E05–E07) — confirmar comportamiento de fechas al reactivar.
- **P8**: Umbral de similitud: se usa 80% (N04) como punto de partida acordado; confirmar si es configurable.

## Tabla de cobertura por bloque

| Bloque | Nombre | FR | Prioridad dominante | Estado |
|---|---|---|---|---|
| A | Identidad, Correlativos y Contexto | FR-A01…A07 | P1 | Definido (Local: LEGACY PENDIENTE) |
| B | Tipos y Clasificación | FR-B01…B04 | P1 | Definido |
| C | Ciclo de Vida y Cierre | FR-C01…C08 | P1 | Definido (Fase 1 parcial implementada) |
| D | Asignación, Responsables y Participantes | FR-D01…D10 | P1 | Definido |
| E | Jerarquía de Trabajo | FR-E01…E09 | P2 | Definido |
| F | Avance, Hitos y Mini-tareas | FR-F01…F07 | P2 | Definido |
| G | Fechas, Atrasos y Reprogramación | FR-G01…G05 | P2 | Definido |
| H | Documentos y Evidencias | FR-H01…H06 | P2 | Definido |
| I | Cotizaciones | FR-I01…I08 | P3 | Definido (pendiente valores P3) |
| J | Proveedores | FR-J01…J05 | P3 | Definido (LEGACY PENDIENTE) |
| K | Notificaciones y Email | FR-K01…K04 | P2 | Definido |
| L | Dashboards y KPI | FR-L01…L06 | P3 | Definido (pendiente KPI P6) |
| M | Reuniones de Revisión | FR-M01…M07 | P3 | Definido |
| N | Origen, Derivación y Similitud | FR-N01…N08 | P3 | Definido |
| O | Equipos / Máquinas | FR-O01…O04 | P2 | Definido (sin legacy) |
| P | Seguridad, Multiempresa y Enlaces | FR-P01…P05 | P1 | Definido (Fase 1 implementada) |
| Q | Reglas de Cierre | FR-Q01…Q06 | P2 | Definido |
| R | Exclusiones Actuales | FR-R01…R06 | — | Definido |
