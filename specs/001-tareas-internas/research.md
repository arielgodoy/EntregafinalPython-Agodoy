# Research: Tareas Internas - SPEC MAESTRA

**Date**: 2026-09-07 | **Feature**: [spec.md](spec.md)

Las decisiones de la feature reutilizan interfaces existentes. No quedan `NEEDS
CLARIFICATION` para P4, P6 o P8. P1 permanece bloqueado por contrato legacy; P2 ya no
bloquea la operación local de proveedores y queda reservado para integración ERP.

## Decisions

### Sincronizacion documental 2026-10-30 — Fase 1.6

Decision aprobada: la maestra gobierna tareas y
[Fase 1.6](../003-organizacion-tareas-fase-1-6/spec.md) gobierna membresias e
integracion organizacional. FR-P06 enlaza la Opcion B sin sustituir VICMEAS,
participacion ni reglas de operacion; no se crean versiones independientes de
F16-FR01 a F16-FR30. No se renumeran decisiones D1 a D28.

Evidencia: T092/T093 y los modelos actuales confirman que Local/Departamento
existen; las referencias a una app futura son contexto historico. P1 mantiene
pendiente la integracion legacy, no la identidad canónica de esos maestros.
Fase 1.6 no resuelve P2 ni otras deudas historicas de esta maestra.

Las relaciones y condiciones se concentran en la
[matriz de sincronizacion](../003-organizacion-tareas-fase-1-6/synchronization.md);
los bloqueos F16-G01 a F16-G10 conservan su clasificacion tecnica, funcional,
documental o externa. Ninguna ausencia en SYSTEM se resuelve con infraestructura
paralela ni se transforma automaticamente en una decision de negocio pendiente.
No se ejecutaron pruebas ni se modificaron servicios con esta sincronizacion.

### D1. Frontera y compatibilidad

- **Decision**: ampliar la app existente `tareas`, sin reutilizar ni modificar
  `control_de_proyectos.Tarea`.
- **Rationale**: ciclos y responsabilidades distintos; la Fase 1 debe conservar PK, URLs
  y comportamiento.
- **Alternatives considered**: fusionar modelos o mover el dominio a proyectos; rechazadas.

### D2. Seguridad, visibilidad y empresa activa

- **Decision**: consumir VICMEAS ya implementado: `Permiso.ver` controla exclusivamente
  la visibilidad del sidebar por usuario, Vista y `request.session['empresa_id']`;
  ICMEAS, `LoginRequiredMixin` cuando corresponda y la misma empresa activa protegen
  toda vista/acción. Validar cada queryset y objeto.
- **Rationale**: V/I son independientes y separan descubribilidad de autorización,
  evitando exposición cross-company sin convertir V en seguridad backend.
- **Alternatives considered**: permisos Django estándar, usar `ver` para autorizar
  acciones, hacer depender el menú de `ingresar`, o recibir la empresa por POST;
  rechazadas.

La decisión V independiente de I está cerrada y no se reabre en fases de `tareas`.
Los padres del sidebar se derivan de hijos visibles, el superuser tiene bypass visual
del sidebar únicamente, y el mapping item → Vista o clasificación GLOBAL pertenece a
la infraestructura base. La vista inicial sigue dependiendo de `ingresar=True`.

### D3. Persistencia incremental

- **Decision**: migraciones aditivas por fase, backfills idempotentes y activación gradual.
- **Rationale**: la Fase 1 contiene datos que deben conservarse mientras se agregan estados,
  relaciones y auditoría.
- **Alternatives considered**: reemplazo de `Tarea` o migración única; rechazadas.

### D4. Correlativos A/B

- **Decision**: un único registro cambia de A a B al publicar; unicidad por empresa y
  generación transaccional segura.
- **Rationale**: FR-A01/A06 exige transformación sin duplicación.
- **Alternatives considered**: tabla separada o duplicar al publicar; rechazadas.

### D5. Estados y auditoría

- **Decision**: servicio de transiciones explícitas, historial inmutable de origen/destino,
  usuario y fecha; anulación/reactivación separadas.
