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
| GET | `/tareas/<tarea_id>/similitud/` | `similitud_tarea` | Vista de similitud T060 | `Tareas - Ciclo de vida` | `modificar` |
| POST | `/tareas/<tarea_id>/similitud/<evaluacion_id>/confirmar/` | `confirmar_similitud` | Acción de similitud T060 | `Tareas - Ciclo de vida` | `modificar` |

## Reconciliación con `tareas/urls.py`

Esta matriz distingue el estado documental de cada superficie sin cambiar el contrato
funcional. `ACTIVE` significa que la ruta existe actualmente en `tareas/urls.py`;
`DEFERRED` conserva una superficie prevista pero bloqueada por contrato; `OUT_OF_SCOPE`
identifica una ruta que no debe inventarse en esta feature.

| Estado | Método | Ruta actual | Nombre |
|---|---|---|---|
| ACTIVE | GET | `/tareas/` | `listar_tareas` |
| ACTIVE | GET | `/tareas/mis-tareas/` | `mis_tareas` |
| ACTIVE | GET | `/tareas/dashboard/general/` | `dashboard_general` |
| ACTIVE | GET | `/tareas/dashboard/general/empresa/<empresa_id>/` | `dashboard_general_empresa` |
| ACTIVE | GET | `/tareas/dashboard/general/empresa/<empresa_id>/departamento/<departamento_id>/` | `dashboard_general_departamento` |
| ACTIVE | GET | `/tareas/dashboard/general/empresa/<empresa_id>/usuario/<usuario_id>/` | `dashboard_general_usuario` |
| ACTIVE | GET | `/tareas/<pk>/` | `detalle_tarea` |
| ACTIVE | GET/POST | `/tareas/crear/` | `crear_tarea` |
| ACTIVE | GET/POST | `/tareas/<pk>/editar/` | `editar_tarea` |
| ACTIVE | POST | `/tareas/<pk>/publicar/` | `publicar_tarea` |
| ACTIVE | POST | `/tareas/<pk>/gestionar/` | `gestionar_tarea` |
| ACTIVE | POST | `/tareas/<pk>/completar/` | `completar_tarea` |
| ACTIVE | POST | `/tareas/<pk>/aprobar-cierre/` | `aprobar_cierre` |
| ACTIVE | POST | `/tareas/<pk>/rechazar-cierre/` | `rechazar_cierre` |
| ACTIVE | POST | `/tareas/<pk>/anular/` | `anular_tarea` |
| ACTIVE | POST | `/tareas/<pk>/reactivar/` | `reactivar_tarea` |
| ACTIVE | GET/POST | `/tareas/<pk>/hitos/` | `hitos_tarea` |
| ACTIVE | GET/POST | `/tareas/<pk>/documentos/` | `documentos_tarea` |
| ACTIVE | GET/POST | `/tareas/<pk>/comentarios/...` y gestión de participantes | Contrato T100; adaptadores server-side en `tareas/urls.py` |
| ACTIVE | GET | `/tareas/<tarea_id>/similitud/` | `similitud_tarea` |
| ACTIVE | POST | `/tareas/<tarea_id>/similitud/<evaluacion_id>/confirmar/` | `confirmar_similitud` |
| ACTIVE | POST | `/tareas/<tarea_id>/enlaces/crear/` | `crear_enlace_tarea` |
| ACTIVE | GET | `/tareas/enlace/<token>/` | `enlace_tarea` |
| ACTIVE | POST | `/tareas/enlaces/<enlace_id>/revocar/` | `revocar_enlace_tarea` |
| ACTIVE | GET | `/tareas/reuniones/` | `reunion_revision_lista` |
| ACTIVE | GET/POST | `/tareas/reuniones/crear/` | `reunion_revision_crear` |
| ACTIVE | GET | `/tareas/reuniones/<pk>/` | `reunion_revision_detalle` |
| ACTIVE | GET/POST | `/tareas/reuniones/<pk>/editar/` | `reunion_revision_editar` |
| ACTIVE | POST | `/tareas/reuniones/<pk>/accion/` | `reunion_revision_accion` |
| DEFERRED | GET/POST | `/tareas/rondas/` y operaciones de cotización | contrato PRE-P2/local pendiente de superficie web estable |
| OUT_OF_SCOPE | Cualquier ruta de integración ERP/legacy de Proveedor o Local | No existe | P2 ERP y P1 Local requieren contrato separado |

