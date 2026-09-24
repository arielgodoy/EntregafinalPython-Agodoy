# Data Model: Tareas Internas - SPEC MAESTRA

**Date**: 2026-09-07 | **Feature**: [spec.md](spec.md) | **Research**: [research.md](research.md)

## Entidad: `Tarea` (app `tareas`)

| Campo | Tipo (Django) | Nulable | Default | Reglas |
|---|---|---|---|---|
| `id` | BigAutoField (PK) | no | auto | Se conserva exactamente para compatibilidad MVP; no se cambia el tipo ni el valor. |
| `correlativo` | `CharField(max_length=9)` | sí durante backfill, no al finalizar | nullable durante backfill | Constraint única `(empresa, correlativo)`; índice compuesto `(empresa, correlativo)`; formato exacto `A`/`B` + 7 dígitos (`B0000001` borrador / `A0000001` activa-publicada). `TD` queda reservado para TO-DO futuro. Solo se guarda este string; el número no se duplica en `Tarea`. |
| `cierre_completado` | BooleanField | no | `False` | Señal de lifecycle: la tarea alcanzó la condición funcional equivalente al 100% para solicitar cierre; no es porcentaje general de avance. |
| `titulo` | CharField(max_length=200) | no | — | Obligatorio siempre (FR-001). `blank=False`. |
| `descripcion` | TextField | sí (`blank=True, default=""`) | `""` | Opcional en borrador y publicada. |
| `prioridad` | CharField (choices aprobados: `SIMPLE`, `NORMAL`, `URGENTE`, `CRITICA`) | no | `NORMAL` (default aprobado por el usuario) | Valores aprobados: simple < normal < urgente < crítica (jerarquía: crítica > urgente > normal > simple). Default: `NORMAL`. Sin comportamientos adicionales asociados (sin colores, SLA, notificaciones ni vencimientos). |
| `estado` | CharField(choices=Estado) | no | `BORRADOR` | Estados persistentes canónicos del ciclo funcional: `BORRADOR`, `ACTIVA`, `GESTION`, `PENDIENTE_APROBACION_CIERRE`, `CERRADA`. `PUBLICADA` MVP se migra a `ACTIVA`; rechazo y reactivación son eventos/acciones. `ANULADA` deja de ser estado canónico (la anulación es un flag separado). |
| `anulada` | BooleanField | no | `False` | Flag de anulación, independiente del `estado` funcional. Anular pone `anulada=True`; reactivar pone `anulada=False`. NO cambia `estado` ni ningún otro dato. La condición efectiva es lógica (`anulada_efectivamente`), no una cascada física. |
| `responsable` | FK(`auth.User`, on_delete=PROTECT, related_name="tareas_responsable") | sí (`null=True, blank=True`) | `None` | Opcional en borrador (FR-004); obligatorio y válido en publicada (FR-007/FR-008). PROTECT evita borrar un usuario con tareas asignadas. |
| `empresa` | FK(`access_control.Empresa`, on_delete=PROTECT, related_name="tareas") | no | — | Asignada desde `session['empresa_id']` al crear (FR-003); nunca editable desde el request. |
| `creada_por` | FK(`auth.User`, on_delete=PROTECT, related_name="tareas_creadas") | no | — | Auditoría mínima coherente con el sistema. |
| `fecha_creacion` | DateTimeField(auto_now_add=True) | no | auto | UTC (D9). |
| `fecha_publicacion` | DateTimeField | sí (`null=True, blank=True`) | `None` | Se fija solo al publicar; inmutable después (D4). |
| `fecha_asignacion` | DateTimeField | sí (`null=True, blank=True`) | `None` | Se fija al publicar/asignar oficialmente; es histórica y no cambia por reasignación. |
| `fecha_tope` | DateField | sí (`null=True, blank=True`) | `None` | Nullable técnicamente solo durante edición en `BORRADOR`; MUST estar definida antes de publicar/activar. Una Tarea publicada/operativa no puede carecer de fecha. |
| `fecha_cumplimiento` | DateTimeField | sí (`null=True, blank=True`) | `None` | Se fija al completar operativamente y pasar a `PENDIENTE_APROBACION_CIERRE`; la aprobación no la modifica. Si el cierre se rechaza y vuelve a `GESTION`, vuelve a NULL y el intento queda auditado en `TareaTransicion`. |
| `todo_origen` | FK conceptual nullable a `Todo` | sí | `None` | Origen canónico opcional; mutuamente excluyente con `tarea_origen`. |
| `tarea_origen` | FK conceptual nullable a `Tarea` | sí | `None` | Origen canónico opcional; cadenas históricas permitidas; mutuamente excluyente con `todo_origen`. |

## Entidad: `Todo` (diseño funcional, implementación futura)

| Campo | Tipo conceptual | Nulable | Reglas |
|---|---|---|---|
| `id` | PK | no | Identidad propia, separada de `Tarea`. |
| `empresa` | FK a `Empresa` | no | Todo TO-DO pertenece obligatoriamente a una Empresa. |
| `correlativo` | `CharField(max_length=9)` | no | Formato `TD` + 7 dígitos; único por Empresa; usa namespace propio. |
| `titulo` | texto | no | Asunto breve del problema o necesidad. |
| `descripcion` | texto | sí | Observación o contexto pendiente de formalización. |
| `estado` | choices | no | Solo `ABIERTO` o `CERRADO`. Un TO-DO cerrado no se reabre. |
| `creada_por` | FK a usuario | no | Usuario creador. |
| `fecha_creacion` | DateTime | no | Fecha/hora de creación. |
| `cerrada_por` | FK a usuario | sí | Usuario que ejecutó el cierre explícito. |
| `fecha_cierre` | DateTime | sí | Fecha/hora del cierre explícito. |
| `comentario_cierre` | texto | sí | Comentario del cierre. |

### Secuencia y relaciones conceptuales de TO-DO

- `CorrelativoTodoEmpresa`: secuencia propia por Empresa para `TD0000001`, `TD0000002`, etc.; no comparte contador con `CorrelativoEmpresa` ni con A/B.
- `Todo -> Tarea`: un TO-DO puede originar cero, una o varias Tareas mediante `Tarea.todo_origen`; cada una es un registro Tarea independiente, conserva el TO-DO y exige `fecha_tope` para publicarse. El TO-DO permanece existente y no se transforma.
- `Tarea -> Tarea`: `Tarea.tarea_origen` representa derivación directa y permite cadenas históricas.
- `Todo -> Todo`: un TO-DO nuevo puede quedar relacionado con un TO-DO cerrado anterior cuando reaparece el problema; el modelo concreto de esta relación queda pendiente.

La restricción conceptual del origen canónico es:

```text
NO permitir simultáneamente:
Tarea.todo_origen IS NOT NULL
AND Tarea.tarea_origen IS NOT NULL
```

Referencias históricas o de similitud pueden ser múltiples, pero no son origen canónico. Tampoco lo son `TareaRelacion` padre/hija/nieta, clonación ni trabajo en equipo.

### `EvaluacionSimilitud`

Entidad persistente de una comparación entre una Tarea nueva/candidata
(`tarea`) y una Tarea histórica válida (`tarea_candidata`). Una Tarea puede
tener múltiples evaluaciones, una por candidata concreta. No se usa una
relación M2M opaca ni se crean relaciones automáticas a todas las coincidencias.

