# Patrón oficial: Conexión MySQL legacy (eltit_conta)

Resumen corto y normativo para consultas a bases MySQL legacy desde `gestiondte`.

1) Fuente de configuración
- Las conexiones legacy se administran mediante el modelo `SettingsMySQLConnection` (ver `settings/models.py`).
- No hardcodear host, base, usuario, password ni puerto en código productivo.
- La conexión lógica principal usada por `gestiondte` es `eltit_conta` (valor de `nombre_logico` en el registro correspondiente).

2) Patrón obligatorio (estándar)
- Pipeline: `View → Service/Helper → conexión legacy → SQL parametrizado → resultado`.
- Las Views NO deben:
  - crear conexiones ni registrar aliases en `connections.databases`;
  - usar `pymysql.connect(...)` directamente para lógica aplicativa;
  - ejecutar SQL ni manejar passwords.

3) Mecanismos de conexión permitidos
- Según el registro `SettingsMySQLConnection` la implementación debe seleccionar:
  - `django.db.connections` con un alias dinámico (registrado temporalmente a partir de `settings.DATABASES['default']` + datos del registro), o
  - `pymysql.connect(...)` únicamente cuando `engine` esté marcado como legacy (compatibilidad), y siempre desde la capa de servicio.
- La selección lógica se hace en código a partir del campo `engine` del registro (`ENGINE_LEGACY_PYMYSQL` vs default).

4) SQL y seguridad
- Siempre usar consultas parametrizadas. Ejemplo permitido:

  ```py
  cursor.execute('SELECT codigoempresa, nombre, rut FROM maestroempresas WHERE codigoempresa = %s LIMIT 1', [codigo])
  ```

- Nunca concatenar valores proporcionados por el usuario en SQL.
- No devolver errores SQL crudos al usuario; devolver errores controlados.

5) Empresa contable
- La llave lógica entre Django y el sistema legacy es `codigoempresa` (ej.: "09").
- Tabla principal actualmente consultada: `eltit_conta.maestroempresas`.

6) Permisos
- Todas las vistas que consumen estos servicios deben seguir usando ICMEAS mediante `access_control.decorators.verificar_permiso`.
- No crear permisos ad-hoc fuera del sistema existente.

7) Charset y encoding
- Las tablas legacy pueden usar `latin1`. El servicio debe respetar el `charset` configurado en `SettingsMySQLConnection.charset`.
- No aplicar conversiones globales a menos que se haya comprobado y validado la necesidad (ej.: problemas con acentos); preferir ajustar `cfg.charset` o `OPTIONS` en el registro.

8) Manejo de errores y limpieza
- Reglas que debe cumplir cualquier servicio:
  - Cerrar `cursor` y `connection` en `finally`.
  - Eliminar aliases temporales añadidos a `connections.databases`.
  - No exponer `traceback` ni credenciales en respuestas públicas.
  - Registrar errores con logger (sin credenciales), y devolver un resultado controlado (`None`, lista vacía, o dict con `error_key`).

9) Referencias (implementación actual)
- `gestiondte/utils/maestro.py` → `get_maestroempresa_by_codigo(codigo)` (lectura parametrizada, alias temporal o `pymysql` según `engine`).
- `settings/models.py` → `SettingsMySQLConnection` (almacena host/user/password/db/charset/engine/is_active).
- `settings/views.py` → `MySQLConnectionTestView` (modelo de referencia para creación de alias temporal y prueba de `SHOW TABLES`).
- `settings/services/mysql_connections.py` → helpers para obtener config UI (`get_mysql_connection_config`).
- `common/utils.py` → `crear_conexion` / `sql_sistema` (ejemplos de conexión dinámica y uso de `pymysql`).

10) Patrón recomendado para futuras consultas legacy
- Crear funciones de servicio reutilizables bajo `gestiondte/services/` (p.ej. `legacy_queries.py`) que:
  1. Reciban parámetros de entrada y validen formato.
  2. Obtengan la `SettingsMySQLConnection` apropiada (por `nombre_logico` o `is_active`).
  3. Construyan la configuración de conexión (o usen `pymysql` si `engine` legacy).
  4. Ejecuten SQL parametrizado mediante cursor.
  5. Cierren recursos y limpien alias.
  6. Retornen estructuras simples (dict/list) y errores controlados.

- No repetir en cada view:
  - registro/gestión de aliases en `connections.databases`;
  - manejo bajo nivel de sockets/conexiones; encapsularlo en el helper;
  - lógica de cierre/limpieza.

11) Buenas prácticas adicionales
- No loggear ni devolver passwords ni cadenas de conexión.
- Tests: agregar tests unitarios/mocks que simulen `pymysql` o `connections` (ver tests en `settings/tests/`).
- Documentar en UI (`Settings - Conexiones MySQL`) el `charset` recomendado cuando se añada una conexión legacy.

---
Este README es la definición del patrón oficial que debe ser reutilizado por futuras implementaciones (facturas, cesiones, RCV, cruces contables, etc.).

No modificar código productivo en esta tarea; este documento describe el patrón ya implementado.
