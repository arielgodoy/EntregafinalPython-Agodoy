# Operational Connection Transformation Contract v1.0

**Status:** listo para revisión humana
**Scope:** `APPLICATION_APPS` clasificadas en `AppDocs/app_classification.py`
**Precedencia:** complementa `COPILOT/ARQUITECTURA_APPS.md`; no autoriza cambios
fuera del alcance aprobado para una tarea.

## 1. Principio rector

> No estamos transformando funcionalidades.
> Estamos transformando conexiones.

El comportamiento observable de una aplicación debe permanecer equivalente
antes y después de la transformación. El objetivo es cambiar el origen
físico/configurable de los datos operacionales y eliminar dependencias
implícitas de conexión, sin rediseñar la funcionalidad de negocio.

Una transformación solo es aceptable cuando:

```text
CAN_MOVE_DATA_PLANE_BY_CONFIGURATION = YES
```

La aplicación debe poder mover su Data Plane a otra conexión o servidor
mediante configuración, sin cambiar reglas de negocio ni afectar a otras
aplicaciones que compartan hoy el servidor.

## 2. Alcance y límites

Este contrato aplica exclusivamente a las aplicaciones clasificadas como
`APPLICATION_APPS` en `AppDocs/app_classification.py` (también llamadas
`USER_APPS` o `BUSINESS_APPS` en el lenguaje de producto). Esa fuente de código
es autoritativa para la lista; este documento no replica ni redefine la lista.

No impone una transformación sobre:

- `SYSTEM_APPS`, incluidas `CORE_SYSTEM_APPS` y `SYSTEM_SUPPORT_APPS`;
- infraestructura global, `DATABASE_ROUTERS`, `DATABASES` o `AppDocs`;
- aplicaciones externas a la aplicación actualmente autorizada.

Las APPLICATION_APPS consumen las interfaces públicas existentes de
SYSTEM/CORE. No pueden alterar esas capas, copiar/forkear su lógica ni crear
infraestructura shadow para facilitar una migración. Si la interfaz pública
no alcanza, detenerse y registrar `MISSING_SYSTEM_CAPABILITY`; solicitar una
tarea y autorización arquitectónica separadas.

Una tarea de auditoría read-only no autoriza código, configuración, schema ni
datos. Una transformación posterior requiere su propio scope, precheck,
autorización y gates.

## 3. Frontera privada, propiedad y aislamiento

Toda APPLICATION_APP con Data Plane operacional debe poseer su propia
frontera privada de conexión:

```text
APPLICATION_APP
    -> private operational router / resolver de esa app
    -> storage / adapter
    -> backend físico configurable
```

La frontera pertenece a la aplicación; mantiene sus roles, resolución,
aislamiento, adapters y pruebas. Una aplicación no puede depender del router
privado de otra, aunque ambas apunten hoy al mismo servidor:

```text
gestiondte -> gestiondte private router -> Settings -> backend
tareas     -> tareas private router     -> Settings -> backend
```

Está prohibido importar o consumir operacionalmente
`otra_app.services.connection_roles` o equivalente privado. Compartir servidor
no significa compartir router. El router privado no se mueve fuera de su
aplicación ni se convierte automáticamente en router global.

`Django DATABASE_ROUTERS` puede complementar un backend que use un alias
Django, pero no sustituye esta frontera: `MYSQL_CONFIG` puede no existir como
alias de `DATABASES`. Este contrato no autoriza crear o modificar routers
globales.

## 4. Separación de responsabilidades

### Settings / SYSTEM

`settings` es propietaria del catálogo central de conexiones físicas y de sus
interfaces públicas. Las aplicaciones consumidoras reutilizan, según
corresponda, `SettingsMySQLConnection`, `open_mysql_connection()` y los demás
servicios públicos documentados. No duplican:

- host, port, usuario, password, credenciales, secretos o DSN;
- catálogo de servidores ni gestión de credenciales;
- lógica común de apertura de conexión.

### Router/resolver privado de la aplicación

- selecciona el rol lógico de la app;
- resuelve backend, alias/base y metadata estrictamente necesaria;
- valida la configuración y el alcance de rol;
- consume APIs públicas de Settings cuando corresponde;
- falla cerrado y no contiene reglas de negocio.

Los roles y su scope pertenecen a la aplicación. El scope debe declararse
(`GLOBAL POR APP`, `POR EMPRESA` u otro contrato explícito); no se infiere de
la multiempresa general ni se copia automáticamente el catálogo de roles de
Tareas.

### Storage / adapter

- ejecuta primitives de persistencia equivalentes por backend;
- transporta IDs/valores y materializa DTOs backend-neutrales;
- conserva identidad, relaciones operacionales y límites transaccionales;
- no decide reglas de negocio ni ubicación física fuera del backend resuelto.

