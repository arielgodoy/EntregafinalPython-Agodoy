# Feature Specification (SPEC MAESTRA): Tareas — App completa de gestión de tareas

**Feature Branch**: `001-tareas-internas`

**Created**: 2026-09-07

**Status**: Draft (Spec Maestra — dominio completo auditado)

**Input**: Dominio completo de `tareas` como app de gestión de tareas del sistema. Integra decisiones confirmadas de la iteración inicial y las decisiones de diseño funcional tomadas fuera del repositorio (22 grupos), sin perder comportamiento.

> **Alcance**: SPEC MAESTRA del dominio completo. La implementación se descompone en fases; la Fase 1 (borrador/publicada, ya implementada) sigue válida e integrada. LOCAL legacy queda como **`LEGACY API PENDIENTE`**. PROVEEDOR tendrá un maestro local Django transversal; su integración/validación con ERP legacy queda diferida a P2.

## Clarifications

### Session 2026-09-07

- Q: ¿Publicar con responsable desactivado/eliminado? → A: Bloquear la publicación e informar; el usuario debe asignar un responsable válido antes de publicar.
- Q: ¿Operaciones sobre una tarea ya publicada? → A: Edición libre de campos (manteniendo responsable válido); la tarea publicada no puede volver a borrador.
- Q: ¿Qué valores predeterminados deben aplicarse al mínimo de cotizaciones por ronda y al máximo de versiones permitidas por proveedor? → A: Mínimo 3 cotizaciones y máximo 3 versiones por proveedor dentro de cada ronda.
- Q: ¿Qué regla debe controlar las transiciones entre los estados de una tarea publicada? → A: Flujo explícito con transiciones autorizadas; el cierre requiere aprobación y la anulación/reactivación son acciones separadas.
- Q: ¿Qué debe ocurrir con los descendientes y las fechas cuando se anula y luego se reactiva una tarea padre? → A: Anular padre, hijos y nietos en cascada; reactivar toda la estructura exactamente como estaba, sin recalcular fechas automáticamente, dejando las fechas afectadas pendientes de reacomodo o confirmación y notificando a los participantes afectados.
- Q: ¿Cómo debe calcularse exactamente el avance ponderado cuando los hitos tienen pesos distintos y se agrega un nuevo hito? → A: Los pesos son relativos y se normalizan automáticamente; el avance es la suma de (cumplimiento × peso) dividida por la suma de pesos, redistribuyéndose proporcionalmente al agregar hitos.
- Q: ¿Cuál debe ser el catálogo cerrado de KPI disponible en los dashboards y repetido en cada dimensión permitida? → A: Total de tareas por estado; tareas atrasadas; tareas próximas a vencer; tareas sin movimiento; tareas esperando aprobación; carga abierta por responsable; porcentaje de cumplimiento; tiempo promedio de cierre.
- Q: ¿Debe el umbral de similitud del 80% ser configurable y, si lo es, cuál debe ser su alcance? → A: Configurable por empresa, con valor predeterminado de 80%, modificación restringida a usuarios autorizados y aplicación a nuevas evaluaciones de similitud.

---

## Regla arquitectónica (vigente)

- Toda la lógica funcional nueva vive dentro de `tareas/` y respeta APPLICATION BOUNDARY (ver Constitución y `COPILOT/ARQUITECTURA_APPS.md`).
- `tareas` REUTILIZA, no duplica: VICMEAS/access_control, sesión/usuario autenticado, seguridad, multiempresa, `notificaciones`, email (`acounts`/email_service).
- No se modifican otras apps ni archivos globales desde este scope; cualquier registro o cambio externo requiere una tarea separada con autorización y scope explícitos.
- Detención: si una necesidad no puede resolverse dentro de `tareas/`, se DETIENE y reporta (archivo, motivo, impacto, alternativa).

### Gate transversal permanente de i18n

Una superficie de UI no se considera terminada solo por incluir `data-key`.
El cierre i18n exige simultáneamente:

`template/data-key o message_key correcto` + `clave en sp.json` + `clave en en.json`
+ `sin claves dinámicas no resolubles` + `enums visibles con etiqueta traducida`
+ `mensajes backend/AJAX traducidos` + `validación manual ES/EN completada`.

El gate de cierre debe producir estas métricas, todas en cero:

- `MISSING_SP`
- `MISSING_EN`
- `ONE_SIDE`
- `DYNAMIC_KEYS`
- `RAW_MESSAGE_KEYS_VISIBLE`
- `VISIBLE_HARDCODED_TEXT`, salvo excepciones explícitamente justificadas como datos dinámicos, valores técnicos no visibles, logs/debug o excepciones documentadas.

Toda nueva superficie o task de UI de `tareas` debe pasar este gate antes de marcarse terminada.

### Seguridad funcional y visibilidad de navegación

- `VICMEAS` es la nomenclatura canónica única del sistema de visibilidad y autorización.
- `Permiso.ver` controla exclusivamente si el item de Tareas aparece en el sidebar
	para la empresa activa. `ingresar`, `crear`, `modificar`, `eliminar`, `autorizar` y
	`supervisor` controlan autorización funcional según la acción.
- `Permiso.ver` controla exclusivamente si el item de Tareas aparece en el sidebar
	para la empresa activa. `ingresar`, `crear`, `modificar`, `eliminar`, `autorizar` y
	`supervisor` continúan controlando las operaciones backend correspondientes.
- `V` e `I` son independientes: `V=True/I=False` deja visible el menú pero permite
	que el backend responda 403; `V=False/I=True` oculta el menú pero no bloquea el
	ingreso directo por URL. No se documenta que una bandera implique la otra.
- La visibilidad es multiempresa y depende de usuario, empresa activa, Vista y
	`ver=True`. Los padres del sidebar no tienen permiso `V` propio: aparecen solo si
	al menos un hijo es visible. El superuser ve todo el sidebar por bypass visual,
	sin obtener por ello un bypass automático de autorización backend.
- El sidebar de Tareas usa mapping explícito item → Vista; cualquier item navegable
	nuevo debe tener mapping o clasificación `GLOBAL`. Los elementos `GLOBAL` no son
	un bypass general. `V` no controla búsqueda, notificaciones, enlaces directos,
	breadcrumbs ni la vista inicial; esta última continúa dependiendo de `ingresar=True`.

---

## A. Identidad, Correlativos y Contexto

- **FR-A01**: Al crear una tarea se MUST reservar un único número secuencial por empresa; el borrador MUST mostrarlo como `B0000001` y al publicar el mismo número MUST mostrarse como `A0000001`. `TD` queda reservado para TO-DO futuro. La publicación transforma el mismo registro, conserva la misma PK, NO consume un segundo número y NO existen secuencias A/B independientes.
- **FR-A02**: Un borrador MUST tener vida indefinida y ser visible inicialmente SOLO en el dashboard propio del creador.
- **FR-A03** `[PARCIAL — implementación organizacional pendiente]`: Toda tarea MUST pertenecer a una empresa (empresa activa al crearla) y MUST poder asociarse a un `organizacion.Local` o `organizacion.Departamento` cuando corresponda. Ambas dimensiones pertenecen directamente a Empresa; Departamento no depende de Local. La futura `APPLICATION_APP` `organizacion` será su owner canónico.
- **FR-A04** `[PARCIAL — definición de Equipo/Activo pendiente]`: Una tarea MUST poder asociarse opcionalmente a un equipo/máquina/activo cuando corresponda. No se define aún modelo, campo, código ni relación de Equipo/Activo.
- **FR-A05**: Toda tarea MUST registrar su creador (creada_por) automáticamente desde el usuario autenticado.
- **FR-A06**: El correlativo MUST ser único por empresa y legible.
- **FR-A07** `[ARQUITECTURA DEFINIDA — IMPLEMENTACIÓN PENDIENTE]`: Local se modelará como entidad Django canónica en `organizacion`, con PK interna, código funcional por Empresa y `legacy_code` separado. El ERP legacy (`g_maestroempresas`, accesible mediante `api`) es la fuente externa inicial y se integrará mediante sincronización futura; las APPLICATION_APPS no consultan SQL legacy directamente.

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
- **FR-D09**: Permisos por rol integrados con VICMEAS (sin sistema paralelo).
- **FR-D10**: Confirmación de lectura para participantes/invitados cuando corresponda.

