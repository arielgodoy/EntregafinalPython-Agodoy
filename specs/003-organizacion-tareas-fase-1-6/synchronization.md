# Sincronizacion de la SPEC MAESTRA con Fase 1.6

## Internacionalización autorizada — 2026-11-10

La plantilla compartida de Proveedores y Locales conserva claves dinámicas por
reutilización, pero el conjunto está registrado explícitamente en
`tareas.views` y cubierto por paridad `sp`/`en` en `tareas/tests/test_i18n.py`.
Las 26 claves `tareas.master_catalog.common.*`, `provider.*` y `local.*`
fueron agregadas únicamente a los dos catálogos globales autorizados. Esto
resuelve la cobertura i18n de la pantalla sin modificar el motor, vendor,
themes ni navegación; G05 continúa abierto para el bootstrap VICMEAS.

## Sincronización de implementación CRUD — 2026-11-10

Las superficies HTTP de los tres maestros ahora viven exclusivamente en
`tareas`. Proveedores y Locales tienen listado company-scoped/seguro según su
contrato, detalles controlados y rutas mutantes preparadas; Departamentos tiene
listado, detalle y rutas de ciclo de vida protegidas. Los gates G17, G18 y
G19/T201 mantienen las mutaciones bloqueadas y los controles visuales
deshabilitados. Las nuevas claves de traducción fueron agregadas con
autorización específica; G05 continúa abierto únicamente para el
registro/navegación VICMEAS y no se cierra por la paridad i18n.

## Sincronización postauditoría — 2026-11-10

Las decisiones A/B/C del propietario quedan reflejadas así:

1. Las 39 claves de Departamentos se mantienen en ambos catálogos globales,
   sin alterar el motor i18n, navegación ni vendor.
2. Las identidades VICMEAS se preparan mediante un management command explícito
   de `tareas`; la inspección no escribe y la aplicación requiere `--apply`.
   No se asignan permisos, no se crean Empresas y no se ejecuta durante HTTP,
   importación, `ready()` o señales.
3. La recuperación de operaciones usa únicamente evidencia durable de T229.
   `COMMITTED` es recuperable; `PENDING`/`UNKNOWN`, ausencia y contradicción
   quedan en revisión manual. No se cierra ninguna puerta de certificación.

Los cambios de código y pruebas están limitados a `tareas/` y a las dos
traducciones expresamente autorizadas. La certificación MariaDB y la eventual
ejecución del bootstrap permanecen pendientes.

## Rectificación arquitectónica — 2026-11-09

La correspondencia distingue ahora dos capas: DDL y servicios SQL target en
`tareas` sobre `BASE_TAREAS`, que pueden avanzar sin APIs owner; y transición,
adaptación de callers, desactivación de writers antiguos e integración de
membresías, que permanecen condicionadas por G17/G18/G19. No se introducen ORM,
migraciones Django, routers ni una segunda fuente autoritativa.

La actualización del 2026-11-09 agrega F16-FR34/F16-FR35/F16-FR36: autonomía
de `tareas`, validación Python interna de RUT y registro técnico durable de
operaciones. T216 queda cerrada como decisión documental; su implementación,
certificación y reconciliación permanecen pendientes.

Decisiones de identidad sincronizadas el 2026-11-10:
`Proveedores - Maestro` para Proveedores y `Tareas - Maestro de locales` para
Locales. La identidad de Departamentos permanece `Tareas - Maestro de
departamentos`. Estas decisiones no crean Vistas, permisos ni navegación y no
cierran G05, G17 ni G18.

Fecha: 2026-10-30. Baseline documental: rama `main`, HEAD
`196658dfb4d77b3942bde1603e1affa00fc112d2`, diez documentos complementarios
sin seguimiento y respaldo SQLite preexistente, no abierto ni modificado.
**Resultado: SI, CON CONDICIONES**. Esto sincroniza documentos; no activa membresias,
ejecuta tareas ni certifica una implementacion. SYNC-C01 sigue pendiente.

**Actualizacion 2026-11-03**: se aprueba la arquitectura C para que los maestros
Proveedor/Local/Departamento tengan su fuente autoritativa en el rol configurable
`BASE_TAREAS`; toda nueva implementacion funcional queda en `tareas`. Esta decision
actualiza solo Fase 1.6; no modifica la SPEC MAESTRA, CORE ni los modelos/servicios
existentes de `proveedores`/`organizacion`. El baseline anterior conserva valor
historico, no es la topologia objetivo ni certifica los datos actuales.

## Autoridad y lectura conjunta