### Service, View y Form

- **Service:** conserva reglas, estados, validaciones funcionales, operaciones
  compuestas y side effects.
- **View:** conserva HTTP, sesión, autorización, UX y composición; no decide
  dónde vive el Data Plane.
- **Form:** conserva contrato de entrada/validación observable; no debe
  introducir persistencia ORM implícita que evada el storage.

## 5. Control Plane y Data Plane

### Control Plane

Contiene la configuración necesaria para descubrir/resolver la ubicación del
Data Plane, por ejemplo roles privados, `source_type`, `django_alias`,
referencia a `SettingsMySQLConnection`, `database_name` y metadata de routing.
Puede residir legítimamente en `default` cuando esa base sea necesaria para
llegar al router privado.

Una tabla no es operacional solo por pertenecer al paquete Python de una app,
tener prefijo de esa app o declararse en su `models.py`. La clasificación se
hace por responsabilidad arquitectónica.

Una vista administrativa/read-only puede exponer la configuración del Control
Plane para diagnóstico. Es opcional, no es Data Plane y no debe duplicar
lógica del resolver ni crear una segunda fuente de verdad. La interfaz de
edición existente sigue siendo la fuente oficial.

### Data Plane

Contiene los datos operacionales propios de la aplicación. Todo acceso debe
atravesar su frontera privada. El Data Plane completo debe poder trasladarse a
otro servidor mediante configuración, manteniendo las referencias canónicas
externas fuera de ese traslado.

## 6. Backends y resolución fail-closed

La frontera contempla al menos:

### `DJANGO_ALIAS`

- Resolver y validar explícitamente un alias permitido/clasificado.
- Consultas operacionales con `.using(alias)` o equivalente.
- Transacciones con `transaction.atomic(using=alias)`.
- No depender de la selección implícita de `default`.

### `MYSQL_CONFIG`

- Resolver un registro de conexión mediante Settings y el rol privado de la
  app.
- Abrir/usar la conexión mediante la interfaz pública de Settings.
- Usar SQL parametrizado; nunca interpolar valores de usuario.
- No duplicar credenciales ni crear conexiones operacionales hardcoded si hay
  una configuración pública equivalente.

La resolución debe fallar cerrado. Se prohíben fallback silencioso o por
excepción a `default`, alias inventados, degradar `MYSQL_CONFIG` a ORM default,
elegir backend/legacy alternativo sin configuración explícita y ocultar
errores de resolución con una operación exitosa aparente.

## 7. Contrato funcional e identidad

### Inmutable: comportamiento observable

Preservar, salvo autorización explícita de cambio funcional:

- reglas de negocio, estados, transiciones y validaciones observables;
- permisos VICMEAS/ICMEAS cuando correspondan y aislamiento multiempresa;
- resultados, filtros, orden, mensajes funcionales y UX;
- destinatarios, eventos, notificaciones y demás side effects;
- correlativos, relaciones observables y operaciones compuestas;
- comportamiento de transacción/rollback que sea observable;
- API/HTTP público y seguridad.

### Mecanismos internos no congelados por sí mismos

No son requisito funcional autónomo: QuerySet/laziness, `.objects`,
RelatedManager, Subquery/OuterRef, `_state.db`, alias implícito, ModelForm,
ModelChoiceField/ModelMultipleChoiceField como mecanismo, `full_clean()`,
signals, `transaction.atomic()` u `on_commit()` implícitos y atributos
puramente ORM. Se pueden sustituir para conseguir independencia física si se
preserva el contrato observable. No declarar un blocker solo porque el ORM
histórico lo hacía difícil.

La identidad operacional no depende de `_state.db`, alias implícito,
existencia en `default`, instancia ORM concreta ni RelatedManager. Usar una
identidad estable (normalmente la PK persistida) y transportar referencias
mediante IDs/DTOs apropiados.

## 8. Referencias canónicas externas

`User`, `Empresa`, `Permiso`, `Vista`, `Local`, `Departamento`, `Proveedor` y
otras entidades propiedad de SYSTEM/CORE o de sus apps canónicas permanecen
en sus propietarios. La app puede conservar IDs conforme al contrato actual;
no las copia ni las mueve automáticamente a su Data Plane.

No crear una FK física cross-database ni un JOIN entre servidores que impida
mover independientemente el Data Plane. Cuando corresponda, resolver la
referencia a través del propietario, transportar identidad/DTO y preservar el
comportamiento.

## 9. Transacciones y side effects

Toda escritura y operación compuesta debe pertenecer al backend resuelto del
Data Plane. Auditar explícitamente `atomic`, `atomic(using=...)`,
`on_commit`, nested transactions, rollback, callbacks, señales y efectos
posteriores al commit.