- **Rationale**: FR-C08/C09 y la restauración exacta requieren auditoría distinta del estado.
- **Alternatives considered**: cambios directos desde formularios; rechazados.

### D6. Jerarquía y anulación (REVISADO — diseño simplificado aprobado)

- **Decision**: la anulación usa un flag persistente `Tarea.anulada` (BooleanField,
  default False). `estado` representa SOLO el ciclo funcional (BORRADOR, ACTIVA, GESTION,
  PENDIENTE_APROBACION_CIERRE, CERRADA); `ANULADA` deja de ser estado canónico. La
  anulación jerárquica es LÓGICA (`anulada_efectivamente` = propia OR padre OR abuelo),
  NO una cascada física de escritura. Anular/reactivar solo cambia `anulada` de la tarea
  afectada; no modifica estados, responsables, participantes, correlativo ni relaciones.
- **Rationale**: elimina la cascada física y la necesidad de snapshot de estados para
  restaurar jerarquía; los datos nunca cambian, por lo que no hay nada que reconstruir.
- **Alternatives considered**: cascada física de estados ANULADA y snapshot de estructura
  para reactivación; rechazadas por duplicar fuente de verdad y complejidad.

Nota T134.2E: Reprogramación usa el ledger existente `Reprogramacion` y su M:N,
sin agregar `TareaTransicion`. La fecha anterior se captura bajo lock; la comunicación
se ejecuta después del commit. Reacomodo tras reactivar sigue siendo deuda separada.

### D7. Avance ponderado

- **Decision**: pesos relativos normalizados; `avance = sum(cumplimiento * peso) / sum(pesos)`.
  Agregar hitos actualiza el denominador sin alterar cumplimientos anteriores.
- **Rationale**: decisión P4.
- **Alternatives considered**: pesos fijos que suman 100 o pesos iguales; rechazadas.

### D8. Local y maestro local de Proveedor

- **Decision**: Local solo se consumirá con contrato autorizado; Proveedor tendrá un maestro
  global Django en la futura `APPLICATION_APP proveedores`. La relación por Empresa,
  convenio, visitas e identidad legacy quedan fuera del primer modelo.
- **Rationale**: la identidad local permite operar sin ERP; P2 se reserva para lookup,
  validación, identificador, conciliación y sincronización legacy.
- **Alternatives considered**: depender del legacy para toda operación o duplicar maestros;
  rechazadas.

### D9. Cotizaciones

- **Decision**: rondas históricas, mínimo configurable por ronda con default 3 y máximo de
  3 versiones por proveedor/ronda; el cierre verifica el mínimo.
- **Rationale**: P3 y FR-I01/I08.
- **Alternatives considered**: mínimo global o versiones ilimitadas; rechazadas.

La evolución aprobada añade `Cotizacion.proveedor` nullable para preservar histórico PRE-P2,
exige proveedor en nuevas cotizaciones, valida máximo 3 por `(ronda, proveedor)` y cuenta
proveedores Django distintos vigentes sin sumar rondas.

### D10. KPI y consultas

- **Decision**: ocho KPI repetidos en dimensiones permitidas: total por estado, atrasadas,
  próximas a vencer, sin movimiento, esperando aprobación, carga abierta por responsable,
  cumplimiento y tiempo promedio de cierre.
- **Rationale**: P6 evita divergencias; Local sigue dependiendo de P1 y Proveedor podrá
  habilitarse desde su maestro local sin depender de legacy.
- **Alternatives considered**: KPI distintos por dimensión o métricas adicionales; rechazadas.

### D11. Similitud y enlaces

- **Decision**: comparar también tareas cerradas; umbral configurable por empresa con default
  80%, cambios solo para nuevas evaluaciones. Enlaces solo para usuarios autenticados, con
  ICMEAS, empresa activa y auditoría de acceso.
- **Rationale**: P8 y FR-N04/P03.
- **Alternatives considered**: umbral por usuario/tarea, enlaces públicos o convertir la tarea
  antigua; rechazadas.

### D12. Integraciones transversales

- **Decision**: consumir `notificaciones` y email de `acounts`; JS nuevo, si hace falta, vive
  en `tareas/`; no se editan vendor, apps consumidas ni templates globales.