Las rutas activas de esta matriz son la fuente de reconciliación con el enrutador actual;
las tablas de rutas previstas más abajo permanecen como diseño histórico/futuro y no
autorizan crear endpoints ausentes.

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
- **Precondición de similitud**: obtener el umbral efectivo con
  `get_similarity_threshold(tarea.empresa)` y ejecutar
  `evaluate_task_similarity(tarea=tarea, threshold=threshold)`. Si existe alguna
  evaluación con `supera_umbral=True` y `decision=PENDIENTE`, la Tarea permanece
  en `BORRADOR`, se muestra la advertencia y no se publica.
- **Éxito**: cuando no existen coincidencias relevantes pendientes,
  `publish_task()` completa la publicación, con `estado=PUBLICADA` y
  `fecha_publicacion=now()`; redirect a detalle con mensaje de éxito.
- **Rechazo (responsable ausente o inválido)**: la tarea permanece en `BORRADOR`; se informa
  el motivo (mensaje de error en la vista, patrón `messages` / JSON controlado según canal).
- **Publicación irreversible**: no existe ruta ni operación de retorno a borrador (Q2).

### Similitud — T060

- **GET** `/tareas/<tarea_id>/similitud/`: muestra todas las evaluaciones de la
  Tarea con `supera_umbral=True`, ordenadas por porcentaje descendente, con
  candidata, título, estado, prioridad, porcentaje, umbral aplicado, indicador
  `CERRADA`, decisión y enlace de solo lectura si está autorizado.
- **POST** `/tareas/<tarea_id>/similitud/<evaluacion_id>/confirmar/`: recibe sólo
  `MISMO_PROBLEMA` o `DISTINTO_PROBLEMA` y llama a `confirm_similarity(...)`.
  No modifica `EvaluacionSimilitud` directamente desde la vista.
- **Empresa y autorización**: la Tarea y evaluación deben pertenecer a la
  Empresa activa; usa `Tareas - Ciclo de vida` + `modificar`.
- **Continuación**: reutiliza `/tareas/<pk>/publicar/` cuando todas las
  coincidencias relevantes están resueltas; no crea una API REST paralela.
- **Errores**: los `ValidationError` se devuelven como respuesta controlada y
  se muestran en la UI.

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
| 5 | Reunión/similitud | GET/POST | `reunion_revision` / `similitud_tarea` / `confirmar_similitud` | Reunión: ver, crear, modificar, `CONVOCAR` y marcar realizada; similitud: evaluar, mostrar coincidencias y confirmar decisiones antes de publicar |
| 5 | Crear enlace compartible | POST | `/tareas/<tarea_id>/enlaces/crear/` | `Tareas` + `modificar`; destinatario interno, Empresa activa y fecha de expiración futura |
| 5 | Abrir enlace compartible | GET | `/tareas/enlace/<token>/` | `login_required`, destinatario exacto, Empresa activa, token vigente; lectura específica sin permiso VICMEAS general |
| 5 | Revocar enlace compartible | POST | `/tareas/enlaces/<enlace_id>/revocar/` | `Tareas` + `modificar`; conserva el enlace y registra revocación |
| 6 | Dashboard personal | GET | `/tareas/mis-tareas/` | `Tareas - Dashboard personal` + `ingresar`; Empresa activa |
| 6 | Dashboard general | GET | `/tareas/dashboard/general/` | `Tareas` + `supervisor`; solo Empresas autorizadas |
| 6 | Drill-down Empresa | GET | `/tareas/dashboard/general/empresa/<empresa_id>/` | Hereda `Tareas` + `supervisor` de la Empresa seleccionada |
| 6 | Drill-down Departamento | GET | `/tareas/dashboard/general/empresa/<empresa_id>/departamento/<departamento_id>/` | Departamento directo de la Empresa; `tipo_ambito=DEPARTAMENTO` |
| 6 | Drill-down Usuario | GET | `/tareas/dashboard/general/empresa/<empresa_id>/usuario/<usuario_id>/` | Agrupa por `Tarea.responsable`; no duplica participantes |
| 6 | Drill-down Tarea | GET | `/tareas/<pk>/` | Reutiliza `detalle_tarea`; muestra contexto de una Tarea |

### Comentarios de Tarea — Phase 8 (rutas T100; integración visual T101 pendiente)

