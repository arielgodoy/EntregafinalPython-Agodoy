# Data Model: Tareas Internas - SPEC MAESTRA

**Date**: 2026-09-07 | **Feature**: [spec.md](spec.md) | **Research**: [research.md](research.md)

## Entidad: `Tarea` (app `tareas`)

| Campo | Tipo (Django) | Nulable | Default | Reglas |
|---|---|---|---|---|
| `id` | BigAutoField (PK) | no | auto | Se conserva exactamente para compatibilidad MVP; no se cambia el tipo ni el valor. |
| `correlativo` | `CharField(max_length=9)` | sí durante backfill, no al finalizar | nullable durante backfill | Constraint única `(empresa, correlativo)`; índice compuesto `(empresa, correlativo)`; formato exacto `A`/`B` + 7 dígitos (`A0000001` / `B0000001`). Solo se guarda este string; el número no se duplica en `Tarea`. |
| `cierre_completado` | BooleanField | no | `False` | Señal de lifecycle: la tarea alcanzó la condición funcional equivalente al 100% para solicitar cierre; no es porcentaje general de avance. |
| `titulo` | CharField(max_length=200) | no | — | Obligatorio siempre (FR-001). `blank=False`. |
| `descripcion` | TextField | sí (`blank=True, default=""`) | `""` | Opcional en borrador y publicada. |
| `prioridad` | CharField (choices aprobados: `SIMPLE`, `NORMAL`, `URGENTE`, `CRITICA`) | no | `NORMAL` (default aprobado por el usuario) | Valores aprobados: simple < normal < urgente < crítica (jerarquía: crítica > urgente > normal > simple). Default: `NORMAL`. Sin comportamientos adicionales asociados (sin colores, SLA, notificaciones ni vencimientos). |
| `estado` | CharField(choices=Estado) | no | `BORRADOR` | Estados persistentes canónicos: `BORRADOR`, `ACTIVA`, `GESTION`, `PENDIENTE_APROBACION_CIERRE`, `CERRADA`, `ANULADA`. `PUBLICADA` MVP se migra a `ACTIVA`; rechazo y reactivación son eventos/acciones. |
| `responsable` | FK(`auth.User`, on_delete=PROTECT, related_name="tareas_responsable") | sí (`null=True, blank=True`) | `None` | Opcional en borrador (FR-004); obligatorio y válido en publicada (FR-007/FR-008). PROTECT evita borrar un usuario con tareas asignadas. |
| `empresa` | FK(`access_control.Empresa`, on_delete=PROTECT, related_name="tareas") | no | — | Asignada desde `session['empresa_id']` al crear (FR-003); nunca editable desde el request. |
| `creada_por` | FK(`auth.User`, on_delete=PROTECT, related_name="tareas_creadas") | no | — | Auditoría mínima coherente con el sistema. |
| `fecha_creacion` | DateTimeField(auto_now_add=True) | no | auto | UTC (D9). |
| `fecha_publicacion` | DateTimeField | sí (`null=True, blank=True`) | `None` | Se fija solo al publicar; inmutable después (D4). |

## Enums

```text
Estados persistentes: BORRADOR | ACTIVA | GESTION | PENDIENTE_APROBACION_CIERRE |
                     CERRADA | ANULADA.
Eventos/acciones no persistentes como estado: PUBLICAR, RECHAZAR_CIERRE, REACTIVAR.
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
- **V2 (FR-008)**: Una tarea en `PUBLICADA` MUST NOT guardarse sin `responsable` válido;
  `fecha_publicacion` MUST estar fijada y no cambia en ediciones posteriores.
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

          ACTIVA/GESTION/PENDIENTE_APROBACION_CIERRE --anular--> ANULADA
          ANULADA --reactivar--> estado persistente anterior (acción auditada)
          Publicada no puede volver a BORRADOR.
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

Phase 2 usa la opción A: `Tarea.fechas_pendientes_confirmacion`, campo persistente booleano,
default `False`, nullable durante backfill y `False` para datos MVP. Al reactivar una tarea
con fechas afectadas se establece en `True`; la confirmación/reacomodo posterior lo devuelve
a `False`. No se inventan fechas nuevas ni se recalculan automáticamente. El snapshot y los
eventos conservan la auditoría de quién/cuándo anuló y reactivó.

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
- `TareaAnulacionSnapshot`: FK a una Tarea, `estado_anterior`,
  `fechas_pendientes_confirmacion` anterior, usuario que anuló, timestamp de anulación, usuario que
  reactivó nullable y timestamp de reactivación nullable. No incluye hijos, nietos,
  participantes ni `TareaRelacion`.
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

### Avance, fechas y documentos

- `Hito`: tarea, nombre, cumplimiento, peso relativo, fecha de creación y orden.
- `Avance`: tarea, modo manual/ponderado, porcentaje calculado y fecha.
- `CausaAtraso` y `Reprogramacion`: catálogo, fechas, causa, justificación, usuario y auditoría.
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
- Anular/reactivar guarda y restaura la estructura completa; las fechas afectadas quedan
  pendientes de confirmación sin recálculo automático.
- Estados, reasignaciones, cierres, documentos, cotizaciones y accesos generan auditoría.
- Todo texto visible nuevo lleva `data-key`; no se editan diccionarios globales silenciosamente.

## Índices

- `(empresa, estado)` — soporta el listado filtrado por empresa activa y separación
  borrador/publicada (FR-010).
- `(empresa, fecha_creacion)` — orden del listado (más recientes primero).

## Límites y fuera de alcance

- No hay eliminación física; la anulación es una transición auditada.
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
`BORRADOR` recibe prefijo `A`, y una tarea `PUBLICADA` recibe prefijo `B` y se migra a `ACTIVA`.
Se preservan PK, registro, empresa, creador, responsable, prioridad y fechas; no se consume un
segundo número al publicar. Después del backfill, `CorrelativoEmpresa.siguiente_numero` es el
máximo número asignado para esa Empresa más 1, o `1` si no existen tareas. Publicar después
no modifica `siguiente_numero`. El proceso detecta correlativos ya rellenados y no los reasigna
destructivamente al reejecutarse conceptualmente.
No se agregan Departamento, Equipo/Activo, relaciones jerárquicas, participantes, Local ni
Proveedor en Phase 2. No se borran filas ni se modifican migraciones de otras apps. La secuencia
futura usa `transaction.atomic()` y bloqueo persistente por empresa para reservar el número al
crear, sin consumir otro número al publicar.
