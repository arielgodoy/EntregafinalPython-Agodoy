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
- Q: ¿Qué valores predeterminados deben aplicarse al mínimo de cotizaciones por ronda y al máximo de versiones permitidas por proveedor? → A: Mínimo 3 cotizaciones y máximo 3 versiones por proveedor.
- Q: ¿Qué regla debe controlar las transiciones entre los estados de una tarea publicada? → A: Flujo explícito con transiciones autorizadas; el cierre requiere aprobación y la anulación/reactivación son acciones separadas.
- Q: ¿Qué debe ocurrir con los descendientes y las fechas cuando se anula y luego se reactiva una tarea padre? → A: Anular padre, hijos y nietos en cascada; reactivar toda la estructura exactamente como estaba, sin recalcular fechas automáticamente, dejando las fechas afectadas pendientes de reacomodo o confirmación y notificando a los participantes afectados.
- Q: ¿Cómo debe calcularse exactamente el avance ponderado cuando los hitos tienen pesos distintos y se agrega un nuevo hito? → A: Los pesos son relativos y se normalizan automáticamente; el avance es la suma de (cumplimiento × peso) dividida por la suma de pesos, redistribuyéndose proporcionalmente al agregar hitos.
- Q: ¿Cuál debe ser el catálogo cerrado de KPI disponible en los dashboards y repetido en cada dimensión permitida? → A: Total de tareas por estado; tareas atrasadas; tareas próximas a vencer; tareas sin movimiento; tareas esperando aprobación; carga abierta por responsable; porcentaje de cumplimiento; tiempo promedio de cierre.
- Q: ¿Debe el umbral de similitud del 80% ser configurable y, si lo es, cuál debe ser su alcance? → A: Configurable por empresa, con valor predeterminado de 80%, modificación restringida a usuarios autorizados y aplicación a nuevas evaluaciones de similitud.

---

## Regla arquitectónica (vigente)

- Toda la lógica funcional nueva vive dentro de `tareas/` (app autocontenida; COPILOT/ARQUITECTURA_APPS.md).
- `tareas` REUTILIZA, no duplica: ICMEAS/access_control, sesión/usuario autenticado, seguridad, multiempresa, `notificaciones`, email (`acounts`/email_service).
- No se modifican otras apps ni archivos globales salvo integración técnica mínima con autorización expresa.
- Detención: si una necesidad no puede resolverse dentro de `tareas/`, se DETIENE y reporta (archivo, motivo, impacto, alternativa).

---

## A. Identidad, Correlativos y Contexto

- **FR-A01**: Al crear una tarea se MUST reservar un único número secuencial por empresa; el borrador MUST mostrarlo como `B0000001` y al publicar el mismo número MUST mostrarse como `A0000001`. `TD` queda reservado para TO-DO futuro. La publicación transforma el mismo registro, conserva la misma PK, NO consume un segundo número y NO existen secuencias A/B independientes.
- **FR-A02**: Un borrador MUST tener vida indefinida y ser visible inicialmente SOLO en el dashboard propio del creador.
- **FR-A03** `[PARCIAL — definición de Departamento pendiente]`: Toda tarea MUST pertenecer a una empresa (empresa activa al crearla) y MUST poder asociarse a local y a departamento/área. Local sigue bloqueado por P1; no se define aún el modelo/campo de Departamento.
- **FR-A04** `[PARCIAL — definición de Equipo/Activo pendiente]`: Una tarea MUST poder asociarse opcionalmente a un equipo/máquina/activo cuando corresponda. No se define aún modelo, campo, código ni relación de Equipo/Activo.
- **FR-A05**: Toda tarea MUST registrar su creador (creada_por) automáticamente desde el usuario autenticado.
- **FR-A06**: El correlativo MUST ser único por empresa y legible.
- **FR-A07**: LOCAL es concepto legacy → **`LEGACY API PENDIENTE`**: no se define tabla/IDs/sincronización sin autorización y lectura del legacy.

