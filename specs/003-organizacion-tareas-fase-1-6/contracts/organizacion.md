# Contrato publico de organizacion

## Rectificación arquitectónica definitiva — 2026-11-09

La ausencia de APIs owner para CRUD no bloquea la creación del catálogo SQL
autoritativo en `BASE_TAREAS`. Los servicios nuevos de Proveedores, Locales y
Departamentos serán servicios SQL de `tareas`, usando únicamente el resolver
configurable existente y sin importar ORM de `proveedores` u `organizacion`.

Las APIs públicas de `organizacion` siguen siendo obligatorias para consumir
membresías, elegibilidad, liderazgo e historia cuando la operación cruza el
dominio organizacional. La falta de `create_department`, reemplazo atómico de JEFE
o lifecycle no bloquea el DDL, pero sí bloquea la habilitación de esas operaciones
hasta contar con contrato público, adaptación autorizada o un protocolo SQL
compatible con T176/T182/T183/T201.

La transición debe conservar PK e IDs, reconciliar referencias de tareas y
membresías, adaptar callers existentes y deshabilitar los writers antiguos por
un procedimiento autorizado. Mientras eso no ocurra, el SQL target puede
construirse y probarse en un entorno aislado, pero no puede convertirse en un
segundo writer productivo.

**Limite de esta revision**: toda nueva funcionalidad se implementa en `tareas`.
Los modelos y servicios existentes de `organizacion` permanecen intactos. Tareas
solo puede consumir interfaces publicas ya existentes; este documento no autoriza
crear endpoints/servicios nuevos en organizacion ni importar sus modelos/helpers
privados. El target de persistencia sigue siendo el rol configurable `BASE_TAREAS`,
pero no se considera migrado ni activo.

### Autonomía reforzada de `tareas`

Para los tres maestros, `tareas` es propietaria de la validación y del servicio
de dominio target. No puede importar modelos, servicios, formularios, vistas,
migraciones ni tablas de `proveedores` u `organizacion`. Las interfaces públicas
organizacionales solo se consumen cuando una operación cruza membresías,
elegibilidad, liderazgo o historia.

El RUT de Proveedores se validará mediante una utilidad interna de `tareas`
(`tareas/utils/rut.py`) con módulo 11, normalización canónica, `K`, DV `0` y
tratamiento contractual de vacío/nulo. La interfaz JavaScript compartida es
auxiliar y nunca sustituye esta validación de servidor.

Los IDs de los maestros son referencias estables entre dominios. El nombre
histórico de una tabla SQL no crea ownership ni dependencia con la aplicación
que lo utilizaba anteriormente.

## Convenciones y contexto

Las interfaces se clasifican abajo por disponibilidad. Los contratos propuestos
que no existen son bloqueos, no tareas para implementarlos en organizacion.
Tareas consume el resolver ya existente en `tareas`; no se agrega resolver local
en organizacion ni se asume alias Django fijo.

HTTP deriva empresa_id de `request.session['empresa_id']` y actor_id de usuario
autenticado. Un servicio interno recibe contexto explicito validado por el caller;
no convierte un parametro del formulario en Empresa confiable. Todas las funciones
verifican Empresa de cada Departamento/membresia y rechazan mezcla de Empresas.

| Interfaz | Estado actual y uso permitido desde `tareas` |
|---|---|---|
| `list_active_departments(*, empresa_id)` | Existe como consulta publica en el worktree; devuelve DTO company-scoped. No acredita lectura desde `BASE_TAREAS` |
| `get_effective_memberships`, `check_department_eligibility`, `get_department_leadership`, `list_memberships`, `change_membership` | Interfaces publicas existentes; Tareas puede consumirlas sin modificar su implementacion. Membresias/historia siguen en el almacenamiento actual |
| `create_department`, `update_department_name` | No existe API owner; no bloquea DDL/servicios SQL de tareas, pero bloquea transición o integración de membresías hasta cerrar G19 |
| `replace_department_head` | No existe contrato/API atómica confirmada; T182 requiere contrato compatible o protocolo autorizado. No reemplazar con dos llamadas parciales a `change_membership` |
| `prepare_department_change`, `finalize_department_change` | No existen APIs públicas confirmadas; bloquean lifecycle T183/T201, no el DDL inicial |
| `list_active_locals`, `create_local`, `update_local`, `set_local_active` | No existen APIs públicas confirmadas; el CRUD SQL de tareas no usa ORM owner, pero la transición y callers antiguos requieren G18 |
| `get_membership_history`, `get_eligibility_changes` | Consumir solo si se verifica la interfaz publica existente; no importar helpers privados para completar una superficie |
| `organization_guard(*, empresa_id)` | Fence del owner en `default`; no es API HTTP ni protege por si solo writers MySQL. Tareas no lo importa como helper privado; G01/G07 siguen abiertos |