- **Rationale**: FR-K04 y reglas de autocontención.
- **Alternatives considered**: subsistemas paralelos o editar `static/js/app.js`; rechazadas.

### D13. Comentarios de Tarea

- **Decision**: Comentarios permanece dentro de `tareas`. El modelo actual de `TareaLectura` (solo `leido` y `fecha_lectura`, único por Tarea/usuario) NO satisface lectura parcial, contador ni primer pendiente. Se reutiliza su fila y se amplía con cursor por Comentario; las pausas de inactividad son intervalos por lector/Tarea, no filas por Comentario. Carga cronológica en bloques de 20; ocultos pendientes conservan tombstone neutro. Adjuntos usan relaciones históricas a `DocumentoTarea`, sin copia física.
- **Rationale**: `TareaLectura` y `mark_task_read` actuales solo expresan leído/no leído general de Tarea. El diseño preserva esa semántica y evita marcar al abrir el detalle. `DocumentoTarea` se protege de borrado normal mediante `DocumentoHistorial.PROTECT`; `update_document` puede mutar archivo/URL y solo registra acción/usuario/fecha, pero la FK histórica conserva la identidad del `DocumentoTarea`. No se requieren cambios externos ni subsistema de mensajería.
- **Authorization**: `Tareas` + `ingresar` para leer el feed; `modificar` para crear/editar/vincular/desvincular; `supervisor` (S de VICMEAS) para ocultar/restaurar. La lectura del feed requiere usuario activo y Empresa activa, pero no participación funcional; las mutaciones, el reconocimiento y el seguimiento requieren participación funcional efectiva (`Tarea.creada_por OR Tarea.responsable OR TareaParticipante OR Hito.responsable` para Hitos de la Tarea con `anulado=False`). El creador no tiene bypass y no se crean permisos nuevos.
- **Notifications**: creación/edición/ocultación/restauración reutilizan T053/T054; notifican participantes actuales y activos, excluyen actor y deduplican. En `CRITICA` se mantienen in-app y email automático existentes. Solo creación incrementa no leídos; lectura y las otras mutaciones no lo hacen. Un adjunto no duplica el evento documental.
- **Alternatives considered**: nueva app, almacenamiento de archivo duplicado, lectura por fila para cada Comentario, permisos/roles nuevos y chat independiente; rechazados o innecesarios frente al cursor y relaciones existentes.

### D14. Connection Roles para Tareas

- **Decision**: Tareas tendra roles propios con alcance `GLOBAL POR APP`.
- **Rationale**: la configuracion logica pertenece a la app completa, aunque una fuente
  MySQL seleccionada conserve su propia empresa en `SettingsMySQLConnection`.
- **Alternatives considered**: `(empresa, role)` y reutilizar registros de Gestion DTE;
  rechazadas.

### D15. Roles y fuentes

- **Decision**: `BASE_TAREAS` y `AUDITORIA_TAREAS` admiten Django o MySQL; `LEGACY_MYSQL`
  y `LEGACY_AUDITORIA` admiten solo MySQL.
- **Rationale**: conserva la separacion funcional probada en Gestion DTE.
- **Alternatives considered**: permitir Django para Legacy o mezclar fuentes; rechazadas.

### D16. Gestion DTE como referencia

- **Decision**: `GestionDTEConnectionRole` y `CertificadoSIIRepository` son referencia,
  no dependencia. Tareas tendra modelo y resolver propios.
- **Rationale**: las APPLICATION_APPS no dependen funcionalmente entre si.
- **Alternatives considered**: importar `gestiondte.services.connection_roles`; rechazada.

### D17. Puente publico y no fallback

- **Decision**: reutilizar `SettingsMySQLConnection` y `open_mysql_connection()`; para
  Django usar alias validado SYSTEM y `.using(alias)`. No existe fallback silencioso a
  `default`.
- **Rationale**: `CertificadoSIIRepository` demuestra el contrato y sus tests verifican
  el error cuando falta `serverbasedte`.
- **Alternatives considered**: abrir conexiones ad hoc o modificar router/DATABASES;
  rechazadas.

### D18. Catalogo Django SYSTEM

