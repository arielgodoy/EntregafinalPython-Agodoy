# Tasks: Fase 1.6 organizacion + tareas

**Estado**: 42 tareas de implementacion futura, ninguna ejecutada.
**Entrada**: [plan](plan.md), [spec](spec.md), [data-model](data-model.md),
[contratos](contracts/consistencia.md), [matriz](traceability.md).
Los paths son relativos a la raiz del repositorio; archivos nuevos son propuestas.
Cada tarea requiere autorizacion futura de su owner; no autoriza modificar CORE
por dependencia. Tests aqui descritos se ejecutaran solo en bases temporales.
Formato: checkbox, ID nuevo T170-T211, historia cuando aplica, path, dependencia
explicita y criterio de aceptacion (CA). Todos los gates citados estan en research.

## Preparacion y prerrequisitos

**Plan complementario sincronizado**: [tasks de la maestra](../001-tareas-internas/tasks.md)
conserva sus IDs, dependencias y checkboxes. T170-T211 no reemplazan T092/T093,
asignacion/clonacion, T053/T054 ni L4/L5. Las relaciones por requisito/escenario
y los bloqueos externos se consultan en [synchronization.md](synchronization.md).
No se habilita modificar SYSTEM desde ninguna de estas tareas.

- [x] T170 Contrastar HEAD, scope futuro y capacidades de backends en `specs/003-organizacion-tareas-fase-1-6/research.md`. Dep: ninguna. CA: autorizacion por owner registrada; baseline sin tocar DB; G01/G02/G05/G06/G07 tienen responsable y bloqueo explicito; no se intenta ejecutar setup que escriba fuera de scope.
- [ ] T171 Registrar resolucion de F16-G03/G04 en `specs/003-organizacion-tareas-fase-1-6/contracts/tareas.md`. Dep: T170. CA: politica expresa de sustitucion para roles no soportados y matriz de notificacion organizacional, sin volver a decidir Opcion B; si no hay decision, mantener bloqueadas solo esas funciones, no marcar tarea completa.

## Etapa 1 / US1: Organizacion

Objetivo: persistir/consultar membresias con historia, aislamiento y unicidad.
Prueba independiente: F16-AC01/03/04/05/07/08 sin depender de pantallas de tareas.

- [x] T172 [US1] Crear pruebas de membresia/maestros en `organizacion/tests/test_memberships.py`. Dep: T170. CA: casos sin relacion Local->Departamento, triple unica, multiples Empresas, suspension/baja e historia cubiertos; fixtures sin conexiones externas.
- [x] T173 [US1] Definir entidades aditivas de membresia, eventos y coordinacion en `organizacion/models.py`. Dep: T172. CA: modelo respeta data-model, constraints y PROTECT; cero cambios semanticos a Local/Departamento.
- [x] T174 [US1] Generar y revisar migracion aditiva en `organizacion/migrations/` tras T173. Dep: T173. CA: plan solo crea lo requerido, no backfill de membresias ni DDL de tareas/SYSTEM; aplicada unicamente en DB temporal de test.
- [x] T175 [US1] Implementar consultas publicas de Departamento/membresia/liderazgo en `organizacion/services/memberships.py`. Dep: T174. CA: DTO materializado, filtros de Empresa, elegibilidad efectiva, ausencia de JEFE sin warning e indisponibilidad distinguida de lista vacia.
- [ ] T176 [US1] Implementar transiciones e historia idempotente en `organizacion/services/memberships.py`. Dep: T175 y cierre G02. CA: alta/suspension/baja/recuperacion con motivo/autor/UUID; cambio e historia atomicos; auditoria central consumida por contrato autorizado, sin shadow.
- [ ] T177 [US1] Implementar fence/orden de locks en `organizacion/services/coordination.py` e integrarlo a cambios de membresia. Dep: T176. CA: serializa altas aun sin filas previas; cada writer participa; backend sin exclusion efectiva falla cerrado; no mutex solo de proceso.
- [ ] T178 [US1] Registrar modelos nuevos read-only en `organizacion/admin.py`. Dep: T174. CA: cobertura administrativa, sin secretos, sin edicion masiva que evada servicios; no cambiar permisos de sistema.
- [ ] T179 [US1] Completar tests de servicios/historia en `organizacion/tests/test_memberships.py` y `organizacion/tests/test_membership_concurrency.py`. Dep: T177,T178. CA: unicidad concurrente, rollback y replay demostrados; indicar diferencia entre tests temporales y certificacion fisica.

## Etapa 2 / US2: Administracion organizacional