**Key Entities — A**: Tarea (correlativo_borrador `B*`, correlativo_activo `A*`, `TD*` reservado para TO-DO futuro, empresa, local [LEGACY], departamento, equipo_activo [opcional], creada_por).

---

## B. Tipos y Clasificación

- **FR-B01**: La prioridad MUST ser SIMPLE, NORMAL, URGENTE o CRITICA; jerarquía CRITICA > URGENTE > NORMAL > SIMPLE; default NORMAL. NO existe prioridad "baja".
- **FR-B02**: La prioridad MUST poder cambiar dinámicamente durante la vida de la tarea.
- **FR-B03**: Una tarea MUST clasificarse como "trabajo en equipo" (múltiples participantes) o "tarea independiente por responsable".
- **FR-B04**: Las clasificaciones MUST ser utilizables como filtros en listados y dashboards.

**Key Entities — B**: Clasificación (prioridad, naturaleza_trabajo).

---

## C. Ciclo de Vida y Cierre

- **FR-C01**: Estados persistentes canónicos del ciclo funcional: `BORRADOR`, `ACTIVA`, `GESTION`, `PENDIENTE_APROBACION_CIERRE` y `CERRADA`. `ANULADA` deja de ser estado canónico: la anulación es el flag separado `Tarea.anulada` (ver E). Publicación, aprobación/rechazo de cierre, anulación y reactivación son acciones/eventos auditables, no estados persistentes adicionales.
- **FR-C02**: Toda tarea nace como borrador (vida indefinida).
- **FR-C03**: Publicar exige responsable válido/activo, registra fecha de publicación, convierte correlativo B→A, transforma `BORRADOR` en `ACTIVA` y es irreversible hacia borrador. El valor MVP `PUBLICADA` se migra a `ACTIVA`.
- **FR-C04**: El responsable puede llevar la tarea a 100%; entonces pasa a "en espera de aprobación de cierre".
- **FR-C05**: El creador o un perfil autorizado MUST aprobar el cierre.
- **FR-C06**: Si el cierre se rechaza, la tarea queda "cierre rechazado / vuelve a gestión" y MUST mantener el 100% aunque vuelva a gestión.
- **FR-C07**: MUST registrarse quién cerró/canceló y cuándo.
- **FR-C08**: Cada transición MUST registrar fecha y usuario (auditoría).
- **FR-C09**: Las transiciones MUST seguir un flujo explícito: `BORRADOR` --publicar--> `ACTIVA` → `GESTION` → `PENDIENTE_APROBACION_CIERRE` --aprobar--> `CERRADA`; rechazar el cierre es un evento auditado que devuelve a `GESTION` conservando el 100%. Anular/reactivar NO son transiciones de estado: solo cambian el flag `anulada` (ver E), sin tocar `estado` ni crear un estado `REACTIVADA`. Ninguna transición puede devolver una tarea publicada a `BORRADOR`.

**Key Entities — C**: Estado, Transición (origen, destino, fecha, usuario), Cierre/Cancelación (por, fecha).

### Señal mínima de lifecycle para la condición de 100%

No existe actualmente en los artefactos una representación persistente equivalente a
"alcanzó la condición funcional para solicitar cierre". Phase 2 incorporará únicamente
`Tarea.cierre_completado`, un `BooleanField(default=False)`. Esta señal no representa el
porcentaje general de avance, no implementa pesos, hitos ni el futuro modelo `Avance`; solo
persiste que la tarea alcanzó la condición funcional equivalente al 100% necesaria para
solicitar cierre. Una fase posterior podrá derivarla, sustituirla o ampliarla mediante
migración aditiva cuando exista el modelo real de avance.

La señal se comporta así: en gestión normal es `False`; al marcar 100% pasa a `True` y el
estado pasa a `PENDIENTE_APROBACION_CIERRE`; al aprobar queda `CERRADA` y `True`; al rechazar
vuelve a `GESTION` y conserva `True`. No se define todavía cómo vuelve a `False` en flujos
posteriores de reprogramación.

### Tabla canónica de estados y eventos

