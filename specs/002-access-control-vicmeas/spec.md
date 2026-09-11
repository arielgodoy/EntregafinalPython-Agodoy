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

## Fuera de alcance

- Reemplazar `access_control` o introducir permisos Django estándar.
- Cambiar el modelo de empresa activa o el aislamiento multiempresa.
- Modificar el sidebar base, `static/js/app.js`, settings, Docker o infraestructura.
- Rediseñar permisos de aplicaciones de negocio.

## Trazabilidad

La implementación existente se contrasta en `access_control/services/permissions.py`,
`access_control/decorators.py`, `access_control/services/access_utility.py` y sus
pruebas focalizadas.