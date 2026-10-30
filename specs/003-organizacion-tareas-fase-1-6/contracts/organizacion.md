# Contrato publico de organizacion

**Estado**: interfaces conceptuales propuestas, no endpoints existentes.
Propietario: `organizacion`. Persistencia: `default`, conforme al deployment actual.
Consumidor de dominio: `tareas`. No importar storages/resolvers privados de tareas
desde organizacion ni leer sus tablas desde el maestro.

## Convenciones y contexto

Seguir el patron existente de servicios por keywords, comandos inmutables y DTOs
observado en `tareas/services/participant_storage.py`. Los nombres siguientes
son propuesta de API publica a crear en `organizacion/services/memberships.py`,
no firmas encontradas en codigo. Solo ids y valores, sin QuerySets lazy exportados.

HTTP deriva empresa_id de `request.session['empresa_id']` y actor_id de usuario
autenticado. Un servicio interno recibe contexto explicito validado por el caller;
no convierte un parametro del formulario en Empresa confiable. Todas las funciones
verifican Empresa de cada Departamento/membresia y rechazan mezcla de Empresas.

| Interfaz conceptual | Entrada | Salida y condiciones |
|---|---|---|
| `list_active_departments(*, empresa_id)` | Contexto validado | DTOs id/codigo/nombre/Empresa; solo activos de esa Empresa |
| `get_effective_memberships(*, empresa_id, user_id)` | Usuario y Empresa | Lista de membresias efectivas y revision; vacia es resultado de dominio, indisponibilidad no es vacia |
| `check_department_eligibility(*, empresa_id, user_id)` | Idem | elegible, codigos de causa, departamentos efectivos/revision; no concede VICMEAS |
| `get_department_leadership(*, empresa_id, department_id)` | Departamento | JEFE activo opcional y lista SUPERVISOR; cero no produce warning |
| `change_membership(command)` | Empresa, actor, usuario, Departamento, operacion, rol/estado destino, motivo, UUID y revision esperada | Nueva revision + eventos; atomico; no escribe tareas |
| `replace_department_head(command)` | Idem + nuevo JEFE + resolucion explicita del anterior | Una transaccion; ambos eventos, o ninguno |
| `get_membership_history(*, empresa_id, membership_id)` | Contexto/identidad | Eventos ordenados por fecha/PK; permiso de lectura aplicado; no mutacion |
| `get_eligibility_changes(*, empresa_id, operation_id)` | Operacion organizacional | Usuarios/Departamentos afectados y revisiones para revision en tareas; sin tarea copiada |
| `organization_guard(*, empresa_id)` | Empresa | Contexto de exclusion coordinada segun consistencia; no una API HTTP |
| `prepare_department_change(command)` / `finalize_department_change(command, review)` | Activacion/baja, motivo y prueba actual de revision | Cambio logico protegido; review debe proceder del orquestador confiable, nunca del navegador |

`change_membership` cubre suspension, baja y recuperacion; no crear servicios
duplicados con reglas divergentes para cada boton. Cada cambio revalida usuario,
acceso Empresa, Departamento, unicidad y capacidad administrativa. El saliente de
una baja no necesita conservar acceso/actividad; el entrante/reactivado si.

## Superficie administrativa y permisos

Identidad aprobada literal: **`Tareas - Maestro de departamentos`**. No tiene
metadata/ruta implementada en HEAD; no se asigna un ID numerico ni route_name
supuestamente existente. Cumple `App - Vista`; no renombrar a `Maestros - ...`
por convencion generica ni dividir en Vistas por boton.

Propuesta de integracion: superficie y orquestacion en `tareas/views.py`,
`tareas/urls.py`, formularios/templates propios de tareas; dominio de membresias
en organizacion. Asi se conserva la Vista funcional aprobada y no aparece el ciclo
organizacion -> tareas -> organizacion. La UI delega, no guarda membresias
directamente ni duplica validadores SYSTEM.

| Accion | Capacidad existente a declarar | Estado de la asignacion |
|---|---|---|
| Listar/detalle/historial/preview organizacional | `ingresar` | Mapeo propuesto segun convencion CRUD; no existente |
| Crear Departamento o alta inicial de membresia | `crear` | Mapeo propuesto, sin nuevo flag |
| Editar, suspender, recuperar, reactivar, sustituir JEFE | `modificar` | Mapeo propuesto; no habilitar sin validacion de metadata de la superficie |
| Baja logica de membresia o Departamento | `eliminar` | Mapeo propuesto por semantica de baja; no borrado fisico |

Estos mapeos son diseño de endpoints con flags existentes, no una concesion de
permisos a usuarios. Deben contrastarse con el catalogo del entorno al implementar,
sin renombrar ni ampliar permisos preexistentes. Si hay una Vista manual con politica
diferente, detener esa parte y reconciliarla; no se inspecciono DB en esta entrega.

Cada View/FBV expone `vista_nombre` y capacidad mediante mixin/decorator oficial.
Servicios revalidan con `user_has_permission_for_empresa`; respetan semantica
oficial de `supervisor`, pero JEFE/SUPERVISOR organizacional nunca se evalua
como permiso. No crear un permiso separado por endpoint auxiliar.

Navegacion normal no se filtra por `ingresar`: V e I siguen separados; V verdadero
con I falso debe mostrar el item y producir 403 oficial al acceder. No forzar V
ni materializar concesiones desde la app. F16-G05 cubre el registro/navegacion
cuando requiera archivos globales. La administracion estrictamente tecnica puede
mantener las restricciones de rol existentes; no convertir la vista funcional
aprobada en una pantalla solo-superuser.

## Efectos y errores

- Motivo obligatorio para cambios; UUID estable para replay; auditoria/historial
  con antes/despues. Repetir UUID con payload distinto es conflicto.
- Sustituir JEFE sin resolucion del anterior o con Empresa cruzada rechaza todo.
- Reactivar Departamento no levanta BAJA/SUSPENDIDA de membresias independientes.
- Una falla de almacenamiento/auditoria exigida no se comunica como exito.
  Publicacion central de auditoria necesita F16-G02; no tratar `None` como evento.
- Respuestas HTTP controladas `success` y `message_key`; errores de validacion,
  permiso o conflicto diferenciados conforme al patron existente, sin excepciones
  crudas. Nuevas claves quedan inventariadas para autorizacion i18n posterior.
- Los eventos organizacionales entregan ids/revisiones al consumidor; no llaman
  automaticamente a tareas para reasignar personas ni borran participaciones.
  La lista de revision de tareas debe poder reconstruirse por consulta, aunque
  una notificacion no se haya entregado.
