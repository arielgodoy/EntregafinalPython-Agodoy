# Pruebas físicas de locks de Tareas

`test_mariadb_mutation_lock_integration.py` está desactivado salvo que se
configure explícitamente `TAREAS_MARIADB_TEST_HOST`. Solo acepta una IP
loopback, una base con prefijo `tareas_it_`, un usuario con el mismo prefijo,
servidor MariaDB y un marcador de aislamiento previamente instalado.

No apuntar estas pruebas a `BASE_TAREAS`, `default`, `system_test`, ERP,
SYSTEM/CORE ni a una instancia compartida. El servidor local MySQL 8.0 no
satisface el requisito de MariaDB. La prueba falla cerrada si detecta tablas
distintas del marcador antes de crear las dos tablas sintéticas InnoDB.

## Preparación explícita

Usar una instancia MariaDB temporal/local que se haya verificado como aislada.
Crear una base vacía con nombre como `tareas_it_local`, un usuario dedicado
`tareas_it_runner` con permisos limitados a esa base, y la única tabla inicial:

```sql
CREATE TABLE tareas_it_isolation_marker (
    id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
    marker VARCHAR(100) NOT NULL
) ENGINE=InnoDB;
INSERT INTO tareas_it_isolation_marker (id, marker)
VALUES (1, '<identificador-aleatorio-de-esta-instancia>');
```

El usuario de pruebas requiere `SELECT`, `INSERT`, `UPDATE`, `CREATE` y `DROP`
solo sobre la base aislada. No poner la contraseña ni el identificador del
marcador en el repositorio.

## Ejecución desde PowerShell

Configurar las variables desde un gestor local de secretos:

```powershell
$env:TAREAS_MARIADB_TEST_HOST = "127.0.0.1"
$env:TAREAS_MARIADB_TEST_PORT = "3306"
$env:TAREAS_MARIADB_TEST_DATABASE = "tareas_it_local"
$env:TAREAS_MARIADB_TEST_USER = "tareas_it_runner"
$env:TAREAS_MARIADB_TEST_PASSWORD = "<secreto-local>"
$env:TAREAS_MARIADB_TEST_INSTANCE_ID = "<mismo-identificador-aleatorio>"
$python = (Resolve-Path "..\venv\Scripts\python.exe").Path
& $python manage.py test tareas.tests.test_mariadb_mutation_lock_integration --settings=AppDocs.settings_test
```

La prueba crea y elimina exclusivamente las tablas `tareas_tarea` y
`tareas_correlativoempresa` que ella misma crea en esa base vacía; vuelve a
verificar la identidad y el marcador antes de la limpieza. Si el proceso se
interrumpe, no ejecutar limpieza manual hasta volver a verificar la identidad
de la instancia.

Estos casos verifican el sentinel transaccional para una empresa sin tareas,
serialización entre dos conexiones y timeout controlado. No sustituyen pruebas
físicas de los escritores completos, del ledger/outbox, de jerarquía ni de
archivos. Esos gates siguen pendientes mientras no se ejecute una instancia
aislada.
