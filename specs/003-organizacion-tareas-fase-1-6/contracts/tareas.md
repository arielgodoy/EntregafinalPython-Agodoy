# Contrato de integracion y regularizacion de tareas

**Estado**: extension propuesta; no API externa nueva.
Base existente: [FR-D y T054](../../001-tareas-internas/spec.md),
`participant_storage.py`, `authorization.py`, `participants.py`,
`notifications.py`, `task_mutation_locks.py`.

Precedencia: [SPEC MAESTRA, FR-P06](../../001-tareas-internas/spec.md) reconoce
este contrato como restriccion adicional de elegibilidad, no como sustituto de
roles, permisos o lifecycle. La
[matriz de sincronizacion](../synchronization.md) distingue asignacion/clonacion
de regularizacion, lectura de operacion y dependencias SYSTEM protegidas.

## Capas y alcance de elegibilidad

Tareas consume la API publica de organizacion; no lee internamente sus filas de
membresia. Reutiliza `get_valid_users_for_empresa` (union vigente de usuarios con
perfil de Empresa o Permiso) y `user_has_permission_for_empresa`. No sustituir
esa semantica por otra tabla de acceso inventada.

Agregar Opcion B como condicion de dominio, no como middleware global ni filtro
de visibilidad. Revalidar en servicios, no solo en botones/formularios.

| Superficie/familia existente | Aplicacion del nuevo requisito |
|---|---|
| Crear/publicar/editar/asignar tareas | Actor operativo y nuevos destinatarios segun funcion; conservar Base00 guard donde ya existe |
| Participantes/responsable | Actor elegible + M y creador o S; reemplazante activo/acceso/membresia; saliente no necesita elegibilidad |
| Lifecycle, cierre, anular/reactivar | Actor elegible y permisos/rol propios de cada operacion; no sustituirlos por regla administrativa de FR-D12 |
| Hitos, MiniTareas, progreso y reprogramacion | Actor y nuevas asignaciones elegibles; conservar reglas de autor/responsable/estado de cada familia |
| Comentarios, documentos/evidencia, reuniones, cotizaciones, enlaces y TO-DO cuando constituyan operaciones de tareas | Gate de dominio en sus comandos operativos; conservar excepciones/participacion especificas, sin ampliar el dominio funcional |
| Detalle, historiales, dashboards, consultas y lecturas ya autorizadas | No negar solo por falta de membresia; mantener permisos/acceso Empresa y visibilidad existente |
| Marcas/cursor de lectura | Conservar el flujo asociado a lectura autorizada; no confundirlo con gestion operativa |
| Maestro organizacional | Autorizacion propia, sin exigir membresia previa al administrador para poder dar altas |
| Login, sesiones, usuarios u otras apps | Fuera del gate |

T187 inventaria los callers concretos de cada familia antes de modificar codigo:
views, forms, servicios, endpoints AJAX y entradas internas/admin/commands si existen.
La tabla no autoriza crear superficies ausentes ni modificar SYSTEM.
La participacion efectiva conserva creador/responsable implicitos, participantes
explicitos, responsables de Hitos no anulados y MiniTareas segun T105.

## Interfaces conceptuales

Nombres propuestos siguiendo comandos por IDs y resultados DTO existentes;
no afirmar que estas funciones ya estan implementadas.

| Interfaz | Entrada/salida |
|---|---|
| `list_organizational_impacts(*, empresa_id, actor_id, user_id=None, department_id=None)` | Filas tarea/estado/ambito/roles/origen/causa; distingue revision de operacion permitida |
| `get_task_participations(*, empresa_id, task_ids)` | Referencias funcionales explicitas/implicitas deduplicadas, sin crear filas |
| `build_regularization_preview(command)` | DTO de solo lectura y huella ligada a actor/Empresa/backend/manifiesto/motivo/rol/revisiones |
| `validate_regularization(command, snapshot)` | Resultado por tarea con bloqueos; reutilizar validaciones de dominio, no ejecutar mutaciones |
| `regularize_task(command)` | Mismo nucleo y evidencias con una tarea; no degrada validaciones por ser individual |
| `regularize_tasks(command)` | Resultado confirmado con UUID, IDs modificados, estado de auditoria/comunicacion y replay |
| `reconcile_regularization(*, empresa_id, actor_id, operation_id)` | Consulta/reconciliacion de resultado incierto y auditoria, no repeticion ciega de mutaciones |

`command`: `empresa_id`, `actor_id`, `source_user_id`, `replacement_user_id`,
`role`, `task_ids` unicos/ordenados, `reason`, `operation_id` y
`expected_fingerprint` al confirmar. Rechazar vacio, duplicados, ids invalidos,
origen=destino, mezcla de Empresa o payload manipulado. No seleccionar todas las
tareas del usuario por defecto.

## Roles permitidos y preservacion

| Seleccion | Vinculo afectado | Regla |
|---|---|---|
| RESPONSABLE_LIDER | `Tarea.responsable_id` | Reasignacion real y ledger vigente; no crear TareaParticipante |
| PARTICIPANTE | Fila explicita de ese rol | Sustituir solo ese vinculo, preservando historia |
| INVITADO_OBSERVADOR | Fila explicita de ese rol | Idem, sin promover facultades |
| SUPERVISOR / AUTORIZADOR historicos | Fila historica, si existe | F16-G03: falta contrato de sustitucion publica, bloquear sin degradar a otro rol |
| CREADOR | Autor historico/rol legado | No cambiar `creada_por`; no usar regularizacion para reescribir autoria |
| Responsable de Hito / persona de MiniTarea | Relacion propia | Identificar en revision; conservar comandos y contratos propios, no incluir implicitamente en este lote |