| Campo | Tipo Django | Nulable | Default | Reglas |
|---|---|---:|---|---|
| `id` | BigAutoField (PK) | no | auto | Identidad propia. |
| `tarea` | ForeignKey(`Tarea`) | no | — | Tarea nueva evaluada; `on_delete=PROTECT`. |
| `tarea_candidata` | ForeignKey(`Tarea`) | no | — | Candidata histórica; `on_delete=PROTECT`; no puede ser la misma Tarea. |
| `porcentaje` | DecimalField(max_digits=5, decimal_places=2) | no | — | Rango `0.00..100.00`; score V1 de título 60% y descripción 40%. |
| `umbral_aplicado` | DecimalField(max_digits=5, decimal_places=2) | no | — | Rango `0.00..100.00`; valor suministrado por el servicio, sin configuración propia. |
| `supera_umbral` | BooleanField | no | — | Resultado persistido de `porcentaje >= umbral_aplicado`. |
| `decision` | CharField con choices | no | `PENDIENTE` | Choices: `PENDIENTE`, `MISMO_PROBLEMA`, `DISTINTO_PROBLEMA`. |
| `confirmada_por` | ForeignKey(User) | sí | `None` | Nullable mientras `decision=PENDIENTE`; actor de la decisión humana. `on_delete=PROTECT`. |
| `confirmada_at` | DateTimeField | sí | `None` | Nullable mientras `decision=PENDIENTE`; fecha/hora de confirmación. |
| `created_at` | DateTimeField(auto_now_add=True) | no | auto | Auditoría de creación. |

Reglas adicionales:

- `tarea.empresa_id` y `tarea_candidata.empresa_id` deben coincidir.
- La candidata debe estar en `ACTIVA`, `GESTION`,
  `PENDIENTE_APROBACION_CIERRE` o `CERRADA`.
- Se excluyen candidatas `BORRADOR`, candidatas con `anulada=True` y la propia
  Tarea evaluada.
- Si ambas Tareas tienen ámbito, deben coincidir en tipo y referencia; no se
  compara `LOCAL` contra `DEPARTAMENTO`.
- Las Tareas históricas sin ámbito pueden participar por texto dentro de la
  misma Empresa para preservar compatibilidad con registros anteriores a T093.
- `UniqueConstraint(fields=("tarea", "tarea_candidata"))` impide duplicar la
  evaluación vigente de una pareja. T056 no conserva historial de
  reevaluaciones; una futura necesidad de reevaluación histórica requiere una
  ampliación contractual separada.
- La confirmación `MISMO_PROBLEMA` no modifica la candidata. Solo una evaluación
  por Tarea puede establecer `tarea_origen`; cualquier otra evaluación queda como
  referencia de similitud.

El score V1 se calcula con `difflib.SequenceMatcher` sobre `titulo` y
`descripcion` normalizados (`casefold`, `strip`, espacios múltiples), con
ponderación 60%/40% y redondeo a dos decimales. Prioridad, estado, responsable,
creador, fechas y dimensiones organizacionales no forman parte del score.

TO-DO es el asunto aún no formalizado como Tarea y puede existir sin `fecha_tope`. Una Tarea solo puede carecer técnicamente de `fecha_tope` mientras está en `BORRADOR` y edición; una Tarea publicada/operativa siempre debe tenerla.

### Auditoría mínima de TO-DO

Debe persistirse conceptualmente la creación, el cierre explícito, la creación de una Tarea desde TO-DO y el usuario y fecha/hora de cada evento. El comentario de derivación es opcional; el comentario de cierre pertenece al cierre del TO-DO.

## Enums

```text
Estados persistentes del ciclo funcional: BORRADOR | ACTIVA | GESTION |
                     PENDIENTE_APROBACION_CIERRE | CERRADA.
Anulación: NO es un estado. Es el flag `Tarea.anulada` (True/False), separado del ciclo.
Eventos/acciones no persistentes como estado: PUBLICAR, RECHAZAR_CIERRE, ANULAR, REACTIVAR.
Prioridad:  SIMPLE | NORMAL | URGENTE | CRITICA   (definición aprobada por el usuario)
            Jerarquía: CRITICA > URGENTE > NORMAL > SIMPLE
            Default: NORMAL (aprobado por el usuario)
            Sin comportamientos adicionales por prioridad (sin colores, SLA,
            notificaciones, vencimientos ni reglas especiales)
```

## Reglas de validación (modelo / `clean()`)

- **V1 (FR-007)**: Al publicar, `responsable` MUST existir y corresponder a un usuario
  válido/activo (`is_active=True`). Si no → `ValidationError` y la tarea permanece en
  `BORRADOR`. (Incluye Clarification Q1: responsable desactivado tras la asignación
  bloquea la publicación.)
- **V1b (FR-G01/FR-S12)**: Al publicar, `fecha_tope` MUST existir. Si es NULL →
  `ValidationError` y la tarea permanece en `BORRADOR`; una Tarea publicada/operativa
  nunca puede carecer de `fecha_tope`.
- **V2 (FR-008)**: Una tarea en `PUBLICADA` MUST NOT guardarse sin `responsable` válido ni
  `fecha_tope`; `fecha_publicacion` y `fecha_asignacion` MUST estar fijadas y no cambian
  en ediciones posteriores. Una reasignación no modifica `fecha_tope`.
- **V3 (Q2)**: La transición `PUBLICADA → BORRADOR` MUST ser imposible (no existe operación
  de "despublicar"; cualquier intento es error de validación).
- **V4 (FR-003)**: `empresa` se asigna en creación desde la sesión y no cambia.
- **V5**: Los borradores no tienen restricción temporal (FR-006): sin expiración ni job de
  limpieza.

## Máquina de estados

```text
            crear (solo título requerido)
              │
              ▼
          ┌───────────┐   publicar() [responsable válido]   ┌────────────┐
          │ BORRADOR  │ ─────────────────────────────────▶ │   ACTIVA   │
          └───────────┘                                    └────────────┘
                             │
                             ▼
                            ┌────────────┐
                            │  GESTION   │
                            └────────────┘
                             │ 100%
                             ▼
                         ┌────────────────────────┐
                         │ PENDIENTE_APROBACION_  │
                         │ CIERRE                 │
                         └────────────────────────┘
                          │ aprobar       │ rechazar
                          ▼               ▼
                      CERRADA          GESTION (100%)

          ACTIVA/GESTION/PENDIENTE_APROBACION_CIERRE: anular -> anulada=True (estado intacto)
          anulada=True: reactivar -> anulada=False (estado intacto, nunca cambió)
          Publicada no puede volver a BORRADOR.
          Anulación efectiva (jerárquica, LÓGICA): tarea.anulada OR padre.anulada OR abuelo.anulada.
```

## Relaciones

- `Tarea.empresa` → `access_control.Empresa` (N:1). Aislamiento por `session['empresa_id']`.
- `Tarea.responsable` → `django.contrib.auth.models.User` (N:1, opcional en borrador).
- `Tarea.creada_por` → `User` (N:1).

## Phase 2 boundary decisions

- `Local` y `Departamento` tienen arquitectura canónica aprobada en la futura
  `APPLICATION_APP` transversal `organizacion`; esta app todavía no existe y
  no se implementa en esta feature.
- `Local` será un modelo Django canónico con PK interna, FK obligatoria a
  `Empresa` (`on_delete=PROTECT`), `codigo` funcional único por Empresa,
  `nombre`, `activo`, `legacy_code` nullable separado, `source` y timestamps.
  El ERP legacy (`g_maestroempresas`, expuesto actualmente por `api`) será la
  fuente externa inicial mediante sincronización futura; `legacy_code` nunca
  será PK ni FK de dominio.
- `Departamento` será un modelo Django canónico con PK interna, FK obligatoria
  a `Empresa` (`on_delete=PROTECT`), `codigo` funcional único por Empresa,
  `nombre`, `activo`, `source` y timestamps. Su fuente inicial será el catálogo
  local de `organizacion`; no tendrá FK obligatoria a `Local` ni `legacy_code`
  mientras no exista una fuente externa definida.
- `Local` y `Departamento` son dimensiones alternativas de Empresa. No se
  inventa una jerarquía `Local -> Departamento`.
