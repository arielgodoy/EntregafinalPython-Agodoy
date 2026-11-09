# Tasks: Fase 1.6 organizacion + tareas

**Estado**: 61 tareas; 11 completadas (T170, T172-T180 y T216 documental) y 50 pendientes. T179 queda cerrada documentalmente con observaciones; esto no habilita el despliegue productivo ni certifica BASE_TAREAS.
**Entrada**: [plan](plan.md), [spec](spec.md), [data-model](data-model.md),
[contratos](contracts/consistencia.md), [matriz](traceability.md).
Los paths son relativos a la raiz del repositorio; archivos nuevos son propuestas.
Cada tarea requiere autorizacion futura de su owner; no autoriza modificar CORE
por dependencia. Tests aqui descritos se ejecutaran solo en bases temporales.
Formato: checkbox, ID nuevo T170-T227, historia cuando aplica, path, dependencia
explicita y criterio de aceptacion (CA). Todos los gates citados estan en research.

## Preparacion y prerrequisitos

**Plan complementario sincronizado**: [tasks de la maestra](../001-tareas-internas/tasks.md)
conserva sus IDs, dependencias y checkboxes. T170-T227 no reemplazan T092/T093,
asignacion/clonacion, T053/T054 ni L4/L5. Las relaciones por requisito/escenario
y los bloqueos externos se consultan en [synchronization.md](synchronization.md).
No se habilita modificar SYSTEM desde ninguna de estas tareas.

La arquitectura objetivo conserva `BASE_TAREAS`; todo DDL, servicio SQL, interfaz
y nueva funcionalidad debe residir en `tareas`. Los modelos/servicios existentes
de `proveedores` y `organizacion` permanecen intactos. T176/T177 siguen
completadas históricamente en `default`; no certifican MySQL ni autorizan imports
privados. La ausencia de APIs owner no bloquea el DDL ni los servicios SQL nuevos,
pero sí bloquea transición, adaptación de callers y habilitación productiva hasta
cerrar los gates correspondientes. No habilitar baja departamental antes de
T201/G07.

- [x] T170 Contrastar HEAD, scope futuro y capacidades de backends en `specs/003-organizacion-tareas-fase-1-6/research.md`. Dep: ninguna. CA: autorizacion por owner registrada; baseline sin tocar DB; G01/G02/G05/G06/G07 tienen responsable y bloqueo explicito; no se intenta ejecutar setup que escriba fuera de scope.
- [ ] T171 Registrar resolucion de F16-G03/G04 en `specs/003-organizacion-tareas-fase-1-6/contracts/tareas.md`. Dep: T170. CA: politica expresa de sustitucion para roles no soportados y matriz de notificacion organizacional, sin volver a decidir Opcion B; si no hay decision, mantener bloqueadas solo esas funciones, no marcar tarea completa.

## Etapa 1 / US1: Organizacion

Objetivo: persistir/consultar membresias con historia, aislamiento y unicidad.
Prueba independiente: F16-AC01/03/04/05/07/08 sin depender de pantallas de tareas.