**Nota UX pendiente**: cada Tarea mantiene un único `responsable` principal,
mientras el trabajo en equipo puede incluir múltiples participantes. El contrato
actual de `/tareas/crear/` conserva únicamente la selección del responsable
principal; los participantes se gestionan después de crear la Tarea. Al cierre
del desarrollo se evaluará si conviene permitir seleccionar participantes durante
la creación. Esta nota no cambia el contrato funcional actual, no convierte
participantes en múltiples responsables y no requiere implementación ahora.

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
- **FR-F06**: La Tarea MUST configurar explícitamente si requiere evidencia de cierre (`requiere_evidencia_cierre`). Esta configuración es independiente de la existencia de registros de evidencia.
- **FR-F07**: Las mini-tareas son ultra simples (checkbox hecho/no hecho), con UNA persona por mini-tarea, MUST NOT ponderar el avance y MUST impedir el cierre mientras estén pendientes.
- **FR-F08**: Todo hito MUST tener exactamente un responsable obligatorio, referenciado a un usuario del sistema; el responsable del hito puede ser distinto del responsable principal de la tarea.
- **FR-F09**: El responsable de un hito MUST estar activo y pertenecer/tener acceso válido a la Empresa de la tarea; una asignación inválida, inactiva o cross-company MUST rechazarse sin cambios parciales. No se crean permisos nuevos en `access_control`; se reutiliza la política existente de validación de usuarios y Empresa.
- **FR-F10**: Los hitos MUST conservar su distinción respecto de las mini-tareas: el hito participa en el avance ponderado mediante cumplimiento `0..100` y peso relativo; la mini-tarea representa una persona única y estado hecho/no hecho, y MUST NOT ponderar el avance.
- **FR-F11**: El hito MUST NOT tener prioridad o clasificación propia ni asumir una `fecha_tope` propia o heredada; para presentación y dashboard hereda la prioridad/clasificación de su tarea padre.
- **FR-F12**: Un Hito puede editarse en nombre, cumplimiento y peso. La edición normal MUST NOT modificar responsable ni motivo de reasignación. Toda edición MUST respetar la Empresa de la Tarea, cumplimiento `0..100` y el contrato vigente de pesos; no se agregan prioridad, clasificación ni `fecha_tope` propias.
- **FR-F13**: La reasignación de responsable de Hito está permitida y MUST ser auditada con Hito, responsable anterior, responsable nuevo, usuario que reasigna, fecha/hora y motivo obligatorio no vacío tras trim. El nuevo responsable MUST estar activo y ser válido para la Empresa de la Tarea. La auditoría debe usar historial propio de Hito, no `TareaReasignacion` por analogía.
- **FR-F14**: Todo cambio relevante de Hito MUST conservar historial específico de creación, nombre, cumplimiento, peso, responsable, anulación, reactivación y eliminación física cuando corresponda, incluyendo usuario, fecha/hora, valores anterior/nuevo y motivo cuando aplique. El historial MUST permitir determinar actividad/progreso histórico aunque el cumplimiento actual vuelva a `0`.
- **FR-F15**: Un Hito solo puede eliminarse físicamente si nunca tuvo actividad operativa ni evidencia histórica de cambios, progreso o reasignaciones relevantes. Si la eliminación física requiere conservar auditoría fuera del registro eliminado, esa estrategia debe definirse antes de implementarla; no se asume una solución física en este contrato.
- **FR-F16**: Un Hito con progreso, cambios relevantes, reasignaciones u otra actividad histórica MUST conservarse mediante anulación lógica (`anulado=True`); no se elimina físicamente. El Hito anulado conserva datos e historial, deja de ser pendiente operativo y no aparece como asignación pendiente, pero permanece disponible en historial/consulta.
- **FR-F17**: Se permite reactivar un Hito anulado. Reactivar MUST limpiar únicamente la condición de anulación, conservar responsable, cumplimiento, peso e historial, registrar el evento y reincorporar el Hito al avance ponderado y a la asignación activa; no debe resetear cumplimiento ni peso.
- **FR-F18**: Solo los Hitos operativos (`anulado=False`) participan en el avance ponderado. Crear, editar cumplimiento/peso, anular, reactivar o eliminar físicamente un Hito MUST recalcular el `Avance` ponderado de la Tarea cuando corresponda, usando `sum(cumplimiento * peso) / sum(pesos)` sobre Hitos operativos. MiniTarea sigue fuera de la fórmula.
- **FR-F19**: La edición, reasignación, anulación/reactivación y eliminación de Hitos MUST pasar por la política de autorización vigente de `tareas`; no se crean perfiles nuevos. La autorización canónica queda definida en FR-F20…FR-F25.
- **FR-F20**: El responsable del Hito puede actualizar únicamente su propio cumplimiento, respetando rango `0..100`, Empresa y usuario válido. No puede cambiar nombre o peso, reasignar, anular, reactivar ni eliminar físicamente.
- **FR-F21**: El responsable principal de la Tarea y el creador de la Tarea pueden gestionar los Hitos de esa Tarea: editar nombre, cumplimiento y peso; reasignar; anular; reactivar; y eliminar físicamente cuando la regla de historial lo permita. Deben respetar Empresa, usuario válido, auditoría y eliminación segura.
- **FR-F22**: El supervisor y el autorizador pueden gestionar los Hitos de la Tarea dentro del alcance vigente de autorización de Tarea/Empresa: editar, reasignar, anular, reactivar y eliminar cuando corresponda. No se inventan facultades adicionales fuera del contexto de Hito.
- **FR-F23**: El invitado/observador puede visualizar según sus permisos de participación, pero no puede modificar cumplimiento, editar, reasignar, anular, reactivar ni eliminar Hitos.
- **FR-F24**: Si un usuario tiene más de un rol, se aplica la facultad más amplia que posea dentro de la Tarea. Por ejemplo, quien sea responsable del Hito y responsable principal de la Tarea puede gestionar completamente ese Hito.
- **FR-F25**: Toda acción sobre Hitos MUST respetar Empresa activa, Empresa de la Tarea, usuario válido y aislamiento multiempresa; ningún rol autoriza operar Hitos de otra Empresa. Las acciones autorizadas, incluido el cambio de cumplimiento realizado por el responsable del Hito, MUST quedar registradas en `HitoHistorial` cuando corresponda.
- **FR-F26**: Un Hito MUST admitir una operación formal y explícita `Completar Hito`, distinta de editar cumplimiento. Completar exige reseña de cierre no vacía tras trim y al menos una evidencia válida; la operación MUST ser atómica.
- **FR-F27**: Pueden completar un Hito su responsable asignado, el responsable principal de la Tarea, el creador de la Tarea y supervisor/autorizador cuando su alcance vigente ya les permita gestionar ese Hito. Invitado/observador solo puede leer. Completar no concede reasignación.
- **FR-F28**: Completar Hito MUST establecer `completado=True`, cumplimiento `100`, reseña, usuario que completa y fecha/hora de completitud, conservando sin cambios el responsable asignado. `cumplimiento=100` mediante actualización manual MUST NOT marcar el Hito como completado.
- **FR-F29**: La evidencia de Hito es distinta de `EvidenciaCierre` de Tarea. Un Hito MUST relacionarse con cero o más `HitoEvidencia`; para completar se exige al menos una. Cada evidencia exige exactamente un archivo o una URL, formato físico válido del catálogo `PDF`, `JPG`, `JPEG`, `PNG`, `DOC`, `DOCX`, `XLS`, `XLSX`, usuario y fecha/hora.
- **FR-F30**: Completar Hito MUST registrar en `HitoHistorial` el evento `COMPLETADO`, permitiendo reconstruir Hito, responsable original, usuario que completó, fecha, reseña y referencias a sus evidencias sin duplicar archivos en el historial.
- **FR-F31**: Un Hito anulado no puede completarse; debe reactivarse primero. La anulación/reactivación conserva el historial y las reglas vigentes de `anulado`.
- **FR-F32**: Un Hito completado no puede cambiar silenciosamente su cumplimiento por debajo de `100`. No puede eliminarse físicamente si posee historial operativo; cualquier reapertura formal queda fuera de este contrato y requiere decisión explícita antes de implementarse.
- **FR-F33**: Completar Hito MUST recalcular el avance ponderado de la Tarea cuando corresponda. La operación no debe dejar completitud, reseña, usuario, fecha o evidencias parcialmente persistidos si falla una validación.
- **FR-F34**: La vista de Hitos y avance MUST mostrar `Completar Hito` solo a usuarios autorizados. El modal exige reseña, formato físico y exactamente una fuente inicial entre archivo y URL; la primera versión puede exigir una evidencia y permitir evidencias adicionales posteriormente sin cambiar la cardinalidad `0..N`.
- **FR-F35**: El responsable asignado y el usuario que completa son conceptos distintos. Completar conserva el responsable original y registra por separado `completado_por`; por ejemplo, un responsable puede entregar una cotización al responsable/creador de la Tarea, quien registra la reseña, adjunta la evidencia y completa el Hito sin reasignarlo.
- **FR-F36**: El contrato visual de gestión debe ofrecer, según autorización, `[Editar] [Reasignar] [Completar Hito] [Anular] [Eliminar]`; al responsable del Hito, `[Actualizar avance] [Completar Hito]`; al invitado/observador, ninguna acción de completar. El modal conceptual de completitud contiene `Reseña de cierre *`, `Formato de evidencia *`, `Archivo`, `URL`, `[Cancelar]` y `[Completar Hito]`, preservando XOR archivo/URL.
- **FR-F37**: Todo Hito con `completado=True` MUST ofrecer una acción de solo lectura `Ver cumplimiento Hito`. La consulta MUST mostrar nombre, estado `Completado`, responsable asignado, `completado_por`, `fecha_completado`, `resena_cierre` y todas sus `HitoEvidencia`; no debe modificar, completar nuevamente, reasignar ni conceder permisos adicionales.
- **FR-F38**: La consulta de cumplimiento reutiliza la autorización de lectura vigente sobre la Tarea/Hito y respeta Empresa activa y aislamiento multiempresa. Puede ser utilizada por responsable del Hito, responsable principal, creador, supervisor/autorizador dentro de alcance e invitado/observador cuando su acceso vigente permita leer el Hito; un usuario sin acceso no puede consultar.
- **FR-F39**: La relación de evidencias mostrada en la consulta es `Hito 1 -> 0..N HitoEvidencia`. Debe listar formato, archivo o URL usable, usuario registrador y fecha para cada evidencia, sin mezclar `EvidenciaCierre` de Tarea ni reconstruir los datos principales parseando `HitoHistorial`.
- **FR-F40**: La UI de `Ver cumplimiento Hito` será preferentemente un modal Bootstrap sin inputs editables ni acciones de guardar, editar, reasignar o completar; tendrá como mínimo el título, los datos formales del Hito, la reseña, la tabla/listado de evidencias y el botón `Cerrar`. La futura vista personal T077 MUST reutilizar esta misma consulta canónica.
- **FR-F41**: Un Hito con `completado=True` queda congelado operativamente para preservar trazabilidad. Puede consultarse mediante `Ver cumplimiento Hito` y puede anularse únicamente por el responsable principal de la Tarea, el creador o supervisor/autorizador con facultad vigente de anulación. No puede editarse, reasignarse, completarse nuevamente, actualizarse en avance ni eliminarse físicamente. El responsable exclusivo del Hito no obtiene facultad de anulación por haberlo completado.
- **FR-F42**: Anular un Hito completado conserva `completado=True`, `completado_por`, `fecha_completado`, `resena_cierre`, todas sus `HitoEvidencia` y `HitoHistorial`. La anulación solo lo excluye del avance ponderado y de la operación vigente; no borra ni reemplaza la trazabilidad de completitud.
- **FR-F43**: Los Hitos anulados, incluidos los completados que luego se anulen, quedan excluidos del cálculo de avance ponderado conforme a FR-F18. No se redefine la fórmula vigente.
- **FR-F44**: [NEEDS CLARIFICATION: reactivación de Hito completado anulado] Queda fuera de alcance definir si un Hito con `completado=True` y `anulado=True` vuelve completado, vuelve pendiente, conserva la evidencia como histórico o exige una nueva completitud. No debe inventarse comportamiento hasta resolver esta decisión.

