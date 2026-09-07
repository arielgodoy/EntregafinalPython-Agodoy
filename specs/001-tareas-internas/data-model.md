# Data Model: Tareas Internas

**Date**: 2026-09-07 | **Feature**: [spec.md](spec.md) | **Research**: [research.md](research.md)

## Entidad: `Tarea` (app `tareas`)

| Campo | Tipo (Django) | Nulable | Default | Reglas |
|---|---|---|---|---|
| `id` | AutoField (PK) | no | auto | — |
| `titulo` | CharField(max_length=200) | no | — | Obligatorio siempre (FR-001). `blank=False`. |
| `descripcion` | TextField | sí (`blank=True, default=""`) | `""` | Opcional en borrador y publicada. |
| `prioridad` | CharField (choices aprobados: `SIMPLE`, `NORMAL`, `URGENTE`, `CRITICA`) | no | `NORMAL` (default aprobado por el usuario) | Valores aprobados: simple < normal < urgente < crítica (jerarquía: crítica > urgente > normal > simple). Default: `NORMAL`. Sin comportamientos adicionales asociados (sin colores, SLA, notificaciones ni vencimientos). |
| `estado` | CharField(max_length=10, choices=Estado) | no | `BORRADOR` | Choices: `BORRADOR`, `PUBLICADA` (FR-005). |
| `responsable` | FK(`auth.User`, on_delete=PROTECT, related_name="tareas_responsable") | sí (`null=True, blank=True`) | `None` | Opcional en borrador (FR-004); obligatorio y válido en publicada (FR-007/FR-008). PROTECT evita borrar un usuario con tareas asignadas. |
| `empresa` | FK(`access_control.Empresa`, on_delete=PROTECT, related_name="tareas") | no | — | Asignada desde `session['empresa_id']` al crear (FR-003); nunca editable desde el request. |
| `creada_por` | FK(`auth.User`, on_delete=PROTECT, related_name="tareas_creadas") | no | — | Auditoría mínima coherente con el sistema. |
| `fecha_creacion` | DateTimeField(auto_now_add=True) | no | auto | UTC (D9). |
| `fecha_publicacion` | DateTimeField | sí (`null=True, blank=True`) | `None` | Se fija solo al publicar; inmutable después (D4). |

## Enums

```text
Estado:     BORRADOR | PUBLICADA   (respaldado por FR-005 y clarifications)
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
        ┌───────────┐   publicar() [requiere responsable válido]   ┌────────────┐
        │ BORRADOR  │ ───────────────────────────────────────────▶ │ PUBLICADA  │
        └───────────┘                                              └────────────┘
              │                                                          │
              │ edición libre                                            │ edición libre
              │ (cualquier campo)                                        │ (responsable válido obligatorio)
              ▼                                                          ▼
        permanece BORRADOR                                        permanece PUBLICADA
        (indefinidamente)                                         (sin retorno a BORRADOR)
```

## Relaciones

- `Tarea.empresa` → `access_control.Empresa` (N:1). Aislamiento por `session['empresa_id']`.
- `Tarea.responsable` → `django.contrib.auth.models.User` (N:1, opcional en borrador).
- `Tarea.creada_por` → `User` (N:1).

## Índices

- `(empresa, estado)` — soporta el listado filtrado por empresa activa y separación
  borrador/publicada (FR-010).
- `(empresa, fecha_creacion)` — orden del listado (más recientes primero).

## Fuera de alcance (FR-013)

Sin subtareas, hitos, cotizaciones, proveedores, reuniones ni similitud histórica:
no se crean modelos ni relaciones adicionales.

Además, la **eliminación de tareas NO forma parte del alcance de esta primera spec**:
no se modela borrado (lógico o físico), ni cascadas, ni reglas de eliminación.

## Migración

- Una única migración inicial generada con `python manage.py makemigrations tareas`
  durante la implementación (autorizada por ser parte del alcance de la feature). No se
  tocan migraciones de otras apps.