- [x] T172 [US1] Crear pruebas de membresia/maestros en `organizacion/tests/test_memberships.py`. Dep: T170. CA: casos sin relacion Local->Departamento, triple unica, multiples Empresas, suspension/baja e historia cubiertos; fixtures sin conexiones externas.
- [x] T173 [US1] Definir entidades aditivas de membresia, eventos y coordinacion en `organizacion/models.py`. Dep: T172. CA: modelo respeta data-model, constraints y PROTECT; cero cambios semanticos a Local/Departamento.
- [x] T174 [US1] Generar y revisar migracion aditiva en `organizacion/migrations/` tras T173. Dep: T173. CA: plan solo crea lo requerido, no backfill de membresias ni DDL de tareas/SYSTEM; aplicada unicamente en DB temporal de test.
- [x] T175 [US1] Implementar consultas publicas de Departamento/membresia/liderazgo en `organizacion/services/memberships.py`. Dep: T174. CA: DTO materializado, filtros de Empresa, elegibilidad efectiva, ausencia de JEFE sin warning e indisponibilidad distinguida de lista vacia.
- [x] T176 [US1] Implementar transiciones e historia idempotente en `organizacion/services/memberships.py`. Dep: T175 y cierre G02. CA: alta/suspension/baja/recuperacion con motivo/autor/UUID; cambio e historia atomicos; auditoria central consumida por contrato autorizado, sin shadow.
- [x] T177 [US1] Implementar fence/orden de locks en `organizacion/services/coordination.py` e integrarlo a cambios de membresia. Dep: T176. CA: serializa altas aun sin filas previas; cada writer participa; backend sin exclusion efectiva falla cerrado; no mutex solo de proceso.
- [x] T178 [US1] Registrar modelos nuevos read-only en `organizacion/admin.py`. Dep: T174. CA: cobertura administrativa, sin secretos, sin edicion masiva que evada servicios; no cambiar permisos de sistema.
- [x] T179 [US1] Completar tests de servicios/historia en `organizacion/tests/test_memberships.py` y `organizacion/tests/test_membership_concurrency.py`. Dep: T177,T178. CA: unicidad concurrente, rollback y replay demostrados; indicar diferencia entre tests temporales y certificacion fisica.

## Etapa 2 / US2: Administracion organizacional

Objetivo: superficie aprobada y sustitucion de JEFE autorizada.
Prueba independiente: F16-AC07/08/29; baja completa requiere T201.

- [x] T180 [US2] Escribir contrato de metadata/403 de maestro en `tareas/tests/test_department_views.py`. Dep: T175. CA: literal aprobado unico, acciones ICMEAS existentes, JEFE sin permiso rechazado, administracion inicial sin gate de membresia de tareas.
- [ ] T212 [US2] Orquestar en `tareas/services/department_catalog.py` la creacion/edicion de Departamento mediante APIs publicas. Dep: T177,T216,T217,T220,G02,G19. CA: codigo/Empresa/source y nombre segun F16-FR33; auth C/M y Empresa oficial; sin ORM/import privado/escritura directa ni modelo espejo; G02/G19 confirman auditoria/API publica y fuente unica. Si falta alguna, detener T212 y solicitar autorizacion independiente; no devolver exito ficticio ni agregar la API a `organizacion`.
- [ ] T181 [US2] Agregar formularios y superficie madre HTTP en `tareas/forms.py`, `tareas/views.py` y `tareas/urls.py`. Dep: T176,T180,T212,T220,G19. CA: empresa/actor desde sesion, mixin/decorator oficial, solo APIs publicas existentes, sin ORM directo ni Vista por boton; lecturas actuales en default no se presentan como catalogo target BASE_TAREAS; no fingir CRUD faltante.
- [ ] T182 [US2] Orquestar en `tareas/services/department_memberships.py` la sustitucion explicita de JEFE. Dep: T177,G19. CA: solo API publica atomica existente con resolucion del anterior y motivo; si no existe, bloquear y solicitar autorizacion separada; no encadenar dos `change_membership`, acceder al modelo organizacional ni alterar tareas.
- [ ] T183 [US2] Orquestar en `tareas/services/department_lifecycle.py` la preparacion/finalizacion/reversion y reactivacion departamental. Dep: T182,T212,T217,T220,G19. CA: operar solo mediante API publica; no acceder al modelo ni escribir Departamento; finalizacion requiere revision confiable y G07/T201; G19 bloquea baja/reactivacion si no existe API; no habilitar antes de T201/G07.
- [ ] T184 [US2] Preparar la pantalla madre de Departamentos en `tareas/templates/tareas/departamentos/` y JS propio bajo `tareas/static/tareas/js/`. Dep: T181,T183. CA: una identidad VICMEAS, modales Bootstrap, fetch/CSRF, data-key y respuestas controladas; controles de escritura deshabilitados si la API publica no existe; no habilitar baja/reactivacion antes de T201/G07; no tocar vendor.
- [ ] T185 [US2] Documentar dependencias de menu lateral/i18n en `specs/003-organizacion-tareas-fase-1-6/research.md`. Dep: T181,T184. CA: solo estas excepciones SYSTEM, paths exactos y autorizacion/revision especifica G05; no editar archivos globales en esta tarea ni ampliar la excepcion a otras apps/infraestructura; una identidad VICMEAS por maestro.
- [ ] T186 [US2] Validar capacidades disponibles y bloqueos en `tareas/tests/test_department_views.py`. Dep: T182,T184,T185,T223. CA: lecturas/membresias existentes y permisos cubiertos; I falso usa 403; sin warning por cero JEFE; APIs ausentes se reportan bloqueadas, no se simulan; baja no probada antes de T201/G07.