Una escritura exitosa en MySQL no demuestra por sí sola paridad: un callback
puede quedar registrado en `default`, no ejecutarse en el límite esperado o
leer antes/después del commit incorrecto. Verificar orden, commit, rollback,
destinatarios y payloads en cada backend. No depender de señales ORM que el
adapter alternativo no dispara sin equivalencia explícita.

No prometer atomicidad entre una base de datos y filesystem/servicios externos
si el sistema no puede proporcionarla; definir cleanup/reconciliación de
acuerdo con el resultado confirmado o incierto.

## 10. Forms y superficies de acceso

El inventario de acceso cubre Models, services y views, además de forms,
admin, signals, management commands, APIs/serializers, jobs, reportes,
exports/imports, generación documental, helpers y templatetags con acceso a
datos.

Auditar `ModelForm`, `ModelChoiceField`, `ModelMultipleChoiceField`,
`queryset=`, `.objects`, `clean()`, `save()`, `save_m2m()`, `full_clean()` y
related managers: cualquiera puede ejecutar consultas ocultas contra
`default`. La misma UX no obliga a conservar el mecanismo ORM interno.

Un acceso a datos no es bypass solo por usar `.objects`, ni queda aprobado
solo por ocurrir en un storage. Clasificar por tabla/propietario, rol,
caller, backend real y responsabilidad.

## 11. Clasificación de hallazgos

Cada acceso sospechoso recibe exactamente una clasificación:

`CONTROL_PLANE`, `EXTERNAL_CANONICAL`, `BACKEND_ADAPTER`, `PRODUCTIVE`,
`PUBLIC_BUT_NOT_PRODUCTIVE`, `TEST_ONLY`, `DEAD_CONFIRMED`,
`OPERATIONAL_BYPASS` o `UNKNOWN`.

Para certificación:

```text
OPERATIONAL_BYPASS = 0
UNKNOWN = 0
```

La ausencia de caller localizado no basta para declarar `DEAD_CONFIRMED`.
Investigar APIs públicas, imports/aliases, URLs, commands y entradas
indirectas; si la evidencia no alcanza, conservar `UNKNOWN`.

## 12. Inventario read-only obligatorio

Antes de transformar, recorrer la aplicación completa sin editar. Buscar como
mínimo:

`.objects`, `.using(`, `connections[`, `connection.cursor`, `cursor(`,
`transaction.atomic`, `transaction.on_commit`, `_state.db`, `full_clean`,
`save(`, `delete(`, `bulk_`, `raw(`, `ModelForm`, `ModelChoiceField`,
`ModelMultipleChoiceField`, `queryset=`, related managers, `DATABASES`,
`DATABASE_ROUTERS`, `host`, `port`, `password`, `mysql`, `pymysql`,
`MySQLdb`, connector/driver, `storage.alias`, signals, management commands,
tasks/jobs/APIs; incluir wrappers y helpers que oculten acceso.

Por cada sitio, documentar archivo/línea, símbolo/caller/call chain, modelo o
tabla, lectura/escritura, backend real/esperado, clasificación, evidencia,
riesgo, decisión y confidence. No incluir passwords, tokens, DSN sensibles ni
datos personales en artifacts.

La plantilla está en
`COPILOT/APPLICATION_CONNECTION_INVENTORY_TEMPLATE.md`.

## 13. Paridad y gates de certificación

No declarar paridad por una sola vista exitosa. Cubrir las superficies que
existan: CRUD, listas/detalle, validaciones, estados/transiciones,
relaciones/FK lógicas/N:M, correlativos, DTOs, documentos, comentarios,
lecturas, participantes, formularios/choices, jerarquías, operaciones
compuestas, reportes, eventos/notificaciones, signals, exports/imports,
commands, APIs y background work.

La certificación exige:

1. inventario completo, contract/identity snapshot y `UNKNOWN = 0`;
2. pruebas de aislamiento/fail-closed y paridad por backend;
3. gates de formas, relaciones, transacciones, side effects y errores;
4. validación física de backend real cuando sea seguro y esté autorizado;
5. Physical Isolation Gate cuando sea seguro, con `default` incapaz de
   contestar por el Data Plane;
6. cero fallos introducidos e inconclusos en el scope de certificación;
7. diff/scope/revisión final sin cambios funcionales, schema o SYSTEM/CORE
   no autorizados.

Los tests con base temporal son necesarios pero no sustituyen evidencia del
backend físico real cuando ésta sea segura y aplicable. HTTP 200 tampoco
demuestra persistencia: verificar filas y relaciones físicamente.

Clasificar fallos de tests `HISTORICAL`, `INTRODUCED` o `INCONCLUSIVE`.
Certificación requiere `INTRODUCED = 0` y `INCONCLUSIVE = 0`; deuda histórica
no relacionada no se corrige automáticamente.