La tarjeta se integrará en el detalle existente `GET /tareas/<pk>/` en T101. El feed usa páginas fijas de 20,
orden `(created_at, pk)`, cursor por `TareaLectura` para participantes funcionales efectivos
(`Tarea.responsable` o `TareaParticipante`) y navegación histórica antes del cursor
sin avanzar lectura; cuando no hay pendientes muestra los 20 más recientes. Un lector con `ingresar`, Empresa activa,
usuario activo y acceso válido a la Tarea puede consultar el feed sin vínculo `TareaParticipante`; en ese caso no se
crea ni usa cursor, unread, badge o reconocimiento de Comentarios y la tarjeta no muestra composer. El reconocimiento
POST solo acepta el final de la siguiente página contigua efectivamente cargada y requiere participación funcional.
Abrir el detalle no mueve el cursor. La lectura usa `vista_nombre="Tareas"` e `ingresar`; las mutaciones requieren
además el vínculo vigente y el permiso VICMEAS/lifecycle correspondiente. Un enlace `EnlaceTarea` no crea participación
ni habilita acciones de Comentarios.

| Estado | Método | Ruta propuesta | Nombre sugerido | Autorización VICMEAS |
|---|---|---|---|---|
| ACTIVE | GET | `/tareas/<pk>/comentarios/` | `listar_comentarios` | `Tareas` + `ingresar`; Empresa/usuario activos y acceso válido a Tarea; vínculo no requerido para feed, sin cursor/unread para no vinculados |
| ACTIVE | POST | `/tareas/<pk>/comentarios/leer/` | `marcar_comentarios_leidos` | `Tareas` + `ingresar` + participación funcional; reconocer solo el final de la siguiente página contigua cargada, revalidado por backend; permitido también en Tarea cerrada/anulada (estado personal de lectura) |
| ACTIVE | POST | `/tareas/<pk>/comentarios/crear/` | `crear_comentario` | `Tareas` + `modificar` + participación funcional |
| ACTIVE | POST | `/tareas/<pk>/comentarios/<comentario_id>/editar/` | `editar_comentario` | `Tareas` + `modificar` + participación funcional; autor y hasta 1 hora |
| ACTIVE | POST | `/tareas/<pk>/comentarios/<comentario_id>/ocultar/` | `ocultar_comentario` | `Tareas` + `supervisor` (S) + participación funcional; motivo obligatorio |
| ACTIVE | POST | `/tareas/<pk>/comentarios/<comentario_id>/restaurar/` | `restaurar_comentario` | `Tareas` + `supervisor` (S) + participación funcional; motivo obligatorio |
| ACTIVE | POST | `/tareas/<pk>/participantes/<usuario_id>/vincular/` | `vincular_participante` | `Tareas` + `modificar`; el actor no necesita ser participante; bloqueado en `CERRADA`/anulada efectivamente |
| ACTIVE | POST | `/tareas/<pk>/participantes/<usuario_id>/desvincular/` | `desvincular_participante` | `Tareas` + `modificar`; el actor no necesita ser participante; bloqueado en `CERRADA`/anulada efectivamente |

La administración de `TareaParticipante` requiere VICMEAS `modificar`, pero no requiere que el
actor administrador sea él mismo participante; así una Tarea puede comenzar con cero
participantes y recibir su primer vínculo explícito, sin auto-vincular creador ni actor.
El responsable es participante funcional sin crear una fila explícita. `add_participant`/
`remove_participant` reciben el actor y revalidan en dominio
Empresa, usuario activo, `modificar` y lifecycle: `CERRADA` y anulada efectivamente bloquean
cambios de participantes; `BORRADOR` los admite. Para Comentarios, la participación funcional
efectiva es el responsable actual o un vínculo explícito; el creador no obtiene participación
por sí solo.

Las mutaciones de Comentarios revalidan en backend, inmediatamente antes de persistir, Empresa,
VICMEAS, participación funcional y estado vigente. Solo estados `ACTIVA`, `GESTION` y
`PENDIENTE_APROBACION_CIERRE` no anulados admiten cambios; `BORRADOR`, `CERRADA` y anulada
efectivamente son de solo lectura. Cerrar/anular congela las mutaciones del contenido de
Comentarios, pero no impide actualizar el estado personal de lectura
(`comentario_leido_hasta`). Restaurar una Tarea conserva lifecycle e historial.
Tarea, Comentario y documentos deben pertenecer a la Empresa activa y misma Tarea;
`DocumentoTarea` mantiene sus validaciones y el límite es cinco. Retirar asociación no
borra el documento físico. Los endpoints usan POST HTML/CSRF y respuestas controladas;
no se añade API REST ni permisos nuevos.