**Key Entities — F**: Avance, Hito (responsable, anulado, completado, completado_por, fecha_completado, resena_cierre, peso, cumplimiento, fecha_creacion), HitoEvidencia, HitoHistorial, Mini-tarea (hecho/no hecho, persona).

---

## G. Fechas, Atrasos y Reprogramación

- **FR-G01**: Toda Tarea formal MUST tener `fecha_tope` para poder publicarse o activarse. `fecha_tope` puede ser NULL técnicamente mientras el registro permanece en `BORRADOR` durante su edición, pero la publicación MUST rechazar una Tarea sin fecha. Una necesidad todavía no formalizada y sin fecha corresponde a TO-DO, no a una Tarea publicada. Con `fecha_tope`, empieza a estar atrasada cuando la fecha de referencia supera dicha fecha; `fecha_tope` es el dato funcional principal.
- **FR-G02**: MUST calcularse `dias_atraso` de forma derivada, sin almacenarlo si puede calcularse. Toda Tarea publicada tiene `fecha_tope`; mientras no esté cumplida, si `fecha_referencia > fecha_tope`, el atraso es la diferencia entre ambas fechas. `fecha_cumplimiento` MUST registrar la fecha/hora real en que se completa la última acción operativa necesaria y, al pasar a `PENDIENTE_APROBACION_CIERRE`, MUST ser el corte del atraso: la aprobación administrativa posterior no suma días. Si el cierre es rechazado y vuelve a `GESTION`, `fecha_cumplimiento` MUST volver a NULL y el intento anterior MUST quedar auditado en `TareaTransicion`; al completarse nuevamente se fija una nueva fecha. La fecha de asignación/publicación MUST conservarse como referencia histórica original y una reasignación no la cambia ni modifica `fecha_tope`.
- **FR-G03**: MUST soportarse múltiples causas de atraso por cada reprogramación. La lista inicial incluye únicamente: imposibilidad técnica, atraso importación, permisos municipales, problemas de escrituras, causas internas y causas externas. La relación `Reprogramacion` ↔ `CausaAtraso` MUST ser M:N y conservar el contexto histórico de cada operación.
- **FR-G04**: La justificación MUST ser obligatoria para reprogramar.
- **FR-G05**: Cambiar una `fecha_tope` ya definida MUST tratarse como reprogramación y ser trazable mediante registro de `fecha_tope` anterior/nueva, justificación obligatoria, usuario, fecha/hora de operación y una o varias causas asociadas. No existe asignación inicial de fecha sobre una Tarea publicada: la fecha debe estar resuelta antes de publicar. La reprogramación explícita no se confunde con la reasignación. La anulación no cambia fechas, no pausa el reloj histórico, no borra atraso ni limpia desempeño; la reactivación conserva las fechas existentes y no recalcula ni extiende la planificación. `fechas_pendientes_confirmacion` se conserva únicamente por compatibilidad histórica, sin semántica nueva en T030.

**Fórmula funcional de atraso**: durante la edición de un `BORRADOR` sin `fecha_tope`, `dias_atraso = 0`; toda Tarea publicada tiene fecha y, si no está cumplida, se calcula la diferencia cuando `fecha_referencia > fecha_tope`; con Tarea cumplida, `fecha_cumplimiento` es el corte; con Tarea anulada, se conserva el atraso histórico generado hasta la anulación sin resetearlo.

**Key Entities — G**: Fechas (asignación, vencimiento), Causa de atraso, Reprogramación.

---

## H. Documentos y Evidencias

- **FR-H01**: Tipos de documento predefinidos: Cotización, Fotografía, Informe, Orden de trabajo, Factura, Contrato, Plano, Certificado, Otro.
- **FR-H02**: Los documentos MUST soportar adjunto (archivo) o URL.
- **FR-H03**: Cada documento MUST registrar fecha de documento y fecha de vencimiento informativa.
- **FR-H04**: Sin control automático de vencimientos por ahora (vencimiento solo informativo; ver R).
- **FR-H05**: Una Tarea puede tener cero o más evidencias de cierre. La exigencia de contar con al menos una evidencia se determina por `Tarea.requiere_evidencia_cierre`, no por la existencia ni por los atributos de una evidencia individual.
- **FR-H06**: Los documentos MUST mantener historial.
- **FR-H07**: La evidencia de cierre es propia de la Tarea, se modela como una relación de múltiples registros y debe poder registrarse directamente con `formato_archivo` físico y exactamente un archivo o una URL, sin exigir un `DocumentoTarea` previo. Cada envío crea una evidencia independiente y no reemplaza automáticamente evidencias anteriores. El catálogo inicial compartido es `PDF`, `JPG`, `JPEG`, `PNG`, `DOC`, `DOCX`, `XLS` y `XLSX`; no se fija todavía un catálogo exhaustivo.
- **FR-H08**: La interfaz debe mostrar la configuración de cierre por separado y listar las evidencias con formato físico, fuente archivo/URL, usuario y fecha; no debe presentar el tipo documental (`Cotización`, `Informe`, etc.) como sustituto del formato físico. La validación debe exigir coherencia entre el formato declarado y la extensión real, con comparación insensible a mayúsculas; `JPG` y `JPEG` forman una familia equivalente, mientras `DOC`/`DOCX` y `XLS`/`XLSX` permanecen distintos. La relación histórica opcional con `DocumentoTarea` puede conservarse sin ser la fuente principal de la UI.
- **FR-H09**: `HitoEvidencia` acredita la completitud de un Hito específico y no sustituye ni reutiliza funcionalmente `EvidenciaCierre`, que acredita el requisito global de cierre de una Tarea. Ambas entidades mantienen relaciones, cardinalidad y validaciones independientes.

**Key Entities — H**: Documento (tipo documental, archivo/url, `formato_archivo`, fecha_documento, fecha_vencimiento), configuración de Tarea (`requiere_evidencia_cierre`), Evidencia de cierre propia de la Tarea (múltiples registros con formato físico, archivo/url, usuario y fecha), HitoEvidencia, Historial.

---

## I. Cotizaciones

- **FR-I01** `[PARCIAL — mínimo PRE-P2 implementado; evolución local planificada]`: Una tarea MUST poder requerir o no cotización; si la requiere, MUST existir un mínimo configurable por tarea, con valor predeterminado de 3 cotizaciones por ronda.
- **FR-I02** `[PLANIFICADA — requiere proveedor local]`: MUST soportar un máximo de 3 versiones por `(ronda, proveedor)`, validado transaccionalmente por servicio.
- **FR-I03** `[IMPLEMENTABLE AHORA]`: Las cotizaciones MUST organizarse por rondas; MUST existir histórico por ronda y MUST poder abrirse una nueva ronda.
- **FR-I04** `[IMPLEMENTABLE AHORA]`: El mínimo de cotizaciones MUST poder cambiar en una nueva ronda.
- **FR-I05** `[PLANIFICADA — requiere proveedor local]`: MUST existir una última cotización válida por proveedor.
- **FR-I06** `[PLANIFICADA — requiere proveedor local]`: Los estados internos deben permitir identificar la participación y la selección de una cotización/proveedor dentro de Django.
- **FR-I07** `[PLANIFICADA — requiere proveedor local]`: El proveedor seleccionado dentro de Django MUST ser visible.
- **FR-I08** `[PARCIAL — PRE-P2 por cotizaciones; evolución local planificada]`: El cierre MUST bloquearse si no se cumple el mínimo configurable de proveedores Django distintos cuando aplique.