No se declara completada la regularizacion de roles bloqueados. Una nueva decision
podra habilitarlos con sus validaciones existentes sin redisenar el catalogo.
Si reemplazante ya posee fila incompatible o duplicada, bloquear esa tarea y por
tanto todo el lote; no fusionar roles ni eliminar otra participacion silenciosamente.
Conservar restricciones existentes para creador/responsable implicitos.
La sustitucion no transfiere permisos VICMEAS ni lecturas/autoría del saliente.

## Revision y estados

Revisar tareas no CERRADA ni eliminadas, incluyendo BORRADOR y pendientes de cierre;
listar anuladas efectivamente como bloqueadas, no omitirlas para fingir ausencia
de trabajo pendiente. No permitir modificaciones que FR-D14/FR-E10 prohiben.
Tareas eliminadas pertenecen al historial L4/L5, no a un lote operativo.
Si se restauran, revalidar referencias organizacionales antes de nuevas operaciones,
sin cambiar las marcas/historia que L5 conserva.

Una baja de Departamento con una tarea abierta anulada o con bloqueo de jerarquia
no se finaliza: primero resolverla por sus flujos autorizados. No forzar cierre,
reactivacion o anulacion. Tareas cerradas no cambian de Departamento.
Toda tarea revisada conserva su padre y Empresa; una hija departamental puede
tener Departamento distinto de su madre por FR-E02.

## Preview y confirmacion

Preview incluye Empresa, identidad origen/destino, rol, motivo, IDs/correlativos,
estado de cada tarea, ambito, relacion afectada, validaciones de actor/reemplazante,
restricciones de jerarquia, warnings/bloqueos, backend/revision y fingerprint.
No escribir membresias, historial, notificaciones ni reservas de operacion durante
preview. Mostrar por separado "a revisar" y "se modificara"; no confundir impacto
con autorizacion.

Confirmacion POST/CSRF, modal Bootstrap, motivo visible y seleccion explicita.
Reutilizar firma de payload/fingerprint del patron L5, no su ledger de eliminacion.
Un token firmado no evita revalidacion ni otorga permisos. Si cambian tarea,
membresias, Empresa/actor, permisos o configuracion backend: rechazar confirmacion
obsoleta o recalcular preview, nunca ejecutar un contenido distinto del confirmado.

Regularizacion reutiliza Vista madre `Tareas`, M y regla por tarea creador o S.
Preview necesita acceso autorizado y validacion de la misma facultad, no basta I
para autorizar una futura escritura. Una seleccion con tareas de distintos creadores
puede requerir S segun la regla vigente; no introducir rol de "gestor global".
UI en templates propios, respuestas `success`/`message_key`, sin credenciales.

## Auditoria y notificaciones

Guardar Detalle por tarea y operacion comun en BASE_TAREAS antes de commit.
Reutilizar ledger de responsable; completar evidencia de participacion sin
reescribir eventos historicos. Proyectar auditoria central por interfaz publica
existente despues de commit, con identificador estable por detalle y tipo de evento;
no registrar un rollback como sustitucion exitosa.

| Evento | Destinatarios/canal |
|---|---|
| Sustitucion de responsable | Nuevo y anterior responsable activos, mensajes distintos, actor excluido, deduplicados; T054/FR-D17 |
| Sustitucion de PARTICIPANTE/INVITADO | Saliente/entrante activos segun baja/alta real; actor excluido; no notificar a quien no cambio |
| Traslado/perdida/suspension organizacional | Evento e identidad afectada documentados; destinatarios/canal finales pendientes F16-G04, no inventar audiencia |
| Recuperacion organizacional | Afectado obligatorio; otras audiencias/canal y auto-notificacion del actor requieren F16-G04 |
| Operacion rechazada/rollback | Ninguna notificacion de exito |

Eventos de tareas usan `emit_task_event`, `notify_task_event` y `send_task_email`,
que consumen `notificaciones.services.create_notification` y
`acounts.services.email_service.send_email_for_purpose`.
Canal ordinario in-app; CRITICA agrega correo de sistema por Empresa y
`purpose="notifications"`, nunca SMTP de perfil ni `email_enabled`.

Esta regla de canales corresponde a los eventos de sustitucion aqui definidos,
no redefine todas las comunicaciones de tareas: MiniTarea conserva destinatarios
opt-in y ausencia de correo automatico por prioridad (FR-F48/FR-F51/FR-T13);
convocatoria conserva FR-M04 y enlaces conserva T058. Una accion manual solo usa
correo de perfil si su contrato vigente lo dispone; que un usuario pulse un boton
no convierte un evento de sistema en correo personal. No cambiar SMTP ni APIs base.

Deduplicacion por `(operacion, tarea, tipo_evento, destinatario, canal)`.
Un replay confirmado no reemite automaticamente todos los efectos. Fallos
posteriores se registran sanitizados y distinguen operacion aplicada de entrega
pendiente. No prometer entrega exactamente-una-vez de email: el contrato base
no dispone de confirmacion idempotente transaccional del proveedor externo.
