# Contract: Tareas Connection Roles

**Feature**: Tareas Internas
**Status**: Documental; no implementado

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