## Etapa 3 / US3: Integracion operativa

Objetivo: Opcion B en todas las operaciones pertinentes sin bloquear historia.
Prueba independiente: F16-AC01 a AC06, AC09 a AC12 y AC28.

- [ ] T187 [US3] Inventariar entradas operativas y de lectura en `specs/003-organizacion-tareas-fase-1-6/contracts/tareas.md`. Dep: T175. CA: paths/callers concretos de todas las familias de la tabla, incluidos commands/admin si existen; sin exigir membresia a lectura/login; no crear funcionalidades ausentes.
- [ ] T188 [US3] Crear adaptador de elegibilidad en `tareas/services/organization.py`. Dep: T175,T177,T187. CA: consume API publica con IDs/DTOs, cualquier Departamento efectivo de misma Empresa, errores controlados y sin cache de autorizacion obsoleta ni consultas privadas duplicadas.
- [ ] T189 [US3] Integrar gate y fence en creacion/asignacion/edicion/lifecycle en `tareas/services/task_storage.py`, `tareas/services/participant_storage.py` y `tareas/services/lifecycle.py` con sus adapters. Dep: T188. CA: actor y entrantes validados; saliente inelegible reemplazable; Base00/estados/roles existentes intactos; todos usan el mismo orden de locks.
- [ ] T190 [US3] Integrar operaciones restantes localizadas por T187 en `tareas/services/` y sus entradas en `tareas/views.py`/`tareas/forms.py`. Dep: T189. CA: hitos/MiniTareas/progreso/comentarios/documentos/reuniones/reprogramacion/cotizaciones/enlaces/TO-DO pertinentes cubiertos, sin alterar sus reglas particulares ni bloquear lectura/cursor.
- [ ] T191 [US3] Implementar lista de afectaciones en `tareas/services/organizational_impacts.py`. Dep: T188. CA: traslado/perdida distingue tareas abiertas y bloqueadas, explicitos/implicitos, no reasigna; reconstruible por consulta aunque falle notificacion; cero datos cross-company.
- [ ] T192 [US3] Integrar eventos de perdida/recuperacion/traslado en `tareas/services/organization.py` y `tareas/services/notifications.py`. Dep: T171,T190,T191. CA: matriz G04 aprobada, afectado notificado en recuperacion, sin SMTP personal ni restaurar asignaciones sustituidas ni alertar automaticamente por vacancia.
- [ ] T193 [US3] Verificar Opcion B y lectura en `tareas/tests/test_organizational_eligibility.py`. Dep: T190,T191,T192. CA: tres ambitos, membresia en otro Departamento misma Empresa, aislamiento entre Empresas y recuperacion automatica sin bypass de VICMEAS/estado.

## Etapa 4 / US4: Regularizacion

Objetivo: sustitucion individual y lote todo-o-nada con evidencia y efectos tardios.
Prueba independiente: F16-AC16 a AC27/33/34; G01/G03/G06 condicionan habilitacion.

