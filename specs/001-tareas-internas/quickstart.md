# Quickstart: Tareas Internas - SPEC MAESTRA

## Extension futura Fase 1.6

Esta guia mantiene sus escenarios y resultados historicos. Para una implementacion
autorizada de [FR-P06](spec.md), agregar fixtures de membresias explicitas sin
backfill y ejecutar los escenarios pertinentes del
[quickstart complementario](../003-organizacion-tareas-fase-1-6/quickstart.md).
Sus 36 escenarios son previsiones, no pruebas ejecutadas con esta sincronizacion.

Separar regresion de lectura/cursor/historia de gestion: la primera conserva
autorizacion existente; la segunda acumula Opcion B y permisos/rol/estado.
La reasignacion individual ordinaria conserva su contrato; la regularizacion
individual y el lote se validan separadamente, sin asumir commits individuales
como prueba de todo-o-nada. Notificaciones mantienen T054 y las excepciones de
MiniTarea, convocatoria y enlaces, no una politica nueva universal.
El [primer bloque y sus limites](../003-organizacion-tareas-fase-1-6/synchronization.md)
define pruebas futuras de persistencia/consultas y dependencias protegidas.
No se ejecutaron tests, check Django, migraciones ni accesos a DB en esta entrega.

**Date**: 2026-09-07 | **Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Guía de validación ejecutable y progresiva. Los detalles de campos y rutas están en
[data-model.md](data-model.md) y [contracts/web-urls.md](contracts/web-urls.md); aquí solo
se describen escenarios de verificación end-to-end.

> **REGISTRO INICIAL RESUELTO**: el alta de la app en `AppDocs/app_classification.py`,
> `INSTALLED_APPS` y `AppDocs/urls.py` ya fue autorizada, ejecutada, testeada y versionada.
> Cualquier modificación futura adicional de esos archivos requiere una tarea separada con
> autorización y scope explícitos; no es una excepción al APPLICATION BOUNDARY.

## Prerequisitos

### Conexiones SQL de Tareas (validacion futura)

1. Sin `ingresar`, GET devuelve 403.
2. Con `ingresar`, la superficie muestra exactamente los cuatro roles globales.
3. Con `modificar`, un POST valido devuelve 302.
4. `BASE_TAREAS` acepta Django y MySQL.
5. `AUDITORIA_TAREAS` acepta Django y MySQL.
6. `LEGACY_MYSQL` rechaza Django.
7. `LEGACY_AUDITORIA` rechaza Django.
8. Un role inexistente, alias invalido, conexion inexistente/inactiva o `database_name`
   invalido devuelve error controlado.
9. No existe fallback a `default`.
10. Con Empresa 09 activa, el catálogo MySQL de Tareas sigue mostrando únicamente
   conexiones activas asociadas a Empresa código `00`; la empresa activa no interviene.
11. Los tests confirman ausencia de imports desde `gestiondte` y ausencia de credenciales
   en HTML, respuestas y logs.

Estos escenarios son futuros y no implican implementacion en esta actualizacion documental.

### Bootstrap Base Tareas MySQL

El bootstrap inicial administra únicamente `BASE_TAREAS` cuando su fuente es
`MYSQL_CONFIG`. No administra `AUDITORIA_TAREAS`, `LEGACY_MYSQL`,
`AUDITORIA_LEGACY` ni `TareaConnectionRole`.

La estructura se deriva de las 39 tablas operacionales propias actuales. Las referencias
externas conservan IDs sin FK física; las relaciones internas conservan constraints.
La acción usa supervisor, POST/CSRF, `open_mysql_connection()` y es idempotente mediante
DDL no destructivo. No ejecuta `migrate` ni SQL recibido desde el frontend.

La validación manual queda pendiente y no debe ejecutar DDL real automáticamente:

```text
Tareas -> Conexiones SQL -> Base tareas -> MYSQL
-> mysqldjango -> database=tareas -> Crear estructura Base Tareas
```

Las claves i18n nuevas de bootstrap (`tareas.connection_roles.bootstrap.button`,
`confirmation` y `confirm`) requieren incorporación coordinada en los catálogos globales.
Esta fase no modifica `static/lang/en.json` ni `static/lang/sp.json` por el boundary y por
los cambios históricos unstaged existentes.

### Storage runtime futuro

`BASE_TAREAS_RUNTIME_STORAGE=PENDING`. El bootstrap no cambia los QuerySets funcionales
ni agrega `.using()` dispersos. Una fase posterior implementará una abstracción propia de
Storage/Repository con resolver Django/MySQL y transacciones por agregado, sin modificar
routers, `DATABASES` ni infraestructura SYSTEM/CORE.

1. Entorno local del proyecto activo (venv, dependencias ya instaladas según README).
2. Migraciones de la fase habilitada aplicadas:
   ```powershell
   python manage.py migrate
   ```
3. El sidebar consume la infraestructura VICMEAS existente: `Permiso.ver` controla solo
   visibilidad por empresa activa y el mapping explícito de items a Vistas. No se agrega
   una implementación de VICMEAS en `tareas`; cualquier cambio futuro en SYSTEM_APPS
   requiere una tarea separada con autorización y scope explícitos.
4. Un usuario con empresa activa en sesión y permisos ICMEAS sobre las vistas `Tareas - *`
   para las acciones que probará, y `Permiso.ver` cuando deba verificar visibilidad.

## Validación automatizada por fase

```powershell
python manage.py test tareas --settings=AppDocs.settings_test
python manage.py check
```

Resultado esperado: todos los tests de `tareas/tests/` pasan; `check` sin errores nuevos.

### Estado de reconciliación de validación

- `AUTOMATED_VALIDATED`: suite `tareas` y gates focalizados ejecutados con resultado verde.
- `AUTOMATED_I18N_GATE=PASS`: `tareas.tests.test_i18n` ejecutado; las claves usadas por
   código y templates de `tareas` están presentes y son simétricas en ambos catálogos.
- `MANUAL_VALIDATION_PENDING`: permanece para los escenarios fuera de E14 que conservan
   ese estado; E14 se cierra como PASS con la evidencia aceptada que se registra abajo.