- La futura implementación de `organizacion`, su registro global y su
  sincronización ERP requieren una task y autorización separadas. No entran en
  la migración Phase 2 ni habilitan cambios en `api` desde esta feature.
- Equipo/Activo: pendiente de definición exacta; no se determina aún modelo, código, relación
  con Empresa, nulabilidad o constraints. No entra como campo de la migración Phase 2.
- Tarea y las demás APPLICATION_APPS sólo podrán consumir FKs, catálogos y
  validaciones públicas de `organizacion`; no podrán consultar SQL legacy,
  duplicar maestros ni modificar sincronización.

### Fechas pendientes tras reactivación

Con el diseño de anulación por flag, NO se requiere snapshot de estados para restaurar
jerarquía: las relaciones no se eliminan y los estados/responsables/participantes no cambian.
`TareaAnulacionSnapshot` (construido en Phase 2) queda en revisión: su responsabilidad de
restaurar estado/estructura deja de ser necesaria. La información de auditoría que sigue
siendo útil (quién anuló/reactivó, cuándo, motivo) se cubre con `TareaTransicion`
(acciones ANULAR/REACTIVAR). Evolución posterior: el modelo puede simplificarse o
eliminarse en una migración aditiva futura; en esta intervención NO se elimina ni se
diseña su migración. `Tarea.fechas_pendientes_confirmacion` se conserva como señal de
fechas afectadas pendientes de confirmación (sin recálculo automático). En T030 se
mantiene únicamente por compatibilidad histórica: no activa un flujo especial, no
extiende fechas, no resetea atraso ni fuerza confirmación al reactivar.

### Señal de cierre completado

`Tarea.cierre_completado` es un `BooleanField(default=False)` de lifecycle. No representa
un porcentaje 0..100, no reemplaza el futuro modelo general de `Avance`, no implementa pesos
ni hitos y no es una fuente de avance. Solo registra que se alcanzó la condición funcional
equivalente al 100% necesaria para solicitar cierre. Phase 2 no implementa porcentaje general;
una fase posterior podrá derivar, sustituir o ampliar esta señal mediante migración aditiva.

## Entidades nuevas por fase

Las siguientes entidades viven en `tareas/` y se incorporan mediante migraciones aditivas.
Los nombres son contratos de dominio y no autorizan modificar apps externas.

### Identidad, ciclo y seguridad

- `TareaTransicion`: FK a Tarea, `estado_origen`, `estado_destino`, `accion_evento`,
  usuario, timestamp y `motivo` opcional.
- `TareaCierre`: FK a Tarea, usuario aprobador/rechazador, timestamp, `resultado` (`APROBADO`
  o `RECHAZADO`) y `comentario` opcional; no incluye documentos/evidencias de Phase 4.
- `TareaAnulacionSnapshot`: **EN REVISIÓN** (ver nota de anulación por flag). Construido en
  Phase 2 con FK a una Tarea, `estado_anterior`, `fechas_pendientes_confirmacion` anterior,
  usuario que anuló, timestamps de anulación/reactivación. Su rol de restaurar estados deja
  de ser necesario con el flag `anulada`; se evaluará su simplificación o retiro en una
  migración aditiva futura. La auditoría de anular/reactivar la cubre `TareaTransicion`.
- `CorrelativoEmpresa`: FK a Empresa con `OneToOneField`/unicidad efectiva por empresa,
  `siguiente_numero` entero positivo inicial `1`, constraint única sobre empresa e índice
  por empresa. En una reserva se bloquea la fila dentro de `transaction.atomic()`, se toma
  el número actual y se incrementa una sola vez; si no existe fila se crea con `siguiente_numero=1`
  dentro de la misma transacción y se reintenta la reserva bajo la restricción única.

### Asignación y jerarquía

- `TareaParticipante`: tarea, usuario, rol y fechas.
- `TareaReasignacion`: responsable anterior/nuevo, usuario, fecha y motivo.
- `TareaLectura`: tarea, usuario, leído y fecha.
- `TareaRelacion`: padre/hija con máximo dos niveles bajo el padre.
- `MiniTarea`: tarea, descripción, persona única, hecho y fechas.

### Avance, fechas, reprogramación y documentos

