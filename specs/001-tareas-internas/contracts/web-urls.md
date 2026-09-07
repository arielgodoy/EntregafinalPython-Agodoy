# Contracts: Tareas Internas — URLs web y respuestas

**Date**: 2026-09-07 | **Feature**: [spec.md](../spec.md) | **Data model**: [data-model.md](../data-model.md)

Contrato de la interfaz web (server-side rendered). No se expone API REST en esta versión
(el sistema usa APIs internas separadas en `api/`; esta feature no las requiere).
La eliminación de tareas NO forma parte de esta versión (FUERA DE ALCANCE).

> **PENDIENTE DE AUTORIZACIÓN EXPRESA**: las rutas siguientes requieren registrar la app
> en `AppDocs/urls.py` (archivo CORE). La elección de app nueva NO autoriza ese cambio;
> queda bloqueado hasta autorización expresa del usuario.

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

Esta primera versión NO expone eliminación de tareas: no hay ruta, vista, modal, JS ni
permiso `eliminar`. Si en el futuro se solicita, se evaluará conforme a las reglas
vigentes del proyecto en ese momento.

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