**Key Entities — I**: Cotización (proveedor, ronda, versión, vigente, monto, estado), Adjudicación.

### Contrato interno de Cotización para T045

La `Cotizacion` PRE-P2 se implementa sin identidad de proveedor. Sus estados canónicos mínimos son `RECIBIDA` (registrada y disponible para evaluación), `SELECCIONADA` (elegida dentro de Django) y `DESCARTADA` (no seleccionada o descartada). `SELECCIONADA` representa una elección interna de Django; no crea todavía una entidad `Adjudicacion`.

Además de su `ronda`, la cotización debe conservar `version` como entero positivo, `monto` como valor decimal no negativo, `vigente` como indicador histórico independiente del estado, `fecha_cotizacion` como fecha indicada en la cotización o documento recibido y `observaciones` como texto opcional para notas internas. No se agregan fechas de estado ni timestamps funcionales adicionales en T045.

Una cotización puede tener cero o más `DocumentoCotizacion`. Cada documento debe contener formato físico, archivo o URL, usuario y fecha; archivo y URL son excluyentes y se reutiliza el catálogo canónico `PDF`, `JPG`, `JPEG`, `PNG`, `DOC`, `DOCX`, `XLS`, `XLSX`. No se duplica tarea, empresa ni identidad de proveedor.

Las cotizaciones son históricas: recibir otra versión no elimina ni sobrescribe las anteriores; `vigente` permite distinguir la versión actual cuando corresponda. La futura relación `Cotizacion.proveedor` hacia el maestro local será nullable durante la transición para preservar cotizaciones PRE-P2 con `proveedor=NULL`; no se hará backfill inventado. Las nuevas cotizaciones creadas después de esa evolución deberán exigir proveedor.

### Regla contractual de cierre por cotizaciones para T046

Una Tarea queda sujeta al requisito de cotizaciones cuando tiene al menos una `RondaCotizacion` asociada. La existencia de la ronda es la señal explícita de inicio del proceso: evita duplicar un booleano en `Tarea`, no obliga cotizaciones a todas las tareas y mantiene la decisión dentro del dominio de cotizaciones.

En el estado PRE-P2, el mínimo de una ronda se calcula como la cantidad de `Cotizacion` internas asociadas a esa ronda con `vigente=True`. Tras incorporar el maestro local, evolucionará a la cantidad de proveedores Django distintos con al menos una cotización `vigente=True` en esa ronda. Los estados `RECIBIDA`, `SELECCIONADA` y `DESCARTADA` no excluyen por sí solos del conteo; `vigente=False` no computa.

El cierre controla la última ronda de la Tarea por `numero`. Si esa ronda está `ABIERTA`, se evalúa su propio `minimo_cotizaciones`; no se suman cotizaciones de rondas anteriores. Las rondas anteriores permanecen históricas y cada ronda conserva su mínimo independiente. Una ronda no puede pasar a `CERRADA` si no satisface su mínimo interno PRE-P2, y cerrarla no selecciona una cotización ni adjudica un proveedor.

Cuando se abre una nueva ronda como continuación de otra, hereda `minimo_cotizaciones` de la ronda anterior. La primera ronda que no recibe una configuración explícita usa el default contractual de 3. Crear una nueva ronda conserva la anterior y asigna el siguiente `numero`.

El conteo no suma proveedores entre rondas. P2 no bloqueará esta evolución local; solo bloqueará la validación, conciliación y sincronización con ERP legacy.

---

## J. Proveedores

- **FR-J01** `[PLANIFICADA — MAESTRO LOCAL DJANGO]`: MUST existir un maestro global de proveedores en una nueva `APPLICATION_APP` transversal `proveedores`.
- **FR-J02** `[FUTURA — CONTRATO LOCAL PENDIENTE]`: Evaluación manual 1–5 del proveedor: malo / deficiente / regular / normal / sobresaliente.
- **FR-J03** `[FUTURA — CONTRATO LOCAL PENDIENTE]`: El responsable líder podrá calificar al proveedor cuando ese flujo se autorice.
- **FR-J04** `[FUTURA — CONTRATO LOCAL PENDIENTE]`: Podrá existir promedio global del proveedor.
- **FR-J05** `[DEFERRED — P2 LEGACY]`: Vínculo con legacy mediante identificador externo, lookup, validación, conciliación y sincronización; no es requisito para operar con el maestro Django.

**Key Entities — J**: `Proveedor` como maestro global local de Django. El contrato inicial
incluye `id`, `rut`, `nombre`, `direccion`, `comuna`, `ciudad`, `fono1`, `fono2`, `fax`,
`contacto`, `email1`, `email2`, `activo`, `created_at` y `updated_at`. No incluye todavía
`convenio`, `visitas`, `ProveedorEmpresa`, identificador legacy ni sincronización ERP.

### Contrato T084: maestro y VICMEAS

- La Vista VICMEAS canónica del maestro es `Proveedores - Maestro`.
- El `route_name` canónico del listado principal es `proveedores:listado`.
- La etiqueta visible del menú es `Proveedores`; su visibilidad depende de `Permiso.ver`.
- T084 usa `ingresar` para listado/detalle, `crear` para alta, `modificar` para edición y
	reactivación, y `eliminar` exclusivamente para inactivación lógica (`activo=False`).
- T084 no usa `autorizar` ni `supervisor`.
- No existe eliminación física en T084. Inactivar conserva el registro, el RUT y la
	historia; la inactivación no libera la unicidad del RUT. Reactivar establece
	`activo=True` y requiere `modificar`, nunca `eliminar`.
- El registro de la Vista se realizará mediante un seed idempotente dentro de
	`proveedores`, preferentemente un management command propio; no se modifica el seed
	global de otras apps.
- `Proveedor` es global: el maestro y sus listados no se filtran por empresa ni agregan
	`empresa_id`. La empresa activa participa únicamente en la resolución de autorización
	VICMEAS según el mecanismo existente.
- La integración del menú usará el grupo existente más coherente si existe uno definido.
	No se inventa un grupo nuevo `Maestros`; si no hay ubicación canónica, esa decisión se
	resolverá durante la implementación sin bloquear el backend ni el CRUD.

### Estado de implementación del bloque J

El maestro local J queda planificado independientemente de P2. Un proveedor puede existir
sin RUT; cuando exista, el RUT se normaliza y es único globalmente incluso si el proveedor
queda inactivo. La inactivación es lógica y no permite reutilizar el RUT. `visitas` queda
DEFERRED por semántica legacy no resuelta y `convenio` se reserva para una futura relación
`ProveedorEmpresa`.

### Estado de implementación frente a P2

- T044-T048 conservan su implementación y documentación histórica PRE-P2.
- El maestro local, la relación nullable `Cotizacion.proveedor`, el conteo distinto y el
	máximo por `(ronda, proveedor)` se implementarán mediante nuevas tasks, sin backfill inventado.
- P2 bloquea únicamente lookup ERP, validación legacy, identificador externo, conciliación,
	sincronización y actualización desde ERP.
- La selección `SELECCIONADA` sigue siendo interna de Django; `Adjudicacion` queda diferida.

---

## K. Notificaciones y Email

- **FR-K01**: Notificación interna por: asignación, lectura, aceptación/rechazo (cuando aplique), comentarios, documentos, cambio de responsable, vencimientos, aprobaciones, rechazo de cierre, cierre, anulación, reactivación, cambios clave.
- **FR-K02**: Las tareas críticas MUST notificar por sistema Y por email.
- **FR-K03**: Las notificaciones MUST soportar leídas/no leídas.
- **FR-K04**: MUST reutilizar la infraestructura existente (`notificaciones`, email de `acounts`); MUST NOT crear un subsistema paralelo.

Para T054, las notificaciones in-app deben usar el adaptador local
`notify_task_event(...)` y el correo automático de sistema debe usar
`send_task_email(...)`, que delega en `send_email_for_purpose(...)` con
`purpose="notifications"`; no se debe usar el SMTP personal del actor ni
interpretar `email_enabled` como opt-in u opt-out de este canal.

### Contrato funcional T054 (`DEFERRED_BY_CONTRACT`)

- Asignación o reasignación: notificar al nuevo responsable y a los participantes
	afectados cuando el flujo real los incluya; el actor no se duplica como destinatario.
- Lectura: solo registra `TareaLectura`; no genera notificación in-app ni email.
- Comentarios: no existe todavía modelo, servicio ni UI funcional de comentarios en
	`tareas`; el evento de notificación por comentario queda diferido hasta que exista
		esa feature. Esta ausencia bloquea la implementación completa de T054 por contrato;
	T054 queda `DEFERRED_BY_CONTRACT` y no debe crear la feature de comentarios.
- Documento agregado: notificar al creador (`Tarea.creada_por`), responsable y
	participantes, excluyendo al actor y duplicados.
- Cambio relevante: se limita a responsable, `fecha_tope`, prioridad/clasificación,
	reprogramación o estado funcional. No incluye correcciones ortográficas, descripción
	menor ni campos administrativos. Notificar al responsable y participantes, excluyendo
	al actor y duplicados.