- [ ] T194 [US4] Escribir casos de lote/preview/replay en `tareas/tests/test_organizational_regularization.py`. Dep: T188. CA: una tarea invalida, origen inelegible, reemplazante invalido, permisos revocados, motivo vacio, rol bloqueado y fallo intermedio especificados antes de implementar.
- [ ] T195 [US4] Definir ledger de regularizacion en `tareas/models.py`. Dep: T194. CA: UUID/manifiesto/detalle unico por tarea/rol, refs externas por identidad, no reutiliza ledger L5 ni borra historia.
- [ ] T196 [US4] Preparar migracion y extension SQL/preflight propios en `tareas/migrations/`, `tareas/sql/` y `tareas/services/base_tareas_schema.py`. Dep: T195. CA: evoluciona solo el schema de regularizacion de tareas; no sustituye la migracion de maestros T215; paridad Django/MySQL, sin DDL automatico real ni FK cross-database; G06 satisfecho.
- [ ] T197 [US4] Implementar validacion y preview en `tareas/services/regularization.py`. Dep: T191,T194. CA: todos los campos F16-FR18, exactitud de seleccion, permiso por tarea y cero escrituras; G03 bloquea roles sin contrato.
- [ ] T198 [US4] Extraer primitives transaccionales sin side effects en `tareas/services/participant_storage.py`. Dep: T189,T196,T197. CA: wrappers individuales mantienen comportamiento, primitives comparten conexion del caller y no confirman/notifican por tarea.
- [ ] T199 [US4] Implementar ejecutor masivo en `tareas/services/regularization_storage.py`. Dep: T177,T198 y certificacion G01. CA: una transaccion operacional, fence hasta commit, locks/validacion final, rollback de tareas y detalles, UUID estable; nunca fallback ni fragmentacion.
- [ ] T200 [US4] Integrar regularizacion individual en `tareas/services/regularization.py`. Dep: T199. CA: mismo nucleo con una tarea, justificacion siempre obligatoria para regularizacion, sin ampliar reglas del flujo ordinario de borrador.
- [ ] T201 [US4] Coordinar traslado de ambito y baja departamental desde `tareas/services/organizational_impacts.py`. Dep: T183,T189,T190,T191,T196 y cierre G07/G19. CA: transferencias solo por APIs/storage publicos autorizados; no escribir modelo de organizacion ni importar helpers privados; cero bloqueos/writers al finalizar, cerradas/jerarquia conservadas; si falta API publica de estado, marcar finalizacion bloqueada y no responder exito.
- [ ] T202 [US4] Implementar preview/confirmacion de regularizacion en `tareas/views.py`, `tareas/urls.py` y `tareas/templates/tareas/regularizacion/`. Dep: T184,T185,T197,T199,T200. CA: Vista Tareas/M y creador o S por tarea, firma/CSRF/modal, campos completos, errores sanitizados, ningun lote ejecutado desde GET.
- [ ] T203 [US4] Integrar auditoria central/reconciliacion en `tareas/services/audit.py` y `tareas/services/regularization.py`. Dep: T199. CA: evidencia operacional atomica; evento central por detalle via API publica, UUID/fingerprint, fallo postcommit visible sin repetir mutaciones; no modificar auditoria desde scope tareas.
- [ ] T204 [US4] Integrar notificaciones posteriores e idempotencia de replay en `tareas/services/notifications.py`. Dep: T199,T203. CA: cero eventos en rollback, dedupe por operacion/tarea/usuario/canal, CRITICA usa correo de sistema; entrega incierta no se declara exactamente-una-vez.
- [ ] T205 [US4] Completar tests backend/HTTP del bloque en `tareas/tests/test_organizational_regularization.py` y `tareas/tests/test_organizational_regularization_views.py`. Dep: T200,T201,T202,T203,T204. CA: todos los AC del bloque pasan en bases aisladas; commit incierto y reintento no duplican; roles G03 pendientes siguen explicitamente bloqueados.

## Etapa 5 / US5: Validacion de integracion

Objetivo: certificar exactamente las propiedades exigidas, no solo HTTP 200.
Prueba independiente: matriz completa, estado persistido y scope por owner.