| Estado origen | Acción/evento | Estado destino | Condiciones | Auditoría |
|---|---|---|---|---|
| `BORRADOR` | Publicar | `ACTIVA` | Responsable activo y válido | Publicación, usuario y fecha |
| `ACTIVA` | Iniciar gestión | `GESTION` | Tarea publicada | Transición, usuario y fecha |
| `GESTION` | Marcar 100% | `PENDIENTE_APROBACION_CIERRE` | Responsable completa la tarea | Transición y avance |
| `PENDIENTE_APROBACION_CIERRE` | Aprobar cierre | `CERRADA` | Creador o perfil autorizado | Aprobación, usuario, fecha y comentario |
| `PENDIENTE_APROBACION_CIERRE` | Rechazar cierre | `GESTION` | Rechazo autorizado; conserva 100% | Evento de rechazo, usuario, fecha y motivo |
| `ACTIVA`/`GESTION`/`PENDIENTE_APROBACION_CIERRE` | Anular/cancelar | `ANULADA` | Acción autorizada | Anulación, snapshot, usuario y fecha |
| `ANULADA` | Reactivar | Estado persistente anterior | Acción autorizada; no recalcula fechas | Reactivación y restauración |
| Cualquier estado publicado | Intentar volver a borrador | Sin transición | Siempre prohibido | Intento rechazado, si corresponde |

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
- **FR-E05**: **Anulación por flag (diseño simplificado aprobado)**: `Tarea.anulada` (BooleanField, default False). Anular una tarea pone `anulada=True` y reactivar pone `anulada=False`, SIN cambiar `estado`, responsable, participantes, correlativo, `cierre_completado`, relaciones ni ningún otro dato funcional. NO se usa `estado == ANULADA` junto a `anulada == True` como doble fuente de verdad.
- **FR-E06**: **Anulación efectiva jerárquica (LÓGICA, no física)**: una tarea se considera `anulada_efectivamente` cuando ella misma tiene `anulada=True`, OR su padre está anulado efectivamente, OR su abuelo está anulado efectivamente (máximo padre→hija→nieta, sin cuarto nivel). NO existe cascada física de escritura (`for descendiente: anulada=True` está prohibido); la cascada la calcula `is_effectively_annulled(tarea)` considerando tarea+padre+abuelo.
- **FR-E07**: **Reactivación sin restauración de estados**: reactivar el padre (`anulada=False`) hace que hijas y nietas vuelvan a operar automáticamente con sus estados previos intactos (nunca cambiaron). NO se restauran estados, NO se reconstruye estructura, NO se modifica descendencia. Una hija anulada directamente (`anulada=True`) sigue anulada aunque el padre se reactive. Las fechas NO se recalculan automáticamente: quedan pendientes de reacomodo/confirmación por los responsables o participantes antes de continuar la gestión.
- **FR-E08**: Al anular o reactivar MUST notificarse a todos los participantes afectados. La trazabilidad (tarea, usuario, fecha/hora, acción ANULAR/REACTIVAR, motivo) se registra reutilizando `TareaTransicion` o el mecanismo vigente, sin crear otra auditoría.
- **FR-E09**: MUST existir el concepto de subtarea y de mini-tarea (ver F).
- **FR-E10**: **Reglas de operación mientras `anulada_efectivamente` es True**: la tarea sigue visible según filtros y conserva todos sus datos, pero MUST NOT permitir operaciones normales de gestión, modificaciones de lifecycle, cierre, reasignaciones u otras acciones operativas, salvo lectura/auditoría/reactivación.
- **FR-E11**: **Cierre de padre con descendientes**: el padre no puede cerrarse mientras tenga descendientes operativos pendientes. Una descendiente anulada efectivamente MUST NOT considerarse trabajo pendiente activo.
- **FR-E12**: **Empresa en jerarquía**: toda relación jerárquica MUST permanecer dentro de la misma Empresa; padre, hija y nieta comparten el mismo `empresa_id` obligatorio.
- **FR-E13**: **Ciclos y profundidad**: una tarea MUST NOT ser hija de sí misma; MUST NOT existir ciclo (A→B→A); cada tarea tiene como máximo un padre; máximo padre→hija→nieta (sin tercer nivel bajo la raíz). La validación concreta se implementa en el servicio de jerarquía.

