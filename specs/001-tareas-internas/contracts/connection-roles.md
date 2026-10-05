# Contract: Tareas Connection Roles

**Feature**: Tareas Internas
**Status**: Implementado para configuración; bootstrap Base Tareas en preparación

## Alcance

`GLOBAL POR APP`.

Tareas mantiene un unico conjunto global de roles. No existe configuracion `(empresa,
role)` ni FK `Empresa` en el modelo de roles.

## Roles

- `BASE_TAREAS`
- `AUDITORIA_TAREAS`
- `LEGACY_MYSQL`
- `LEGACY_AUDITORIA`

## Fuentes permitidas

| Rol | Sistema Django | MySQL |
|---|---:|---:|
| `BASE_TAREAS` | Si | Si |
| `AUDITORIA_TAREAS` | Si | Si |
| `LEGACY_MYSQL` | No | Si |
| `LEGACY_AUDITORIA` | No | Si |

Django y MySQL son mutuamente excluyentes. Legacy solo admite MySQL.

Para Tareas, el catálogo MySQL disponible para estos roles corresponde exclusivamente a
conexiones activas de `SettingsMySQLConnection` asociadas a `Empresa.codigo == "00"`.
La empresa activa de sesión no interviene en la selección ni resolución.

## Resolver

Entrada conceptual:

```text
role
```

Salida conceptual para Django:

```text
source_type=DJANGO
alias=alias SYSTEM validado
```

Salida conceptual para MySQL:

```text
source_type=MYSQL_CONFIG
mysql_connection=referencia SettingsMySQLConnection
database_name=base validada, cuando corresponda
```

El resolver es propio de `tareas`. Para Django consume un alias validado como SYSTEM y
la operacion usa `.using(alias)`. Para MySQL consume `SettingsMySQLConnection` y
`open_mysql_connection()`.

## Errores

El resolver debe producir errores controlados para:

- role inexistente;
- role sin configurar;
- alias Django invalido;
- alias no clasificado como SYSTEM;
- conexion MySQL inexistente;
- conexion MySQL inactiva;
- conexion MySQL fuera del catálogo Empresa 00;
- `database_name` invalido;
- tipo de fuente prohibido;
- combinacion simultanea de fuentes.

No existe fallback silencioso a `default`.

## Seguridad

- No se exponen passwords ni secretos en HTML, JSON, logs o mensajes.
- Tareas no duplica credenciales de `settings`.
- Tareas no importa servicios, modelos, forms, views, templates ni JS de `gestiondte`.
- Tareas no modifica `DATABASES` ni `MultiDatabaseRouter`.
- La configuracion de permisos usa Vista VICMEAS propia.

## Referencia

`CertificadoSIIRepository` documenta el patron de consumo, pero no es una dependencia de
Tareas. `gestiondte` permanece como APPLICATION_APP de referencia y no como infraestructura
comun.

## Storage operacional y bootstrap

`BASE_TAREAS` es el storage operacional completo de Tareas y contiene las 38 tablas
propias actuales más la tabla through automática de `Reprogramacion.causas` (39 tablas
operacionales). `AUDITORIA_TAREAS` no recibe tablas en esta fase.

El bootstrap MySQL de `BASE_TAREAS` ejecuta un SQL congelado generado y revisado desde los
modelos actuales mediante un service propio de `tareas`, excluye `TareaConnectionRole` y
no crea tablas SYSTEM/CORE ni maestros externos. Las relaciones externas conservan sus
columnas `_id` sin FK física; las relaciones entre tablas de Tareas sí conservan sus
constraints internas.

El precedente conceptual es `CertificadoSIIRepository` de Gestión DTE: resolver primero,
usar ORM `.using(alias)` para Django y SQL parametrizado con `open_mysql_connection()` para
MySQL. No existe dependencia runtime con `gestiondte`.

El bootstrap inicial está separado de `BASE_TAREAS_RUNTIME_STORAGE`, que permanece
`PENDING` y será una futura abstracción Storage/Repository con transacciones por agregado.
La evolución automática del schema MySQL también queda como deuda futura separada.

T134.2E: Reprogramación resuelve exclusivamente `BASE_TAREAS`, sin fallback ni router
transparente. El catálogo `CausaAtraso`, ledger y through son operacionales; usuario
se resuelve en SYSTEM después por ID.

T134.2E.3: `Crear estructura Base Tareas` garantiza también las seis causas oficiales
de `CausaAtraso`. La fuente canónica runtime es `tareas/services/reference_data.py`,
con los mismos códigos/nombres que la migración histórica 0009, que permanece intacta.
`ensure_base_tareas_reference_data()` permite preparar únicamente ese catálogo en una
base MySQL ya estructurada, resolviendo `BASE_TAREAS` sin fallback ni cambios de roles.
Solo inserta causas faltantes; conserva IDs y datos existentes. Conflictos de código
o nombre abortan con identificación del código oficial, sin sobrescritura ni seed
parcial. Requiere InnoDB y ejecuta el seed completo en una transacción propia.
MySQL puede confirmar DDL implícitamente: estructura y seed son fases separadas; un
fallo del catálogo no promete revertir tablas ya creadas, pero nunca informa éxito del
bootstrap. No incorpora otros backfills históricos ni ejecuta migraciones Django.
