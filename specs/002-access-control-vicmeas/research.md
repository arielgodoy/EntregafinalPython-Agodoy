# Research: Control de acceso VICMEAS

## D1. VICMEAS es una extensión semántica de ICMEAS

La persistencia comparte `ver` con las seis acciones ICMEAS, pero sus decisiones son
distintas. Se conserva el modelo actual y se documenta la separación.

## D2. El sidebar y el backend tienen decisiones independientes

El sidebar usa `get_sidebar_visible_items` y `ver`. Las vistas protegidas usan la acción
requerida mediante el decorador o mixin. No se debe reutilizar `ver` para autorizar.

## D3. `is_superuser` no crea bypass

La búsqueda explícita en `decorators.py`, `views.py` (donde vive
`VerificarPermisoMixin`) y `services/permissions.py` no encontró una rama de
autorización basada en `is_superuser`. Las pruebas verifican que el superusuario respeta
`V` en el sidebar y las acciones ICMEAS en backend. La bandera explícita
`permiso.supervisor` sí tiene semántica de autorización amplia; no es un bypass por
`is_superuser` y debe mantenerse diferenciada.

## D4. El utilitario es aditivo

Las asignaciones crean filas cuando faltan, activan solo banderas seleccionadas y
preservan valores verdaderos existentes. Las operaciones usan transacciones y
recalculan el estado en confirmación.

## D5. La empresa activa es el límite de seguridad

Las operaciones reciben una empresa objetivo, pero la autorización del ejecutor y las
mutaciones se validan con permisos de esa empresa. Ninguna operación debe cruzar el
alcance lógico de otra empresa.

## D6. Topbar es una dependencia SYSTEM obligatoria

`/notificaciones/topbar/` resuelve a `notificaciones:topbar` y es atendido por
`NotificacionesTopbarView`, que usa `VerificarPermisoMixin` y exige `ingresar` para
`Vista.nombre = "Notificaciones - Topbar"`. `notificaciones` pertenece a
`SYSTEM_SUPPORT_APPS`, por lo que es una dependencia legítima del entorno SYSTEM.

La Vista existente tenía `route_name = NULL` o un valor legacy no clasificable; el
bootstrap la enviaba a `ambiguous/omitted`, no creaba el permiso y el endpoint devolvía
403. La corrección agrega una excepción SYSTEM explícita y mínima, conserva el registro
legacy y mantiene omitidas las demás ambiguas.

La evidencia operacional fue 403 antes de reejecutar el bootstrap sobre el mismo usuario
y 200 después, repetido en ejecuciones posteriores. Esto valida la idempotencia y la
actualización aditiva del usuario existente.

## Decisiones no negociables

- No usar permisos Django estándar.
- No tocar `access_control` en esta entrega documental.
- No modificar `specs/001-tareas-internas`.
- `Notificaciones - Topbar` es la única excepción SYSTEM explícita documentada para el
	bootstrap; no se generaliza a las demás vistas ambiguas.

## Follow-ups no bloqueantes

- `Vista.route_name` puede ser `NULL` en registros legacy.
- Vistas legacy ambiguas (sin namespace o sin ruta) son reportadas y omitidas por bootstrap.
- Menús legacy mantienen mappings fuera del árbol recursivo canónico.
- Persisten textos/i18n incompletos en templates internos y labels de formularios con
	fallback temporal.
- No hay una prueba flaky vigente identificada en esta revisión; si aparece, debe
	registrarse aquí como deuda y no como bloqueo de la spec.