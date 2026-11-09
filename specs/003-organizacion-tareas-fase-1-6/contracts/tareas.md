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

## Rectificación arquitectónica definitiva — 2026-11-09

Proveedores, Locales y Departamentos se implementarán como tablas SQL MySQL en
el rol configurable `BASE_TAREAS`. Todo DDL, servicio SQL e interfaz nueva vive
en `tareas`; no se usarán modelos ORM, migraciones Django ni modelos espejo.
La ausencia de APIs owner no bloquea el DDL ni el CRUD SQL target, pero sí bloquea
la transición, la adaptación de callers y la habilitación productiva hasta cerrar
fuente única, writers antiguos, auditoría, membresías y consistencia.

Los servicios deben resolver la conexión mediante `tareas.services.connection_roles`,
validar la Empresa activa donde corresponda, usar ICMEAS en las vistas, ejecutar
mutaciones en transacciones InnoDB con unicidades/locks SQL y consumir auditoría,
idempotencia y notificaciones existentes. No se crea un sistema paralelo.

## Capas y alcance de elegibilidad

Toda nueva pantalla/orquestacion de maestros reside en `tareas`. Los modelos y
servicios existentes de `proveedores` y `organizacion` permanecen intactos. Tareas
no accede a sus modelos/ORM privados: consume solo APIs publicas ya existentes y
usa su resolver `BASE_TAREAS` actual para el target aprobado. No se asume alias
fijo, FK fisica ni JOIN cross-database.

Tareas reutiliza `get_valid_users_for_empresa` (union vigente de usuarios con
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

Capacidades existentes y bloqueos para Tareas:

| Dependencia | Estado verificable del contrato | Consecuencia |
|---|---|---|
| Autenticacion/sesion/Empresa | APIs oficiales de Django/access_control; `request.user`, `session['empresa_id']`, helpers de Empresa | Reutilizar; nunca aceptar Empresa autoritativa del cliente |
| VICMEAS/ICMEAS | `VerificarPermisoMixin`, `verificar_permiso`, `user_has_permission_for_empresa` | Una identidad madre por maestro; sin permisos locales ni bypass |
| Organizacion | Consultas publicas de Departamento/membresias y `change_membership` existen en el worktree; T176/T177 son historicas | La lectura de Departamento usa el almacenamiento actual y no certifica BASE_TAREAS; consumir solo flujos compatibles con fuente vigente, no CRUD ni lock MySQL |
| Proveedores | CRUD existente usa ORM owner; no hay servicio público identificado | DDL/CRUD SQL target viable; G17 bloquea corte y writers antiguos |
| Locales | No hay API pública owner de listado/CRUD identificada | DDL/CRUD SQL target viable; G18 bloquea transición, callers y coordinación ERP |
| Departamentos | No hay API pública para create/update, JEFE atómico o lifecycle | DDL/CRUD SQL target viable; G19 bloquea membresías/lifecycle hasta contrato compatible |
| Auditoria | Servicio central publico existente; alcance/registro de eventos Tareas y maestros debe verificarse por G02 | Reutilizar API; el registro técnico aprobado por T216 no es auditoria paralela |
| Conexiones | Resolver `tareas.services.connection_roles` y APIs publicas de `settings` existentes | Reutilizar; no crear otro resolver ni modificar `DATABASES`/router |
| Notificaciones | APIs publicas de `notificaciones` y correo de sistema `acounts` | Reutilizar solo segun contrato; no clonar SMTP/cola |
| Sidebar/i18n | Recursos globales protegidos | Solo G05, con autorizacion especifica para cada excepcion |

Los consumidores de Tareas usan IDs estables, nunca un `ModelChoiceField`/QuerySet
de un owner remoto. Las lecturas/CRUD target se implementan mediante SQL autorizado en `tareas`, no
mediante ORM owner. Los consumidores antiguos requieren adaptación antes del
corte; no se mantiene una segunda fuente autoritativa. Fallos de resolver son
errores explícitos, sin fallback a `default`.

## Autonomía de catálogos y operación durable

La aplicación `tareas` debe poder operar los catálogos target sin instalar
`proveedores`, `organizacion`, `biblioteca` o `control_de_proyectos`. Solo puede
requerir las SYSTEM APPS y las interfaces públicas de SYSTEM/CORE declaradas en
este contrato. No se permiten imports directos de otra `APPLICATION_APP`, ORM
privado, migración remota, tabla owner ni fallback a `default`.

La validación Python de RUT pertenece a `tareas/utils/rut.py`. Debe exponer una
API interna estable para limpiar, normalizar, calcular DV y validar el RUT
completo, incluyendo `K`, `0` y valores vacíos según el contrato de Proveedores.
La validación JavaScript de `static/js/funciones.js` es únicamente de UX.

Toda mutación autorizada requiere un UUID y un registro técnico en
`BASE_TAREAS`. La operación se identifica por UUID y hash de payload, incluye
entidad, acción, Empresa, actor, resultado y estado de auditoría, y se bloquea
con `FOR UPDATE` durante replay/reconciliación. La mutación y el registro
participan de la misma transacción InnoDB. La auditoría central se proyecta
mediante `AuditoriaService.log_event_idempotent()` después del commit; no se
crea auditoría paralela ni se promete 2PC.

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