- **Decision**: la primera implementacion adaptara en Tareas la logica minima de
  `get_system_database_catalog()` sin importar Gestion DTE. Promoverla a CORE queda para
  una tarea arquitectonica separada.
- **Rationale**: el catalogo actual reside en Gestion DTE y no existe una API publica
  equivalente en settings.
- **Alternatives considered**: importar Gestion DTE o modificar settings ahora;
  rechazadas.

### D19. Infraestructura protegida

- **Decision**: no modificar `api.Router_Databases.MultiDatabaseRouter`, `DATABASES`,
  settings funcional, seed/sidebar de CORE ni Gestion DTE desde la feature.
- **Rationale**: son dependencias externas protegidas y requieren autorizacion propia.

### D20. Catalogo MySQL central de Tareas

- **Decision**: Tareas consume únicamente conexiones activas de
  `SettingsMySQLConnection` cuya `Empresa.codigo == "00"`; la empresa activa de sesión
  no participa en la selección ni resolución.
- **Rationale**: preserva el modelo per-company de Settings y da a Tareas un catálogo
  central estable para sus roles globales sin modificar Settings, Gestión DTE, API o router.
- **Alternatives considered**: usar la empresa activa, globalizar Settings o crear una
  capa de asignaciones; quedan fuera de esta feature.

### D21. Bootstrap Base Tareas y storage runtime

- **Decision**: el bootstrap inicial de `BASE_TAREAS` ejecuta SQL MySQL congelado desde
  una preview de SchemaEditor, excluye `TareaConnectionRole` y elimina únicamente FKs
  hacia tablas externas. Las relaciones internas permanecen físicas. El runtime storage
  queda separado y pendiente.
- **Rationale**: `CertificadoSIIRepository` demuestra la frontera resolver/repository y
  backend Django/MySQL sin modificar SYSTEM/CORE; el SchemaEditor permite mantener el
  schema actual sin duplicar manualmente 39 definiciones.
- **Alternatives considered**: `migrate` sobre conexión dinámica, router global, copiar
  maestros externos, importar `gestiondte` o implementar CRUD MySQL completo ahora;
  rechazadas.

### D22. Transacciones y evolución MySQL

- **Decision**: el bootstrap ejecuta DDL no destructivo y maneja commit/rollback del
  connection wrapper, pero no promete atomicidad DDL del motor. Las transacciones por
  agregado pertenecen a la futura abstracción Storage/Repository.
- **Rationale**: el precedente de certificados no coordina siempre operaciones múltiples;
  Tareas no debe ampliar esa debilidad al runtime futuro.
- **Alternatives considered**: migrador externo o versionado SQL en T124-T130; diferidos
  a una task de evolución separada.

### D23. Eliminación física administrativa del árbol (2H.0.2, supersedida)

- **Decisión histórica**: el propietario autorizó en 2H.0.2 la eliminación física
  administrativa de la raíz, descendientes y registros operacionales exclusivos.
- **Estado actual**: esa decisión queda sustituida por D24/2H.0.3 y ya no es una
  autorización funcional vigente. El executor físico WIP no debe ejecutarse ni
  conectarse a una ruta HTTP. Se conserva la referencia histórica para trazabilidad.
- La autorización anterior no cambió las reglas ordinarias de anulación/reactivación ni
  las operaciones individuales de Hitos, MiniTareas y Comentarios.

### D24. Eliminación lógica definitiva sin restauración (2H.0.3)

- **Decisión funcional autorizada por el propietario**: eliminar lógicamente una raíz y
  todos sus descendientes de forma atómica, sin restauración, conservando físicamente
  todas las filas, relaciones, documentos, historiales, evidencias, reuniones, TO-DO,
  archivos y datos de otras aplicaciones. Las tareas dejan de operar y pasan a una
  superficie histórica de solo lectura.
- **Boundary documental**: esta decisión reemplaza FR-R06…FR-R15 de 2H.0.2 y añade
  FR-R16…FR-R17 para el contrato vigente de consulta histórica/no restauración. El
  contrato vigente queda en FR-R06…FR-R17. No autoriza campos, migraciones, código, SQL, POST ni
  cambios de conexiones. No modifica anulación/reactivación ordinarias ni eliminación
  individual de Hitos, MiniTareas o Comentarios.