El checklist reusable está en
`COPILOT/APPLICATION_CONNECTION_AUDIT_CHECKLIST.md`.

## 14. Physical Isolation Gate y producción

El gate busca hacer físicamente imposible que `default` atienda el Data Plane
de la app, preservando SYSTEM/CORE, Control Plane y referencias canónicas.
En un entorno DEV expresamente autorizado, se puede dejar `default` con esas
tablas legítimas y cero tablas operacionales de la aplicación, enrutar el
Data Plane por su resolver y ejecutar una matriz funcional instrumentando el
SQL de `default`.

Un `no such table`, consulta operacional en `default` o fallback implícito es
evidencia de bypass; nunca se soluciona recreando tablas operacionales en
`default`.

El gate no autoriza por sí solo DROP/TRUNCATE ni destrucción de datos. En
aplicaciones productivas: inventariar, clasificar, probar routing, diseñar
aislamiento seguro, obtener autorización explícita y ejecutar en ventana
aprobada. El diagnóstico inicial es no destructivo. GestionDTE se rige por
esta restricción.

## 15. Lecciones de Tareas (reference implementation)

Tareas es referencia arquitectónica; su código no es librería ni router común
para importar. Sus roles y resolver permanecen dentro de Tareas. Las demás
apps pueden reutilizar conceptos, no depender de sus módulos privados.

T135 y las correcciones posteriores muestran que la primera ruta verde no
certifica la aplicación completa. El checklist debe comprobar, entre otros:

- primitives faltantes, guards Django-only o fail-closed incompleto;
- DTO incompleto, atributos/relaciones que esperan views, forms o eventos;
- participantes N:M y roles efectivos omitidos;
- `ModelForm`, choices, clean/full_clean y related managers que vuelven a
  consultar `default`;
- relaciones documentales, comentarios, lecturas y señales no ejecutadas
  por backend alternativo;
- side effects/eventos/notificaciones sensibles al ORM o al momento de commit;
- `_state.db`, `storage.alias`, `atomic`/`on_commit` implícitos;
- acceso directo desde views/forms y servicios legacy todavía invocables;
- helpers sin caller aparente, pero públicos/alcanzables;
- acceso correcto al resolver seguido de composición funcional incompleta.

T135 documentó correcciones de publicación/similitud, creación/convening de
reuniones, comentarios/lecturas/participantes y el acceso de `Tarea.clean()`
que producía lectura operacional implícita en `default`. Son casos de prueba,
no un modelo de roles a copiar.

El estado de certificación de Tareas no se infiere de esos checkpoints. El
inventario actual contiene estados históricos que requieren reconciliación;
además, la matriz física del 2026-10-07 reprodujo que la edición de un
comentario falla porque el `CommentDTO` no provee el atributo `tarea` que
consume el servicio. Por ello Tareas sirve como referencia de lecciones, pero
ese resultado no debe presentarse como prueba de certificación global. La
matriz y el Corrective WIP deben cerrarse por separado.

Durante pruebas físicas, limpiar fixtures de datos tras comprobar identidad y
dependencias. No revertir manualmente secuencias/correlativos consumidos sin
evidencia y autorización; registrar ese efecto separado de la limpieza de
filas.

## 16. Administración del Control Plane

La inspección del Control Plane puede ser read-only y opcional. Debe exponer
solo metadata segura, impedir ADD/CHANGE/DELETE si ése es el propósito y no
probar conexiones ni implementar resolución. La edición oficial permanece en
la UI fuente de verdad propia de la app. No es obligatorio copiar la pantalla
o ModelAdmin de Tareas a otras apps.

## 17. Workflow y condiciones de detención

Workflow estándar:

```text
diagnóstico corto
-> congelar contrato e identidad
-> adaptación mecánica de conexión
-> pruebas de aislamiento/paridad
-> backend real seguro
-> checkpoint
```

Usar proceso extendido ante identidad ambigua, transacciones compuestas,
correlativos, relaciones/forms complejos, schema faltante, interacción entre
storages, side effects o referencias canónicas complejas.

Detener y registrar blocker si se requiere cambiar comportamiento observable,
schema sin autorización, SYSTEM/CORE, seguridad/permisos, contratos públicos,
infraestructura compartida o una nueva capacidad de Settings. No detener solo
porque el código dependa de un mecanismo ORM sustituible; evaluar primero
adaptación interna compatible.

No crear infraestructura global, APIs nuevas de SYSTEM/CORE, catálogo global,
router Django global, migraciones ni cambios de DATABASES como consecuencia
automática del contrato.

## 18. Estado de aprobación

Este texto establece el contenido propuesto de la versión 1.0 para revisión
humana. No equivale por sí solo a aprobación para transformar una aplicación,
aislar físicamente tablas, cambiar schema ni modificar producción.