- Solicitud de aprobación de cierre: al pasar a `PENDIENTE_APROBACION_CIERRE`, los
	destinatarios son todos los `TareaParticipante` activos de esa Tarea cuyo rol sea
	`AUTORIZADOR`, deduplicados por usuario. No se incluyen automáticamente todos los
	usuarios con permiso VICMEAS `modificar`, los `SUPERVISOR`, los demás participantes ni
	usuarios de otras Tareas.
- Si la Tarea no tiene ningún `TareaParticipante` activo con rol `AUTORIZADOR`, se usa
	`Tarea.creada_por` como destinatario fallback cuando exista y sea válido. Este fallback
	evita dejar una solicitud de cierre sin destinatario y no convierte a `creada_por` en
	`AUTORIZADOR`.
- `SUPERVISOR` no recibe automáticamente la solicitud; solo la recibe si el contrato
	futuro lo establece expresamente o si además tiene participación como `AUTORIZADOR`.
	Los roles no se mezclan.
- VICMEAS determina si un usuario puede ejecutar una acción HTTP, como aprobar o rechazar,
	según el endpoint y `vista_nombre`. El rol funcional
	`TareaParticipante.AUTORIZADOR` determina a quién se dirige la solicitud de esta Tarea;
	el permiso VICMEAS no se usa como lista automática de destinatarios. La ejecución
	posterior recibe el usuario actor en `approve_closure(tarea, usuario)` y registra
	`TareaCierre.usuario`.
- Aprobación o rechazo de cierre: notificar al responsable y creador, excluyendo al actor
	y duplicados.
- Anulación o reactivación: notificar al creador, responsable y participantes, excluyendo
	al actor y duplicados, conforme a FR-E08.
- El canal normal de estos eventos es in-app. Cuando `Tarea.prioridad == CRITICA`, se
	usan in-app y email automático de sistema. El email usa `send_task_email(...)` y nunca
	`UserPreferences`, `email_enabled` ni el SMTP del actor.
- La deduplicación se realiza por usuario dentro de cada evento y canal; no se crea una
	política global nueva de `dedupe_key` en esta definición.
- Las notificaciones de T054 son efectos secundarios posteriores a una operación de
	negocio ya persistida. Un fallo in-app o de email no revierte la operación principal,
	no debe producir un error HTTP que haga parecer que falló y debe registrarse mediante
	logging. No se implementan retries ni colas, ni se modifica infraestructura CORE.
	Los adaptadores T053 continúan propagando errores cuando se invocan directamente; la
	tolerancia pertenece únicamente a este orquestador T054.

**Key Entities — K**: Notificación de tarea (tipo, leída/no leída), canal (sistema/email).

---

## L. Dashboards y KPI

- **FR-L01**: Dashboard Usuario: urgentes/por vencer arriba; acordeones por prioridad; tareas donde es responsable directo o participante activo, diferenciando invitado/observador; leído/no leído manual; vista Equipo para jefaturas; acumulación de trabajo.
- **FR-L02**: Dashboard Jefatura/General MUST mostrar exactamente estos ocho KPI: total de tareas por estado, tareas atrasadas, tareas próximas a vencer, tareas sin movimiento, tareas esperando aprobación, carga abierta por responsable, porcentaje de cumplimiento y tiempo promedio de cierre.
- **FR-L03**: Dimensiones activas con drill-down: General → Empresa → Departamento → Usuario → Tarea. Local queda DEFERRED por P1; Proveedor podrá incorporarse desde el maestro local cuando exista contrato de lectura.
- **FR-L04**: Los mismos ocho KPI por cada dimensión activa: General, Empresa, Departamento, Usuario y Tarea. No se habilitan dimensiones adicionales.
- **FR-L05**: Presentación con DataTables, modal "Ver info de la tarea" y opción de abrir la tarea completa.
- **FR-L06**: La dimensión Local depende de P1; Proveedor dependerá del maestro Django local y no del ERP para su operación básica.
- **FR-L07**: Los ocho KPI de FR-L02 MUST repetirse en cada dimensión permitida del drill-down; no se definirán KPI adicionales por dimensión.
- **FR-L08**: El dashboard personal MUST mostrar las tareas donde el usuario es responsable directo, las tareas donde participa mediante `TareaParticipante` activo y los hitos donde el usuario es responsable directo, aunque no sea responsable de la tarea padre.
- **FR-L09**: Los hitos del dashboard personal MUST agruparse para presentación según `Tarea.prioridad` de la tarea padre. La prioridad canónica usa exactamente `SIMPLE`, `NORMAL`, `URGENTE` y `CRITICA`, con jerarquía `CRITICA > URGENTE > NORMAL > SIMPLE`; no se crea una dimensión `clasificacion`, el hito no tiene clasificación propia y no se agrega un campo `prioridad` al hito.
- **FR-L10**: Cada hito mostrado en el dashboard personal MUST identificar conceptualmente tipo `HITO`, nombre, correlativo y título de la tarea padre, prioridad heredada desde `Tarea.prioridad`, cumplimiento, peso, responsable y enlace a la pantalla existente de Hitos de su Tarea (`/tareas/<tarea_pk>/hitos/`). La navegación MUST conservar Tarea → Hito sin convertir el hito en tarea independiente; T077 no crea una vista ni un enlace de detalle individual de Hito.
- **FR-L11**: El dashboard personal MUST mostrar como asignación pendiente solo Hitos con `responsable == usuario` y `anulado == False`; los Hitos anulados no aparecen como pendientes, aunque pueden aparecer en vistas históricas cuando corresponda.

**Key Entities — L**: Dashboard (dimensión), KPI, Drill-down.

### Estado de dimensiones KPI

- **ACTIVAS AHORA**: General, Empresa, Departamento, Usuario, Tarea.
- **DEFERRED**: Local — bloqueada por P1; integración ERP de Proveedor — bloqueada por P2. El maestro local de Proveedor queda planificado.
- Catálogo cerrado: total de tareas por estado; atrasadas; próximas a vencer; sin movimiento;
	esperando aprobación; carga abierta por responsable; porcentaje de cumplimiento; tiempo
	promedio de cierre.

### Contrato operativo cerrado de T059

Para los ocho KPI V1, la población operativa excluye `BORRADOR` y toda Tarea con
`anulada=True`. Los estados publicados son `ACTIVA`, `GESTION`,
`PENDIENTE_APROBACION_CIERRE` y `CERRADA`. Cada Tarea persistida cuenta como una
unidad independiente, incluyendo padres, hijas y nietas válidas; los Hitos no se
suman como Tareas. Los KPI de estado actual usan `timezone.localdate()` como fecha
de referencia y no crean snapshots históricos.

1. **Total por estado**: cuenta una vez cada Tarea publicada no anulada según su
	estado actual, solo en `ACTIVA`, `GESTION`, `PENDIENTE_APROBACION_CIERRE` o
	`CERRADA`.
2. **Atrasadas**: cuenta Tareas no anuladas en `ACTIVA`, `GESTION` o
	`PENDIENTE_APROBACION_CIERRE`, con `fecha_tope` no nula,
	`fecha_tope < fecha_referencia` y `fecha_cumplimiento IS NULL`. No cuenta
	`CERRADA`; una Tarea cumplida deja de estar actualmente atrasada.
3. **Próximas a vencer**: cuenta Tareas no anuladas en `ACTIVA`, `GESTION` o
	`PENDIENTE_APROBACION_CIERRE`, con `fecha_cumplimiento IS NULL` y
	`fecha_tope` entre `fecha_referencia` y `fecha_referencia + 7 días` inclusive.
	No incluye vencidas ni `CERRADA`.
4. **Sin movimiento**: cuenta Tareas abiertas no anuladas cuyo último movimiento
	operativo sea igual o anterior a `now() - 7 días`. El último movimiento es el
	máximo timestamp disponible de publicación/creación operativa, última
	`TareaTransicion`, última actividad persistida de Hito, último DocumentoTarea
	agregado mediante su historial y, solo si existiera, modificación propia de
	Tarea. No cuentan lecturas, aperturas de enlaces, dashboards ni notificaciones.
	No se crea `ultima_actividad`.
5. **Esperando aprobación**: cuenta una vez cada Tarea no anulada con
	`estado=PENDIENTE_APROBACION_CIERRE`; no cuenta transiciones históricas ni
	multiplica por autorizadores.
6. **Carga abierta por responsable**: cuenta Tareas no anuladas en
	`ACTIVA`, `GESTION` o `PENDIENTE_APROBACION_CIERRE` cuyo `responsable` sea el
	usuario. No pondera prioridad ni incluye participantes, invitados, creador,
	supervisor, autorizador ni Hitos.
7. **Porcentaje de cumplimiento**: `CERRADA / total_publicadas * 100`, donde el
	numerador son Tareas `CERRADA` no anuladas y el denominador son todas las Tareas
	publicadas no anuladas. Si el denominador es cero, devuelve `0.00`; se redondea
	a dos decimales. No equivale al avance ponderado de Hitos.
8. **Tiempo promedio de cierre**: sobre Tareas `CERRADA` no anuladas con
	`fecha_publicacion` y `fecha_cumplimiento`, promedia en horas calendario
	`fecha_cumplimiento - fecha_publicacion`. Excluye registros sin ambas fechas y
	no usa creación de borrador ni aprobación como inicio.