La [SPEC MAESTRA](../001-tareas-internas/spec.md) gobierna el dominio general de
tareas. La [SPEC Fase 1.6](spec.md) gobierna membresias e integracion organizacional.
FR-P06 reconoce expresamente Opcion B y remite al detalle especializado.
La decision C de 2026-11-03 modifica la persistencia objetivo de los maestros en
003, no los contratos de la SPEC MAESTRA. 003 no sustituye 001 por numeracion ni
autoriza reabrir funciones implementadas.

La matriz siguiente relaciona contratos; [traceability.md](traceability.md)
mantiene la cobertura completa requisito -> decision -> owner -> tarea -> escenario.
Los [contratos de organizacion](contracts/organizacion.md),
[tareas](contracts/tareas.md) y [consistencia](contracts/consistencia.md) especifican
las interfaces futuras, distinguiendolas de APIs existentes.
Los IDs y checkboxes de [tasks maestra](../001-tareas-internas/tasks.md) se
conservan. Las 61 tareas T170-T230 de esta fase no reemplazan ni duplican las
tareas de la maestra.

## Matriz de correspondencia

Estado sincronizado significa coherencia/enlace documental, no implementacion.
Las cinco relaciones utilizadas son Complementa, Restringe, Depende de, No afecta
y Contradiccion pendiente; esta ultima se muestra con su rotulo solicitado.