`change_membership` cubre transiciones de membresia segun su contrato existente;
no crear servicios duplicados ni mutar directamente los modelos de organizacion.
La referencia actual a Departamento no se cambia en esta autorizacion. T176/T177
permanecen historicamente completadas para `default`; no certifican la nueva
topologia ni autorizan Tareas a importar coordinacion privada.

## Mutaciones de Local

`Local` es por Empresa y conserva PK, codigo, `legacy_code`, `source`, activo y
fechas. La Empresa se deriva del contexto validado; su ID es referencia a CORE,
no FK fisica desde `BASE_TAREAS`. Los registros `source=ERP` no admiten edicion
manual. Los `source=LOCAL` admiten alta/edicion autorizadas. El contrato de
integridad para baja/reactivacion y el alcance editable de codigo/`legacy_code`
deben resolverse en T227 antes de exponer esas acciones; no inferirlos ni convertir
un registro ERP en LOCAL.

La nueva superficie/modal-AJAX se implementaria en `tareas`, con una identidad
VICMEAS y permisos ICMEAS por accion. El literal exacto de la identidad Local aun
requiere registro/confirmacion bajo G05; no crear Vistas por boton. No habilitar
acciones mientras G18 no ofrezca una API publica de lectura/escritura.

## Mutaciones del maestro de Departamento

El código es obligatorio al crear, único dentro de la Empresa según la restricción
existente e inmutable después del alta. No se inventan formato ni normalización.
`nombre` es obligatorio al crear y puede editarse; el contrato no impone unicidad
de nombre. La edición no acepta cambios de Empresa, código, `source` o `activo`.
Crear/editar requiere acceso vigente a la Empresa y C/M ICMEAS respectivamente;
no exige membresía organizacional del actor ni crea permisos/membresías. El source
inicial es `LOCAL`, conforme a la propiedad local del catálogo.

Las operaciones futuras en `tareas` requieren el protocolo pendiente G01/G07,
motivo, UUID y revision, y auditoria con valores anterior/nuevo. El mismo UUID/
payload debe replayarse sin duplicar el efecto; payload distinto es conflicto.
T216 selecciona un registro técnico de operación dentro de `BASE_TAREAS` para
persistir idempotencia, resultado incierto y estado de proyección. Esto no
convierte el registro en una auditoría central ni sustituye G02/G01/G07.
No consultar tablas CORE directamente ni crear shadow audit.

## Superficie administrativa y permisos

Identidad aprobada literal: **`Tareas - Maestro de departamentos`**. No tiene
metadata/ruta implementada en HEAD; no se asigna un ID numerico ni route_name
supuestamente existente. Cumple `App - Vista`; no renombrar a `Maestros - ...`
por convencion generica ni dividir en Vistas por boton.

Las nuevas superficies de los tres maestros pertenecen a `tareas`. Las vistas
delegan solo en APIs publicas existentes y no guardan modelos de `organizacion`
directamente ni duplican validadores SYSTEM. Cada maestro tiene una unica identidad;
auxiliares AJAX reutilizan la identidad madre. Las operaciones sin API publica
quedan bloqueadas, no se implementan con acceso privado.

| Accion | Capacidad existente a declarar | Estado de la asignacion |
|---|---|---|
| Listar/detalle/historial/preview organizacional | `ingresar` | Mapeo propuesto segun convencion CRUD; no implica membresia |
| Crear Departamento/Local o alta inicial de membresia | `crear` | Mapeo propuesto, sin nuevo flag |
| Editar Local manual/Departamento, suspender, recuperar o sustituir JEFE | `modificar` | Mapeo propuesto; ERP permanece protegido |
| Baja logica de membresia o Departamento | `eliminar` | Baja de Departamento solo T183/T201/G07; no borrado fisico |

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