**Key Entities — E**: Relación padre/hija (tarea_padre), Subtarea, Mini-tarea.

---

## F. Avance, Hitos y Mini-tareas

- **FR-F01**: Tarea simple con porcentaje de avance manual.
- **FR-F02**: Tarea ponderada: avance calculado por hitos.
- **FR-F03**: Cada hito MUST tener un peso relativo; los pesos MUST normalizarse automáticamente y el avance ponderado MUST calcularse como la suma de (porcentaje de cumplimiento × peso) dividida por la suma total de pesos.
- **FR-F04**: Agregar un nuevo hito MUST actualizar la suma total de pesos y redistribuir proporcionalmente el avance existente sin alterar los porcentajes de cumplimiento registrados en los hitos anteriores.
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

- **FR-I01** `[PARCIAL — IMPLEMENTABLE AHORA hasta el mínimo por ronda]`: Una tarea MUST poder requerir o no cotización; si la requiere, MUST existir un mínimo configurable por tarea, con valor predeterminado de 3 cotizaciones por ronda.
- **FR-I02** `[PARCIAL — regla documentable ahora; validación efectiva DEFERRED POR P2]`: MUST soportar un máximo de 3 versiones por proveedor en cada ronda.
- **FR-I03** `[IMPLEMENTABLE AHORA]`: Las cotizaciones MUST organizarse por rondas; MUST existir histórico por ronda y MUST poder abrirse una nueva ronda.
- **FR-I04** `[IMPLEMENTABLE AHORA]`: El mínimo de cotizaciones MUST poder cambiar en una nueva ronda.
- **FR-I05** `[DEFERRED — BLOQUEADO POR P2 LEGACY]`: MUST existir una última cotización válida por proveedor.
- **FR-I06** `[DEFERRED — BLOQUEADO POR P2 LEGACY]`: Estados de cotización por proveedor: "Participó cotizando" y "Proveedor seleccionado".
- **FR-I07** `[DEFERRED — BLOQUEADO POR P2 LEGACY]`: El proveedor adjudicado MUST ser visible.
- **FR-I08** `[PARCIAL — regla general implementable; conteo por proveedor DEFERRED POR P2]`: El cierre MUST bloquearse si no se cumple el mínimo de cotizaciones cuando aplique.

**Key Entities — I**: Cotización (proveedor, ronda, versión, vigente, monto, estado), Adjudicación.

---

## J. Proveedores

- **FR-J01** `[DEFERRED — BLOQUEADO POR P2 LEGACY]`: MUST existir un maestro de proveedores en Django.
- **FR-J02** `[DEFERRED — BLOQUEADO POR P2 LEGACY]`: Evaluación manual 1–5 del proveedor: malo / deficiente / regular / normal / sobresaliente.
- **FR-J03** `[DEFERRED — BLOQUEADO POR P2 LEGACY]`: Califica el responsable líder.
- **FR-J04** `[DEFERRED — BLOQUEADO POR P2 LEGACY]`: MUST existir promedio global del proveedor.
- **FR-J05** `[DEFERRED — BLOQUEADO POR P2 LEGACY]`: Vínculo con legacy mediante `rut_contable` → **`LEGACY API PENDIENTE`**: NO se define integración real (tabla/IDs/sincronización/contrato) sin revisar primero el legacy con el usuario.

**Key Entities — J**: Proveedor como **ENTIDAD CONCEPTUAL FUTURA**. Los datos maestros,
`rut_contable`, evaluación 1–5, promedio global e identidad externa son necesidades
funcionales futuras, no diseño actual de modelo, campos ni contrato.

### Estado de implementación del bloque J

Todo el bloque J queda `DEFERRED — BLOQUEADO POR P2 LEGACY`. No se define actualmente
maestro, tabla, campos, ID externo, endpoint, sincronización, evaluación ni promedio.
`ProveedorReferencia` permanece únicamente como **PLACEHOLDER DE DISEÑO — IMPLEMENTACIÓN
BLOQUEADA POR P2**.

