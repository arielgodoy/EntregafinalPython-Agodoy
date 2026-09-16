# Contracts: Tareas Internas - URLs web y respuestas por fases

**Date**: 2026-09-07 | **Feature**: [spec.md](../spec.md) | **Data model**: [data-model.md](../data-model.md)

Contrato de la interfaz web server-side rendered. No se inventa una API REST pública;
si una fase requiere integración, se documenta un adaptador dentro de `tareas/` y se
mantiene bloqueado hasta autorización del contrato externo. La eliminación física no existe;
la anulación es una acción protegida y auditada.

> **REGISTRO INICIAL RESUELTO**: la app ya está registrada en `AppDocs/urls.py`,
> `AppDocs/settings.py` y `AppDocs/app_classification.py`. Cualquier modificación futura
> adicional de esos archivos requiere una tarea separada con autorización y scope
> explícitos; no forma parte del APPLICATION BOUNDARY de `tareas`.

Todas las rutas viven bajo el include `tareas/` con namespace `tareas`. Todas requieren
sesión autenticada + empresa activa + autorización ICMEAS según la operación; ante falta
de autorización responden **403** con `access_control/403_forbidden.html` (permite
solicitar acceso). La visibilidad de los items del sidebar se evalúa por separado con
`Permiso.ver` para la empresa activa. V no participa en la autorización de estas rutas.
Ante falta de empresa activa, redirigen al selector de empresa (comportamiento del
decorador vigente).

El sidebar de Tareas mantiene mapping explícito `tasks -> Tareas` y
`tasks_list/tasks_create ->` sus Vistas respectivas. El padre aparece si algún hijo es
visible; no tiene V propio. El superuser ve el sidebar completo por bypass visual, sin
alterar las autorizaciones ICMEAS de las rutas. Los elementos GLOBAL quedan fuera de
este contrato salvo clasificación explícita.

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
| 3 | Hitos/documentos | GET/POST | `hitos_tarea` / `documentos_tarea` | Peso normalizado; historial documental; `hitos_tarea` admite `accion=completar_hito` con reseña y evidencia y muestra `Ver cumplimiento Hito` en lectura para Hitos completados |

La acción `Ver cumplimiento Hito` reutiliza el GET de `hitos_tarea` y un modal de solo lectura; no crea una URL ni una acción POST nueva. Solo se muestra cuando `Hito.completado=True` y la autorización de lectura vigente permite consultar la Tarea/Hito. El modal lee los campos canónicos del Hito y lista todas sus `HitoEvidencia` (`0..N`), sin mezclar `EvidenciaCierre` de Tarea ni modificar datos. Para un Hito completado, el contrato visual solo ofrece `Ver cumplimiento Hito` y `Anular` cuando el actor tenga esa facultad; no ofrece edición, reasignación, nueva completitud, actualización de avance ni eliminación física. La reactivación de un Hito completado y anulado queda fuera de contrato hasta resolver FR-F44.
| 4 | Cotizaciones | GET/POST | `rondas_cotizacion` / `cotizaciones_ronda` | Default 3; máximo 3 versiones |
| 5 | Reunión/similitud | GET/POST | `reunion_revision` / `similitud_tarea` | Reunión: ver, crear, modificar, `CONVOCAR` y marcar realizada; crea su Tarea planificada, usa ámbito LOCAL/DEPARTAMENTO y no duplica una Tarea dentro de la misma reunión |
| 5 | Crear enlace compartible | POST | `/tareas/<tarea_id>/enlaces/crear/` | `Tareas` + `modificar`; destinatario interno, Empresa activa y fecha de expiración futura |
| 5 | Abrir enlace compartible | GET | `/tareas/enlace/<token>/` | `login_required`, destinatario exacto, Empresa activa, token vigente; lectura específica sin permiso VICMEAS general |
| 5 | Revocar enlace compartible | POST | `/tareas/enlaces/<enlace_id>/revocar/` | `Tareas` + `modificar`; conserva el enlace y registra revocación |
| 6 | Dashboard personal | GET | `/tareas/mis-tareas/` | `Tareas - Dashboard personal` + `ingresar`; Empresa activa |
| 6 | Dashboard general | GET | `/tareas/dashboard/general/` | `Tareas` + `supervisor`; solo Empresas autorizadas |
| 6 | Drill-down Empresa | GET | `/tareas/dashboard/general/empresa/<empresa_id>/` | Hereda `Tareas` + `supervisor` de la Empresa seleccionada |
| 6 | Drill-down Departamento | GET | `/tareas/dashboard/general/empresa/<empresa_id>/departamento/<departamento_id>/` | Departamento directo de la Empresa; `tipo_ambito=DEPARTAMENTO` |
| 6 | Drill-down Usuario | GET | `/tareas/dashboard/general/empresa/<empresa_id>/usuario/<usuario_id>/` | Agrupa por `Tarea.responsable`; no duplica participantes |
| 6 | Drill-down Tarea | GET | `/tareas/<pk>/` | Reutiliza `detalle_tarea`; muestra contexto de una Tarea |

