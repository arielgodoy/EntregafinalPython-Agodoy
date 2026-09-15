# Data Model: Control de acceso VICMEAS

## Entidades existentes

### `Empresa`

Define el alcance lógico de los permisos. La empresa activa se identifica mediante
`session['empresa_id']`.

### `Vista`

Representa una funcionalidad protegida catalogada. No equivale necesariamente a una
URL, View Django o punto de navegación individual. Varias Views/endpoints internos
pueden compartir una Vista Madre mediante el mismo `vista_nombre`. Las vistas
navegables del sidebar se resuelven mediante el mapa canónico de
`SIDEBAR_VIEW_NAMES`.

### `Permiso`

Relaciona `usuario`, `empresa` y `vista` con estas banderas booleanas:

| Grupo | Campo | Responsabilidad |
|---|---|---|
| V | `ver` | Visibilidad del item navegable |
| I | `ingresar` | Acceso efectivo a la vista |
| C | `crear` | Crear |
| M | `modificar` | Modificar |
| E | `eliminar` | Eliminar |
| A | `autorizar` | Autorizar |
| S | `supervisor` | Operaciones sensibles |

## Invariantes

- Una fila siempre pertenece a una combinación concreta de usuario, empresa y vista.
- `ver=True` no implica ninguna bandera ICMEAS.
- Una bandera ICMEAS no implica `ver=True`.
- Cambiar `ver` no modifica las otras seis banderas.
- La lectura y mutación se limita a la empresa autorizada.
- Los endpoints internos de una Vista Madre comparten su fila `Permiso`; el permiso
  requerido de cada endpoint se declara en su metadata protegida.

## Catálogo de endpoints

`discover_protected_views()` puede devolver varias definiciones para un mismo
`vista_nombre`. `ensure_protected_views_catalog()` las deduplica como una sola Vista
Madre y no concede permisos ni altera flags existentes. `ensure_user_view_permissions`
materializa una sola fila `Permiso` por usuario, empresa y Vista Madre, con flags
nuevos en `False`.

## Alcances de navegación

Los alcances jerárquicos se traducen a hojas catalogadas. Los contenedores del sidebar
y las vistas globales no se tratan como hojas ocultables.

## Bootstrap SYSTEM

`Notificaciones - Topbar` es una Vista interna obligatoria del shell/base funcional.
Su permiso se asocia al usuario y a `Empresa 00` como parte del bootstrap, aunque la
fila existente conserve `route_name` nulo o legacy; esta excepción no reclasifica otras
vistas ambiguas.