Objetivo: superficie aprobada y sustitucion de JEFE autorizada.
Prueba independiente: F16-AC07/08/29; baja completa requiere T201.

- [ ] T180 [US2] Escribir contrato de metadata/403 de maestro en `tareas/tests/test_department_views.py`. Dep: T175. CA: literal aprobado unico, acciones ICMEAS existentes, JEFE sin permiso rechazado, administracion inicial sin gate de membresia de tareas.
- [ ] T181 [US2] Agregar formularios y superficie madre en `tareas/forms.py`, `tareas/views.py` y `tareas/urls.py`. Dep: T176,T180. CA: empresa/actor desde sesion, mixin/decorator oficial, servicios publicos de organizacion, sin guardar modelos directamente ni crear una Vista por boton.
- [ ] T182 [US2] Implementar sustitucion explicita de JEFE en `organizacion/services/memberships.py`. Dep: T177. CA: exige destino del anterior (SUPERVISOR/STAFF/BAJA) y motivo; dos eventos y cambio atomicos; ninguna participacion de tareas cambia.
- [ ] T183 [US2] Implementar preparacion/finalizacion/reversion tecnica segura y reactivacion departamental en `organizacion/services/departments.py`. Dep: T177,T182. CA: operacion reiniciable; finalizacion exige revision confiable bajo fence; no acepta un booleano enviado por navegador como ausencia de tareas; no importa tareas.
- [ ] T184 [US2] Preparar interfaz del maestro en `tareas/templates/tareas/departamentos/` y JS propio bajo `tareas/static/tareas/js/`. Dep: T181,T183. CA: layout existente, modal Bootstrap, CSRF, data-key; no habilitar finalizacion de baja hasta T201; no tocar vendor ni convertir POST ordinario innecesariamente.
- [ ] T185 [US2] Documentar y obtener autorizacion de dependencias de navegacion/registro/i18n en `specs/003-organizacion-tareas-fase-1-6/research.md`. Dep: T181,T184. CA: paths externos exactos identificados desde evidencia; tarea externa separada completa G05; sin catalogos paralelos ni Vistas duplicadas.
- [ ] T186 [US2] Validar CRUD/motivos/permisos/UI en `tareas/tests/test_department_views.py`. Dep: T182,T184,T185. CA: operaciones de membresia cubiertas; acceso I falso usa 403; sin warning por cero JEFE; no declarar probada baja final antes de T201.

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
- [ ] T196 [US4] Preparar migracion y extension SQL/preflight propios en `tareas/migrations/`, `tareas/sql/` y `tareas/services/base_tareas_schema.py`. Dep: T195. CA: evoluciona solo BASE_TAREAS, paridad Django/MySQL, sin DDL automatico real ni FK cross-database; G06 satisfecho.
- [ ] T197 [US4] Implementar validacion y preview en `tareas/services/regularization.py`. Dep: T191,T194. CA: todos los campos F16-FR18, exactitud de seleccion, permiso por tarea y cero escrituras; G03 bloquea roles sin contrato.
- [ ] T198 [US4] Extraer primitives transaccionales sin side effects en `tareas/services/participant_storage.py`. Dep: T189,T196,T197. CA: wrappers individuales mantienen comportamiento, primitives comparten conexion del caller y no confirman/notifican por tarea.
- [ ] T199 [US4] Implementar ejecutor masivo en `tareas/services/regularization_storage.py`. Dep: T177,T198 y certificacion G01. CA: una transaccion operacional, fence hasta commit, locks/validacion final, rollback de tareas y detalles, UUID estable; nunca fallback ni fragmentacion.
- [ ] T200 [US4] Integrar regularizacion individual en `tareas/services/regularization.py`. Dep: T199. CA: mismo nucleo con una tarea, justificacion siempre obligatoria para regularizacion, sin ampliar reglas del flujo ordinario de borrador.
- [ ] T201 [US4] Implementar baja coordinada/traslado de ambito en `tareas/services/organizational_impacts.py` y adapter propio de tareas. Dep: T183,T189,T190,T191,T196 y cierre G07. CA: cero bloqueos al finalizar, sin writers que reintroduzcan tareas, cerradas/jerarquia conservadas; fallo default posterior no declara rollback de transferencias ya confirmadas.
- [ ] T202 [US4] Implementar preview/confirmacion de regularizacion en `tareas/views.py`, `tareas/urls.py` y `tareas/templates/tareas/regularizacion/`. Dep: T184,T185,T197,T199,T200. CA: Vista Tareas/M y creador o S por tarea, firma/CSRF/modal, campos completos, errores sanitizados, ningun lote ejecutado desde GET.
- [ ] T203 [US4] Integrar auditoria central/reconciliacion en `tareas/services/audit.py` y `tareas/services/regularization.py`. Dep: T199. CA: evidencia operacional atomica; evento central por detalle via API publica, UUID/fingerprint, fallo postcommit visible sin repetir mutaciones; no modificar auditoria desde scope tareas.
- [ ] T204 [US4] Integrar notificaciones posteriores e idempotencia de replay en `tareas/services/notifications.py`. Dep: T199,T203. CA: cero eventos en rollback, dedupe por operacion/tarea/usuario/canal, CRITICA usa correo de sistema; entrega incierta no se declara exactamente-una-vez.
- [ ] T205 [US4] Completar tests backend/HTTP del bloque en `tareas/tests/test_organizational_regularization.py` y `tareas/tests/test_organizational_regularization_views.py`. Dep: T200,T201,T202,T203,T204. CA: todos los AC del bloque pasan en bases aisladas; commit incierto y reintento no duplican; roles G03 pendientes siguen explicitamente bloqueados.