- `MANUAL_ES_EN_REVIEW=PENDING`: permanece para las superficies fuera de E14 que sigan
   pendientes. La revisión manual ES/EN de Comentarios E14 está en PASS.

## Escenarios manuales end-to-end

Levantar el servidor local (task "Django: Runserver (local)") y verificar:

### E1. Crear borrador mínimo (FR-001, FR-003, FR-005)

1. Login → empresa activa seleccionada.
2. Menú → "Tareas" → Crear. Ingresar solo título → Guardar.
3. **Esperado**: tarea visible en el listado con estado "Borrador", fecha de creación de hoy,
   empresa = empresa activa.

### E2. Borrador indefinido y edición (FR-006, FR-009)

1. Editar el borrador: cambiar descripción/prioridad/responsable → Guardar.
2. **Esperado**: sigue en "Borrador", sin fecha de publicación; sin límite de tiempo.

### E2 bis. Administrar responsable desde el detalle (FR-D11)

1. Abrir el detalle de un borrador y seleccionar un usuario activo válido como responsable.
2. Guardar la administración del responsable desde el bloque de participantes.
3. **Esperado**: el responsable queda visible en el detalle sin crear una fila
   `TareaParticipante`; quitarlo vuelve a ser posible mientras la tarea siga en borrador.
4. Publicar la tarea y comprobar que el selector ya no permite dejar el responsable vacío;
   una reasignación válida conserva el registro de reasignación.

### E2 ter. Paridad Responsable/Participantes (T134.3B)

1. En ACTIVA/GESTION, reasignar desde Detalle y desde Editar con motivo
   ingresado. Verificar anterior/nuevo/actor/fecha/motivo y ausencia de vínculos
   artificiales. Sin motivo, la edición completa debe quedar sin cambios.
2. Agregar un usuario activo válido que no sea creador, responsable ni explícito.
   Cambiar PARTICIPANTE a INVITADO_OBSERVADOR: misma PK/fecha, solo cambia rol.
3. Quitar el vínculo y reingresar: misma lectura y cursor, comentarios y pausas
   conservados. Quitar un usuario inactivo o sin pertenencia actual sigue válido.
4. CERRADA/anulación propia/padre/abuelo bloquean POST y ocultan controles.
   Un participante con modificar sin ser creador/supervisor recibe 403.
5. Tras commit, comprobar avisos separados a responsables anterior/nuevo y al
   participante afectado en alta, baja y cambio real de rol; mismo valor no avisa.
6. Repetir en BASE_TAREAS Django (alias explícito) y MySQL; verificar rollback,
   errores de resolver sin fallback, mismo ID Django intacto, candidatos reales
   filtrados y alternancia ES/EN sin destruir opciones de los selects.

### E2 quater. MiniTareas configurables (T134.3D)

- Repetir alta/cierre/reapertura/cierre y eliminación de una pendiente sin eventos
  en Django y MySQL. Verificar comentario/versión, asociaciones documentales,
  lectura con cursor conservado y comunicaciones independientes por evento.
- Verificar negativos de actor/persona, estados, anulación, historial protegido,
  configuración inválida, same-PK y propagación de alias a todo el agregado.
- Evidencia de desarrollo T134.3D: Tarea MySQL 1 (misma PK que Django);
  MiniTarea 1 con eventos 1/2/3, feeds 1/2 y MiniTarea 2 eliminada. Doble CLOSE
  real sobre MiniTarea 3: un commit/evento 4 y un rechazo; sin feed duplicado.
  Historial/Detalle/Mis Tareas HTTP 200 mediante RequestFactory sin sesiones
  persistidas. Hash lógico Django sin cambios y guard de cero writes SYSTEM.
  Selección de comunicaciones vacía; archivos reales omitidos, cubiertos por
  tests con storage en memoria. Los datos MySQL de prueba quedan en desarrollo.
- 135 archivos Python compilados, check con solo ckeditor.W001 y sin drift de
  modelos. La inspección de migraciones conserva el warning histórico de
  DB_sistema/django_lab. Sin migración, cambio de schema ni modificación SYSTEM/CORE.
- Historial de cierre: el gate intermedio dio 257 PASS / 1 FAIL por 13 `data-key`
  dinámicos de assignment presentes en HEAD. T134.3D.1 los sustituyó por literales
  con render equivalente; el siguiente gate reveló tres claves bootstrap ausentes
  en ES/EN, catalogadas en T134.3D.2. Ambos bloqueos históricos están resueltos.
- Resultado final: regresión Responsable/Participantes + i18n 101/101 PASS;
  selección consolidada 258/258 PASS, 0 FAIL, 0 ERROR. Los 25 tests nuevos pasan.
  Workaround de migraciones de Settings únicamente en runtime, no persistido.
  REAL_MYSQL_VALIDATION = PASS_ALREADY_DEMONSTRATED: no se repitieron mutaciones
  reales durante las reparaciones i18n ni la sincronización documental T134.3D.3.
  T134_3D_GLOBAL = PASS; checkpoint listo para commit.

### E3. Publicación bloqueada sin responsable (FR-007)

1. Quitar el responsable del borrador → intentar Publicar.
2. **Esperado**: rechazo con mensaje claro; la tarea permanece en "Borrador".

### E4. Publicación exitosa (FR-008)

1. Asignar un responsable activo → Publicar.
2. **Esperado**: estado "Publicada", fecha de publicación registrada y visible en el detalle.

### E5. Publicación irreversible + responsable obligatorio (Q2, FR-008)

1. En la tarea publicada: verificar que NO existe acción "volver a borrador".
2. Intentar editar dejando el responsable vacío.
3. **Esperado**: error de validación; la tarea conserva responsable y fecha de publicación.

### E6. Aislamiento multiempresa (FR-003, FR-010)

1. Cambiar la empresa activa a otra empresa del usuario.
2. **Esperado**: el listado no muestra las tareas de la empresa anterior; el acceso directo
   por URL a una tarea de otra empresa responde 404.

### E7. VICMEAS e ICMEAS independientes (FR-011)

1. Con `Permiso.ver=True` y `Permiso.ingresar=True` en `Tareas - Listado`: el item aparece
   y el acceso funciona.
