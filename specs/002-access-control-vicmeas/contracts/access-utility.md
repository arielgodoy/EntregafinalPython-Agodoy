# Contract: Utilitario de Acceso

## C. Asignación masiva

Interfaz web server-side en `access_control:utilitario_acceso`.

- `action=preview` valida usuario, empresa, alcance y banderas sin escribir.
- `action=confirm` recalcula el alcance en backend y aplica de forma aditiva las
  banderas seleccionadas.
- Una autorización `modificar` del ejecutor es obligatoria en la empresa objetivo.
- `autorizar` y `supervisor` requieren autorización `supervisor` y confirmación sensible.
- Las banderas existentes verdaderas se preservan; no se crean filas para vistas fuera
  del alcance catalogado.

## D. Ocultar vista del menú

- `action=hide_view_preview` muestra el impacto sobre permisos con `ver=True` sin escribir.
- `action=hide_view_confirm` recalcula y cambia únicamente `ver` a `False` para la vista
  y empresa seleccionadas.
- No modifica ICMEAS, no crea filas y no elimina permisos.
- La vista seleccionada debe ser una hoja navegable catalogada, no un contenedor, vista
  global o vista interna no navegable.

## Seguridad

La autorización del utilitario usa permisos ICMEAS explícitos. `V` solo controla el
sidebar y no sustituye la autorización backend. No se define una API REST.