| Contrato maestro | Contrato Fase 1.6 | Relación | Estado | Acción documental |
|---|---|---|---|---|
| FR-A03/FR-A07; T092/T093 | F16-FR01/F16-FR23 | Complementa | Target BASE_TAREAS; no migrado | Nueva superficie/orquestacion Tareas; APIs publicas o bloqueos G17-G19; IDs sin FK cross-database |
| FR-D05/FR-D06 | F16-FR02 | Complementa | Membresias nuevas | Mantener modelo/triple unica en organizacion, no en participantes |
| FR-D06 | F16-FR03 | Complementa | Precision aprobada | Maximo un JEFE; no obligatoriedad ni warning por vacancia; separar SUPERVISOR de S |
| FR-D06; registro de cambios de dominio | F16-FR04 | Complementa | T176/T179 historicamente completadas; migraciones no aplicadas | Referir historia al owner organizacion, no confundirla con auditoria/proyeccion multi-base |
| FR-D06 | F16-FR05 | Complementa | Sustitucion aprobada | Conservar resolucion explicita SUPERVISOR/STAFF/BAJA y motivo; sin reasignacion de tareas |
| FR-P02; convenciones de vistas | F16-FR06 | Depende de | Nombre aprobado; superficie no implementada | Registrar `Tareas - Maestro de departamentos`, ICMEAS y G05; no declararla ACTIVE |
| FR-P01/FR-P02 y nuevo FR-P06 | F16-FR07 | Restringe | Opcion B reconocida, no activada | Misma Empresa, cualquier Departamento efectivo, tres ambitos; no Local -> Departamento |
| FR-D12/FR-D14; permisos de cada familia | F16-FR08 | Restringe | Condiciones acumulativas | No sustituir usuario/acceso/VICMEAS/rol/estado por membresia o liderazgo |
| FR-P03; FR-T02/FR-T07/FR-T08; lectura L4 | F16-FR09 | No afecta | Lectura autorizada preservada | No exigir membresia a lectura/cursor/login ni a administracion inicial organizacional |
| FR-D05; participantes/responsables existentes | F16-FR10 | Complementa | Lista de revision futura | Traslado no reasigna; conservar asignaciones y revisar tareas abiertas |
| FR-D05/FR-D08/FR-D11 | F16-FR11 | Restringe | Suspension operativa futura | No borrar participantes, responsables, supervisores ni historial; eventos G04 |
| FR-D12; condiciones vigentes por operacion | F16-FR12 | Complementa | Recuperacion futura | Reevaluar condiciones; no revertir sustituciones; eventos G04 |
| FR-A03; FR-E02 | F16-FR13 | Complementa | Baja coordinada futura; G07 | Revision/bloqueos/traslado misma Empresa; cerradas conservadas |
| FR-E01 a FR-E14; FR-C; FR-R; L5 | F16-FR14 | No afecta | Jerarquia/lifecycle preservados | No cambiar padre-hija-nieta, flags, XOR, cierres ni restauracion para facilitar bajas |
| FR-A03; historial y asignaciones | F16-FR15 | Complementa | Reactivacion futura | No levantar decisiones independientes de BAJA/SUSPENDIDA ni restaurar asignaciones sustituidas |
| FR-D08 a FR-D17; T025-T027 | F16-FR16 | Complementa | Individual ordinario preservado | Enlazar regularizacion con motivo; saliente inelegible reemplazable; G03 acota roles |
| FR-D03/FR-D04; asignacion/clonacion | F16-FR17 | Complementa | Lote nuevo, no clonacion | Separar operaciones; una Empresa/origen/destino/rol y seleccion expresa |
| FR-D12/FR-D14 y contratos de gestion | F16-FR18 | Complementa | Preview futuro | Validacion detallada de solo lectura; ningun efecto de dominio |
| FR-P01/FR-P02; autorizacion por tarea | F16-FR19 | Depende de | Confirmacion futura | Revalidar backend/contexto/permiso, no confiar en preview |
| Atomicidad individual de participantes; BASE_TAREAS | F16-FR20 | Complementa | Nueva atomicidad de lote | No encadenar commits individuales ni prometer rollback entre servidores |
| FR-D17; historial; auditoria existente | F16-FR21 | Complementa | Ledger futuro | Detalle por tarea/rol y UUID comun; conservar identidades y eventos previos |
| FR-K01 a FR-K04; T053/T054 | F16-FR22 | Depende de | APIs existentes; integracion futura | Entrega solo postcommit, nada en rollback; no declarar fallo tardio como rollback |
| Contrato connection-roles; inventario de conexiones | F16-FR23 | Depende de | Objetivo C; configuracion no verificada | Tareas reutiliza su resolver; BASE_TAREAS no alias fijo; IDs/DTOs sin FK/JOIN cross-storage |
| Locks operacionales y reglas de cada backend | F16-FR24 | Complementa | G01/G07 sin certificar | Fence y coordinacion sin 2PC; bloquear backend no certificado |
| FR-D17; API de auditoria central | F16-FR25 | Depende de | G02: soporte organizacion en worktree, no certificado con BASE_TAREAS | Separar historia organizacional, evidencia operacional y proyeccion central |
| Datos historicos y tareas sin ambito | F16-FR26 | No afecta | Rollout condicionado por G08 | No inferir membresias ni backfill; altas autorizadas antes de activar gate |
| Respuestas controladas; replay operacional | F16-FR27 | Complementa | G09 tecnico | Resolver commit incierto, no duplicar mutacion ni prometer exactly-once email |
| FR-K; FR-D17; FR-F48/FR-F51/FR-T13; FR-M04; T058 | F16-FR28 | Depende de | Canales preservados; G04 acotado | Mantener excepciones de MiniTarea/reunion/enlaces; no SMTP personal para eventos |
| FR-P02; layout y metadata vigentes | F16-FR29 | Depende de | G05 externo protegido | V separado de I, 403 oficial, data-key/modal; sin cambiar servicios ni vendor |
| Plan/quickstart/regresion maestra | F16-FR30 | Complementa | Pruebas futuras | Enlazar 42 escenarios; no registrar tests ejecutados ni reabrir tareas historicas |
| Proveedores/Proveedor | F16-FR31 | Complementa | Global; DDL/servicios SQL en Tareas; modelo existente preservado durante transición | RUT normalizado/único; G17 bloquea corte y writer paralelo |
| Organizacion/Local | F16-FR32 | Restringe | Por Empresa; DDL/servicios SQL en Tareas; modelo existente preservado durante transición | ERP protegido; G18 bloquea callers/corte; baja/reactivación T227 |
| Organizacion/Departamento | F16-FR33 | Complementa | Por Empresa; DDL/servicios SQL en Tareas; modelo existente preservado durante transición | G19 bloquea integración CRUD owner/membresías/lifecycle y corte; T183/T201/G07 |
| Hitos/MiniTareas, avances, cierre/evidencia, comentarios, documentos, reuniones, cotizaciones, TO-DO, similitud y dashboard | FR-P06 y F16-FR07 a F16-FR09 | No afecta | Contratos de familia preservados | Solo elegibilidad en operaciones pertinentes; no gate global a lectura ni a entidades ajenas |
| Orden conceptual individual -> masiva | T200 depende de T199 | Contradicción pendiente | SYNC-C01, bloque localizado | Conservar dependencia; requerir ajuste autorizado antes de ejecutar ese bloque |

## Dependencias SYSTEM, owners preservados y superficies protegidas

Toda fila es **fuera del alcance de implementacion de tareas** respecto de cambios
al proveedor. Consumir una interfaz existente no autoriza modificarla.
No se introducen tareas para alterar SYSTEM bajo permiso de implementar tareas.