- `Hito`: tarea, nombre, `responsable` FK obligatorio a `auth.User` con `on_delete=PROTECT`, `anulado` BooleanField(default=False), `completado` BooleanField(default=False), `completado_por` FK nullable a `auth.User`, `fecha_completado` DateTime nullable, `resena_cierre` nullable/texto requerido al completar, cumplimiento `0..100`, peso relativo, fecha de creación y orden. La combinación `anulado=False, completado=False` representa pendiente; `completado=True` representa completado formalmente; `anulado=True` representa anulado y no puede completarse. El responsable puede diferir del responsable principal de la Tarea, pero MUST estar activo y pertenecer/tener acceso válido a la Empresa de la Tarea; la validación debe impedir cruces multiempresa y rechazar la operación sin cambios parciales.
- `Hito` no tiene campo propio de `prioridad`, `clasificacion` ni `fecha_tope`; para presentación y dashboard T077 hereda únicamente `Tarea.prioridad` de su Tarea padre, usando el catálogo `SIMPLE`, `NORMAL`, `URGENTE`, `CRITICA`. No se crea una dimensión `clasificacion` ni se asume herencia de vencimiento.
- `Avance`: tarea, modo manual/ponderado, porcentaje calculado y fecha.
- `Tarea.fecha_asignacion`: DateTime nullable mientras no se publica, fijada al publicar/asignar oficialmente y conservada como referencia histórica original; una reasignación no la modifica.
- `Tarea.fecha_tope`: Date nullable; puede ser NULL solo en `BORRADOR` durante edición y es el dato funcional principal de vencimiento. Toda Tarea publicada/operativa MUST tenerla.
- `Tarea.fecha_cumplimiento`: DateTime nullable; fecha/hora real en que se completa la última acción operativa necesaria. Es distinta de la fecha de cierre/aprobación, corta el cálculo de atraso y vuelve a NULL si el cierre es rechazado y la Tarea vuelve a `GESTION`; el intento queda en `TareaTransicion`.
- `CausaAtraso`: catálogo inicial cerrado a imposibilidad técnica, atraso importación, permisos municipales, problemas de escrituras, causas internas y causas externas.
- `Reprogramacion`: tarea, `fecha_tope_anterior`, `fecha_tope_nueva`, justificación obligatoria, usuario y `fecha_operacion`; cambiar una `fecha_tope` existente es una reprogramación explícita y no una reasignación. Cada reprogramación se relaciona con una o varias `CausaAtraso` mediante M:N.
- `dias_atraso` es derivado: durante la edición de un `BORRADOR` sin `fecha_tope` vale cero; toda Tarea publicada tiene fecha y, si no está cumplida, se calcula contra `fecha_referencia`; con Tarea cumplida se usa `fecha_cumplimiento` como corte. La aprobación posterior no suma atraso. La anulación no reescribe fechas ni elimina el atraso histórico, y la reactivación no recalcula fechas.
- `MiniTarea`: mantiene una persona única y estado hecho/no hecho; no pondera el avance y no se fusiona con `Hito`.
- `HitoHistorial`: historial específico de Hito con `hito`, `tipo_evento`, `usuario`, fecha/hora, datos anteriores, datos nuevos y motivo cuando corresponda. Cubre creación, cambios de nombre/cumplimiento/peso/responsable, anulación, reactivación, completitud (`COMPLETADO`) y eliminación física cuando corresponda; debe conservar evidencia de actividad/progreso histórica aunque el cumplimiento actual sea `0`. El evento `COMPLETADO` referencia conceptualmente la reseña y las evidencias relacionadas, sin duplicar archivos dentro del historial. La representación física de datos anteriores/nuevos queda abierta.
- La reasignación de Hito se resuelve en `HitoHistorial` como fuente auditable única, sin reutilizar físicamente `TareaReasignacion`.
- `HitoEvidencia`: relación `ForeignKey` obligatoria con `Hito`, cardinalidad `0..N`, `formato_archivo`, exactamente uno entre `archivo` y `url`, usuario que registra y fecha/hora. El formato se valida contra la extensión real usando el catálogo `PDF`, `JPG`, `JPEG`, `PNG`, `DOC`, `DOCX`, `XLS`, `XLSX`, con equivalencia `JPG`/`JPEG` y distinción entre `DOC`/`DOCX` y `XLS`/`XLSX`. Debe tener índice por Hito y restricciones/validación XOR; una primera implementación puede exigir una evidencia al completar y admitir altas adicionales después.
- `EvidenciaCierre` sigue siendo evidencia global de cierre de `Tarea` y no se reutiliza como evidencia de Hito. `HitoEvidencia` acredita un Hito específico y mantiene entidad, FK, cardinalidad y ciclo de vida independientes.
- Matriz de autorización de Hito: el responsable del Hito solo puede cambiar su propio cumplimiento; el responsable principal y el creador de la Tarea pueden editar nombre/cumplimiento/peso, reasignar, anular, reactivar y eliminar cuando el historial lo permita; supervisor y autorizador pueden editar, reasignar, anular, reactivar y eliminar dentro del alcance vigente de Tarea/Empresa; invitado/observador solo puede visualizar. El responsable del Hito no puede auto-reasignarse ni ejecutar acciones de gestión fuera de su cumplimiento.
- Si un usuario tiene varios roles, se aplica la facultad más amplia dentro de la Tarea. Toda acción debe respetar Empresa activa, Empresa de la Tarea, usuario válido y aislamiento multiempresa; ningún rol habilita cruces de Empresa. La política de autorización no crea perfiles nuevos y los intentos no autorizados no deben producir cambios parciales.
- La edición, reasignación, anulación/reactivación y eliminación de Hitos quedan sujetas a esta matriz y a la política vigente de `tareas`; el cambio de cumplimiento realizado por el responsable del Hito también se registra en `HitoHistorial`. Una vez `completado=True`, el Hito queda congelado: solo lectura de cumplimiento y anulación por actores con facultad vigente; no editar, reasignar, completar nuevamente, actualizar avance ni eliminar físicamente.
- Completar Hito es una operación separada de editar cumplimiento: pueden ejecutarla responsable del Hito, responsable principal, creador y supervisor/autorizador dentro de su alcance vigente; exige reseña y al menos una `HitoEvidencia`, establece `completado`, `cumplimiento=100`, `completado_por` y `fecha_completado`, conserva el responsable asignado y registra `COMPLETADO` en `HitoHistorial` dentro de una operación atómica. El responsable del Hito no obtiene facultad de reasignación.
- Actualizar manualmente cumplimiento a `100` no establece `completado`. Un Hito completado no puede bajar silenciosamente de `100` ni eliminarse físicamente si posee historial operativo; la reapertura queda fuera de alcance y requiere decisión explícita antes de implementarse.
- La consulta de cumplimiento formal no requiere campos nuevos ni una copia de `HitoEvidencia`: lee `Hito.completado`, `responsable`, `completado_por`, `fecha_completado`, `resena_cierre` y la relación `HitoEvidencia` `0..N`. `HitoHistorial` permanece como auditoría y no es la fuente primaria para reconstruir estos datos.
- La consulta solo lectura distingue `EvidenciaCierre` de Tarea de `HitoEvidencia` de Hito; para cada evidencia muestra formato, archivo o URL, usuario y fecha. No agrega una relación ni entidad paralela para la vista.
- Anular un Hito completado conserva todos sus campos de completitud, evidencias e historial; únicamente deja de participar en el avance ponderado y de operar como Hito vigente. El responsable exclusivo del Hito no puede anularlo por ese rol. La reactivación de un Hito completado y anulado queda pendiente de decisión y no debe inferirse de la reactivación ordinaria.
- Un Hito sin actividad histórica puede eliminarse físicamente. Un Hito con progreso, cambios relevantes, reasignaciones u otra actividad histórica debe conservarse con `anulado=True`; anular preserva datos e historial, lo excluye del avance y de asignaciones pendientes, y lo mantiene disponible para historial/consulta. Reactivar limpia solo `anulado`, conserva responsable, cumplimiento, peso e historial y lo reincorpora al avance y asignaciones activas.
- Al introducir `Hito.anulado`, los Hitos históricos existentes se consideran inicialmente no anulados salvo evidencia contractual en contrario.
- Los Hitos históricos existentes sin responsable requieren una estrategia de migración segura posterior. La implementación futura debe detenerse/reportar ante esos registros y no puede asignar automáticamente el responsable de la Tarea, creador, administrador ni otro usuario sin autorización explícita.
- `DocumentoTarea`: tipo, archivo o URL, fechas informativas, usuario y estado.
- `DocumentoHistorial`: historial de cambios de `DocumentoTarea`.
- `Tarea.requiere_evidencia_cierre`: configuración booleana directa de la Tarea, independiente de que existan evidencias. No se recomienda una configuración 1:1 adicional mientras no aparezca un patrón canónico que la justifique.
- `EvidenciaCierre`: relación `ForeignKey` con `Tarea`, cardinalidad `0..N`, con formato físico, exactamente un archivo o URL, usuario y fecha/hora. Cada registro es independiente y una nueva alta no reemplaza evidencias anteriores. El campo `requerida` fue retirado de esta entidad. Mantiene una FK opcional a `DocumentoTarea` solo por compatibilidad histórica; no se usa para nuevas evidencias ni es fuente principal de la UI.
- `formato_archivo`: catálogo canónico compartido por `DocumentoTarea` y `EvidenciaCierre`; no debe confundirse con `DocumentoTarea.tipo`, cuyo catálogo documental permanece separado. Cada evidencia exige exactamente un archivo o URL al registrarse.
- El catálogo inicial de `formato_archivo` es `PDF`, `JPG`, `JPEG`, `PNG`, `DOC`, `DOCX`, `XLS` y `XLSX`. La validación compara el formato declarado con la extensión real; `JPG`/`JPEG` son familia equivalente y `DOC`/`DOCX`, `XLS`/`XLSX` son distintos. Las URL sin extensión detectable aceptan la clasificación declarada.
- Regla de cierre: con `requiere_evidencia_cierre=False`, la Tarea puede cerrarse sin EvidenciaCierre salvo otra regla contractual; con `True`, debe existir al menos una evidencia válida antes de aprobar/cerrar. La integración efectiva con el flujo de cierre queda para la task de cierre correspondiente.
- Migración histórica `0017_tarea_evidencia_configuracion`: trasladar `EvidenciaCierre.requerida` a la configuración de la Tarea y conservar cada registro histórico como evidencia asociada. Un registro existente con archivo o URL real permanece como evidencia; no se borran evidencias ni se pierden datos. Los registros ambiguos o sin fuente real requieren decisión explícita antes de completar el backfill.

### Cotizaciones y maestro local de proveedores

- `RondaCotizacion`: tarea, número, mínimo configurable (default 3), fechas y estado.
- `Cotizacion`: relación obligatoria con `RondaCotizacion`, relación futura nullable con
  `proveedores.Proveedor` durante la transición, `version` entera positiva,
  `monto` decimal no negativo, `vigente`, `estado`, `fecha_cotizacion` y
  `observaciones` opcionales. Los estados canónicos internos son `RECIBIDA`,
  `SELECCIONADA` y `DESCARTADA`; `SELECCIONADA` no identifica ni adjudica un proveedor real.