2. Con `Permiso.ver=True` y `Permiso.ingresar=False`: el item sigue visible, pero el
   backend responde **403** con la página que permite solicitar acceso.
3. Con `Permiso.ver=False` y `Permiso.ingresar=True`: el item no aparece, pero el acceso
   directo por URL funciona.
4. Con ambas banderas en `False`: el item no aparece y el acceso está prohibido.
5. Repetir la comprobación en dos empresas: `ver` en una empresa no hace visible el item
   en la otra. El superuser ve el sidebar completo por bypass visual, sin inferir bypass
   backend. Los padres aparecen solo si un hijo es visible.

## Validaciones del dominio por fases

### E8. Correlativos y estados (Phase 2)

- Crear un borrador y comprobar correlativo `B*` único por empresa.
- Publicar con responsable válido y comprobar conversión al correlativo `A*` sin nueva PK.
- Ejecutar transiciones permitidas y rechazar saltos de estado; verificar auditoría.
- Al marcar 100%, comprobar `cierre_completado == True` y estado `PENDIENTE_APROBACION_CIERRE`.
- Aprobar cierre y comprobar estado `CERRADA` con `cierre_completado == True`.
- Rechazar cierre y comprobar retorno a `GESTION` conservando `cierre_completado == True`;
   esta señal es lifecycle, no porcentaje general de avance.

### E9. Asignación y jerarquía (Phase 3)

- Crear padre, hijos y nietos dentro del máximo permitido (padre→hija→nieta, sin cuarto nivel).
- Anular el padre y comprobar que SOLO cambia `padre.anulada=True`; hijas/nietas conservan
  `anulada=False` y sus estados funcionales intactos, pero todas quedan anuladas
  efectivamente (lógica: tarea+padre+abuelo). Verificar notificación a participantes.
- Reactivar el padre y comprobar que SOLO cambia `padre.anulada=False`; los estados
  funcionales de toda la estructura siguen intactos (nunca cambiaron; no hay restauración).
- Confirmar que una hija anulada directamente (`anulada=True`) sigue anulada tras
  reactivar el padre.
- Confirmar que fechas afectadas quedan pendientes, sin recálculo automático.
- Bloqueo documentado: la notificación a participantes no está conectada desde
   `tareas`; queda pendiente de integración y no se implementa P1 Local en esta fase.

### E10. Hitos, mini-tareas y documentos (Phase 3)

- Validar `sum(cumplimiento * peso) / sum(pesos)` y redistribución al agregar un hito.
- Comprobar que mini-tareas pendientes bloquean cierre y no ponderan avance.
- Adjuntar documento/evidencia, cambiarlo y verificar historial y vencimiento informativo.
- T134.4B: con Django alias y MySQL, probar alta/edición/no-op, completitud
  formal con evidencia, reasignación con motivo, anulación/reactivación,
  borrado físico solo con CREACION y Eliminar con actividad como anulación.
  Verificar permisos por acción, pending/closed y anulación efectiva congelados.
  Probar avance simple descendente/ascendente y modo ponderado con recálculo
  inmediato, sin cierre automático ni aportes de MiniTareas.
  Comprobar same-PK default intacto, locks/rollback y las cuatro regresiones T081;
  la prueba MySQL real solo usa datos DEV y no escribe SYSTEM/legacy.

### E11. Cotizaciones (Phase 4)

- Crear o reutilizar proveedores del maestro local Django y abrir una `RondaCotizacion`.
- Crear cotizaciones asociadas a proveedores locales, conservando cotizaciones históricas con `proveedor=NULL` sin contarlas para el mínimo.
- Verificar máximo de 3 versiones por `(ronda, proveedor)`, mínimo por proveedores distintos y que varias versiones del mismo proveedor cuentan una sola vez.
- Confirmar que el cierre de ronda se bloquea hasta cumplir el mínimo y que cotizaciones vigentes de proveedores distintos permiten cerrarla.
- Marcar una cotización como `SELECCIONADA`, comprobar que el proveedor seleccionado es visible dentro de Django y que no se crea `Adjudicacion`.
- Reutilizar el cierre de Tarea vigente y validar que la ronda más reciente controla el mínimo.
- Confirmar que todo el flujo opera con el maestro local Django sin consultar ERP/legacy; la integración, conciliación y sincronización permanecen bloqueadas por P2.

Estado E11 PRE-P2: EJECUTADO/VALIDADO exclusivamente sobre las capacidades
internas autorizadas: rondas, mínimos, estados, fechas, observaciones,
documentos, histórico, selección interna, cierre controlado, nuevas rondas,
maestro local Django y versionado por `(ronda, proveedor)`.

Estado P2 ERP/legacy: BLOQUEADO/PENDIENTE DE CONTRATO O AUTORIZACIÓN. Quedan
fuera de esta validación la identidad externa del proveedor, lookup ERP,
validación ERP, conciliación, sincronización y actualización desde legacy.
No se declara identidad ERP ni se implementa integración legacy.

### E12. Colaboración, similitud y enlaces (Phase 5)

- Verificar notificaciones internas/email mediante mocks y reuniones de revisión.
- Comparar con tareas abiertas y cerradas usando 80% por defecto; cambiar umbral por empresa
   y comprobar que solo afecta evaluaciones nuevas.
- Abrir enlace como usuario autenticado de la empresa y rechazar acceso cross-company/externo.

Estado E12: EJECUTADO/VALIDADO mediante la regresión focal de colaboración,
similitud, enlaces y reuniones, con mocks de notificaciones/email y cobertura
de aislamiento cross-company.

### E13. Dashboards (Phase 6)

- Comprobar exactamente ocho KPI en cada dimensión permitida: estado, atrasadas, próximas a
   vencer, sin movimiento, aprobación pendiente, carga, cumplimiento y tiempo promedio de cierre.
- Verificar drill-down, paginación y aislamiento; mantener Local/Proveedor bloqueados sin legacy.

Estado E13: EJECUTADO/VALIDADO mediante la regresión integrada de KPI,
dashboards, T060, dashboard personal y metadata, manteniendo Local/Proveedor
fuera de las dimensiones de drill-down.