Crear, editar, ocultar y restaurar notifican a participantes funcionales efectivos y activos,
excepto al actor, sin duplicados por usuario; `CRITICA` conserva email automático de sistema. Solo crear
incrementa no leídos. La carga/expansión reconoce solo los registros de la siguiente página
contigua de 20; leer no notifica. Ocultos pendientes se entregan como tombstone neutro, sin
contenido/historial a quienes no son autor/S. Adjuntos inline no duplican `documento_agregado`.

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
ni migraciones. T060 puede renderizar ese contexto en templates HTML y es
responsable de DataTables, cards, acordeones, modal y presentación, sin mover ni
duplicar fórmulas de T059.

Las filas contractuales son: Empresas autorizadas en General; Departamentos y,
separadamente, Tareas `LOCAL` o sin Departamento histórico en Empresa;
responsables/Usuarios del Departamento en la dimensión Departamento; y Tareas
del responsable seleccionado en Usuario. Una fila de Tarea contiene `id`,
correlativo, título, estado, prioridad, responsable, `fecha_tope`,
`fecha_publicacion`, `tipo_ambito` y URL de detalle. Nunca se crea un
Departamento ficticio.

El modal `Ver info de la tarea` es de solo lectura, puede consumir datos
embebidos en la fila y muestra correlativo, título, descripción resumida, estado,
prioridad, responsable, fechas, ámbito, Local/Departamento y enlace al detalle.
No ofrece mutaciones. DataTables sólo se aplica a tablas de dashboard/drill-down
que requieran búsqueda, orden, paginación o filtros; no se aplica por defecto a
reuniones, enlaces ni similitud.

El dashboard personal conserva `/tareas/mis-tareas/` y el contexto de T059.
T060 puede usar JavaScript app-local en `tareas/static/tareas/js/`, separado por
dashboard, similitud y enlaces. `static/js/app.js` y vendor son inmutables.
Todo texto estático nuevo usa `data-key`; no se añaden claves dinámicas ni se
editan diccionarios de idioma en T060.

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

## Claves i18n T060/T064

### Gate transversal de cierre

Las rutas y templates de `tareas` no se consideran completamente implementados
solo por contener `data-key`. Todo texto estático y todo `message_key` debe existir
en los catálogos español e inglés; no se aceptan claves dinámicas no resolubles,
enums técnicos visibles sin etiqueta, ni mensajes backend/AJAX mostrados como
claves. El cierre requiere validación manual ES/EN de la superficie afectada y
estas métricas en cero: `MISSING_SP`, `MISSING_EN`, `ONE_SIDE`, `DYNAMIC_KEYS`,
`RAW_MESSAGE_KEYS_VISIBLE` y `VISIBLE_HARDCODED_TEXT`, salvo excepciones
justificadas y documentadas.

La prueba automática canónica es:

```powershell
python manage.py test tareas.tests.test_i18n --settings=AppDocs.settings_test
```

El inventario de `data-key` literales estáticos de
`tareas/templates/tareas/` identifica 176 claves. Se excluyen claves que
contienen expresiones Django (`{{ ... }}` o tags `{% ... %}`), además de los
valores dinámicos de tareas, usuarios, fechas y correlativos.

Las superficies nuevas de US6/T060 usan estos prefijos reales:

### Catálogo base

- `tareas.actions.*`
- `tareas.common.*`
- `tareas.empty_list`
- `tareas.fields.*`
- `tareas.form.*`
- `tareas.list.*`
- `tareas.priority.*`
- `tareas.state.*`

### Dashboards

- `tareas.dashboard.*`
- `tareas.personal.*`

### Reuniones

- `tareas.meetings.*`

### Similitud

- `tareas.similarity.*`

### Enlaces

- `tareas.links.*`

### Documentos y evidencia

- `tareas.documents.*`
- `tareas.evidence.*`

### Hitos, progreso y jerarquía

- `tareas.milestones.*`
- `tareas.progress.*`
- `tareas.hierarchy.*`

La comparación contra `static/lang/sp.json` y `static/lang/en.json` muestra:

- **20 claves literales presentes en ambos diccionarios**: estado A,
  `YA PRESENTE EN SP/EN`.
- **156 claves literales ausentes en ambos diccionarios**: estado B,
  `AUSENTE EN SP/EN — PENDIENTE DE DICCIONARIO GLOBAL`.

Las 156 claves faltantes quedan documentadas para una autorización separada
de edición de diccionarios globales. T064 no modifica
`static/lang/sp.json` ni `static/lang/en.json`, y no interpreta la ausencia
como autorización para agregarlas.