- `DocumentoCotizacion`: relación `0..N` con `Cotizacion`, con `formato_archivo`,
  `archivo`, `url`, `usuario` y `fecha`. `archivo` y `url` son excluyentes. Reutiliza
  el catálogo canónico `PDF`, `JPG`, `JPEG`, `PNG`, `DOC`, `DOCX`, `XLS`, `XLSX`.
- Cardinalidades: `Tarea 1..N RondaCotizacion`, `RondaCotizacion 1..N Cotizacion` y
  `Cotizacion 1..0..N DocumentoCotizacion`. `Cotizacion` no duplica tarea ni empresa;
  ambas se derivan de `cotizacion.ronda.tarea`.
- Las cotizaciones son históricas: `vigente` distingue la versión actual cuando corresponda,
  pero no equivale a `SELECCIONADA` y recibir otra versión no elimina las anteriores.
- La regla futura es máximo 3 versiones por `(ronda, proveedor)`, validado en servicio
  transaccional; no es un máximo por ronda completa.
- Señal contractual de requisito: la Tarea requiere cotizaciones si existe al menos una
  `RondaCotizacion` asociada; no se agrega `Tarea.requiere_cotizaciones` ni otro booleano.
- Conteo PRE-P2: el mínimo de una ronda usa únicamente sus `Cotizacion` con `vigente=True`.
  Los estados `RECIBIDA`, `SELECCIONADA` y `DESCARTADA` no filtran por sí solos el conteo;
  `vigente=False` identifica versiones históricas que no computan.
- El cierre controla la última `RondaCotizacion` de la Tarea por `numero`, sin acumular
  cotizaciones entre rondas. Cada ronda satisface su propio `minimo_cotizaciones`; las
  rondas anteriores permanecen históricas. Una ronda sucesora hereda el mínimo de la
  anterior, mientras que la primera usa default 3 si no se especifica.
- Evolución local: el mínimo contará proveedores Django distintos con al menos una
  `Cotizacion.vigente=True` en la ronda; no se sumarán proveedores entre rondas. Los estados
  `RECIBIDA`, `SELECCIONADA` y `DESCARTADA` no excluyen por sí solos.
- `Cotizacion.proveedor` será nullable para conservar histórico PRE-P2 con `NULL`; las
  nuevas cotizaciones exigirán proveedor después de implementar la evolución. No habrá
  backfill inventado.
- `SELECCIONADA` representa elección interna Django. No se crea todavía `Adjudicacion`.
- `Proveedor`: maestro global local de la futura `APPLICATION_APP proveedores`, con `id`,
  `rut`, `nombre`, `direccion`, `comuna`, `ciudad`, `fono1`, `fono2`, `fax`, `contacto`,
  `email1`, `email2`, `activo`, `created_at` y `updated_at`.
- Un proveedor puede existir sin RUT; cuando exista, se normaliza y es único globalmente,
  incluso inactivo. La baja es lógica mediante `activo=False`, no existe eliminación física
  en T084 y no se permite reutilizar el RUT. Reactivar establece `activo=True` y requiere
  permiso `modificar`.
- `convenio`, `visitas`, `ProveedorEmpresa`, identificador legacy y sincronización ERP quedan
  fuera del modelo inicial. `ProveedorEmpresa` se reserva para condiciones por Empresa;
  `visitas` queda DEFERRED por semántica legacy no definida.
- `ProveedorReferencia` es un nombre histórico del diseño anterior y queda supersedido por
  el maestro local; no se implementa como modelo.

### Colaboración y analítica

#### `ReunionRevision`

Entidad de una convocatoria de revisión dentro de una Empresa. La reunión se
crea junto con una Tarea planificada obligatoria que representa la reunión
misma; las tareas revisadas se relacionan mediante `ReunionTarea` y no
reemplazan esa Tarea planificada.

| Campo | Tipo Django | `null` | `blank` | Default | Reglas / relaciones |
|---|---|---:|---:|---|---|
| `id` | `BigAutoField` (PK) | no | no | auto | Identidad propia. |
| `empresa` | `ForeignKey(Empresa)` | no | no | — | `on_delete=PROTECT`; se asigna desde la Empresa activa, no desde el request. |
| `titulo` | `CharField(max_length=200)` | no | no | — | Nombre breve de la reunión. |
| `descripcion` | `TextField` | no | sí | `""` | Objetivo o contexto de la revisión. |
| `fecha_hora_programada` | `DateTimeField` | no | no | — | Fecha y hora de la convocatoria. |
| `modalidad` | `CharField` con choices | no | no | — | Sólo `ZOOM` o `PRESENCIAL`; valores derivados de FR-M03. |
| `lugar_o_enlace` | `CharField(max_length=500)` | sí | sí | `None` | Lugar para `PRESENCIAL` o enlace Zoom para `ZOOM`. |
| `tipo_ambito` | `CharField` con choices | no | no | — | Sólo `LOCAL` o `DEPARTAMENTO`. Define la dimensión homogénea de la reunión. |
| `local` | `ForeignKey(Local)` | sí | sí | `None` | `on_delete=PROTECT`; obligatorio sólo cuando `tipo_ambito=LOCAL`. Requiere el modelo/relación Local autorizado por P1. |
| `departamento` | `ForeignKey(Departamento)` | sí | sí | `None` | `on_delete=PROTECT`; obligatorio sólo cuando `tipo_ambito=DEPARTAMENTO`. Requiere el modelo/relación Departamento autorizado por P1. |
| `tarea_planificada` | `OneToOneField(Tarea)` | no | no | — | `on_delete=PROTECT`; Tarea que representa la reunión planificada. Debe pertenecer a la misma Empresa. |
| `creada_por` | `ForeignKey(User)` | no | no | — | `on_delete=PROTECT`; usuario que crea la convocatoria. |
| `estado` | `CharField` con choices | no | no | `PLANIFICADA` | Sólo `PLANIFICADA` y `REALIZADA`; `REALIZADA` se fija al cerrar la reunión. No se agrega cancelación porque no está definida en FR-M01..FR-M07. |
| `convocada_at` | `DateTimeField` | sí | sí | `None` | `None` significa nunca convocada; fecha significa convocada al menos una vez. No crea historial en T055. |
| `created_at` | `DateTimeField(auto_now_add=True)` | no | no | auto | Auditoría de creación. |
| `updated_at` | `DateTimeField(auto_now=True)` | no | no | auto | Auditoría de modificación. |

La creación de `ReunionRevision`, su Tarea planificada y sus relaciones de
agenda debe ser una operación atómica. La reunión no es una entidad
independiente de la tarea planificada: FR-M05 fija la interpretación B (toda
reunión crea obligatoriamente una Tarea asociada). La Tarea planificada no se
confunde con ninguna tarea incluida en la revisión.

El ámbito es XOR: con `tipo_ambito=LOCAL`, `local` es obligatorio y
`departamento` debe ser NULL; con `tipo_ambito=DEPARTAMENTO`, `departamento`
es obligatorio y `local` debe ser NULL. Nunca se permiten ambos ni ninguno.
La Empresa del ámbito debe coincidir con `empresa`.

#### `ReunionTarea`

Entidad intermedia que representa una tarea incluida en el subconjunto y en la
agenda de una reunión.