### Estado de implementación frente a P2

- Antes de resolver P2 solo son implementables las rondas, su histórico, mínimo configurable,
	fechas, observaciones, documentos asociados y reglas generales de cierre que declaren la
	dependencia pendiente.
- La regla de máximo 3 versiones por proveedor se documenta ahora, pero no se valida
	efectivamente sin identidad real.
- Quedan bloqueados por P2: identificar proveedores, contar proveedores distintos, imponer el
	máximo por proveedor, determinar la última válida, adjudicar, asignar estados por proveedor,
	evaluar proveedores, calcular promedio global y cualquier relación/FK lógica con proveedor.
- `ProveedorReferencia` permanece como **PLACEHOLDER DE DISEÑO — IMPLEMENTACIÓN BLOQUEADA POR P2**.

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
- **FR-L02**: Dashboard Jefatura/General MUST mostrar exactamente estos ocho KPI: total de tareas por estado, tareas atrasadas, tareas próximas a vencer, tareas sin movimiento, tareas esperando aprobación, carga abierta por responsable, porcentaje de cumplimiento y tiempo promedio de cierre.
- **FR-L03**: Dimensiones activas con drill-down: General → Empresa → Departamento → Usuario → Tarea. Local queda DEFERRED por P1 y Proveedor queda DEFERRED por P2.
- **FR-L04**: Los mismos ocho KPI por cada dimensión activa: General, Empresa, Departamento, Usuario y Tarea. No se habilitan dimensiones adicionales.
- **FR-L05**: Presentación con DataTables, modal "Ver info de la tarea" y opción de abrir la tarea completa.
- **FR-L06**: Las dimensiones Local y Proveedor dependen de `LEGACY API PENDIENTE` (A y J).
- **FR-L07**: Los ocho KPI de FR-L02 MUST repetirse en cada dimensión permitida del drill-down; no se definirán KPI adicionales por dimensión.

**Key Entities — L**: Dashboard (dimensión), KPI, Drill-down.

### Estado de dimensiones KPI

- **ACTIVAS AHORA**: General, Empresa, Departamento, Usuario, Tarea.
- **DEFERRED**: Local — bloqueada por P1; Proveedor — bloqueada por P2.
- Catálogo cerrado: total de tareas por estado; atrasadas; próximas a vencer; sin movimiento;
	esperando aprobación; carga abierta por responsable; porcentaje de cumplimiento; tiempo
	promedio de cierre.

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

- **FR-N01**: Una tarea MUST poder tener como máximo un origen canónico directo: otra tarea, un TO-DO o ninguno. Una tarea no puede tener simultáneamente `todo_origen` y `tarea_origen`.
- **FR-N02**: El historial de origen MUST ser accesible en lectura.
- **FR-N03**: MUST NOT convertir una tarea antigua en la nueva: se crea una nueva y se referencia. Cadenas históricas permitidas.
- **FR-N04**: Al publicar, el sistema MUST advertir si parece un problema repetido cuando la coincidencia aproximada alcance el umbral configurado para la empresa, cuyo valor predeterminado es 80%.
- **FR-N05**: La evaluación de similitud MUST incluir también tareas cerradas.
- **FR-N06**: El usuario MUST confirmar "es el mismo problema nuevamente"; aun confirmando, la tarea es NUEVA.
- **FR-N07**: La nueva tarea MUST poder mantener una o varias referencias históricas o de similitud a tareas antiguas si corresponde; estas referencias no sustituyen ni multiplican el origen canónico único.
- **FR-N08**: Cambio de repuesto MUST NOT implicar automáticamente "mismo problema".
- **FR-N09**: El umbral de similitud MUST ser configurable por empresa; solo usuarios autorizados podrán modificarlo y cada cambio MUST aplicar únicamente a nuevas evaluaciones de similitud.

**Key Entities — N**: Origen/derivación, Relación de similitud, Cadena histórica, Umbral (80%).

