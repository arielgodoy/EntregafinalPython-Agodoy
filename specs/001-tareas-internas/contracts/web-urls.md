# Contracts: Tareas Internas - URLs web y respuestas por fases

**Date**: 2026-09-07 | **Feature**: [spec.md](../spec.md) | **Data model**: [data-model.md](../data-model.md)

Contrato de la interfaz web server-side rendered. No se inventa una API REST pública;
si una fase requiere integración, se documenta un adaptador dentro de `tareas/` y se
mantiene bloqueado hasta autorización del contrato externo. La eliminación física no existe;
la anulación es una acción protegida y auditada.

> **REGISTRO INICIAL RESUELTO**: la app ya está registrada en `AppDocs/urls.py`,
> `AppDocs/settings.py` y `AppDocs/app_classification.py`. Cualquier modificación futura
> adicional de esos archivos requiere autorización expresa.

Todas las rutas viven bajo el include `tareas/` con namespace `tareas`. Todas requieren
sesión autenticada + empresa activa + permiso ICMEAS; ante falta de permiso responden
**403** con `access_control/403_forbidden.html` (permite solicitar acceso). Ante falta de
empresa activa, redirigen al selector de empresa (comportamiento del decorador vigente).

## Rutas

| Método | Ruta | Nombre (`tareas:`) | Vista | `vista_nombre` | `permiso_requerido` |
|---|---|---|---|---|---|
| GET | `/tareas/` | `listar_tareas` | `ListarTareasView` | `Tareas - Listado` | `ingresar` |
| GET | `/tareas/<pk>/` | `detalle_tarea` | `DetalleTareaView` | `Tareas - Detalle` | `ingresar` |
| GET/POST | `/tareas/crear/` | `crear_tarea` | `CrearTareaView` | `Tareas - Crear tarea` | `crear` |
| GET/POST | `/tareas/<pk>/editar/` | `editar_tarea` | `EditarTareaView` | `Tareas - Editar tarea` | `modificar` |
| POST | `/tareas/<pk>/publicar/` | `publicar_tarea` | `PublicarTareaView` | `Tareas - Publicar tarea` | `modificar` |

## Contratos por operación

### Listar — `GET /tareas/`

- **Response 200**: HTML con las tareas de la **empresa activa** únicamente, ordenadas por
  `fecha_creacion` descendente, paginadas (20), separando/marcando borradores y publicadas.
- **Aislamiento**: una tarea de otra empresa nunca aparece (FR-003, FR-010).

### Detalle — `GET /tareas/<pk>/`

- **Response 200**: HTML con título, descripción, prioridad, estado, responsable, fecha de
  creación y fecha de publicación (si existe).
- **404**: si la tarea no pertenece a la empresa activa.

### Crear — `POST /tareas/crear/`

- **Request (form)**: `titulo` (requerido), `descripcion`, `prioridad`, `responsable` (opcional).
- **Response 302**: redirect a detalle; la tarea queda en `BORRADOR` con
  `empresa = session['empresa_id']` y `fecha_creacion` registrada.
- **Response 200** (form inválido): errores de campo en el formulario.

### Editar — `POST /tareas/<pk>/editar/`

- **Request (form)**: `titulo`, `descripcion`, `prioridad`, `responsable`.
- **Reglas**: en `PUBLICADA`, `responsable` MUST ser válido/activo; `estado` no es editable
  por formulario (la transición ocurre solo vía publicar); `fecha_publicacion` inmutable.
- **404**: tarea de otra empresa.

### Publicar — `POST /tareas/<pk>/publicar/`

- **Precondición**: tarea en `BORRADOR` de la empresa activa.
- **Éxito**: `estado=PUBLICADA`, `fecha_publicacion=now()`; redirect a detalle con mensaje
  de éxito.
- **Rechazo (responsable ausente o inválido)**: la tarea permanece en `BORRADOR`; se informa
  el motivo (mensaje de error en la vista, patrón `messages` / JSON controlado según canal).
- **Publicación irreversible**: no existe ruta ni operación de retorno a borrador (Q2).

### Eliminación — FUERA DE ALCANCE

No existe eliminación física, ruta de borrado ni permiso `eliminar`. La anulación/reactivación
se exponen como acciones de ciclo de vida protegidas por ICMEAS y no destruyen datos.

## Rutas adicionales por fase

Las rutas siguientes son contratos previstos, no implementación actual. Cada una conserva
sesión autenticada, empresa activa, aislamiento, ICMEAS y respuestas controladas.

| Fase | Operación | Método | Nombre sugerido | Regla principal |
|---|---|---|---|---|
| 1 | Transición de estado | POST | `transicionar_tarea` | Solo pares permitidos; registra auditoría |
| 1 | Anular/reactivar | POST | `anular_tarea` / `reactivar_tarea` | Solo cambia el flag `anulada` de la tarea; anulación efectiva lógica (tarea+padre+abuelo); nunca borrar ni tocar estados |
| 2 | Participantes/reasignación | GET/POST | `participantes_tarea` / `reasignar_tarea` | Usuarios activos y empresa activa |
| 2 | Jerarquía/mini-tareas | GET/POST | `jerarquia_tarea` / `minitareas_tarea` | Máximo dos niveles; mini-tareas bloquean cierre |
| 2 | Reprogramación | POST | `reprogramar_tarea` | Justificación y auditoría obligatorias |
| 3 | Hitos/documentos | GET/POST | `hitos_tarea` / `documentos_tarea` | Peso normalizado; historial documental |
| 4 | Cotizaciones | GET/POST | `rondas_cotizacion` / `cotizaciones_ronda` | Default 3; máximo 3 versiones |
| 5 | Reunión/similitud | GET/POST | `reunion_revision` / `similitud_tarea` | Tareas cerradas incluidas; confirmar repetición |
| 5 | Enlace compartible | GET | `enlace_tarea` | Solo autenticado, lectura e ICMEAS |
| 6 | Dashboard/KPI | GET | `dashboard_tareas` | Ocho KPI por dimensión permitida |

Local y Proveedor no tienen rutas propias ni endpoints inventados: sus referencias solo se
habilitan cuando P1/P2 tengan contrato autorizado.

## Claves i18n nuevas (a reportar para alta en `static/lang/sp.json` / `en.json`)

- `tareas.list.title`, `tareas.form.title_create`, `tareas.form.title_edit`,
  `tareas.detail.title`, `tareas.fields.*` (titulo, descripcion, prioridad, estado,
  responsable, empresa, fecha_creacion, fecha_publicacion), `tareas.state.*` (borrador,
  publicada), `tareas.actions.*` (crear, editar, publicar),
  `tareas.publish.error_no_responsable`, `tareas.publish.error_responsable_invalido`,
  `tareas.empty_list`.
- `tareas.priority.*`: `tareas.priority.simple`, `tareas.priority.normal`,
  `tareas.priority.urgente`, `tareas.priority.critica` (valores aprobados: simple, normal,
  urgente, crítica).

> Nota: las claves se reportan en la entrega; los diccionarios de idioma se actualizan solo
> si el usuario lo autoriza (regla i18n: reportar, no editar silenciosamente).
