# Feature Specification: Control de acceso VICMEAS

## Contexto

El sistema utiliza permisos por usuario, empresa y vista. Cada registro `Permiso`
contiene `V` (`ver`) y las acciones `ICMEAS`: `ingresar`, `crear`, `modificar`,
`eliminar`, `autorizar` y `supervisor`.

## Regla principal

`V` controla únicamente si una vista navegable aparece en el sidebar para la empresa
activa. Las acciones ICMEAS controlan la autorización efectiva del backend. Tener `V`
no concede `ingresar` ni ninguna otra acción.

La regla aplica también a superusuarios: `is_superuser` no concede bypass visual del
sidebar ni autorización backend por sí mismo. La autorización backend sigue las reglas
ICMEAS explícitas, incluida la semántica existente de `supervisor`.

## Requisitos funcionales

### FR-001 Visibilidad por empresa y usuario

El sidebar MUST calcular sus elementos usando los permisos del usuario para la empresa
activa almacenada en `session['empresa_id']`.

### FR-002 Separación de responsabilidades

La visibilidad MUST consultar `ver`; la autorización MUST consultar únicamente la
acción ICMEAS requerida por la vista u operación.

### FR-003 Autorización protegida

Una vista protegida MUST usar `VerificarPermisoMixin` o `@verificar_permiso`, con
`vista_nombre` y `permiso_requerido`, y responder mediante el flujo 403 existente
cuando falte la acción requerida.

### FR-004 Aislamiento multiempresa

Una autorización o visibilidad de una empresa MUST no conceder acceso a otra empresa.
Los identificadores recibidos por la petición no sustituyen a la empresa activa.

### FR-005 Operaciones masivas aditivas

El utilitario de acceso MUST permitir asignar una o más banderas a vistas de un
alcance catalogado, preservar las banderas existentes y ejecutarse dentro de una
transacción.

### FR-006 Vista navegable segura

El utilitario MUST poder ocultar una vista reduciendo `ver` a falso únicamente para
la empresa seleccionada y sin modificar las acciones ICMEAS ni crear o eliminar filas.

### FR-007 Confirmación de acciones sensibles

Asignar `autorizar` o `supervisor` MUST requerir autorización `supervisor` del
ejecutor y confirmación explícita.

### FR-008 Bootstrap de vistas SYSTEM

El bootstrap MUST conservar las nueve vistas mínimas de Control de Acceso, incluir
normalmente las vistas SYSTEM clasificables por namespace y permitir excepciones
explícitas, mínimas y documentadas para vistas SYSTEM internas imprescindibles del
shell/base funcional cuando su `route_name` sea nulo o legacy. `Notificaciones -
Topbar` es una excepción AS-BUILT; las demás vistas ambiguas MUST permanecer omitidas
hasta contar con evidencia y clasificación segura.

### FR-009 Vista Madre y endpoints internos

Una `Vista` VICMEAS representa una funcionalidad protegida, no necesariamente una
URL ni una View Django individual. N endpoints relacionados pueden compartir el
mismo `vista_nombre` cuando pertenecen a la misma funcionalidad.

La separación conceptual es:

- `vista_nombre` identifica la funcionalidad madre.
- `permiso_requerido` identifica la capacidad VICMEAS necesaria para una acción
  concreta.
- La URL o View Django representa el endpoint técnico.

No se debe aplicar como regla general la relación "un endpoint = una Vista VICMEAS".
Una Vista Madre puede tener N endpoints internos, cada uno con su permiso requerido
de I/C/M/E/A/S.

El catálogo debe resolver múltiples endpoints con el mismo `vista_nombre` como una
sola funcionalidad/Vista Madre. `discover_protected_views()` puede descubrir los
endpoints individualmente, pero `ensure_protected_views_catalog()` MUST crear o reutilizar una
sola Vista Madre, sin crear una Vista por endpoint, no conceder permisos y no
modificar flags existentes.

`ensure_user_view_permissions` MUST materializar un único `Permiso` por usuario,
empresa y Vista Madre. Los flags nuevos MUST quedar en `False`; no se crea un
permiso distinto por cada endpoint interno.

### FR-010 Navegación y convención de maestros

No todos los endpoints protegidos son elementos de navegación. Sólo las
funcionalidades navegables aparecen en el sidebar mediante su Vista Madre y
`V=True`. Crear, modificar, eliminar, inactivar, reactivar, detalle, copiar y
aprobar son acciones internas y no requieren una opción de menú independiente.

Las funcionalidades de catálogos maestros SHOULD usar la convención:

    Maestros - <Entidad>

Ejemplos: `Maestros - Proveedores`, `Maestros - Clientes`, `Maestros - Ciudades` y
`Maestros - Rubros`. Esta convención agrupa lógicamente las funcionalidades en la
administración de permisos. No convierte ahora otras aplicaciones a esta
nomenclatura.

Cuando una funcionalidad cambia a una Vista Madre nueva, los registros `Vista`
legacy pueden permanecer en la base. No deben borrarse, renombrarse ni perder sus
`Permiso` históricos automáticamente; su limpieza o migración requiere una
operación posterior, explícita y controlada.

### Ejemplo validado: Archivos Maestros / Proveedores

La navegación `Archivos Maestros -> Proveedores` es una referencia validada de
esta política. Usa la Vista Madre `Maestros - Proveedores` para listado, detalle,
crear, editar, inactivar y reactivar, con permisos diferenciados según cada
acción. El catálogo sincroniza una sola Vista funcional y materializa permisos
vacíos deny-by-default; la visibilidad del sidebar depende de `V`.

## Criterios de aceptación

- Un usuario con `ver=True` e `ingresar=False` puede ver el item, pero recibe 403 al
  acceder a una vista protegida que exige `ingresar`.
- Un usuario con `ingresar=True` e `ver=False` puede estar autorizado por backend,
  pero no ve el item en el sidebar.
- Un superusuario sin el `Permiso.ver` correspondiente no ve el item y sin la acción
  ICMEAS requerida recibe 403.
- Los permisos de otra empresa permanecen intactos.
- Las asignaciones repetidas son idempotentes y no restablecen ni eliminan banderas
  no seleccionadas.
- La previsualización no escribe en la base de datos.
- Las operaciones sensibles sin `supervisor` o sin confirmación son rechazadas.
- El bootstrap incluye `Notificaciones - Topbar` y completa su permiso al crear o
  reutilizar un usuario técnico, sin incorporar automáticamente otras vistas ambiguas.
- Los endpoints internos de una funcionalidad comparten una Vista Madre y no crean
  opciones de menú independientes.

## Fuera de alcance

- Reemplazar `access_control` o introducir permisos Django estándar.
- Cambiar el modelo de empresa activa o el aislamiento multiempresa.
- Modificar el sidebar base, `static/js/app.js`, settings, Docker o infraestructura.
- Rediseñar permisos de aplicaciones de negocio.

## Trazabilidad

La implementación existente se contrasta en `access_control/services/permissions.py`,
`access_control/decorators.py`, `access_control/services/access_utility.py` y sus
pruebas focalizadas.