### Dashboard y KPI — T059

Las rutas de dashboard requieren sesión autenticada y Empresa activa. El dashboard
personal conserva `vista_nombre="Tareas - Dashboard personal"` y
`permiso_requerido="ingresar"`. El dashboard general y todos sus drill-down usan
`vista_nombre="Tareas"` y `permiso_requerido="supervisor"`, validado para la
Empresa efectiva de la consulta. General no consulta todas las Empresas: agrega
solo aquellas donde el usuario tiene `Permiso.supervisor=True` para la Vista
`Tareas`. Una Empresa seleccionada y sus niveles descendientes heredan esa misma
autorización; nunca se confía en el `empresa_id` recibido sin validar alcance.

Cada respuesta de dashboard entrega contexto server-side para exactamente ocho KPI:
dimensión actual, filtros activos, filas, estado, prioridad, fechas relevantes,
enlaces al siguiente nivel y datos mínimos de la Tarea. El servicio no genera HTML.
Los KPI se calculan bajo demanda y no crean snapshots, cache persistente, modelos
ni migraciones. T060 es responsable de DataTables, cards, acordeones, modal y
presentación.

El drill-down contractual es `General -> Empresa -> Departamento -> Usuario ->
Tarea`. Departamento filtra exclusivamente Tareas con
`tipo_ambito=DEPARTAMENTO` y `departamento_id` seleccionado. No existe nivel Local
en T059 V1 y no se agrega Proveedor ni `Cotizacion.proveedor`.

### P2 — Integración ERP del proveedor local

La implementación PRE-P2 permite crear `RondaCotizacion`, configurar su mínimo,
conservar histórico de rondas, crear `Cotizacion` internas y sus versiones históricas,
usar los estados `RECIBIDA`, `SELECCIONADA` y `DESCARTADA`, asociar `DocumentoCotizacion`,
contar cotizaciones vigentes, validar el mínimo interno, cerrar una ronda cumplida,
abrir una ronda sucesora y bloquear el cierre de una Tarea cuando la última ronda no
cumple su mínimo. Este conteo significa cantidad de cotizaciones internas vigentes, no
cantidad de proveedores distintos.

El proveedor operativo será el maestro global local de la futura `APPLICATION_APP
proveedores`; no dependerá del ERP para crear, modificar con permisos, asociar a
cotizaciones, contar proveedores distintos ni seleccionar una cotización dentro de Django.
La evolución futura será `Cotizacion.proveedor -> proveedores.Proveedor`, nullable durante
la transición para conservar cotizaciones PRE-P2 con `proveedor=NULL`; las nuevas
cotizaciones exigirán proveedor después de esa evolución, sin backfill inventado.

P2 bloquea únicamente lookup ERP, validación contra el maestro legacy, identificador
legacy, conciliación, sincronización y actualización desde ERP. No bloquea el maestro
local ni el uso de proveedores dentro de Django.

`Cotizacion.estado = SELECCIONADA` representa la cotización elegida dentro de Django. No
crea todavía una entidad `Adjudicacion` ni implica selección en ERP.

El maestro local `Proveedor` tendrá inicialmente `id`, `rut`, `nombre`, `direccion`,
`comuna`, `ciudad`, `fono1`, `fono2`, `fax`, `contacto`, `email1`, `email2`, `activo`,
`created_at` y `updated_at`. Puede existir sin RUT; cuando exista, se normaliza y es único
globalmente incluso si el proveedor está inactivo. La baja es lógica. `convenio`, `visitas`,
`ProveedorEmpresa`, identificador legacy y sincronización ERP quedan fuera del alcance
inicial.

La regla futura es máximo 3 versiones por `(ronda, proveedor)`, validado en servicio
transaccional; no es un máximo por ronda completa. El conteo futuro será de proveedores
Django distintos con al menos una cotización `vigente=True` en la ronda, sin sumar rondas.
Los estados `RECIBIDA`, `SELECCIONADA` y `DESCARTADA` no excluyen por sí solos.

Local no tiene rutas propias ni endpoints inventados hasta resolver P1. Las rutas del
maestro local de Proveedor se definirán dentro de la futura app `proveedores` con ICMEAS;
las rutas de integración ERP permanecen bloqueadas por P2.

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