### E14. Comentarios de Tarea (Phase 8 completada; T102 y validación manual PASS)

Phase 8 está implementada. T102 se cerró el 2026-10-01 tras completar la regresión
automatizada y los gates, y aceptar la evidencia manual del Product Owner registrada al
final de esta sección. Criterios de aceptación cubiertos:

- La tarjeta aparece en el detalle para usuarios autorizados a leer el feed. La participación
   funcional efectiva (creador, responsable, participante explícito o responsable de Hito
   vigente) habilita cursor y reconocimiento según el contrato. Un lector sin vínculo
   funcional puede consultar el feed con `ingresar`, Empresa activa y acceso válido a la
   Tarea, pero no obtiene composer, cursor, unread, badge ni reconocimiento. Desvincular
   elimina la participación explícita salvo que conserve otro vínculo funcional; VICMEAS
   no crea permisos especiales.
- Solo estados publicados operativos (`ACTIVA`, `GESTION`, `PENDIENTE_APROBACION_CIERRE`)
   admiten mutaciones. `CERRADA`, `BORRADOR` y anulada son lectura; reactivar un estado
   operativo permite comentar otra vez y conserva cursor/versiones.
- Crear exige VICMEAS `crear` y participación funcional; editar exige `modificar`, ser
   autor y participación funcional; ocultar/restaurar exige S (`supervisor`), participación
   funcional y motivo no vacío. El historial de comentarios visibles lo ve el autor; el
   historial y contenido de comentarios ocultos solo los ve S. El autor no-S recibe tombstone.
- Texto y/o adjuntos son válidos; el sexto adjunto se rechaza. Reutilizar `DocumentoTarea`
   de la misma Tarea, permitir captura móvil y comprobar que quitar el vínculo no elimina
   el documento ni convierte el adjunto en evidencia formal.
- La bitácora es lineal, sin filtros, buscador, threads ni aplicación/chat separados; la
   carga inicial y cada página son de 20. Abrir la Tarea no marca Comentarios leídos.
- Al expandir/cargar, solo los próximos 20 Comentarios cronológicos contiguos avanzan el
   cursor; navegar a una página histórica/arbitraria no lo mueve ni salta pendientes. Sin
   pendientes, el card muestra los 20 más recientes. El contador muestra `1..9`/`9+`, enfoca
   el primer pendiente, considera leídos los Comentarios propios, conserva ocultos pendientes
   hasta cargar su tombstone y no incrementa por edición/ocultar/restaurar.
- El cursor se guarda en la fila única `TareaLectura` usuario/Tarea; el alta tardía inicia
   en el Comentario más reciente, sin pendientes históricos, y los Comentarios de intervalos
   `is_active=False` no se acumulan. No se crean filas de lectura por Comentario ni recibos
   individuales.
- Crear/editar/ocultar/restaurar notifica a participantes activos vinculados, excluye al
   actor y deduplica; solo crear incrementa no leídos. `CRITICA` conserva email automático;
   no se duplica `documento_agregado` por adjunto inline.
- Comentarios no reemplaza motivos/justificaciones formales; cada escritura revalida en
   backend Empresa, vínculo, VICMEAS y estado justo antes de guardar.
- La autorización contextual administrativa de `tareas` se validó por separado: creador con
   `modificar` y `supervisor` pueden editar datos generales y administrar responsable o
   participantes/invitados; un actor `M-only` no creador, aunque sea responsable o participante,
   recibe 403 y no muta la Tarea. Un creador sin `modificar` también recibe 403. Esta regla no
   concede ni revoca la capacidad independiente de comentar.
- La UI y los mensajes de Comentarios se revisaron en ES/EN y el gate i18n está PASS; el
   detalle de la evidencia manual final se registra abajo.

Estado E14: PASS / COMPLETADO.
Estado T102: [x] CLOSED.
Estado de validación Phase 8: CLOSED.

Regresión final del 2026-10-01: 542 tests de `tareas` PASS; `manage.py check` sin errores
(warning conocido `ckeditor.W001`); `compileall tareas` PASS; JSON de `sp.json` y `en.json`
válido; gate automatizado `tareas.tests.test_i18n` PASS. El workaround de migraciones para
`gestiondte` se aplicó solo en runtime y no se persistió. No hubo cambio de schema ni
migraciones nuevas.

Evidencia manual aceptada del Product Owner (A–N): A creador implícito; B `fecha_tope`;
C responsable y reasignación; D invitado/observador y revinculación; E polling; F unread y
cursor; G paginación; H inactividad; I notificaciones y deduplicación; J adjuntos y máximo
cinco; K captura real con cámara en iPhone; L lifecycle; M edición e historial; N
ocultar/restaurar con S y separación entre autor y S.

Validación manual final E14 del Product Owner: cambio ES → EN → ES correcto; las etiquetas
generales del módulo de Comentarios y la etiqueta dinámica del tipo de adjunto se traducen
en ambos sentidos; no se detectaron problemas funcionales. `MANUAL_ES_EN_REVIEW` para E14
es PASS. La evidencia física de cámara FR-T04 se conserva como PASS reportado por el
Product Owner y no se repitió durante este cierre.

## Límites y bloqueos

- La anulación ordinaria sigue siendo distinta. L2/L3 mantienen la marca lógica y la
  exclusión operacional; L4 es consulta histórica GET-only. El contrato L5 permite una
  restauración explícita; el ledger y el servicio interno transaccional Etapa 2 están
  implementados y probados en base temporal y con fixtures sintéticas en MariaDB de
  desarrollo. No hay ruta ni proyección L4; el guard L2 sigue bloqueando ciclos posteriores
  y no se restauró ningún dato productivo.
- P1 Local: BLOQUEADO/PENDIENTE DE CONTRATO O AUTORIZACIÓN; permanece `LEGACY API PENDIENTE`.
- P2 Proveedor: BLOQUEADO/PENDIENTE DE CONTRATO O AUTORIZACIÓN para integración,
  validación y conciliación con ERP legacy; el maestro Django local no queda bloqueado.