## S. TO-DO y Origen Canónico

- **FR-S01**: TO-DO MUST ser una entidad separada de `Tarea`, perteneciente obligatoriamente a una Empresa. Representa un problema, necesidad, asunto pendiente u observación todavía no formalizado ni planificado como Tarea.
- **FR-S02**: El correlativo de TO-DO MUST usar el namespace propio `TD` y una secuencia independiente por Empresa (`TD0000001`, `TD0000002`); no comparte secuencia numérica con los correlativos A/B de `Tarea`.
- **FR-S03**: TO-DO MUST incluir conceptualmente correlativo, título, descripción, estado, creador, fecha de creación, usuario de cierre, fecha de cierre y comentario de cierre. Puede existir sin responsable, fecha tope o planificación formal.
- **FR-S04**: Los únicos estados persistentes mínimos de TO-DO son `ABIERTO` y `CERRADO`. Un TO-DO `CERRADO` NO se reabre.
- **FR-S05**: Si el problema reaparece después del cierre, MUST crearse un nuevo TO-DO relacionado históricamente con el anterior; la relación concreta queda pendiente de diseño técnico y no crea todavía un modelo.
- **FR-S06**: Un TO-DO MUST poder originar una o varias Tareas a lo largo del tiempo. Cada Tarea originada conserva el lifecycle, responsable, fechas, cierre, jerarquía y correlativo A/B normales de una Tarea.
- **FR-S07**: Cerrar una Tarea originada NO cierra automáticamente el TO-DO. El cierre de TO-DO MUST ser explícito y no puede realizarse mientras exista alguna Tarea originada pendiente operativamente; una Tarea `CERRADA` o efectivamente anulada no es bloqueante. La desaparición de la última pendiente no cierra el TO-DO automáticamente.
- **FR-S08**: La creación de una Tarea desde un TO-DO MUST registrar usuario y fecha/hora; el comentario o motivo de derivación es opcional.
- **FR-S09**: Una Tarea MUST tener como máximo un origen canónico: `todo_origen`, `tarea_origen` o ninguno. MUST existir una restricción de exclusión que impida ambos orígenes simultáneamente.
- **FR-S10**: Las referencias históricas, evaluaciones de similitud, jerarquía `TareaRelacion`, clonación y trabajo en equipo son conceptos distintos del origen canónico y no lo reemplazan.
- **FR-S11**: No se usará `GenericForeignKey` para el origen salvo necesidad arquitectónica real; se prefieren FK explícitas a TO-DO y Tarea.
- **FR-S12**: Una Tarea formal puede no tener fecha tope. La ausencia de fecha no la convierte en TO-DO: TO-DO es un asunto todavía no formalizado como Tarea, mientras que una Tarea sin fecha ya es una Tarea formal.

**Key Entities — S**: TO-DO, CorrelativoTodoEmpresa, OrigenTodoTarea, OrigenTareaTarea y auditoría de TO-DO.

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
- **FR-Q03** `[PARCIAL — IMPLEMENTABLE AHORA hasta la regla general de cierre; validaciones que requieran contar proveedores distintos o identidad real DEFERRED POR P2]`: Si la tarea requiere cotización, el cierre MUST exigir el mínimo configurable.
- **FR-Q04**: El cierre MUST requerir aprobación del creador o perfil autorizado.
- **FR-Q05** `[DEFERRED — BLOQUEADO POR P2 LEGACY]`: Al cerrar una tarea con proveedor, el responsable líder MUST calificar al proveedor (1–5, ver J). No se implementarán evaluación ni promedio de proveedor hasta resolver P2.
- **FR-Q06**: MUST registrarse quién cerró/canceló y cuándo.

**Key Entities — Q**: Regla de cierre, Evidencia, Cierre/Cancelación (por, fecha).

---

## R. Exclusiones Actuales