- [ ] T206 [P] [US5] Probar aislamiento/paridad en `tareas/tests/test_organization_backend_parity.py`. Dep: T179,T193,T205. CA: `default` no contesta Data Plane ni conserva catalogos autoritativos duplicados; Empresa A no afecta B; sin FK/JOIN remoto, fallo de cualquier resolver sin fallback.
- [ ] T207 [P] [US5] Certificar desde `tareas/tests/test_organization_concurrency.py` el consumo concurrente de APIs existentes. Dep: T179,T193,T205. CA: dos conexiones/procesos y APIs publicas; no modificar tests/codigo de organizacion; T177 SQLite no certifica MySQL; G01/G07 solo cerrados con evidencia, no mocks.
- [ ] T208 [P] [US5] Probar preservacion historica en `tareas/tests/test_organization_history.py`. Dep: T179,T193,T205. CA: cerradas/lecturas/comentarios/eventos/jerarquia sin reinterpretacion; perdida de membresia no elimina vinculos; recuperacion no revierte sustituciones.
- [ ] T209 [US5] Ejecutar regresion focal/UI e i18n en `tareas/tests/` y `specs/003-organizacion-tareas-fase-1-6/quickstart.md`. Dep: T186,T206,T207,T208. CA: check y suites focales de Tareas, ambos idiomas, 403/visibilidad, vendor intacto; no modificar suites de otras apps; separar fallos previos sin corregir ajenos.
- [ ] T210 [US5] Preparar activacion/recuperacion en `specs/003-organizacion-tareas-fase-1-6/quickstart.md`. Dep: T193,T205,T209. CA: inventario de usuarios sin membresia y plan de altas autorizadas sin backfill inferido; esquema y backend certificados; procedimiento resultado incierto y rollback de despliegue sin borrar historia.
- [ ] T211 [US5] Cerrar matriz y gates en `specs/003-organizacion-tareas-fase-1-6/traceability.md`. Dep: T171,T185,T209,T210. CA: F16-FR01 a F16-FR33 con evidencia de prueba, 42 escenarios y pendientes explicitos; cero tareas declaradas completas sin evidencia, diff/check y scope verificados; ninguna promesa productiva sobre backend no certificado.

## Etapa 6 / US6: Maestros SQL, servicios y transición en tareas

Objetivo: crear en `tareas` el DDL SQL MySQL versionado, los servicios SQL, las
interfaces CRUD y la transición controlada de Proveedores, Locales y Departamentos
en `BASE_TAREAS`. No modificar modelos/servicios de otros owners, importar ORM
privado ni crear infraestructura paralela. La ausencia de API owner separa la
implementación SQL del gate de transición; ningún writer productivo se habilita
hasta cerrar fuente única, callers, auditoría y consistencia.