| Campo | Tipo Django | `null` | `blank` | Default | Reglas / relaciones |
|---|---|---:|---:|---|---|
| `id` | `BigAutoField` (PK) | no | no | auto | Identidad propia. |
| `reunion` | `ForeignKey(ReunionRevision)` | no | no | — | `on_delete=CASCADE`; relación obligatoria con la reunión. |
| `tarea` | `ForeignKey(Tarea)` | no | no | — | `on_delete=PROTECT`; debe pertenecer a la misma Empresa que la reunión. |
| `orden` | `PositiveIntegerField` | no | no | — | Posición manual de agenda, única dentro de la reunión. Debe respetar prioridad descendente de Tarea; empates de prioridad se resuelven con este orden. No se crea un modelo `Agenda`. |
| `comentario_revision` | `TextField` | no | sí | `""` | Comentario de revisión asociado a esta reunión y tarea. |
| `comentario_cierre` | `TextField` | no | sí | `""` | Comentario registrado al cerrar la reunión para esta tarea. |
| `created_at` | `DateTimeField(auto_now_add=True)` | no | no | auto | Auditoría de inclusión. |

Reglas de `ReunionTarea`:

- `UniqueConstraint(fields=("reunion", "tarea"))`: una tarea no se repite en
  la misma reunión.
- `UniqueConstraint(fields=("reunion", "orden"))`: cada posición de agenda
  es única dentro de la reunión.
- Una Tarea puede aparecer en múltiples reuniones distintas.
- La agenda se ordena por prioridad descendente (`CRITICA`, `URGENTE`,
  `NORMAL`, `SIMPLE`) y, dentro de cada prioridad, por `orden` ascendente.
- El servicio debe rechazar una agenda cuyo orden manual contradiga ese
  agrupamiento de prioridades.
- El cierre de la reunión exige registrar `comentario_cierre` por cada tarea
  incluida en la agenda. Estos comentarios pertenecen al contexto de la
  reunión y no crean ni sustituyen un sistema global de comentarios de Tarea.

Todas las `ReunionTarea` deben pertenecer a la Empresa de la reunión y al
mismo ámbito: mismo `local` cuando `tipo_ambito=LOCAL`, o mismo
`departamento` cuando `tipo_ambito=DEPARTAMENTO`. No se exige igual
responsable, prioridad ni clasificación. La agenda puede mezclar prioridades,
pero se ordena en descendente y luego por `orden` ascendente.

#### `ReunionParticipante`

| Campo | Tipo Django | `null` | `blank` | Default | Reglas / relaciones |
|---|---|---:|---:|---|---|
| `id` | `BigAutoField` (PK) | no | no | auto | Identidad propia. |
| `reunion` | `ForeignKey(ReunionRevision)` | no | no | — | `on_delete=CASCADE`; una reunión tiene cero o más convocados explícitos. |
| `usuario` | `ForeignKey(User)` | no | no | — | `on_delete=PROTECT`; debe ser usuario válido del contexto de Empresa permitido por el sistema. |
| `created_at` | `DateTimeField(auto_now_add=True)` | no | no | auto | Auditoría de inclusión. |

`UniqueConstraint(fields=("reunion", "usuario"))` impide repetir un usuario
en la misma reunión. La relación no hereda automáticamente
`TareaParticipante` ni agrega roles, asistencia, confirmación, estados o
permisos propios.

#### Convocatoria

Crear o editar una reunión no convoca. La acción explícita `CONVOCAR` procesa
cada `ReunionParticipante` válido y genera una notificación in-app y un email
automático de sistema. Usa los adaptadores existentes de `tareas`, la Empresa
de la reunión y `purpose="notifications"`; no usa SMTP de usuario/perfil ni
modifica CORE/emailing. El contenido mínimo incluye título, fecha/hora,
modalidad, lugar o enlace, enlace interno a la reunión cuando exista y
Empresa/contexto.

Si `convocada_at` no es NULL, `CONVOCAR` no se repite accidentalmente. Guardar
cambios después de convocar no reenvía: editar no equivale a convocar. Una
futura actualización de convocatoria queda fuera de T055.

#### Dependencia de implementación organizacional

La arquitectura de referencia para el ámbito de reuniones está resuelta, pero
su implementación aún no existe. T055 queda pendiente de una task separada
que cree `organizacion.Local` y `organizacion.Departamento`; T055 no debe
inventar FKs a entidades inexistentes, códigos legacy, `CharField` de ámbito,
`IntegerField` de referencia ni `GenericForeignKey`.

Una vez implementado el dominio canónico, `ReunionRevision` podrá referenciar
`organizacion.Local` o `organizacion.Departamento` mediante FKs nullable y
validación XOR, exigiendo que el ámbito pertenezca a la misma Empresa de la
reunión. Las `ReunionTarea` deberán coincidir con ese ámbito cuando `Tarea`
disponga de la dimensión organizacional correspondiente.
- `TareaOrigen`: tarea nueva, tarea origen y usuario/fecha de derivación.
- `EvaluacionSimilitud`: comparación persistente entre `tarea` y
  `tarea_candidata`, porcentaje V1, umbral aplicado, `supera_umbral`, decisión,
  actor/fecha de confirmación y fecha de creación; incluye candidatas cerradas.
- `UmbralSimilitudEmpresa`: configuración empresarial única del umbral de similitud.
  Su estructura contractual es:
  - `id`: `BigAutoField` autoincremental.
  - `empresa`: `OneToOneField(Empresa, on_delete=PROTECT)`, obligatorio.
  - `porcentaje`: `DecimalField(max_digits=5, decimal_places=2)`, obligatorio,
    con rango `0.00..100.00`.
  - `actualizado_por`: `ForeignKey(User, on_delete=PROTECT)`, obligatorio para
    toda fila materializada por un cambio explícito autorizado.
  - `actualizado_at`: `DateTimeField`, obligatorio y actualizado en cada cambio.

  El default funcional es `Decimal("80.00")`, pero no es necesario materializar
  una fila default. Si no existe fila para una Empresa, el getter
  `get_similarity_threshold(empresa)` devuelve `Decimal("80.00")` mediante
  fallback virtual, sin escribir en la base de datos. La fila se crea o
  actualiza únicamente mediante `set_similarity_threshold(*, empresa,
  porcentaje, actor)` tras validar el rango y registrar actor/fecha. El cambio
  solo rige para evaluaciones futuras; no modifica ni recalcula
  `EvaluacionSimilitud` existentes. La autorización usa VICMEAS sobre
  `Configuración - Configuracion de Empresa` con `modificar`. No se agregan
  otros campos, signals ni creación automática por lectura.
- `EnlaceTarea`: enlace V1 exclusivamente a `Tarea`, con los campos:
  - `tarea`: FK obligatoria a `Tarea`, `on_delete=CASCADE`.
  - `destinatario`: FK obligatoria a `auth.User`, `on_delete=PROTECT`.
  - `creado_por`: FK obligatoria a `auth.User`, `on_delete=PROTECT`, con
    `related_name` diferenciado.
  - `token_hash`: `CharField(max_length=64, unique=True)` obligatorio; contiene
    únicamente SHA-256 del token URL-safe generado con `secrets.token_urlsafe(32)`.
  - `fecha_creacion`: `DateTimeField(auto_now_add=True)`.
  - `fecha_expiracion`: `DateTimeField` obligatorio y futuro al crear.
  - `revocado_at`: `DateTimeField(null=True, blank=True)`.
  - `revocado_por`: FK nullable a `auth.User`, `on_delete=SET_NULL`.
  No tiene Empresa duplicada, permiso VICMEAS persistente, token plano, contador
  de accesos ni uso único. Es multiuso hasta expirar o revocarse.
- `EventoAccesoEnlace`: evento de auditoría por acceso a un enlace existente,
  con los campos:
  - `enlace`: FK obligatoria a `EnlaceTarea`, `on_delete=CASCADE`.
  - `usuario`: FK nullable a `auth.User`, `on_delete=SET_NULL`.
  - `fecha`: `DateTimeField(auto_now_add=True)`.
  - `resultado`: choices `ACCESO_OK`, `RECHAZADO_USUARIO`,
    `RECHAZADO_EMPRESA`, `RECHAZADO_EXPIRADO`, `RECHAZADO_REVOCADO` y
    `RECHAZADO_TOKEN_INVALIDO`.
  No agrega IP ni User-Agent en T058. Un token inexistente no crea una fila,
  por lo que `RECHAZADO_TOKEN_INVALIDO` solo aplica cuando exista contexto de
  enlace. La Empresa se deriva de `enlace.tarea.empresa`; no se duplica.
