# Data Model: Control de acceso VICMEAS

## Entidades existentes

### `Empresa`

Define el alcance lógico de los permisos. La empresa activa se identifica mediante
`session['empresa_id']`.

### `Vista`

Representa una pantalla o punto de navegación catalogado. Las vistas del sidebar se
resuelven mediante el mapa canónico de `SIDEBAR_VIEW_NAMES`.

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

## Alcances de navegación

Los alcances jerárquicos se traducen a hojas catalogadas. Los contenedores del sidebar
y las vistas globales no se tratan como hojas ocultables.

## Bootstrap SYSTEM

`Notificaciones - Topbar` es una Vista interna obligatoria del shell/base funcional.
Su permiso se asocia al usuario y a `Empresa 00` como parte del bootstrap, aunque la
fila existente conserve `route_name` nulo o legacy; esta excepción no reclasifica otras
vistas ambiguas.