- No hay usuarios externos, plantilla de hitos ni vencimiento automático de documentos.
- El alta inicial ya está resuelta; cualquier modificación futura de `AppDocs/*` requiere
   autorización expresa.

### Eliminación lógica administrativa — verificación futura

L1 implementa los campos, ledger y contrato de esquema. L2 implementa el servicio
transaccional interno `tareas.services.logical_deletion.logically_delete_task_tree` para
ORM y MYSQL_CONFIG. No hay ruta HTTP, POST ni UI nueva; el executor físico anterior no se
invocó contra la base física `tareas`. La suite completa también ejecutó sus pruebas
legacy sobre bases de test aisladas.

**Fotografía anterior a la autorización L2/L3, reemplazada por el cierre actualizado al
final de esta sección:** en ese momento el contrato de auditoría estaba GO, L2 pendiente y
L3 no iniciada. `AuditoriaService.log_event` y sus consumidores no se modificaron durante
esa ejecución; ya existía una API optativa `log_event_idempotent` con lookup público por
UUID para eventos de Tareas.

La validación previa de L2 quedó así:

- `python manage.py test --settings=AppDocs.settings_test tareas.tests.test_task_mutation_locks tareas.tests.test_logical_deletion tareas.tests.test_deletion_ledger tareas.tests.test_logical_deletion_schema tareas.tests.test_base_tareas_schema tareas.tests.test_logical_deletion_metadata`: 95 pruebas PASS.
- `python manage.py test --settings=AppDocs.settings_test tareas.tests`: 1.121 pruebas PASS, 3 omitidas.
- `python manage.py check --settings=AppDocs.settings_test` y `python manage.py makemigrations --check --dry-run --settings=AppDocs.settings_test`: PASS.
- En la base de desarrollo física `tareas` se verificó MariaDB 10.11.13, 43 tablas InnoDB y presencia inicial de `tabladeprueba`. Se aplicaron únicamente las nueve sentencias aditivas de `tareas/sql/logical_deletion_schema.sql`; no se ejecutaron migraciones.
- Pruebas reales con fixtures identificables comprobaron rollback, confirmación lógica, concurrencia de misma raíz, carrera padre/hijo, timeout con reintento por el mismo UUID e inserción jerárquica concurrente. Los fixtures, relaciones y filas de ledger de esas pruebas se limpiaron delimitadamente.
- El estado posterior conserva las seis Tareas preexistentes sin marca lógica; no quedan fixtures identificables ni filas de ledger de prueba. `tabladeprueba` no se modificó.
- Una llamada de verificación inicial alcanzó el servicio central de auditoría por su API pública y dejó el evento `auditoria_tareas_event` id 22. Se conservó; no se editó ni eliminó directamente información de SYSTEM/CORE.
- `log_event` conserva su contrato legacy. `log_event_idempotent` persiste la clave única y hash canónico; reintenta un máximo de dos veces adicionales solo ante bloqueos transitorios, siempre con la misma clave. Errores persistentes se devuelven explícitamente como almacenamiento ambiguo; una nueva llamada con la misma clave recupera el evento si ya se confirmó.

La validación del contrato central se ejecutó solo en bases de test aisladas:

- `python manage.py test --settings=AppDocs.settings_test auditoria.tests.test_idempotent_audit`: 8 pruebas PASS, incluida concurrencia en SQLite.
- `python manage.py test --settings=AppDocs.settings_test auditoria.tests.test_idempotent_audit auditoria.tests.test_middleware auditoria.tests.test_tareas_audit_ui tareas.tests.test_audit_integration tareas.tests.test_logical_deletion`: 53 pruebas PASS.
- `python manage.py test --settings=AppDocs.settings_test auditoria.tests tareas.tests.test_audit_integration tareas.tests.test_logical_deletion`: 142 pruebas; 3 fallos reproducibles en tests existentes de Biblioteca/Gestión DTE: `test_share_email_link_logs_event` (respuesta no JSON) y dos expectativas de enlace en `test_gestiondte_ui`. Esas superficies no se modificaron.
- `makemigrations` generó `auditoria/migrations/0014_idempotent_tareas_audit.py`. La migración solo se aplicó a la base temporal del test runner; no se conectó a `DB_sistema` ni a producción.
- El alias efectivo de auditoría bajo `AppDocs.settings_test` es `default` SQLite. No se demostró concurrencia sobre MySQL de producción; el índice único y la semántica del motor real requieren validación antes del despliegue.

En esa fotografía, L2 permanecía pendiente de integración y L3 no se había iniciado.
L4 está implementada como consulta histórica GET-only. L5 Etapas 1–2 preparan el ledger y
el servicio interno, pero no la ruta HTTP ni la proyección L4; L6 permanece pendiente.

### Cierre L2/L3 previo a la auditoría correctiva (histórico; reabierto)

**Estado de esa validación previa: L2 GO; L3 GO.** La auditoría independiente posterior
reabrió ambos gates por H-L2-001, H-L3-001 y H-L3-002. Esta fotografía se conserva como
historial, pero no representa el gate vigente. No se añadieron rutas, POST, interfaz
histórica, restauración ni eliminación física en ese cierre.

L2 integra `tareas/services/audit.py` con `AuditoriaService.log_event_idempotent` y
`get_event_by_idempotency_key`. La escritura central continúa después del commit de la
operación de Tareas. `reconcile_logical_deletion_audit` consulta primero la clave estable,
reconoce una confirmación previa, reintenta idempotentemente una ausencia y conserva como
conflicto un payload distinto. La reconciliación es explícita; no se añadió un bucle de
reintentos en background.

L3 hace que `Tarea.objects` sea el gestor operativo (`eliminada=False`) y reserva
`Tarea.all_objects` para ledger e integridad administrativa. `Tarea.save` rechaza cambios
operativos sobre filas eliminadas y cambios directos de sus metadatos; `TareaRelacion.save`
rechaza nuevas relaciones con endpoints eliminados. Los locks ORM y MYSQL_CONFIG excluyen
eliminadas por defecto; L2 y los flujos administrativos preexistentes solicitan acceso
explícito cuando lo requieren.