- El acceso exige autenticación, destinatario exacto, Empresa activa coincidente,
  token vigente y ausencia de revocación. El enlace autoriza únicamente lectura
  de su Tarea y no altera VICMEAS ni crea `TareaParticipante`.

Las notificaciones se refieren a la infraestructura existente de `notificaciones` y email de
`acounts`; no se duplica su modelo.

## Comentarios de Tarea (diseño; implementación pendiente)

`Comentario` pertenece a una única `Tarea`; su Empresa se deriva de `comentario.tarea.empresa` y no se duplica. La relación permite cero o más Comentarios por Tarea.

| Entidad | Campos y reglas contractuales |
|---|---|
| `Comentario` | `tarea` FK obligatoria a `Tarea` (`on_delete=PROTECT`); `autor` FK obligatoria a `User` (`on_delete=PROTECT`); `contenido` opcional (`blank=True`, `default=""`); `created_at`, `updated_at`; `oculto` booleano, default `False`. Servicio exige texto no vacío o al menos un adjunto. No representa eventos automáticos ni tiene eliminación física. |
| `ComentarioAdjunto` | Relación actual única entre `Comentario` y `DocumentoTarea`, con protección ante borrado del documento; cada documento debe pertenecer a la misma Tarea. El servicio valida máximo cinco adjuntos. Quitar esta relación no elimina `DocumentoTarea`. |
| `ComentarioVersion` | FK a `Comentario`; `evento` (`CREADO`, `EDITADO`, `OCULTADO`, `RESTAURADO`); `numero_version` nullable para eventos de visibilidad; snapshot del contenido, actor, fecha/hora y `motivo` obligatorio para ocultar/restaurar; relaciones a `DocumentoTarea` vía `ComentarioVersionDocumento`. Unicidad de número por Comentario cuando exista. La primera versión de contenido es 1; cada edición agrega la siguiente sin sobrescribir anteriores. |
| `ComentarioVersionDocumento` | Asociación inmutable de `ComentarioVersion` y `DocumentoTarea`, única por par y con `on_delete=PROTECT` sobre el documento; cada versión conserva el conjunto exacto de referencias y valida que cada documento pertenezca a la Tarea del Comentario. Las diferencias entre conjuntos consecutivos identifican documentos agregados/retirados junto al actor y fecha de la versión. No copia ni versiona archivos, bytes o metadatos del documento. |
| `TareaLectura` (extensión) | Conserva sin cambio `tarea`, `usuario`, `leido` y `fecha_lectura` para lectura general de Tarea; agrega `comentario_leido_hasta`, FK nullable a `Comentario` (`on_delete=PROTECT`), como cursor independiente por usuario/Tarea. La unicidad existente `(tarea, usuario)` permite una sola fila por lector y Tarea, no una fila por Comentario. Se asegura al vincular o en el primer evento de Comentario para los participantes actuales. |
| `ComentarioPausaLectura` | Intervalo de inactividad por fila `TareaLectura`, con `desde` y `hasta` (nullable mientras el usuario siga inactivo). Un listener propiedad de `tareas` abre/cierra intervalos al observar cambios guardados de `User.is_active`; si la fila lectora nace mientras el usuario está inactivo, se abre el intervalo entonces. El contador excluye Comentarios creados dentro del intervalo. Es una fila por intervalo inactivo, no por Comentario, y no reemplaza ni modifica sesiones. |

La lectura de Comentarios usa el cursor `comentario_leido_hasta`, ordenado por `(created_at, pk)`; las columnas `leido`/`fecha_lectura` existentes conservan su semántica general de Tarea y no se actualizan al abrir la Tarea ni al expandir la tarjeta. El contador se calcula sobre Comentarios posteriores al cursor, excluye los escritos por el lector y los que caen en un `ComentarioPausaLectura`, e incluye los ocultos pendientes. Las páginas se cargan cronológicamente en bloques de 20: con pendientes, la carga inicial comienza tras el cursor; sin pendientes, muestra las 20 más recientes. Puede recorrerse el historial anterior sin mover el cursor. El reconocimiento solo acepta y avanza por la siguiente página contigua realmente cargada, nunca por una página histórica/arbitraria. Los ocultos se entregan como tombstone neutro a quienes no pueden ver su contenido, para preservar orden, paginación, contador y primer pendiente; solo autor/S ven contenido, adjuntos e historial. El vínculo vigente nuevo/recreado inicializa el cursor en el Comentario más reciente y deja cero pendientes históricos.

La edición la puede realizar solo el autor durante la primera hora desde `Comentario.created_at` original; el plazo no se renueva. Se pueden editar texto y conjunto de adjuntos; un Comentario oculto no se edita. Cada creación/edición conserva el texto y conjunto de referencias `DocumentoTarea` de esa versión. Esto no congela bytes ni metadatos mutables de `DocumentoTarea`, no duplica archivos ni reemplaza el historial documental. `DocumentoTarea` creado por el servicio existente obtiene historial `CREADO`, cuya FK `PROTECT` impide su borrado ordinario; el FK `PROTECT` de `ComentarioVersionDocumento` protege además toda referencia histórica. La edición que retira un adjunto solo elimina el vínculo actual y nunca llama a `DocumentoTarea.delete()`. Un cambio posterior del archivo/URL conserva la identidad del documento relacionado, pero no reconstruye su contenido anterior.

Ocultar cambia `Comentario.oculto=True`; restaurar lo vuelve a `False`. Solo S (`Permiso.supervisor`) puede realizar ambas acciones, con motivo obligatorio no vacío tras trim. Ambos eventos quedan en `ComentarioVersion` con actor, fecha/hora y motivo; no incrementan versión de contenido ni leído/no leído. El tombstone de la bitácora no revela contenido, adjuntos, actor, motivo ni versiones a otros usuarios. El historial completo solo es visible al autor o S, sujeto al acceso vigente a la Tarea.

Crear, editar, ocultar y restaurar vuelve a validar en backend, dentro de la operación y justo antes de persistir, permiso VICMEAS, Empresa activa, usuario/vínculo vigentes y estado actual de la Tarea. Solo estados publicados operativos permiten mutar. Reactivar no reinicia versiones, cursor ni historial; si la Tarea subyacente sigue `CERRADA`, permanece en solo lectura.

La superficie reutiliza `vista_nombre="Tareas"`: `ingresar` para leer; `modificar` para crear/editar y vincular/desvincular; `supervisor` (S) para ocultar/restaurar. No se crean Vistas, permisos ni roles. Cualquier acceso derivado requiere vínculo `TareaParticipante` vigente y usuario activo en la Empresa activa; creador/responsable no tienen bypass. Desvincular revoca acceso inmediato; volver a vincular reinicia solo el cursor al comentario más reciente, no borra datos ni historial.

Los estados canónicos siguen siendo `BORRADOR`, `ACTIVA`, `GESTION`, `PENDIENTE_APROBACION_CIERRE` y `CERRADA`; la anulación efectiva conserva su flag independiente. Solo `ACTIVA`, `GESTION` y `PENDIENTE_APROBACION_CIERRE` no anuladas admiten nuevas mutaciones; `BORRADOR`, `CERRADA` y anuladas efectivamente son de solo lectura. Comentarios no cambia el estado ni sustituye evidencia o justificación formal.