- **Rationale**: preservar íntegramente datos e historial y reducir riesgo de pérdida,
  manteniendo la separación entre lifecycle, anulación y eliminación funcional definitiva.
- **Adaptación técnica pendiente**: revisar el ledger existente para que `COMMITTED` y el
  resultado representen una marca lógica; el `result_code="DELETED"` del executor físico
  no puede conservarse con semántica falsa. No agregar estados ni duplicar metadata.

### D25. Autorización técnica L1 y decisiones funcionales confirmadas

- **Decisiones aprobadas por el propietario**: la pantalla independiente `Tareas
  eliminadas` requiere VICMEAS `ingresar` (I) explícito; eliminar requiere `supervisor`
  (S) explícito en la Vista `Tareas` y Empresa Base 00; las tareas eliminadas se excluyen
  de KPI operacionales y reportes históricos habituales; el motivo es obligatorio y
  persistente; no existe restauración ni eliminación física administrativa.
- **Autorización técnica L1**: implementar campos/metadatos del modelo, migración Django
  aditiva, persistencia del motivo en ORM/MYSQL_CONFIG, SQL contractual y preflight
  metadata-only. No autoriza aplicar DDL a BASE_TAREAS real, ejecutar el executor físico,
  implementar el servicio transaccional L2 ni habilitar POST.
- **Estado de esta autorización inicial (fotografía 2026-10-16)**: L1 quedó
  implementada; L2…L6 aún no habían comenzado. La autorización posterior de L2/L3 y
  su gate correctivo del 2026-10-18 sustituyen esta fotografía para el estado actual.

### D26. Proyeccion de consulta historica L4 (2026-10-19)

- **Decision**: construir la lectura desde `BASE_TAREAS` y el ledger existente, con
  LEFT JOIN de la fila de Tarea y comprobacion de empresa/UUID/actor antes de exponer
  campos operacionales. La lista se deduplica por item del manifiesto y pagina en SQL.
- **Rationale**: el ledger conserva identidad, motivo, resultado y elementos, pero no es
  un snapshot completo. Las filas 84-86 de la operacion de prueba no existen fisicamente;
  solo puede mostrarse su referencia de manifiesto. La tarea 2 se conserva y permite
  comprobar la proyeccion completa.
- **Alternatives rejected**: recrear nombres/estados a partir de IDs, usar ORM/default
  como fallback, reconciliar auditoria al leer o crear tablas/snapshots para L4.
- **Boundary**: la proyeccion no necesita schema. Con autorizacion expresa del propietario,
  la integracion se limito a la Vista declarativa `Tareas - Tareas eliminadas`, el item VICMEAS
  `tasks_deleted` dentro del grupo Tareas y las claves L4 ES/EN. No se cambiaron permisos
  existentes, semantica general ICMEAS, middleware, routers ni otras aplicaciones.

### D27. Restauración lógica L5 (2026-10-19; contrato documental)

#### Hallazgos verificados en el código actual

- `TareaEliminacionElemento` persiste IDs `tareas.tarea` por operación y una restricción
  única por operación/tipo/ID. El manifiesto L2 contiene el conjunto de tareas, no una
  copia de los bordes padre/hijo.
- `TareaEliminacionOperacion` ya guarda UUID, actor, empresa, raíz, backend/configuración,
  fingerprint, motivo, resultado, timestamps y estados/errores de auditoría. Su índice por
  empresa/raíz/fecha no es único. `get_root_operation()` devuelve la operación histórica
  más antigua; el servicio L2 rechaza la raíz si encuentra cualquier operación previa.
  Por tanto, los ciclos ilimitados requieren cambiar ese guard de servicio, no agregar una
  unicidad histórica por raíz.
- `Tarea` conserva únicamente la operación de eliminación actualmente aplicada en
  `eliminacion_operacion_id`. No existe fila ni campo de restauración, vínculo de reversión
  ni estado L4 `RESTORED`. El lector L4 actual clasifica una marca que ya no coincide con
  la operación como inconsistente.
