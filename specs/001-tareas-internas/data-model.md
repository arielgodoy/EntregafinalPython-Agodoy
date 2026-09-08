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

- Departamento: pendiente de definición exacta; no se determina aún si será modelo propio,
  referencia existente o código/string, ni su obligatoriedad, relación con Empresa o constraints.
  No entra como campo de la migración Phase 2.
- Equipo/Activo: pendiente de definición exacta; no se determina aún modelo, código, relación
  con Empresa, nulabilidad o constraints. No entra como campo de la migración Phase 2.
- Local sigue bloqueado por P1 y no se confunde con Departamento.

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

- `Hito`: tarea, nombre, `responsable` FK obligatorio a `auth.User` con `on_delete=PROTECT`, cumplimiento `0..100`, peso relativo, fecha de creación y orden. El responsable puede diferir del responsable principal de la Tarea, pero MUST estar activo y pertenecer/tener acceso válido a la Empresa de la Tarea; la validación debe impedir cruces multiempresa y rechazar la operación sin cambios parciales.
- `Hito` no tiene campo propio de `prioridad` ni `fecha_tope`; para presentación y dashboard hereda únicamente la clasificación/prioridad de su Tarea padre. No se asume herencia de vencimiento.
- `Avance`: tarea, modo manual/ponderado, porcentaje calculado y fecha.
- `Tarea.fecha_asignacion`: DateTime nullable mientras no se publica, fijada al publicar/asignar oficialmente y conservada como referencia histórica original; una reasignación no la modifica.
- `Tarea.fecha_tope`: Date nullable; puede ser NULL solo en `BORRADOR` durante edición y es el dato funcional principal de vencimiento. Toda Tarea publicada/operativa MUST tenerla.
- `Tarea.fecha_cumplimiento`: DateTime nullable; fecha/hora real en que se completa la última acción operativa necesaria. Es distinta de la fecha de cierre/aprobación, corta el cálculo de atraso y vuelve a NULL si el cierre es rechazado y la Tarea vuelve a `GESTION`; el intento queda en `TareaTransicion`.
- `CausaAtraso`: catálogo inicial cerrado a imposibilidad técnica, atraso importación, permisos municipales, problemas de escrituras, causas internas y causas externas.
- `Reprogramacion`: tarea, `fecha_tope_anterior`, `fecha_tope_nueva`, justificación obligatoria, usuario y `fecha_operacion`; cambiar una `fecha_tope` existente es una reprogramación explícita y no una reasignación. Cada reprogramación se relaciona con una o varias `CausaAtraso` mediante M:N.
- `dias_atraso` es derivado: durante la edición de un `BORRADOR` sin `fecha_tope` vale cero; toda Tarea publicada tiene fecha y, si no está cumplida, se calcula contra `fecha_referencia`; con Tarea cumplida se usa `fecha_cumplimiento` como corte. La aprobación posterior no suma atraso. La anulación no reescribe fechas ni elimina el atraso histórico, y la reactivación no recalcula fechas.
- `MiniTarea`: mantiene una persona única y estado hecho/no hecho; no pondera el avance y no se fusiona con `Hito`.
- No existe todavía una regla de reasignación ni historial de reasignación específico para el responsable de Hito. Si el dashboard futuro requiere esa trazabilidad, deberá definirse como decisión posterior antes de implementarla.
- Los Hitos históricos existentes sin responsable requieren una estrategia de migración segura posterior. La implementación futura debe detenerse/reportar ante esos registros y no puede asignar automáticamente el responsable de la Tarea, creador, administrador ni otro usuario sin autorización explícita.
- `DocumentoTarea`: tipo, archivo o URL, fechas informativas, usuario y estado.
- `DocumentoHistorial` y `EvidenciaCierre`: historial de cambios y evidencia requerida.

### Cotizaciones y referencias externas

- `RondaCotizacion`: tarea, número, mínimo configurable (default 3), fechas y estado.
- `Cotizacion`: ronda, referencia de proveedor pendiente, versión, monto, vigente y estado;
  la identidad real del proveedor queda bloqueada por P2.
- `Adjudicacion`: ronda, cotización seleccionada, usuario, fecha y observación.
- `ProveedorReferencia`: **PLACEHOLDER DE DISEÑO — IMPLEMENTACIÓN BLOQUEADA POR P2**.
  No define campos, `rut_contable`, ID externo, tabla legacy, endpoint ni sincronización;
  tampoco genera una tarea de implementación mientras P2 siga bloqueado.

### Colaboración y analítica

- `ReunionRevision` y `ReunionTarea`: modalidad, agenda, prioridades, convocatoria y comentario.
- `TareaOrigen`: tarea nueva, tarea origen y usuario/fecha de derivación.
- `EvaluacionSimilitud`: tareas, porcentaje, umbral aplicado, confirmación y fecha; incluye cerradas.
- `UmbralSimilitudEmpresa`: empresa, default 80%, usuario/fecha y vigencia para nuevas evaluaciones.
- `EnlaceTarea` y `EventoAccesoEnlace`: identificador, tarea/hito, vigencia, usuario, empresa,
  resultado y auditoría; el acceso exige autenticación, empresa activa e ICMEAS.

Las notificaciones se refieren a la infraestructura existente de `notificaciones` y email de
`acounts`; no se duplica su modelo.

## Reglas de dominio transversales

- Toda entidad de negocio se filtra por empresa activa; los parámetros nunca eligen empresa.
- El avance usa `sum(cumplimiento * peso) / sum(pesos)`; mini-tareas no ponderan.
- Anular/reactivar SOLO cambia el flag `anulada` de la tarea afectada; NO escribe estados,
  responsables, participantes ni relaciones de descendientes. La anulación efectiva es
  lógica (`anulada_efectivamente` = propia OR padre OR abuelo), no una cascada física.
  Las fechas afectadas quedan pendientes de confirmación sin recálculo automático.
- Estados, reasignaciones, cierres, documentos, cotizaciones y accesos generan auditoría.
- Todo texto visible nuevo lleva `data-key`; no se editan diccionarios globales silenciosamente.

## Índices

- `(empresa, estado)` — soporta el listado filtrado por empresa activa y separación
  borrador/publicada (FR-010).
- `(empresa, fecha_creacion)` — orden del listado (más recientes primero).

## Límites y fuera de alcance

- No hay eliminación física; la anulación es un flag persistente con auditoría.
- No hay usuarios externos ni enlaces públicos.
- No hay plantilla de hitos ni vencimiento automático de documentos.
- Local permanece `LEGACY API PENDIENTE`; no se modelan tabla, ID o elegibilidad cerrada.
- Proveedor permanece `LEGACY API PENDIENTE`; no se modelan maestro, tabla, API o `rut_contable`.
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