- [x] T213 [US6] Diseñar, versionar, instalar y verificar el DDL SQL de los tres maestros en `tareas/sql/base_tareas_maestros_v001.sql`, documentando el resolver existente y el alcance MySQL de `BASE_TAREAS` en `data-model.md`, `research.md` y `contracts/tareas.md`. Dep: T170. CA: tablas InnoDB con PK/IDs estables, columnas de los modelos actuales, UNIQUE e índices explícitos, sin FK cross-database, `USE`, credenciales ni DDL destructivo; preflight de `information_schema`, pruebas de unicidad/NULL/IDs/rollback y limpieza de datos de prueba completados exclusivamente en la base de desarrollo `tareas`; no se creó resolver, ni se modificó el instalador, router o CORE. G17-G19 y la transición permanecen pendientes.
- [ ] T214 [US6] Definir esquema SQL target, referencias estables y límite de acceso entre apps en `data-model.md`, `contracts/consistencia.md` y `contracts/tareas.md`. Dep: T213. CA: mapear columnas, PK, índices, unicidades, Empresa/Usuario/Proveedor/Local/Departamento y callers; no FK/JOIN cross-database, import ORM privado ni modelo ORM espejo; cualquier transformación de FK existente en otra app queda separada y requiere autorización.
- [ ] T215 [US6] Preparar DDL, preflight y plan/herramienta SQL de transición en `tareas/services/master_migration.py` y `tareas/sql/`. Dep: T214,T216,T217,T218,T219,T220,T224,T227. CA: DDL InnoDB versionado, preflight, preservación de IDs, dry-run, backup y reconciliación en entorno aislado; no modificar modelos fuente ni ejecutar corte (T226).
- [x] T216 [US6] Definir uso de auditoria/idempotencia/reconciliacion en `contracts/consistencia.md` y `research.md`. Dep: T213,T214. CA: diseño aprobado de registro técnico en `BASE_TAREAS`, UUID/hash/replay/estado de auditoría y reconciliación; consumir `AuditoriaService.log_event_idempotent()` sin modificar CORE ni crear una segunda auditoría. La implementación y certificación siguen pendientes; G02 permanece abierto.
- [ ] T217 [US6] Certificar el protocolo de concurrencia de Tareas para `BASE_TAREAS` en `tareas/tests/test_organization_concurrency.py`. Dep: T213,T214. CA: reutilizar locks existentes de Tareas y solo coordinacion publica disponible; no usar mutex/guard privado de organizacion; T177 SQLite no certifica MySQL; G01/G07 bloquean si no puede demostrarse exclusion.
- [ ] T218 [US6] Implementar en `tareas/services/providers.py` las operaciones SQL de Proveedores sobre `BASE_TAREAS`. Dep: T213,T214,T216,T217,T228,G02,G17. CA: global, sin Empresa, RUT normalizado/único mediante `tareas/utils/rut.py`, CRUD y baja lógica/reactivación transaccionales; no acceder al ORM de `proveedores`; mantener writer productivo bloqueado hasta T226.
- [ ] T219 [US6] Implementar en `tareas/services/locals.py` las operaciones SQL de Locales sobre `BASE_TAREAS`. Dep: T213,T214,T216,T217,T227,G02,G18. CA: por Empresa; ERP protegido y LOCAL editable; baja/reactivación con integridad/referencias; no acceder al ORM de `organizacion`; mantener writer productivo bloqueado hasta T226.
- [ ] T220 [US6] Implementar en `tareas/services/department_catalog.py` el catálogo SQL de Departamentos y su integración pública con membresías T176/T182. Dep: T213,T214,T216,T217,G02,G19. CA: lectura/escritura desde `BASE_TAREAS`, código/Empresa/source inmutables, nombre editable, membresías y JEFE por contrato; no importar modelos/helpers privados; lifecycle sigue T183/T201/G07.
- [ ] T221 [US6] Implementar pantalla modal/AJAX de Proveedores en `tareas/templates/tareas/proveedores/` y static propio. Dep: T185,T218,T230,G17. CA: identidad VICMEAS existente `Maestros - Proveedores`, ICMEAS por accion, Bootstrap/fetch/CSRF/i18n; no habilitar CRUD sin API y fuente unica verificadas.
- [ ] T222 [US6] Implementar pantalla modal/AJAX de Locales en `tareas/templates/tareas/locales/` y static propio. Dep: T185,T219,T227,G18. CA: identidad VICMEAS unica, Empresa desde sesion, ERP protegido, LOCAL editable; no habilitar operaciones sin API publica; baja/reactivacion solo tras T227.
- [ ] T223 [US6] Adaptar la pantalla T184 a APIs disponibles en `tareas/templates/tareas/departamentos/`. Dep: T184,T185,T212,T220,G19. CA: identidad `Tareas - Maestro de departamentos`; separar membresias disponibles de CRUD faltante; lecturas actuales no se presentan como catalogo target; codigo/Empresa/source y nombre segun contrato; no habilitar baja antes de T201/G07 ni mostrar botones sin endpoint funcional.
- [ ] T224 [US6] Adaptar consumidores existentes de Tareas al SQL de `BASE_TAREAS` en `tareas/`. Dep: T213,T214,T218,T219,T220,G17,G18,G19. CA: referencias por ID estable, sin imports ORM ni consultas a otras apps; callers antiguos se adaptan o se mantienen bloqueados y documentados; no fallback ni modelo ORM espejo.
- [ ] T225 [US6] Certificar en `tareas/tests/` el consumo de APIs y el rol en SQLite temporal/MySQL aislado. Dep: T212,T215,T216,T217,T218,T219,T220,T221,T222,T223,T224,T230,G02,G17,G18,G19. CA: no modificar tests de otras apps ni acceder a bases persistentes; APIs y fuente unica autorizadas, permisos/aislamiento/CRUD/replay/concurrencia; separar PASS/FAIL/BLOCKED y cerrar G06/G16 solo con evidencia.
- [ ] T226 [US6] Ejecutar desde `tareas/` el corte/recuperación autorizados de los tres maestros. Dep: T201,T210,T215,T225. CA: autorización expresa para fuente y entorno, inventario, preservación de IDs, adaptación de callers, desactivación autorizada de writers antiguos y fuente única demostradas; no modificar código de apps fuente desde esta tarea; G01/G02/G05/G06/G07/G17-G19/T201 cerrados antes de habilitar escrituras/bajas.
- [ ] T227 [US6] Definir en `contracts/organizacion.md` y `research.md` el gate de integridad de Locales. Dep: T214. CA: reglas de baja/reactivacion y campos editables ERP/LOCAL documentadas; su implementacion permanece en `tareas` y requiere API publica; no implementar ni exponer baja antes de aprobacion/G18.
- [x] T228 [US6] Implementar la utilidad Python interna de RUT en `tareas/utils/rut.py` y sus pruebas. Dep: T214,T216. CA: limpieza, normalización, módulo 11, `K`, DV `0`, vacío/nulo según contrato, formato canónico y ausencia de imports desde otras APPLICATION_APPS; la validación JavaScript no sustituye al servidor. Evidencia: `tareas/tests/test_rut.py`, 11 pruebas focalizadas PASS; `manage.py check` PASS con warning preexistente de CKEditor.
- [x] T229 [US6] Implementar el registro técnico SQL de operaciones en `tareas/sql/` y su storage transaccional. Dep: T216,T217. CA: DDL versionado solo para `BASE_TAREAS`, UUID/hash únicos, estados/replay/`UNKNOWN`, locks y resultado; preflight confirma `SELECT DATABASE() = 'tareas'`. Evidencia: manifiesto aplicado y verificado en InnoDB; 5 pruebas unitarias, 4 checks reales MariaDB y `manage.py check` PASS. La atomicidad con CRUD y la proyección de auditoría permanecen en T230.
- [ ] T230 [US6] Integrar mutaciones de maestros con idempotencia durable, proyección de auditoría y reconciliación en `tareas/services/`. Dep: T218,T219,T220,T229,G02. CA: mutación y registro en una transacción InnoDB; `AuditoriaService.log_event_idempotent()` posterior al commit; payload conflictivo, fallo parcial y commit incierto son respuestas controladas; no modificar `auditoria` ni crear auditoría paralela.