- **FR-R01**: Sin usuarios externos por ahora.
- **FR-R02**: Sin plantilla de hitos por ahora.
- **FR-R03**: Sin vencimiento automático de documentos (vencimiento informativo solamente).
- **FR-R04**: Sin prioridad "baja" (solo Simple/Normal/Urgente/Crítica).
- **FR-R05**: Integración real con legacy de LOCALES y PROVEEDORES fuera de alcance hasta revisión (`LEGACY API PENDIENTE`).
- **FR-R06**: Sin eliminación física de tareas (la anulación usa el flag `anulada`, ver E; no se borran registros ni se cambian estados).

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
- **SC-010**: Correlativo borrador `B*` se convierte a activo `A*` al publicar, sin duplicar la tarea.

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
- **P3**: Resuelto: mínimo predeterminado de 3 cotizaciones por ronda y máximo de 3 versiones por proveedor.
- **P4**: Resuelto: los pesos de hitos son relativos y se normalizan automáticamente; el avance es la suma de (cumplimiento × peso) dividida por la suma de pesos, y agregar hitos redistribuye proporcionalmente el avance sin alterar cumplimientos anteriores.
- **P5**: Resuelto: las transiciones siguen un flujo explícito y auditado; el cierre requiere aprobación, el rechazo vuelve a gestión conservando el 100%, y anulación/reactivación son acciones separadas y autorizadas.
- **P6**: Resuelto: el catálogo cerrado contiene total de tareas por estado, tareas atrasadas, tareas próximas a vencer, tareas sin movimiento, tareas esperando aprobación, carga abierta por responsable, porcentaje de cumplimiento y tiempo promedio de cierre; se repite en cada dimensión permitida, sin KPI adicionales.
- **P7**: Resuelto funcionalmente: anulación y reactivación en cascada para padre, hijos y nietos; la reactivación conserva la estructura y datos históricos, no recalcula fechas automáticamente, deja las fechas afectadas pendientes de confirmación o reacomodo y notifica a los participantes afectados. La cascada queda implementada en la fase que introduce la jerarquía (Phase 3), no en el núcleo de Phase 2.
- **P8**: Resuelto: el umbral de similitud es configurable por empresa, con valor predeterminado de 80%, modificación restringida a usuarios autorizados y aplicación solo a nuevas evaluaciones.

## Tabla de cobertura por bloque

| Bloque | Nombre | FR | Prioridad dominante | Estado |
|---|---|---|---|---|
| A | Identidad, Correlativos y Contexto | FR-A01…A07 | P1 | Definido (Local: LEGACY PENDIENTE) |
| B | Tipos y Clasificación | FR-B01…B04 | P1 | Definido |
| C | Ciclo de Vida y Cierre | FR-C01…C09 | P1 | Definido (Fase 1 parcial implementada) |
| D | Asignación, Responsables y Participantes | FR-D01…D10 | P1 | Definido |
| E | Jerarquía de Trabajo | FR-E01…E09 | P2 | Definido |
| F | Avance, Hitos y Mini-tareas | FR-F01…F07 | P2 | Definido |
| G | Fechas, Atrasos y Reprogramación | FR-G01…G05 | P2 | Definido |
| H | Documentos y Evidencias | FR-H01…H06 | P2 | Definido |
| I | Cotizaciones | FR-I01…I08 | P3 | Definido |
| J | Proveedores | FR-J01…J05 | P3 | Definido (LEGACY PENDIENTE) |
| K | Notificaciones y Email | FR-K01…K04 | P2 | Definido |
| L | Dashboards y KPI | FR-L01…L07 | P3 | Definido |
| M | Reuniones de Revisión | FR-M01…M07 | P3 | Definido |
| N | Origen, Derivación y Similitud | FR-N01…N09 | P3 | Definido |
| O | Equipos / Máquinas | FR-O01…O04 | P2 | Definido (sin legacy) |
| P | Seguridad, Multiempresa y Enlaces | FR-P01…P05 | P1 | Definido (Fase 1 implementada) |
| Q | Reglas de Cierre | FR-Q01…Q06 | P2 | Definido |
| R | Exclusiones Actuales | FR-R01…R06 | — | Definido |
| S | TO-DO y Origen Canónico | FR-S01…S12 | P2 | Definido (implementación futura) |