| Superficie | Archivos y consultas | Tratamiento L3 |
|---|---|---|
| Modelos y mutaciones | `tareas/models.py`; `tareas/services/task_mutation_locks.py` | Gestor operativo, guardas de instancia/jerarquía y locks activos por defecto. |
| Listas, detalle y búsqueda | `task_storage.py`, `dashboard_storage.py`, `detail_storage.py`, `kpi.py`, `movement_storage.py`, `similarity_storage.py` | ORM mediante gestor operativo; SQL MYSQL_CONFIG usa `eliminada=0` en filas y joins visibles. |
| Ciclo de vida y jerarquía | `closure_storage.py`, `hierarchy_creation.py`, `hierarchy_lifecycle_storage.py`, `lifecycle.py`, `reprogramming_storage.py`, `todo_storage.py` | Entradas y ancestros/hijos operativos filtrados; locks de mutación rechazan IDs eliminados. |
| Datos relacionados | `comment_storage.py`, `document_storage.py`, `meeting_storage.py`, `milestone_storage.py`, `minitask_storage.py`, `participant_storage.py`, `quotation_storage.py`, `shared_link_storage.py` | Validación del task raíz, filtros en relaciones y guardas en escrituras. Las reuniones/enlaces ligados a tareas eliminadas no se ofrecen como operativos. |
| Creación y orígenes | `assignment_storage.py`, `origin_storage.py`, `hierarchy_creation.py`, `meeting_storage.py`, `task_storage.py` | Los INSERT crean tareas activas; el modelo no permite iniciar una fila como eliminada y los orígenes deben ser operativos. |
| Ledger y excepciones | `logical_deletion.py`, `deletion_ledger.py`, `permanent_deletion.py` | Acceso histórico explícito y limitado a idempotencia, integridad y flujos administrativos preexistentes; no se expone una superficie nueva de eliminación física. |

La matriz se validó con `tareas.tests.test_logical_deletion`, regresiones de paridad ORM/
MYSQL_CONFIG y la suite completa. Se investigaron los fallos de la suite ampliada:
fixtures SQLite simulando MYSQL_CONFIG carecían del campo L1 `eliminada` en pruebas de
hitos, reuniones, cotizaciones, similitud y TO-DO; sus esquemas se alinearon con el
contrato. También se corrigió la comparación de agenda de reuniones para distinguir la
tarea planificada de los elementos de agenda, se actualizó la expectativa del lock SQL y
el test de persistencia de metadatos para representar el `QuerySet` usado por L2.

Pruebas de ese cierre previo bajo `AppDocs.settings_test`:

- `tareas.tests` más `auditoria.tests.test_idempotent_audit`: 1.135 pruebas PASS, 3 omitidas.
- Regresión focal de L2/modelos/reuniones/similitud/TO-DO/participantes y locks: 126 pruebas PASS.
- `python manage.py check --settings=AppDocs.settings_test`: PASS.
- `python manage.py makemigrations tareas --check --dry-run --settings=AppDocs.settings_test`: sin cambios detectados.

Las pruebas MySQL de esta ejecución usan adaptadores/fixtures aislados; no se conectó a
BASE_TAREAS productiva ni se hizo escritura en una base física.

### Remediación final H-L2/H-L3 — 2026-10-18

**Estado vigente al 2026-10-19: L2 GO; L3 GO; L4 implementada para revisión funcional.
L5–L6 siguen pendientes.** La integracion L4 en `access_control`, el submenu Tareas y los
catalogos ES/EN se limito a los cambios aditivos expresamente autorizados; no se cambiaron
permisos de usuarios, semantica general ICMEAS, requisitos ni rutas de otras aplicaciones.

**H-L2-001 — actor original ausente**:

- El ledger conserva el `actor_id` escalar. Si el usuario ya no existe y no hay evento
  central, la adaptación escribe mediante la API idempotente con `user=None` y conserva
  el `actor_id` original en `meta`; no sustituye al actor ni crea usuarios ficticios.
- El payload idempotente de `user=None` tiene un hash distinto al de una instancia User
  con el mismo PK. Por eso, cuando ya existe el evento, la reconciliación lo consulta
  primero y valida UUID, campos de negocio, metadata y `actor_id`; no vuelve a escribir
  ni modifica el hash persistido. El FK `user` puede quedar `NULL` por `SET_NULL` sin
  perder la identidad histórica numérica.
- Se probaron actor eliminado antes de la primera escritura, actor eliminado después
  de persistir el evento, actor inactivo/reubicado/sin permiso vigente, lookup temporal
  de SYSTEM fallido y recuperado, replay, identidad, hash, conflicto y no duplicación.
  La autorización de reconciliación se comprueba sobre el operador actual y Base 00;
  no se reautoriza retroactivamente al actor original.
- Dos reconciliadores concurrentes también se probaron con el actor original ausente;
  ambos convergen en un solo UUID/evento y el ledger termina confirmado.

**H-L3-001 — preview MYSQL_CONFIG**:

- El adaptador Django y el SQL MySQL filtran `eliminada=0` para raíz y descendientes.
  Una raíz eliminada no es accesible; una relación inconsistente con descendiente
  eliminado, inexistente o fuera de empresa bloquea el preview con el mismo mensaje
  genérico, sin devolver identificador/título ni distinguir la causa.
- El preview continúa siendo GET de solo lectura del WIP físico anterior; no es la
  pantalla histórica L4 ni habilita ejecución física.

**H-L3-002 — escrituras masivas**:

- `TareaQuerySet` protege `update`, `bulk_update`, `bulk_create` y los upserts masivos
  sobre marca y metadata de eliminación; `save(update_fields=...)` conserva la guarda.
  Los gestores `objects`, `all_objects` y el base manager ORM usan el QuerySet protegido.
- El adaptador autorizado de L2 actualiza las marcas mediante SQL parametrizado dentro
  de la transacción y después de autorización/locks. Esta protección no se presenta como
  barrera contra SQL deliberado; no se encontraron otros escritores operacionales de
  esos campos dentro de `tareas`.
- La migración `0033` solo registra opciones/managers ORM; no agrega ni altera columnas
  ni constraints. No fue aplicada a ninguna base operativa.

**Validación final aislada**:

- Pruebas focalizadas de ledger, reconciliación, locks, preview, gestores y API
  idempotente: **85 PASS**.
- `tareas.tests` más `auditoria.tests.test_idempotent_audit`: **1.149 PASS, 3 SKIP,
  0 FAIL, 0 ERROR**.
- `python manage.py check --settings=AppDocs.settings_test`: PASS.
- `python manage.py makemigrations --check --dry-run --settings=AppDocs.settings_test`:
  sin cambios detectados.
- `git diff --check`: PASS.

Las tres omitidas son `test_company_without_tasks_gets_a_transactional_sentinel`,
`test_lock_timeout_is_reported_as_a_controlled_conflict` y
`test_same_company_mutations_serialize_across_connections`; requieren variables
`TAREAS_MARIADB_TEST_*` y una instancia local MariaDB aislada. No había configuración
aislada disponible: el test runner usó `default` y `system_test` como SQLite `:memory:`.
Los mocks validan SQL y resultados de adaptadores, pero no certifican locks ni
concurrencia en un motor MariaDB físico. No hubo conexión ni escritura en bases reales.

Los tres fallos históricos de `auditoria.tests.test_update_audit` y
`auditoria.tests.test_gestiondte_ui` no se reejecutaron ni corrigieron en esta remediación;
siguen fuera del alcance autorizado.

### E15. Consulta historica L4 (implementada)

- Abrir `/tareas/eliminadas/` con la empresa activa y permiso explicito `ingresar` para
  `Tareas - Tareas eliminadas`; combinar filtros y navegar las paginas.
- Abrir el detalle de una Tarea y el detalle de operacion. Confirmar que ledger/auditoria
  se muestran sin mutaciones por GET. Cuando L5 se implemente, el acceso a su preview desde
  L4 requerirá además S explícito en `Tareas`; I por sí solo no mostrará acción de restore.
- Con permiso adicional `Tareas` + `ingresar`, comprobar las secciones relacionadas; sin
  ese permiso deben aparecer restringidas. Los comentarios ocultos requieren ademas
  `supervisor`; documentos y evidencias no exponen bytes ni URL.
- Intentar POST en las rutas historicas y confirmar `405`. Enviar `empresa_id` por GET
  no cambia el alcance de la empresa activa.
- Verificar que una Vista ausente falla cerrado y no crea Vista ni permisos durante la
  solicitud. Ejecutar `ensure_view_catalog --app tareas --dry-run` para previsualizar el
  registro declarativo, y `--apply` solo cuando corresponda al bootstrap autorizado.

Evidencia de desarrollo 2026-10-19: 85 tests focalizados de servicio, proyeccion relacionada,
vistas, permisos, aislamiento, registry/sidebar e i18n PASS. La lectura MySQL real previa fue solo
SELECT y comprobo `DATABASE() == tareas`; la lista de Base 00 devolvio cuatro items. La
tarea 2 estaba conservada y consistente; la consulta detallada ejecuto las secciones
relacionadas con estado `AVAILABLE` y cero filas relacionadas. Los items 84, 85 y 86
estaban ausentes y se presentaban solo como referencias del manifiesto. No se escribieron
datos operacionales ni de auditoria.

### E16. Eliminacion logica desde el detalle (L2 web)

- Entrar con usuario activo y permiso VICMEAS `supervisor=True` sobre `Tareas` en Base 00.
  El permiso `eliminar` por si solo no habilita el boton ni el endpoint.
- Desde el detalle de una tarea raiz elegible, abrir `eliminacion_logica`. Revisar codigo,
  titulo, empresa, estado, descendientes, conteos, referencias, advertencias y bloqueos.
- Si el preview esta limpio, ingresar el motivo obligatorio y confirmar con POST CSRF. Un
  cambio de inventario invalida el token y exige revisar un preview nuevo; un bloqueo desactiva
  la confirmacion.
- Verificar ledger/auditoria, desaparicion del detalle operacional y exclusion del listado.
  Con permiso adicional explicito `ingresar` para `Tareas - Tareas eliminadas`, el resultado
  navega al detalle L4 de operacion; sin ese permiso, vuelve al listado normal sin concederlo.
- No usar el anterior `/eliminacion-definitiva/previsualizar/` como ejecutor: esa ruta sigue
  siendo preview GET del WIP fisico y no ejecuta ninguna eliminacion.
- Para `MYSQL_CONFIG`, la operacion solo inicia si la base configurada es exactamente
  `tareas` y el ledger comprueba `SELECT DATABASE() == 'tareas'` antes de iniciar la
  transaccion operacional.
- Una referencia a archivo no bloquea L2: se informa que documentos y archivos se
  conservan. El preview físico legado mantiene el bloqueo de exclusividad de archivos.
- La validacion automatizada ejecuta la confirmacion unicamente contra SQLite temporal de
  tests. No ejecutar confirmacion real de demostracion en MySQL; esa prueba manual la realiza
  el propietario desde el navegador despues de revisar el preview.

### E17. Restauración lógica L5 (procedimiento futuro; no ejecutar en esta fase)

**Precondiciones**: implementación L5 aprobada y desplegada en entorno aislado; operación
de eliminación `COMMITTED` con resultado `LOGICALLY_DELETED`; usuario activo con I en
`Tareas - Tareas eliminadas` y S en `Tareas`, en la empresa activa de la operación. Para
MYSQL_CONFIG se usará un servidor de pruebas aislado, con base efectiva llamada exactamente
`tareas`; no apuntar a desarrollo compartido, producción ni credenciales reales. Esta guía
documenta pruebas futuras y no autoriza una restauración ni escritura ahora.

1. Crear una tarea individual y una jerarquía padre/hijo/nieto identificables en fixtures.
2. Eliminar lógicamente la tarea individual y restaurarla; verificar mismo PK y correlativo.
3. Eliminar y restaurar un árbol; comprobar que se recuperan exactamente los IDs del
   manifiesto y la jerarquía retenida, sin consultar el árbol para agregar elementos.
4. Incluir un descendiente marcado por otra operación anterior y comprobar que no se
   incorpora ni se restaura.