El dashboard personal mantiene la autorización `Tareas - Dashboard personal` con
`ingresar` y, dentro de la Empresa activa, muestra responsabilidad directa,
participación activa e Hitos no anulados asignados al usuario. Usa `TareaLectura`
para leído/no leído, destaca `CRITICA` y `URGENTE`, muestra próximas a vencer,
agrupa por prioridad y diferencia participante/invitado. Creador, supervisor y
autorizador no se incorporan por esos roles únicamente.

El dashboard general y sus dimensiones usan `Tareas` con `supervisor`, evaluado por
Empresa. General agrega exclusivamente Empresas autorizadas al usuario; Empresa
restringe por `Tarea.empresa_id`; Departamento incluye solo
`tipo_ambito=DEPARTAMENTO` y el `departamento_id` seleccionado; Usuario agrupa por
`Tarea.responsable` sin duplicar por participantes; Tarea muestra el contexto de
una única Tarea sin fabricar agregados. No se inserta Local en el drill-down.

T059 calcula los KPI bajo demanda, sin modelo, snapshots, cache persistente ni
migración. Su servicio entrega a T060 exactamente los ocho KPI, dimensión, filtros,
filas, estado, prioridad, fechas relevantes, enlaces de navegación y datos mínimos
del modal; no genera HTML. T060 es responsable de DataTables, cards, acordeones,
modal y presentación visual. T060 puede completar la orquestación HTTP mínima y
el render server-side para convertir ese contexto en páginas HTML, sin mover las
fórmulas ni duplicar consultas de KPI en las vistas.

### Contrato de filas y presentación T060

Las filas de dashboard son navegables y conservan los ocho KPI de T059:

- **General**: una fila por Empresa autorizada, con `empresa_id`, código/nombre,
	resumen operativo y URL al siguiente nivel.
- **Empresa**: una fila por Departamento disponible y un bloque separado para
	Tareas `LOCAL` o sin Departamento histórico. Estas Tareas siguen contando en
	los KPI de Empresa y no se colocan en un Departamento ficticio.
- **Departamento**: una fila por responsable/Usuario con Tareas en ese
	Departamento.
- **Usuario**: una fila por Tarea cuyo responsable sea ese Usuario.

Las filas de Tarea incluyen como mínimo `id`, correlativo, título, estado,
prioridad, responsable, `fecha_tope`, `fecha_publicacion`, `tipo_ambito` y URL
de detalle. La dimensión Tarea reutiliza el detalle existente para navegación
completa y no requiere una ruta redundante.

El modal contractual `Ver info de la tarea` es de solo lectura y puede usar
datos embebidos en atributos `data-*` o el contexto existente. Muestra
correlativo, título, descripción resumida, estado, prioridad, responsable, fecha
de publicación, fecha tope, ámbito, Local o Departamento cuando corresponda y
el enlace `Ver detalle completo`. No contiene edición, publicación, cierre,
anulación ni reasignación.

DataTables se aplica exclusivamente a las tablas de dashboard y drill-down que
necesiten búsqueda, orden, paginación o filtros visuales. No se aplica por
defecto a formularios, reuniones pequeñas, gestión de enlaces ni similitud.

El dashboard personal conserva `mis-tareas/` y usa el contexto de T059
(`priority_groups`, `tareas`, `hitos`, `read_status`, `upcoming_tasks` y
`filters`) sin modificar fórmulas KPI.

La presentación de T060 puede usar JavaScript app-local, preferentemente en
`tareas/static/tareas/js/dashboard.js`, `similarity.js` y `task_links.js`.
`static/js/app.js` y cualquier vendor son inmutables. Todo texto estático nuevo
visible usa `data-key`; los títulos, usuarios, fechas, correlativos y nombres
dinámicos no reciben `data-key`. Los diccionarios de idioma no se modifican como
parte de T060.

---

## M. Reuniones de Revisión

- **FR-M01**: Debe existir un botón/acción "reunión de revisión".
- **FR-M02**: La reunión se convoca sobre un subconjunto homogéneo de tareas de una Empresa, con ámbito explícito `LOCAL` o `DEPARTAMENTO`; todas las tareas deben compartir ese ámbito. No se exige compartir responsable, prioridad ni clasificación.
- **FR-M03**: Modalidad Zoom o presencial.
- **FR-M04**: La acción explícita `CONVOCAR` envía email automático de sistema y notificación in-app a los convocados seleccionados explícitamente para esa reunión; crear o editar no convoca.
- **FR-M05**: La reunión es una tarea planificada.
- **FR-M06**: La reunión tiene agenda por prioridades descendentes y orden manual dentro de cada prioridad; puede mezclar prioridades.
- **FR-M07**: El cierre de la reunión registra comentarios por tarea.

**Key Entities — M**: Reunión (modalidad, agenda, comentarios), Subconjunto de tareas.

### Contrato visual de reuniones T060

El detalle de reunión reutiliza el backend T055 existente y debe exponer UI para
agregar una Tarea a la agenda, agregar un participante, marcar `REALIZADA` y
registrar el comentario de revisión/cierre por Tarea. No se crea lógica paralela
ni se exige eliminación cuando el backend/contrato no la define.

---

## N. Origen, Derivación y Similitud

- **FR-N01**: Una tarea MUST poder tener como máximo un origen canónico directo: otra tarea, un TO-DO o ninguno. Una tarea no puede tener simultáneamente `todo_origen` y `tarea_origen`.
- **FR-N02**: El historial de origen MUST ser accesible en lectura.
- **FR-N03**: MUST NOT convertir una tarea antigua en la nueva: se crea una nueva y se referencia. Cadenas históricas permitidas.
- **FR-N04**: Durante el flujo de publicación de una Tarea nueva, el sistema MUST obtener el umbral efectivo mediante `get_similarity_threshold(tarea.empresa)`, evaluar candidatas de la misma Empresa con `evaluate_task_similarity(tarea=tarea, threshold=threshold)` y advertir cuando exista al menos una evaluación con `supera_umbral=True` y `decision=PENDIENTE`. Las evaluaciones relevantes pueden persistirse antes de publicar, pero mientras exista una coincidencia pendiente sobre el umbral la Tarea MUST permanecer en `BORRADOR` y la publicación MUST quedar suspendida; no se permite publicar y despublicar. El umbral predeterminado de 80% y su configuración por Empresa pertenecen a T057; T056 no MUST hardcodear ni persistir configuración empresarial.
- **FR-N05**: La evaluación de similitud MUST incluir Tareas en estado `ACTIVA`, `GESTION`, `PENDIENTE_APROBACION_CIERRE` y `CERRADA`. MUST excluir `BORRADOR`, cualquier Tarea con `anulada=True` y la propia Tarea evaluada.
- **FR-N06**: El usuario MUST confirmar "es el mismo problema nuevamente" o "DISTINTO_PROBLEMA" para una coincidencia relevante; mientras la decisión sea `PENDIENTE` no se modifica el origen. Aun confirmando `MISMO_PROBLEMA`, la tarea evaluada es NUEVA.
- **FR-N07**: La nueva tarea MUST poder mantener una o varias referencias históricas o de similitud a tareas antiguas si corresponde; estas referencias no sustituyen ni multiplican el origen canónico único.
- **FR-N08**: Cambio de repuesto MUST NOT implicar automáticamente "mismo problema".
- **FR-N09**: El umbral de similitud MUST ser configurable por empresa; solo usuarios autorizados podrán modificarlo y cada cambio MUST aplicar únicamente a nuevas evaluaciones de similitud.

**Key Entities — N**: Origen/derivación, Relación de similitud, Cadena histórica, Umbral (80%).

### Contrato de similitud T056

La evaluación se limita estructuralmente a la Empresa de la Tarea evaluada; una
Tarea de otra Empresa nunca puede ser candidata y la Empresa no participa en el
porcentaje. Si ambas Tareas tienen dimensión organizacional definida, solo se
comparan cuando comparten el mismo tipo y referencia: `LOCAL` con el mismo
`Local`, o `DEPARTAMENTO` con el mismo `Departamento`. `LOCAL` y
`DEPARTAMENTO` nunca se comparan entre sí. Las Tareas históricas sin dimensión,
creadas antes de T093, no se descartan automáticamente: pueden compararse por
texto dentro de la misma Empresa. Si solo una de las dos Tareas tiene dimensión,
la comparación también puede realizarse por texto dentro de la misma Empresa.

El score V1 representa semejanza del problema y usa únicamente `titulo` y
`descripcion`. Cada valor se normaliza con `casefold`, `strip` y espacios
múltiples antes de compararlo; los valores vacíos se normalizan de forma segura.
El algoritmo es `difflib.SequenceMatcher` de la biblioteca estándar, sin nuevas
dependencias:

```text
score_titulo = similitud(titulo, titulo_candidata)
score_descripcion = similitud(descripcion, descripcion_candidata)
score_final = score_titulo * 0.60 + score_descripcion * 0.40
porcentaje = round(score_final * 100, 2)
```

Prioridad, estado, responsable, creador, fechas, Local y Departamento no
alteran el porcentaje; solo estado, Empresa y ámbito participan en la selección
contextual. Una coincidencia textual alta no equivale por sí misma a
`MISMO_PROBLEMA`: la decisión humana debe distinguir, entre otros casos, un
cambio de repuesto o una intervención diferente.