## Etapa 5 / US5: Validacion de integracion

Objetivo: certificar exactamente las propiedades exigidas, no solo HTTP 200.
Prueba independiente: matriz completa, estado persistido y scope por owner.

- [ ] T206 [P] [US5] Probar aislamiento/paridad en `tareas/tests/test_organization_backend_parity.py`. Dep: T179,T193,T205. CA: default no contesta Data Plane remoto; Empresa A no afecta B; sin FK/JOIN remoto, fallo de resolver sin fallback.
- [ ] T207 [P] [US5] Certificar concurrencia con dos conexiones/procesos en `organizacion/tests/test_membership_concurrency.py` y `tareas/tests/test_organization_concurrency.py`. Dep: T179,T193,T205. CA: JEFE concurrente, membresia vs lote, permisos entre preview/confirmacion, baja vs nueva tarea y perdida de fence ensayados; G01/G07 solo cerrados con evidencia, no mocks.
- [ ] T208 [P] [US5] Probar preservacion historica en `tareas/tests/test_organization_history.py`. Dep: T179,T193,T205. CA: cerradas/lecturas/comentarios/eventos/jerarquia sin reinterpretacion; perdida de membresia no elimina vinculos; recuperacion no revierte sustituciones.
- [ ] T209 [US5] Ejecutar regresion focal/UI e i18n en `tareas/tests/`, `organizacion/tests/` y `specs/003-organizacion-tareas-fase-1-6/quickstart.md`. Dep: T186,T206,T207,T208. CA: check y suites focales, ambos idiomas, 403/visibilidad, vendor intacto; separar fallos previos de introducidos sin corregir ajenos.
- [ ] T210 [US5] Preparar activacion/recuperacion en `specs/003-organizacion-tareas-fase-1-6/quickstart.md`. Dep: T193,T205,T209. CA: inventario de usuarios sin membresia y plan de altas autorizadas sin backfill inferido; esquema y backend certificados; procedimiento resultado incierto y rollback de despliegue sin borrar historia.
- [ ] T211 [US5] Cerrar matriz y gates en `specs/003-organizacion-tareas-fase-1-6/traceability.md`. Dep: T171,T185,T209,T210. CA: cada FR con evidencia de prueba, pendientes explicitos, cero tareas declaradas completas sin evidencia, diff/check y scope verificados; ninguna promesa productiva sobre backend no certificado.

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
T176 sigue bloqueada por G02, T192 por T171/G04, T199 por G01, T201 por G07 y
T185 por autorizacion externa G05. Los permisos de implementacion de tareas no
autorizan auditoria, navegacion, correo, notificaciones, router o configuracion base.

Grafo de historias: US1 -> US2/US3; US1+US3 -> US4; US2+US3+US4 -> US5.
La finalizacion departamental de US2 se completa en T201/US4, no se finge que es
independiente de tareas. T171 bloquea notificaciones completas/roles pendientes,
no el schema organizacional.

Paralelismo posible despues de prerrequisitos: US1 T175 y T178 (archivos distintos);
US2 T180 y T182; US3 T191 mientras se integra T189; US4 T197 y T196;
US5 T206/T207/T208 en entornos aislados distintos. No paralelizar dos tareas que
editan el mismo servicio ni tests que compartan DB writable.

MVP recomendado: T170 y T172-T175 (persistencia/consulta), luego mutaciones US1
con G02 resuelto. No activar Opcion B ni interfaces de baja/lote parcialmente
implementadas. Este listado no marca como hechas T092/T093 de nuevo.