## Dependencias, paralelismo y entrega incremental

El campo Dep de cada tarea es normativo; una dependencia Gxx implica ademas cierre
del gate, no solo completar la tarea anterior. T199 exige una prueba de viabilidad
G01 antes de habilitar su ejecutor; T207 es la certificacion integrada final, no
una dependencia circular para poder escribir pruebas del ejecutor.

**SYNC-C01 pendiente**: la dependencia T200 -> T199 invierte el orden conceptual
individual -> masiva solicitado para el desarrollo. No se elimina ni se oculta
esa dependencia en esta sincronizacion; antes de ejecutar ese bloque se requiere
un ajuste autorizado del plan tecnico que conserve roles y todo-o-nada.
T170 y T172-T175 no dependen de T199/T200 ni de una modificacion SYSTEM.
G02 esta implementado en codigo para `organizacion` en el alcance local; esto no
certifica auditoria atomica con BASE_TAREAS ni resuelve la capacidad para
Proveedores. T216 queda cerrada solo como decisión documental; T230 sigue
pendiente de integración y certificación. T228 y T229 quedan certificadas en sus
alcances internos y no habilitan mutaciones productivas. G17-G19 documentan APIs de owners ausentes y bloquean
transición/corte, no el CRUD SQL interno de `tareas`;
no autorizan cambiar `proveedores`, `organizacion` o SYSTEM. T176, T177 y T178 estan implementadas y validadas en su alcance
historico sobre `default`; T176/T177 no certifican la nueva topologia. T179 se
valido con dictamen **B — APTO CON OBSERVACIONES** y se
cierra documentalmente; esto no confirma activacion persistente ni autoriza
despliegue productivo. Las migraciones `auditoria.0015` y
`organizacion.0003` siguen pendientes de aplicacion en bases persistentes.
T192 sigue bloqueada por T171/G04, T199 por G01, T201 por G07/G19 y T185 por
autorizacion externa G05. T213-T227 son nuevas tareas pendientes, no autorizacion
para inspeccionar datos productivos o modificar CORE. Los permisos de
implementacion de tareas no autorizan auditoria, navegacion, correo, notificaciones,
router o configuracion base.