La UI integra una tarjeta con bitácora lineal, páginas de 20, contador `1..9`/`9+` y desplazamiento al primer pendiente. No hay filtros, buscador, threads, chat ni aplicación separada. Solo creación incrementa no leídos y emite el evento de nuevo Comentario; editar/ocultar/restaurar notifican mediante T053/T054 sin mover el cursor. Notificaciones se limitan a participantes activos vinculados, excluyen al actor y deduplican; `CRITICA` usa los canales existentes de email automático e in-app. Adjuntos inline no duplican `documento_agregado`.

## Seguridad de navegación y autorización

- `ver` no es un campo de `Tarea` ni una autorización de negocio; pertenece a
  `access_control.Permiso` y `PerfilAccesoDetalle` como parte de VICMEAS.
- Para Tareas, `Permiso.ver` controla exclusivamente la visibilidad del item y sus
  hijos en el sidebar para la empresa activa. La autorización backend continúa usando
  VICMEAS: `ingresar` para listar/detallar, `crear` para crear y `modificar` para editar,
  publicar o las acciones funcionales correspondientes; `eliminar`, `autorizar` y
  `supervisor` conservan sus significados funcionales.
- V e I son independientes. Un usuario puede ver el menú y recibir 403 al acceder,
  o tener ingreso autorizado por URL aunque el item esté oculto. El superuser tiene
  bypass visual del sidebar, no bypass automático de VICMEAS.
- La visibilidad se evalúa por usuario, empresa activa, Vista y `ver=True`; los padres
  se muestran solo cuando al menos un hijo es visible. El sidebar usa mapping explícito
  item → Vista; los items GLOBAL son excepciones clasificadas y no un bypass general.

## Reglas de dominio transversales

- Toda entidad de negocio se filtra por empresa activa; los parámetros nunca eligen empresa.
- El avance usa `sum(cumplimiento * peso) / sum(pesos)`; mini-tareas no ponderan.
- El avance ponderado usa `sum(cumplimiento * peso) / sum(pesos)` solo sobre Hitos operativos (`anulado=False`). Crear, editar cumplimiento/peso, anular, reactivar o eliminar físicamente un Hito requiere recalcular el Avance cuando corresponda.
- Anular/reactivar SOLO cambia el flag `anulada` de la tarea afectada; NO escribe estados,
  responsables, participantes ni relaciones de descendientes. La anulación efectiva es
  lógica (`anulada_efectivamente` = propia OR padre OR abuelo), no una cascada física.
  Las fechas afectadas quedan pendientes de confirmación sin recálculo automático.
- Estados, reasignaciones, cierres, documentos, cotizaciones y accesos generan auditoría.
- Todo texto visible nuevo lleva `data-key`; no se editan diccionarios globales silenciosamente.

## Contrato de datos para T059

La población operativa de los ocho KPI excluye Tareas con `estado=BORRADOR` o
`anulada=True`. Los estados publicados considerados son `ACTIVA`, `GESTION`,
`PENDIENTE_APROBACION_CIERRE` y `CERRADA`. Cada fila de `Tarea` cuenta como una
unidad, sin colapsar relaciones padre/hija/nieta y sin sumar Hitos como Tareas.
La fecha de referencia para estado actual es `timezone.localdate()`.

Las fórmulas contractuales son:

- Total por estado: conteo actual por cada estado publicado.
- Atrasadas: `ACTIVA`, `GESTION` o `PENDIENTE_APROBACION_CIERRE`, con
  `fecha_tope < fecha_referencia`, `fecha_tope` no nula y
  `fecha_cumplimiento IS NULL`.
- Próximas a vencer: mismos estados abiertos, sin `fecha_cumplimiento`, con
  `fecha_tope` entre la fecha de referencia y siete días calendario después,
  inclusive; no incluye vencidas.
- Sin movimiento: estado abierto no anulado y último movimiento igual o anterior
  a `now() - 7 días`.
- Esperando aprobación: `estado=PENDIENTE_APROBACION_CIERRE`, una vez por Tarea.
- Carga abierta: conteo de Tareas abiertas no anuladas agrupadas por
  `Tarea.responsable`; no pondera prioridad ni incluye participantes, roles ni Hitos.
- Porcentaje de cumplimiento: `CERRADA / total_publicadas * 100`, con `0.00` si
  el denominador es cero y redondeo a dos decimales.
- Tiempo promedio de cierre: promedio en horas calendario de
  `fecha_cumplimiento - fecha_publicacion` para Tareas cerradas no anuladas con
  ambas fechas.

Para `sin movimiento`, el modelo actual no tiene modificación propia de Tarea.
El timestamp base es `Tarea.fecha_publicacion`; se toma el máximo disponible entre
ese valor, `TareaTransicion.timestamp`, `HitoHistorial.fecha` y
`DocumentoHistorial.fecha` asociado a documentos de la Tarea. La creación de un
`DocumentoTarea` sin historial adicional no aporta un timestamp inventado. No se
usan `TareaLectura`, apertura de `EnlaceTarea`, dashboards ni notificaciones, y no
se crea un campo `ultima_actividad`.

El dashboard personal consulta `Tarea.responsable`,
`TareaParticipante` y `Hito.responsable` dentro de la Empresa activa. Los Hitos
no anulados pueden aportar actividad a `sin movimiento`, pero nunca se agregan como
Tareas ni alteran `carga abierta por responsable`. El avance de Hitos sigue siendo
distinto del porcentaje de cumplimiento del dashboard.

T059 no persiste snapshots, agregados ni cache; los KPI se calculan bajo demanda
mediante ORM y las relaciones existentes.

## Índices

- `(empresa, estado)` — soporta el listado filtrado por empresa activa y separación
  borrador/publicada (FR-010).
- `(empresa, fecha_creacion)` — orden del listado (más recientes primero).

## Límites y fuera de alcance

- No hay eliminación física; la anulación es un flag persistente con auditoría.
- No hay usuarios externos ni enlaces públicos.
- No hay plantilla de hitos ni vencimiento automático de documentos.
- Local permanece `LEGACY API PENDIENTE`; no se modelan tabla, ID o elegibilidad cerrada.
- El maestro local de Proveedor queda planificado en `APPLICATION_APP proveedores`; solo su
  integración, validación, identificador y sincronización ERP permanecen `LEGACY API PENDIENTE`.
- Equipos/activos se modelan solo como concepto interno, sin integración legacy inventada.

## Migración por fases

Cada grupo de entidades se incorpora con migración aditiva y backfill idempotente.
La migración Phase 2 agrega primero `correlativo` nullable, `cierre_completado` nullable,
campos de auditoría/snapshot y
el estado ampliado; después ejecuta backfill idempotente y finalmente aplica unicidad/constraints.
Para cada Empresa, el backfill selecciona tareas existentes ordenadas por `fecha_creacion ASC`
y luego `id ASC` como desempate. Asigna números secuenciales desde `0000001`; una tarea en
`BORRADOR` recibe prefijo `B`, y una tarea `PUBLICADA` recibe prefijo `A` y se migra a `ACTIVA`.
Se preservan PK, registro, empresa, creador, responsable, prioridad y fechas; no se consume un
segundo número al publicar. Después del backfill, `CorrelativoEmpresa.siguiente_numero` es el
máximo número asignado para esa Empresa más 1, o `1` si no existen tareas. Publicar después
no modifica `siguiente_numero`. El proceso detecta correlativos ya rellenados y no los reasigna
destructivamente al reejecutarse conceptualmente.
No se agregan Departamento, Equipo/Activo, relaciones jerárquicas, participantes, Local ni
Proveedor en Phase 2. No se borran filas ni se modifican migraciones de otras apps. La secuencia
futura usa `transaction.atomic()` y bloqueo persistente por empresa para reservar el número al
crear, sin consumir otro número al publicar.