- La operación L2 cambia las marcas y el ledger dentro de la transacción de `BASE_TAREAS`;
  la auditoría central se entrega post-commit mediante la API idempotente existente. No
  existe atomicidad distribuida ni se modifican los eventos de auditoría al leer L4.
- El resolver de ledger comprueba `SELECT DATABASE()`, el nombre configurado y tablas
  transaccionales InnoDB antes de abrir la transacción MySQL. L2 restringe su empresa a
  Base 00; L5 debe mantener la empresa de la operación de origen y exigir que coincida con
  la empresa activa de sesión.

#### Respuestas al análisis del ledger

1. **¿Conserva el manifiesto exacto?** Sí para el conjunto de IDs de tarea de cada
   operación L2 confirmada; los manifiestos lógicos deben contener solo `tareas.tarea`.
2. **¿Distingue eliminaciones sucesivas de una misma tarea?** Cada operación tiene UUID,
   pero hoy L2 prohíbe una segunda operación para la raíz. No hay todavía vínculo entre
   una eliminación y una restauración.
3. **¿Los IDs bastan para la jerarquía?** Bastan para fijar el conjunto completo; las
   relaciones siguen físicamente presentes. No bastan para reconstruir ni demostrar una
   topología histórica si se alteró directamente fuera de los escritores L3.
4. **¿Cómo detectar una ya restaurada?** No existe esa señal hoy. La propuesta usa una
   operación `LOGICALLY_RESTORED` que referencia de forma única la eliminación original,
   y verifica que todas las marcas actuales sigan apuntando a esa eliminación.
5. **¿Esquema mínimo?** Reutilizar las filas de operación y manifiesto actuales; añadir
   `result_code=LOGICALLY_RESTORED` y un self-FK nullable/único `reverses_operation_id`
   en la nueva fila. Extender la constraint de motivo a ambos resultados. No tocar la
   fila original ni crear tablas paralelas.
6. **¿Atomicidad?** Bloquear y confirmar operación, manifiesto, filas de tarea y nueva
   operación/manifiesto en una sola transacción del backend `BASE_TAREAS`; limpiar las
   marcas solo dentro de esa transacción. El fallo revierte todo.
7. **¿Auditoría post-commit fallida?** La restauración queda operacionalmente confirmada
   con auditoría `PENDING`/`ERROR`; se muestra como auditoría pendiente, no como auditoría
   confirmada, y se reconcilia por el UUID nuevo con la API idempotente.
8. **¿Cómo impedir parcialidad?** Manifiesto completo comparado dentro del lock,
   validación de empresa/operación/filas/marcas/relaciones y una referencia única de
   restauración por eliminación. Cualquier diferencia aborta el conjunto.
9. **¿Filas históricas ausentes?** Permanecen en el manifiesto y L4 como referencias
   físicamente ausentes. Como los IDs 84–86 documentados en D26, no se recrean ni se
   consideran restaurados; su presencia bloquea la restauración completa.

#### Clasificación de requisitos

| Requisito | Clasificación | Nota |
|---|---|---|
| L5-R01 | DEFINIDO | Restaurar la misma fila y conservar su identidad/estado |
| L5-R02 | DEFINIDO | Recuperar exactamente el manifiesto completo |
| L5-R03 | DEFINIDO | S para escribir e I independiente para leer L4 |
| L5-R04 | DEFINIDO | Preview, POST/CSRF, motivo y rechazo de preview obsoleto |
| L5-R05 | DEFINIDO | Ciclos sin límite con UUID nuevos |
| L5-R06 | DEFINIDO | Registro nuevo e inmutabilidad del ledger original |
| L5-R07 | DEFINIDO | Validación estricta y atomicidad todo-o-nada |
| L5-R08 | DEFINIDO | Sin operaciones físicas sobre documentos/archivos |
| L5-R09 | DEFINIDO | Historial L4 distingue eliminado actual y restaurado |
| L5-R10 | DEFINIDO | Estado y fechas se conservan sin transición implícita |
| L5-R11 | DEFINIDO | Idempotencia, conciliación y estados de auditoría diferenciados |
| L5-R12 | DEFINIDO | BASE_TAREAS y validación de la base MySQL antes de escribir |