**Validacion T179**: 146 pruebas integradas aprobadas y tres ejecuciones
independientes de 13 pruebas concurrentes aprobadas. Se usaron exclusivamente
bases SQLite temporales file-backed, con conexiones independientes y red
bloqueada. Estos resultados no certifican otros motores ni un entorno productivo.

**Observaciones T179 (no corregidas en esta fase)**:

- **O1 — Escrituras ORM directas**: los modelos no impiden por si mismos escrituras
  fuera del servicio coordinado. Todo nuevo escritor funcional debe consumir los
  servicios y el guard. No se autoriza modificar modelos para imponerlo.
- **O2 — Concurrencia SQLite**: el guard serializa escritores a nivel de base;
  otros motores no estan certificados y deben fallar cerrado.
- **O3 — Administracion tecnica de auditoria**: el Admin central es global y
  read-only; sus permisos deben reservarse a auditores tecnicos autorizados. No se
  verificaron asignaciones reales.
- **O4 — Migraciones pendientes**: `auditoria.0015` y `organizacion.0003` no se
  han aplicado a bases persistentes.

Grafo de historias: US1 -> US2/US3; US1+US3 -> US4; US2+US3+US4 -> US5;
T213/T214 -> DDL y servicios SQL target; G17-G19 bloquean transición, callers y
acciones de owner faltantes; migración/certificación/corte esperan sus gates.
La finalizacion departamental de US2 se completa en T201/US4, no se finge que es
independiente de tareas. T171 bloquea notificaciones completas/roles pendientes,
no el schema organizacional.

Paralelismo posible despues de prerrequisitos: T216/T217/T227 pueden documentar sus
contratos previos; T218-T220 pueden construir SQL aislado, pero no habilitan
writers productivos hasta cerrar G17-G19. T181 solo
expone operaciones con API existente; T183/T201 no finalizan baja sin T201/G07/G19.
No paralelizar tareas que editen el mismo servicio ni pruebas que compartan DB writable.

Secuencia documental: T213 -> T214; cerrar T216/T217/T227 y preparar T228-T230;
solo entonces avanzar T218-T224. Preflight/migracion T215 requiere APIs publicas y
fuente unica; T225 certifica; T226 corta. Si G17-G19 no se resuelven sin modificar
otra app, detener esa operacion y solicitar autorizacion separada. T201/G07 sigue
obligatorio antes de baja departamental. T176/T177 no se reabren ni se consideran
certificacion de esta topologia.