El servicio de dominio debe exponer operaciones equivalentes a:

```text
evaluate_task_similarity(*, tarea, threshold)
confirm_similarity(*, evaluacion, decision, actor)
```

`evaluate_task_similarity` valida la Empresa, obtiene y filtra candidatas,
calcula y persiste una evaluación por pareja, y devuelve las coincidencias
ordenadas por `porcentaje` descendente y luego por identificador de candidata
ascendente. `threshold` es un argumento explícito; T056 no crea
`UmbralSimilitudEmpresa`. `confirm_similarity` registra la decisión y el actor;
solo una evaluación de una misma Tarea puede establecer el origen canónico
directo `tarea_origen`.

La evaluación ocurre antes o durante la publicación: primero se persisten las
evaluaciones relevantes, luego se advierte si alguna supera el umbral y la UI
posterior solicita la decisión. Si no existen coincidencias relevantes
pendientes, la publicación continúa normalmente mediante `publish_task()`.
Mientras exista alguna pendiente, la publicación no continúa. Una coincidencia
nunca bloquea la creación ni transforma la Tarea nueva en la candidata.

Con `MISMO_PROBLEMA`, la nueva Tarea sigue siendo independiente, la candidata
permanece exactamente en su estado actual y nunca se reabre ni se reactiva una
Tarea `CERRADA`; puede establecerse `tarea_origen` hacia esa candidata si la
nueva Tarea aún no tiene `todo_origen` ni otro `tarea_origen`. Con
`DISTINTO_PROBLEMA`, no se establece `tarea_origen` y la evaluación queda como
trazabilidad. Varias evaluaciones pueden marcarse como `MISMO_PROBLEMA`, pero
solo una puede convertirse en origen canónico; las demás permanecen como
referencias de similitud.

T056 conserva una evaluación vigente por pareja `(tarea, tarea_candidata)` y no
define historial de reevaluaciones; la pareja es única. Los cambios de umbral de
T057 solo afectan evaluaciones nuevas. T060 es responsable de templates,
advertencia, confirmación y de la orquestación HTTP mínima de este flujo; T056 no
crea UI ni nuevas rutas.

### Contrato HTTP y visual de similitud T060

La superficie HTTP mínima de T060 es:

- `GET /tareas/<tarea_id>/similitud/`: muestra las evaluaciones de la Tarea,
	restringidas a su Empresa activa y autorizadas por el flujo de ciclo de vida.
- `POST /tareas/<tarea_id>/similitud/<evaluacion_id>/confirmar/`: recibe
	exclusivamente `MISMO_PROBLEMA` o `DISTINTO_PROBLEMA` y delega en
	`confirm_similarity(...)`. La continuación de publicación reutiliza, cuando
	corresponda, el POST existente de publicación; no se crea una API REST
	paralela.

La autorización de ambas operaciones reutiliza
`vista_nombre="Tareas - Ciclo de vida"` y `permiso_requerido="modificar"`.
La Tarea, la evaluación y la candidata deben pertenecer a la Empresa activa.
Los errores de `ValidationError`, incluido el intento de establecer un segundo
origen incompatible, se muestran mediante respuesta controlada.

La vista `tareas/templates/tareas/tarea_similitud.html` debe mostrar todas las
evaluaciones con `supera_umbral=True`, ordenadas por porcentaje descendente, con
correlativo de candidata, título, estado, prioridad, porcentaje, umbral
aplicado, indicador de cierre, decisión actual y enlace de solo lectura al
detalle cuando exista autorización. Debe permitir resolver cada evaluación
relevante y continuar la publicación sólo cuando no queden decisiones
`PENDIENTE`; no permite editar la Tarea histórica.

### Contrato de umbral T057

`UmbralSimilitudEmpresa` mantiene como máximo una configuración por Empresa,
mediante una relación `OneToOneField` obligatoria y `on_delete=PROTECT`. El
porcentaje persistido es un `DecimalField(max_digits=5, decimal_places=2)` y
debe cumplir `0.00 <= porcentaje <= 100.00`; no existe un mínimo práctico
adicional.

El valor funcional predeterminado es `Decimal("80.00")`. Si una Empresa no
tiene fila persistida, `get_similarity_threshold(empresa)` devuelve
`Decimal("80.00")` como fallback virtual y no crea ni modifica datos. La
consulta del getter es de solo lectura. El default funcional no obliga a un
default de base de datos ni a crear filas automáticamente.

La fila solo se materializa cuando un usuario autorizado modifica explícitamente
el umbral mediante una operación equivalente a:

```text
set_similarity_threshold(*, empresa, porcentaje, actor)
```

El setter valida el rango, crea la fila si no existe o actualiza la existente,
registra `actualizado_por` y `actualizado_at`, y no recalcula evaluaciones ya
persistidas. La autorización funcional usa VICMEAS con
`vista_nombre="Configuración - Configuracion de Empresa"` y
`permiso_requerido="modificar"`; no se crea una Vista nueva ni un sistema de
permisos paralelo. La aplicación HTTP/UI de esa autorización queda para el
flujo que corresponda.

La integración con T056 obtiene el valor efectivo y lo pasa al servicio
existente, sin duplicar el cálculo:

```text
threshold = get_similarity_threshold(tarea.empresa)
evaluate_task_similarity(tarea=tarea, threshold=threshold)
```

Cambiar el umbral, por ejemplo de `80.00` a `75.00`, solo afecta evaluaciones
posteriores. Las instancias existentes de `EvaluacionSimilitud` conservan
`porcentaje`, `umbral_aplicado`, `supera_umbral`, `decision`,
`confirmada_por` y `confirmada_at`; no se recalculan automáticamente.

T057 implementa únicamente modelo, servicio y tests. No crea templates, forms,
views, URLs ni sidebar; T060 conserva la responsabilidad de la UI de
similitud. No se usan signals, seeds obligatorios, creación automática por
lectura ni migración masiva de datos.

## S. TO-DO y Origen Canónico

- **FR-S01**: TO-DO MUST ser una entidad separada de `Tarea`, perteneciente obligatoriamente a una Empresa. Representa un problema, necesidad, asunto pendiente u observación todavía no formalizado ni planificado como Tarea.
- **FR-S02**: El correlativo de TO-DO MUST usar el namespace propio `TD` y una secuencia independiente por Empresa (`TD0000001`, `TD0000002`); no comparte secuencia numérica con los correlativos A/B de `Tarea`.
- **FR-S03**: TO-DO MUST incluir conceptualmente correlativo, título, descripción, estado, creador, fecha de creación, usuario de cierre, fecha de cierre y comentario de cierre. Representa un asunto aún no formalizado como Tarea y puede existir sin responsable, `fecha_tope` o planificación formal.
- **FR-S04**: Los únicos estados persistentes mínimos de TO-DO son `ABIERTO` y `CERRADO`. Un TO-DO `CERRADO` NO se reabre.
- **FR-S05**: Si el problema reaparece después del cierre, MUST crearse un nuevo TO-DO relacionado históricamente con el anterior; la relación concreta queda pendiente de diseño técnico y no crea todavía un modelo.
- **FR-S06**: Un TO-DO MUST poder originar una o varias Tareas a lo largo del tiempo. Crear una Tarea desde TO-DO genera un registro Tarea nuevo; el TO-DO no se transforma ni desaparece. Cada Tarea originada nace como Tarea normal, conserva `todo_origen`, usa correlativo `B*` en borrador y pasa a `A*` al publicarse, pero MUST tener `fecha_tope` antes de poder publicarse o activarse.
- **FR-S07**: Cerrar una Tarea originada NO cierra automáticamente el TO-DO. El cierre de TO-DO MUST ser explícito y no puede realizarse mientras exista alguna Tarea originada pendiente operativamente; una Tarea `CERRADA` o efectivamente anulada no es bloqueante. La desaparición de la última pendiente no cierra el TO-DO automáticamente.
- **FR-S08**: La creación de una Tarea desde un TO-DO MUST registrar usuario y fecha/hora; el comentario o motivo de derivación es opcional.
- **FR-S09**: Una Tarea MUST tener como máximo un origen canónico: `todo_origen`, `tarea_origen` o ninguno. MUST existir una restricción de exclusión que impida ambos orígenes simultáneamente.
- **FR-S10**: Las referencias históricas, evaluaciones de similitud, jerarquía `TareaRelacion`, clonación y trabajo en equipo son conceptos distintos del origen canónico y no lo reemplazan.
- **FR-S11**: No se usará `GenericForeignKey` para el origen salvo necesidad arquitectónica real; se prefieren FK explícitas a TO-DO y Tarea.
- **FR-S12**: Una Tarea formal puede permanecer técnicamente sin `fecha_tope` solo mientras está en `BORRADOR` y en edición. La publicación/activación MUST exigir `fecha_tope`; una entidad sin fecha que aún no se formaliza como Tarea debe permanecer como TO-DO. TO-DO y Tarea son entidades separadas, y un TO-DO puede generar múltiples Tareas sin transformarse en ninguna de ellas.

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