#### Decisiones técnicas derivadas

- Reutilizar operación/manifiesto, estados y metadatos de auditoría de
  `TareaEliminacionOperacion`; registrar la restauración en una fila nueva y referenciar
  la eliminación revertida desde esa fila. Esto conserva el evento original y minimiza
  persistencia adicional.
- En el flujo iniciado desde L4, mostrar la acción solo si el actor tiene tanto I en la
  vista histórica como S en `Tareas`; el preview/POST revalidan ambos por separado. I
  conserva su sentido de lectura y S es la autorización de escritura.
- La restauración limpia solo las cuatro marcas lógicas y conserva las relaciones/filas
  existentes. No llama `save()` operativo ni altera lifecycle, fechas o archivos.
- La vista L4 proyecta `RESTORED` desde la relación de operaciones, mantiene visible el
  hecho de eliminación y etiqueta los campos de la tarea como actuales, no como snapshot.

#### Pendiente de decisión o precisión

- Si se requiere probar la topología exacta frente a SQL externo/directo, el manifiesto
  actual carece de edges; decidir si operaciones futuras deben capturarlos. Los escritores
  oficiales L3 mantienen las relaciones retenidas sin cambios.
- Política final ante referencias externas o jerarquía inconsistente detectada en el
  momento de restaurar: el diseño falla cerrado, pero no modifica/desvincula referencias.
- Si además de la operación confirmada debe persistirse cada intento de restore fallido
  como historial durable. El diseño actual no deja una fila `LOGICALLY_RESTORED` al hacer
  rollback; el resultado se informa como error controlado sin falsear el commit.
- Método autoritativo para detectar un archivo externo físicamente ausente; hasta entonces
  solo se informa la metadata/referencia conservada y no se inspeccionan ni reconstruyen bytes.
- Respuesta observable al replay de un UUID de eliminación cuyo resultado histórico ya fue
  restaurado: nunca reejecutar la eliminación; definir si se responde conflicto o estado
  histórico restaurado.
- Los nombres exactos de las rutas L5 son una propuesta documental. La interfaz requiere
  nuevas claves ES/EN en recursos globales fuera del APPLICATION BOUNDARY; cualquier
  edición futura requiere autorización separada.
- No se aprobó política de corrección automática para fechas vencidas ni estados
  temporalmente inconsistentes; se conservan y se reportan para decisión si aparecen.

### D28. Resultado de Etapa 1 L5 — persistencia/ledger (2026-10-19)

- Se añadió `reverses_operation` a `TareaEliminacionOperacion` como FK self-referential
  nullable/PROTECT con unicidad y columna `reverses_operation_id`. El ID nuevo permanece
  en la PK común del ledger; el estado PENDING se registra con resultado vacío y solo el
  commit futuro podrá escribir `LOGICALLY_RESTORED`.
- `TareaEliminacionElemento` sigue siendo el manifiesto común. Las primitivas
  `create_restoration_pending` y `get_restoration_operation` validan el origen confirmado,
  empresa, backend, motivo, unicidad y conjunto exacto de IDs. Crear el registro no toca
  marcas lógicas, archivos, auditoría ni el guard de L2.
- El cambio de Django está en `tareas/migrations/0034_logical_restoration_ledger.py`.
  MYSQL_CONFIG tiene un contrato aditivo separado y preview de solo lectura. El DDL fue
  validado por tests; no se ejecutó. La migración solo se aplicó al test database aislado.
- La consulta genérica MySQL de L2 mantiene su lista de columnas anterior para no exigir
  el nuevo campo a la ruta SQL-direct antes de la evolución L5. Django requiere que la
  migración corresponda al alias `BASE_TAREAS` antes de usar el campo.
- L2/L3/L4 mantienen sus resultados y guards; el rechazo L2 de cualquier operación
  histórica por raíz sigue intacto. La habilitación de ciclos, confirmación
  `COMMITTED/LOGICALLY_RESTORED`, limpieza de marcas, auditoría y ajustes L4 no se
  implementaron.

**Validación aislada**:

- Pruebas focalizadas combinadas de persistencia/schema L5 y regresiones L2/L3/L4:
  **163 PASS, 0 FAIL, 0 SKIP**.