5. Alterar el manifiesto/token para omitir un elemento; el POST debe rechazarse sin cambios.
6. Usar una operación de otra empresa; responder sin revelar sus datos ni modificar filas.
7. Usar I sin S; L4 se puede leer, pero no aparece acción de restore y el POST recibe 403.
8. Usar E sin S y después `is_staff`/`is_superuser` sin S; ambos intentos reciben 403.
9. Enviar POST sin CSRF con el cliente de pruebas que fuerza comprobación CSRF; rechazarlo.
10. Cambiar el alcance después del preview; invalidar fingerprint/token y exigir una nueva
    revisión.
11. Verificar que PK, correlativo, estado de negocio, fechas, porcentaje y responsables no
    cambien durante restore.
12. Verificar que documentos, asociaciones y archivos conservan IDs/referencias y que no
    se llama a mover, copiar, recrear ni borrar archivos.
13. Confirmar una operación y comprobar nueva fila/manifiesto de ledger, relación con la
    eliminación original y evento idempotente; simular auditoría post-commit pendiente y
    reconciliarla sin duplicar el evento.
14. Repetir el mismo POST/UUID; obtener replay idempotente sin segunda mutación. Intentar
    una restauración nueva contra la misma eliminación; rechazarla.
15. Volver a eliminar la tarea restaurada usando UUID nuevo; verificar nuevo manifiesto y
    nueva operación, no reutilizar los IDs históricos.
16. Ejecutar varios ciclos eliminación/restauración con UUIDs distintos y verificar que no
    existe límite artificial ni se sobrescribe el historial anterior.
17. Forzar un error antes del commit; comprobar rollback de todas las marcas, operación y
    manifiesto. Simular commit incierto y reconciliar por el UUID nuevo.
18. Consultar L4: las operaciones antiguas siguen visibles como restauradas, la tarea no
    aparece como actualmente eliminada y la operación de restauración se ve en trazabilidad.
19. Quitar físicamente una fila solo en una fixture de test; restaurar debe fallar todo-o-nada
    y L4 conservar el ID de manifiesto sin inventar título/estado. No reconstruirla.
20. En MYSQL_CONFIG, comprobar `SELECT DATABASE() == 'tareas'` y tablas transaccionales
    InnoDB antes de escribir; nombre distinto debe fallar cerrado. Repetir la matriz
    funcional con backend Django aislado.

### L5 Etapa 1. Persistencia y ledger (validación ejecutada; sin restaurar tareas)

- Pruebas focalizadas combinadas de ledger/schema L5 y regresiones L2/L3/L4 en
  `AppDocs.settings_test`: **163 PASS, 0 FAIL, 0 SKIP**.
- El test de concurrencia usa SQLite de pruebas aislada y dos registros simultáneos; se confirmó un único vínculo. No certifica concurrencia MariaDB.
- Las pruebas MYSQL_CONFIG usan conexión/cursor simulados y verifican `SELECT DATABASE()`/DDL de forma no ejecutable. No se conectó ni escribió en MySQL real.
- `python manage.py check --settings=AppDocs.settings_test`: sin problemas.
- `python manage.py makemigrations --check --dry-run --settings=AppDocs.settings_test`: no se detectaron cambios adicionales.
- La migración `0034` solo se aplicó por el test runner a su base temporal. No se ejecutaron migraciones, SQL DDL/DML ni restauraciones en bases reales.

### L5 Etapa 2.3 — campaña MariaDB de desarrollo (2026-10-20)

- Conexión operacional: `BASE_TAREAS` → `django_tareas` → `tareas`; MariaDB 10.11.13.
- T01–T12 y T14: PASS con el servicio y transacciones reales en MariaDB; T13: parcial,
  con el caso E-solo cubierto por la regresión aislada; T15: commit operacional real y
  auditoría central simulada en memoria; T16: pendiente por no interrumpir conexiones.
- Cada conexión operacional comprobó `DATABASE()`, `VERSION()` y `CURRENT_USER()`; las
  fixtures se limpiaron, no hubo escrituras en SQLite real/`DB_sistema` ni cambios de
  archivos físicos.
- Regresión focal L2/L3/L4/L5 en `AppDocs.settings_test`: 153 PASS.
- Una ejecución ampliada de 164 pruebas tuvo cinco errores en `test_permanent_deletion.py`
  por un argumento `purpose` faltante en el flujo de eliminación física, fuera del scope L5.

## Verificación de cierre

```powershell
git diff --check
git status --short
```

### Gate permanente de i18n

Antes de cerrar cualquier cambio de UI en `tareas`, ejecutar el inventario y la
validación funcional en ambos idiomas. Una superficie solo está completa cuando
el `data-key` o `message_key` es correcto, existe en `static/lang/sp.json` y
`static/lang/en.json`, no es dinámico, los enums visibles tienen etiqueta i18n,
los mensajes backend/AJAX se resuelven y la pantalla fue comprobada en ES y EN.

El cierre requiere:

```powershell
python manage.py test tareas.tests.test_i18n --settings=AppDocs.settings_test
```

Y estas métricas en cero: `MISSING_SP`, `MISSING_EN`, `ONE_SIDE`, `DYNAMIC_KEYS`,
`RAW_MESSAGE_KEYS_VISIBLE` y `VISIBLE_HARDCODED_TEXT`, salvo excepciones
explícitamente justificadas y registradas. El inventario debe cubrir templates,
formularios, vistas, JavaScript app-local y ambos catálogos.

La comprobación manual mínima recorre sidebar, listado, crear/editar, detalle,
ciclo de vida, mis hitos y tareas, hitos, documentos/evidencias, cotizaciones,
reuniones, similitud, enlaces, dashboards y TO-DO si su UI está activa; debe
alternar ES → EN → ES sin reiniciar datos ni alterar la lógica.

Esperado: diff sin errores de whitespace; cambios de código limitados a `tareas/` y `specs/`.
Los cambios futuros adicionales en `AppDocs/app_classification.py`, `AppDocs/settings.py` y
`AppDocs/urls.py` sólo pueden aparecer en una tarea separada con autorización y scope
explícitos; desde este scope son dependencias externas.
Sin commit ni push sin autorización expresa del usuario.