| Owner / contrato | Interfaz pública existente | Capacidad faltante o limite | Requiere autorización externa | Bloque afectado |
|---|---|---|---|---|
| access_control: empresa/VICMEAS | `get_valid_users_for_empresa`, `user_has_permission_for_empresa`, decorator/mixin oficiales | Membresia es dominio organizacion, no nuevo flag ni permiso; registro de la nueva Vista no verificado en DB | Cualquier registro/cambio global; no cambiar semantica V/I/S | T180-T186, G05; T188-T190 solo consumen helpers |
| acounts: autenticacion/sesiones | Sesion Django, usuario autenticado, `session['empresa_id']` y flujo Recuérdame existente | Ninguna nueva capacidad solicitada | Cualquier cambio queda fuera; no necesario para el bloque inicial | F16-FR08/F16-FR09: consumir contexto; cero cambios de login/cookies |
| auditoria | API central existente y soporte G02 local para organizacion | No se acredita migracion persistente ni atomicidad con BASE_TAREAS; Proveedores no tiene capacidad central identificada. T216 define proyeccion/reconciliacion | Si requiere CORE, tarea/autorizacion separada; no shadow audit | G02/T216; T176 historica no certifica writers BASE_TAREAS |
| notificaciones | `create_notification`; tareas usa `emit_task_event`/`notify_task_event` | G04: destinatarios/canales de eventos organizacionales no completos; no falta de API generica | Si se necesitara modificar proveedor; decision G04 es funcional distinta | T171/T192; T204 integra eventos de tareas postcommit |
| acounts: correo automatico | `send_email_for_purpose(empresa, purpose='notifications', ...)`; configuracion efectiva CompanyConfig/SystemConfig | No cambiar SMTP ni interpretar `email_enabled` como opt-out automatico | Toda alteracion de infraestructura de correo, fuera de este alcance | T192/T204; mantener T054 y excepciones de familia |
| settings: correo manual de perfil | `send_email_message(prefs, message)` y UserPreferences | No sirve como sustituto de correo automatico; no todo click implica correo personal | Cualquier cambio de servicio/perfil, no solicitado | Ninguna tarea F16 autoriza editar este servicio |
| settings/api/database_manager: conexiones/router | Contratos/APIs MySQL publicas; resolver existente de tareas | T213 documenta el resolver existente; certificar G01/G06/G07; sin FK remota ni fallback a default | Si falta capacidad SYSTEM, abrir dependencia separada; no resolver desde tareas | T213-T217,T225-T226; no cambiar router |
| proveedores/organizacion/tareas | APIs publicas existentes enumeradas en contracts/tareas.md | Proveedores/Locales carecen de APIs publicas; Departamento solo tiene lecturas/membresias parciales; no importar ORM ni crear APIs en los owners bajo este scope | Autorizacion separada si se requiere API/cambio en un owner | G17-G19; T218-T220,T224 |
| proveedores: Proveedor | CRUD actual por vistas con ORM directo; sin API de servicio publica identificada | G17: Tareas no lee/escribe el modelo; cortar el writer previo requiere dependencia autorizada | Separada, si se requiere API/corte en owner | T215,T218,T221,T224,T226 bloqueadas por G17 |
| organizacion: Local | Modelo existente; sin API publica de lectura/CRUD identificada | G18: no importar modelo/ORM ni modificar su admin/services | Separada, si se requiere API o exportacion | T215,T219,T222,T224,T227 bloqueadas por G18 |
| organizacion: Departamento/membresias | Consultas y `change_membership` publicas existentes; no API publica confirmada para create/update/head/lifecycle | G19: T212/T182/T183/T201 solo pueden orquestar APIs ya publicas | Separada antes de agregar una API owner; no workaround desde Tareas | T181-T184,T201,T212,T220,T223 bloqueadas en funciones faltantes |
| Navegacion/i18n/layout | Metadata y convenciones existentes; layout/modal reutilizables | Una identidad por maestro; Proveedor/Departamento conservan literal; identidad exacta de Local pendiente; registro y claves requieren autorizacion | Si, G05; paths globales/catalogos no editados | T185 documenta/obtiene autorizacion; T221-T223 consumen el gate |
| Configuracion y restantes CORE/SUPPORT | Contratos actuales; identidad/configuracion de sus owners | Ninguna reforma autorizada | Cualquier cambio exige scope separado | No cambiar `.env`, settings, router, middleware, auth, Docker/Nginx ni apps ajenas |

## Condiciones pendientes separadas

- **Funcionales**: G03 solo para roles historicos sin contrato publico de sustitucion;
  G04 solo para audiencia/canal organizacional aun no especificados. No reabrir Opcion B.