- `python manage.py check --settings=AppDocs.settings_test`: sin problemas.
- `python manage.py makemigrations --check --dry-run --settings=AppDocs.settings_test`:
  no se detectaron cambios adicionales.
- El test de carrera en SQLite aislada obtuvo un solo vínculo de restauración para dos
  registros concurrentes. Es prueba de concurrencia SQLite, no certifica MariaDB.
- La capa MYSQL_CONFIG se probó con conexiones/cursors simulados; no hubo conexión,
  escritura ni DDL en MySQL real. La instalación operativa y la concurrencia MariaDB
  siguen pendientes.
- El preflight informa la versión configurada, pero esta ejecución no certificó una
  versión física soportada ni la aplicación de `CHECK`; las validaciones de aplicación
  siguen siendo la autoridad.

## Unresolved by design

- P1: contrato y elegibilidad de Local, `LEGACY API PENDIENTE`.
- P2: integración del maestro local de Proveedor con ERP: lookup, validación, identificador
  legacy, conciliación, sincronización y actualización.
- Fase 2H.1 física: su objetivo quedó obsoleto funcionalmente por D24; el código WIP
  permanece sin autorización de ejecución y no se considera una vía de borrado vigente.
- Fase L1: implementada según D25; cualquier evolución de esquema en BASE_TAREAS real
  requiere autorización y ejecución separadas.
- L2 y L3: implementadas y evaluadas mediante el gate correctivo del 2026-10-18;
  el estado vigente y sus limitaciones se registran abajo.
- L4: consulta historica implementada en solo lectura. L5 Etapa 1 (ledger) y Etapa 2
  (preview, servicio transaccional interno y auditoría post-commit) están implementadas y
  probadas en SQLite aislada y con fixtures sintéticas en MariaDB de desarrollo. HTTP,
  proyección L4 y ciclos siguen pendientes; T16 commit incierto permanece sin ejecutar.
  No hay ruta de restauración ni se modificaron datos productivos. L6 permanece pendiente.
- Habilitación del POST de restauración y de las nuevas claves globales: requiere aprobación
  del contrato L5 y autorización de implementación separada.
- Registro técnico inicial de la app en los tres archivos `AppDocs/*`: resuelto, autorizado,
  ejecutado, testeado y versionado. Cualquier modificación futura adicional requiere
  autorización expresa.

## Gate correctivo L2/L3 — 2026-10-18

- **H-L2-001 — resuelto en `tareas`**: si falta el usuario original y aún no existe
  evento central, la adaptación registra `user=None` y conserva el `actor_id` original
  en `meta`. Si el evento ya existe, la reconciliación lo consulta primero y compara
  sus campos de negocio, metadata y UUID; acepta que `user_id` haya quedado `NULL`
  por `SET_NULL` sin reescribir ni recalcular el hash existente. No se sustituye al
  actor ni se modifica la API central.
- **H-L3-001 — resuelto en `tareas`**: los lectores Django y MYSQL_CONFIG excluyen
  raíces y descendientes eliminados del preview operacional. Un árbol inconsistente
  queda bloqueado con una respuesta genérica que no distingue descendientes eliminados,
  inexistentes o fuera de empresa ni presenta sus datos.
- **H-L3-002 — resuelto en `tareas`**: los QuerySets oficiales rechazan `update`,
  `bulk_update` y `bulk_create` que alteren campos protegidos. La marca operativa
  continúa escribiéndose únicamente desde el servicio L2; su adaptador SQL es una
  excepción interna acotada, no una garantía contra SQL deliberado.
- **Resultado de código**: L2 GO y L3 GO según pruebas aisladas; no se ejecutó ni se
  certificó un backend MariaDB físico en esta remediación. Las tres pruebas opt-in de
  MariaDB quedaron omitidas por falta de una instancia local aislada configurada.
- L4 se completo dentro de la autorizacion especifica del 2026-10-19. La integracion
  SYSTEM/CORE queda limitada a la Vista, el enlace `tasks_deleted` y las claves de idioma
  descritas en D26; no se concedieron permisos a usuarios.