- **FR-P02**: La visibilidad de las opciones de Tareas en el sidebar se controla por
	`Permiso.ver` para la empresa activa. La autorización al acceder y operar continúa
	usando VICMEAS según la acción (`ingresar`, `crear`, `modificar`, `eliminar`,
	`autorizar` o `supervisor`), con 403 y solicitud de acceso cuando corresponda;
	`V` no sustituye autorización funcional y V/I son independientes.
- **FR-P03**: Enlaces compartibles V1: enlace parametrizado exclusivamente a una Tarea, solo para un usuario autenticado del sistema, con acceso específico de lectura, registro de notificación/acceso y aislamiento multiempresa. El enlace no concede un `Permiso` VICMEAS general ni acceso a otras Tareas.
- **FR-P04**: Visibilidad según rol/participación del usuario.
- **FR-P05**: Sin usuarios externos por ahora (ver R).

### Contrato cerrado de enlaces T058

`EnlaceTarea` tiene un único `destinatario` `User` interno y obligatorio. Para
compartir una Tarea con varios usuarios se crea un enlace independiente por
destinatario. No existen enlaces públicos, acceso anónimo ni usuarios externos.

La Empresa efectiva siempre es `enlace.tarea.empresa`; no se duplica en el
enlace. Crear, abrir, revocar y resolver un enlace deben validar que la Empresa
activa de la sesión coincide con `enlace.tarea.empresa_id` y que el destinatario
es válido para esa Empresa mediante el mecanismo canónico existente. Nunca se
permite acceso cross-empresa.

El enlace usa un token multiuso generado con `secrets.token_urlsafe(32)`. Solo
se entrega el token plano al crearlo; se persiste `SHA-256(token)` en
`token_hash`. El token no es la PK y no se reutiliza el helper de activación de
cuentas. `fecha_expiracion` es obligatoria y debe ser futura al crear el enlace;
T058 no define una duración automática.

El enlace permanece multiuso mientras no esté expirado ni revocado y el usuario
y la Empresa sean válidos. La revocación registra `revocado_at` y
`revocado_por`, conserva el registro para auditoría y rechaza accesos
posteriores. No se consume tras el primer acceso.

Abrir un enlace requiere autenticación mediante `login_required`, conservando
`next` según el flujo estándar de Django. Después del login,
`request.user` debe coincidir exactamente con `enlace.destinatario`. El enlace
constituye una autorización específica de lectura de esa Tarea; no crea ni
modifica `access_control.Permiso`, `TareaParticipante` ni otra autorización
VICMEAS persistente. No permite modificar, publicar, gestionar, cerrar, anular
ni acceder a otras Tareas.

Crear y revocar usan VICMEAS sobre la Vista existente `Tareas` con permiso
`modificar`. Abrir un enlace no requiere un permiso VICMEAS general adicional,
pero sí autenticación, token válido, destinatario exacto, Empresa activa,
vigencia y ausencia de revocación. No se crea una Vista nueva.

Al crear exitosamente un enlace se notifica únicamente al destinatario por
in-app y email automático de sistema, reutilizando `notificaciones` y
`acounts` con `purpose="notifications"`. El contenido incluye Tarea, quién
comparte, Empresa, expiración y URL interna. No se notifica en cada acceso ni
al revocar. Las notificaciones son efectos secundarios: sus fallos se registran
sin revertir el enlace ni crear retries o colas.

Cada acceso con enlace existente crea un `EventoAccesoEnlace`. Los intentos
con token inexistente no crean filas huérfanas; se registran mediante logging o
la auditoría HTTP vigente cuando corresponda. La auditoría global permanece
separada.

### Contrato visual de gestión de enlaces T060

El detalle de Tarea debe ofrecer, según autorización, botón `Compartir`, selector
de destinatario interno válido, fecha/hora de expiración y listado de enlaces
de esa Tarea. El listado muestra destinatario, creador, fecha de creación, fecha
de expiración, estado derivado `ACTIVO`, `EXPIRADO` o `REVOCADO` y acción
`Revocar` cuando corresponda. Reutiliza exclusivamente las rutas y servicios de
T058.

El token plano sólo existe en la respuesta de creación. La UI debe mostrar y
permitir copiar la URL inmediatamente después de crear el enlace. No intenta
reconstruir posteriormente la URL secreta desde `token_hash`; los enlaces ya
creados sólo se listan mediante sus metadatos y estado.

T058 V1 no enlaza Hitos de forma independiente. Si se requiere compartir un
Hito como objeto independiente, debe definirse el contrato separado
`T058_HITO_LINK_NEEDS_SEPARATE_CONTRACT`; no se usará `GenericForeignKey`.

**Key Entities — P**: `EnlaceTarea`, `EventoAccesoEnlace` y autorización
específica de lectura por destinatario, apoyados en `access_control`, sesión,
notificaciones y email existentes.

---

## Q. Reglas de Cierre (consolidación)

- **FR-Q01**: Si `Tarea.requiere_evidencia_cierre = False`, la Tarea puede cerrarse sin evidencias, salvo otra regla contractual. Si `Tarea.requiere_evidencia_cierre = True`, el cierre MUST exigir al menos una EvidenciaCierre válida asociada a la Tarea; no basta con la configuración ni con un registro sin archivo/URL válido.
- **FR-Q02**: El cierre MUST estar bloqueado por mini-tareas pendientes y por descendientes sin cerrar.
- **FR-Q03** `[PARCIAL — PRE-P2 implementado; evolución local planificada]`: Si la tarea requiere cotización, el cierre MUST exigir el mínimo configurable y, tras la evolución local, el mínimo de proveedores Django distintos.
- **FR-Q04**: El cierre MUST requerir aprobación del creador o perfil autorizado.
- **FR-Q05** `[FUTURA — CONTRATO LOCAL PENDIENTE]`: Al cerrar una tarea con proveedor, el responsable líder podrá calificar al proveedor (1–5, ver J) cuando ese flujo sea autorizado; no depende de resolver P2 legacy.
- **FR-Q06**: MUST registrarse quién cerró/canceló y cuándo.

**Key Entities — Q**: Regla de cierre, Evidencia, Cierre/Cancelación (por, fecha).

---

## R. Exclusiones Actuales

- **FR-R01**: Sin usuarios externos por ahora.
- **FR-R02**: Sin plantilla de hitos por ahora.
- **FR-R03**: Sin vencimiento automático de documentos (vencimiento informativo solamente).
- **FR-R04**: Sin prioridad "baja" (solo Simple/Normal/Urgente/Crítica).
- **FR-R05**: Integración real con legacy de LOCALES queda fuera de alcance por P1; la integración ERP de PROVEEDORES queda fuera de alcance por P2, sin bloquear el maestro local.
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
- VICMEAS: `Permiso.ver` para menú y los flags funcionales para autorización y 403 → **FR-P02**.
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

- Se reutilizan usuarios, empresa activa, VICMEAS, notificaciones y email existentes; sin sistemas paralelos.
- Prioridad: SIMPLE/NORMAL/URGENTE/CRITICA, default NORMAL (sin "baja").
- Fechas: UTC almacenamiento, presentación en zona local configurada.
- App `tareas` bajo APPLICATION BOUNDARY; una dependencia externa no se elude localmente y requiere tarea separada.
- Implementación por fases; Fase 1 (borrador/publicada, aislamiento, VICMEAS) ya implementada y válida.

---

## BLOQUEOS LEGACY (explícitos, no supuestos)

- **LOCAL (A/G/L)**: **`LEGACY API PENDIENTE`**. No se define modelo, tabla, endpoint, ID ni sincronización. Se necesita leer del legacy: estructura/tabla de locales, clave de vínculo, disponibilidad por empresa. DETENIDO hasta autorización y revisión del legacy con el usuario.
- **PROVEEDOR (I/J/L)**: maestro global local Django planificado en `APPLICATION_APP proveedores`. La integración ERP/legacy, identificador externo, lookup, conciliación y sincronización quedan como P2 futuro.
- **EQUIPOS/ACTIVOS (O)**: NO se inventa integración legacy de equipos/máquinas; solo se modela el concepto (código global, local, departamento) dentro de `tareas` sin vínculo legacy.

---

## PUNTOS NO RESUELTOS / PENDIENTES

- **P1 (LEGACY)**: Contrato de Local (A) — campos, IDs, sincronización. `LEGACY API PENDIENTE`.
- **P2 (LEGACY)**: integración/validación/conciliación del maestro local de Proveedor contra ERP legacy: lookup, identificador externo, sincronización y actualización desde ERP.
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
| J | Proveedores | FR-J01…J05 | P3 | Definido (maestro local; integración legacy P2) |
| K | Notificaciones y Email | FR-K01…K04 | P2 | Definido |
| L | Dashboards y KPI | FR-L01…L07 | P3 | Definido |
| M | Reuniones de Revisión | FR-M01…M07 | P3 | Definido |
| N | Origen, Derivación y Similitud | FR-N01…N09 | P3 | Definido |
| O | Equipos / Máquinas | FR-O01…O04 | P2 | Definido (sin legacy) |
| P | Seguridad, Multiempresa y Enlaces | FR-P01…P05 | P1 | Definido (Fase 1 implementada) |
| Q | Reglas de Cierre | FR-Q01…Q06 | P2 | Definido |
| R | Exclusiones Actuales | FR-R01…R06 | — | Definido |
| S | TO-DO y Origen Canónico | FR-S01…S12 | P2 | Definido (implementación futura) |