- **Tecnicas**: G01 exclusion bajo concurrencia/perdida de conexion; G06 esquema remoto;
  G07 baja multi-base recuperable; G08 preparacion de membresias; G09 replay/efectos
  tardios. Son exigencias de implementacion/certificacion, no nuevas decisiones de negocio.
- **SYSTEM externas**: G02 permanece abierto para auditoria/proyeccion multi-base y
  Proveedores; el soporte de organizacion en el worktree no certifica BASE_TAREAS.
  G05 cubre el registro/navegacion/i18n de las tres pantallas. Toda capacidad CORE
  nueva requiere autorizacion propia.
- **Owners APPLICATION preservados**: G17-G19 bloquean la funcionalidad nueva cuando
  faltan APIs publicas. No se modifican `proveedores`/`organizacion`, no se deshabilita
  su codigo existente desde Tareas y no se habilita un writer paralelo.
- **Documentales**: SYNC-C01 identifica T200 -> T199 frente al orden conceptual
  individual -> masiva solicitado. La prohibicion de eliminar dependencias impide
  invertirla silenciosamente. Antes del bloque T199/T200, autorizar y documentar un
  ajuste acotado de secuencia/nucleo compartido sin duplicar logica, ampliar roles ni
  debilitar atomicidad; conservar IDs/estados y probar ambos flujos.
- **Historicas ajenas**: G10 y textos de fases anteriores (estados/flags, restauracion,
  viejas notas de notificaciones, ID FR-T02 repetido) no se corrigen ni se usan para
  autorizar cambios. Las precisiones de maestros/P1 de esta entrega son localizadas.

## Evidencia historica y primer bloque de transicion

Cadena historica: **T170 -> T172 -> T173 -> T174 -> T175**. La evidencia existente
de esta cadena y T176/T177 cubre el diseno previo de organizacion/default; no
certifica la nueva persistencia de maestros en BASE_TAREAS.

Cadena de transicion documental: **T213 -> T214**, seguida por T216/T217/T227 y
resolucion de G17-G19 antes de habilitar operaciones. T215 requiere APIs publicas
de exportacion autorizadas e inventario persistente antes de migrar; T225/T226 son
gates antes del corte. Ninguna tarea autoriza por si sola modificar apps externas,
CORE ni consultar bases reales.

| Tarea historica completada | Archivo tocado historicamente / dependencia | Resultado ya documentado; no es scope de esta rectificacion |
|---|---|---|
| T170 | research de esta fase; ninguna | Baseline historico; no certifica BASE_TAREAS |
| T172 | `organizacion/tests/test_memberships.py`; T170 | Pruebas originales de triple, Empresa, vigencia e historia |
| T173 | `organizacion/models.py`; T172 | Entidades historicas de membresia/eventos/coordinacion; no se reabren |
| T174 | `organizacion/migrations/`; T173 | Migracion historica; no autoriza nuevas migraciones en esta rectificacion |
| T175 | `organizacion/services/memberships.py`; T174 | Consultas publicas historicas; solo las APIs ya existentes pueden ser consumidas desde Tareas |

Las pruebas de `organizacion.tests.test_memberships` y `python manage.py check`
pertenecen al historial T172-T179; no se ejecutan ni modifican en esta rectificacion.
Las nuevas pruebas de integracion de las pantallas/API consumidas deben residir en
`tareas/tests/` y quedan condicionadas a T225 y a APIs publicas disponibles.

Riesgos: constraints/aislamiento, compatibilidad del esquema, integridad de historia
y usuarios previos sin membresia. No activar FR-P06, correr migraciones reales,
cargar usuarios, tocar SYSTEM ni adelantar T176 al completar este bloque.
La autorizacion actual es solo documental; la implementacion necesita autorizacion
expresa adicional limitada a esos paths y pruebas aisladas.

## Validacion de la sincronizacion

Controles documentales: conservar todos los FR maestros previos y checkboxes,
agregar solo FR-P06 en 001; 36 F16-FR, 61 tareas totales, 42 escenarios; enlaces locales,
dependencias sin ciclos, CA presentes, diff completo y whitespace. Ninguna prueba
de software, check Django, migracion o acceso a bases se ejecuta en esta entrega.

El estado esperado de la sincronizacion previa admite Markdown modificado bajo 001
y documentos de 003. Esta actualizacion se limita a `specs/003-organizacion-tareas-fase-1-6/`;
no se edita la maestra ni se altera la rama, HEAD o index. Los cambios locales de
implementacion se preservan y ninguna base persistente se consulta.
