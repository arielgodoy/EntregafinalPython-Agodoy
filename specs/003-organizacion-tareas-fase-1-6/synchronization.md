# Sincronizacion de la SPEC MAESTRA con Fase 1.6

Fecha: 2026-10-30. Baseline documental: rama `main`, HEAD
`196658dfb4d77b3942bde1603e1affa00fc112d2`, diez documentos complementarios
sin seguimiento y respaldo SQLite preexistente, no abierto ni modificado.
**Resultado: SI, CON CONDICIONES**. Esto sincroniza documentos; no activa membresias,
ejecuta tareas ni certifica una implementacion. SYNC-C01 sigue pendiente.

## Autoridad y lectura conjunta

La [SPEC MAESTRA](../001-tareas-internas/spec.md) gobierna el dominio general de
tareas. La [SPEC Fase 1.6](spec.md) gobierna membresias e integracion organizacional.
FR-P06 reconoce expresamente Opcion B y remite al detalle especializado.
003 no sustituye 001 por numeracion ni autoriza reabrir funciones implementadas.

La matriz siguiente relaciona contratos; [traceability.md](traceability.md)
mantiene la cobertura completa requisito -> decision -> owner -> tarea -> escenario.
Los [contratos de organizacion](contracts/organizacion.md),
[tareas](contracts/tareas.md) y [consistencia](contracts/consistencia.md) especifican
las interfaces futuras, distinguiendolas de APIs existentes.
Los IDs y checkboxes de [tasks maestra](../001-tareas-internas/tasks.md) y las
42 tareas [T170-T211](tasks.md) se conservan; no se duplican en ambos planes.

## Matriz de correspondencia

Estado sincronizado significa coherencia/enlace documental, no implementacion.
Las cinco relaciones utilizadas son Complementa, Restringe, Depende de, No afecta
y Contradiccion pendiente; esta ultima se muestra con su rotulo solicitado.

| Contrato maestro | Contrato Fase 1.6 | Relación | Estado | Acción documental |
|---|---|---|---|---|
| FR-A03/FR-A07; T092/T093 | F16-FR01 | Complementa | Maestros existentes; extension futura | Precisar estado canónico frente a ERP pendiente; enlazar data-model |
| FR-D05/FR-D06 | F16-FR02 | Complementa | Membresias nuevas | Mantener modelo/triple unica en organizacion, no en participantes |
| FR-D06 | F16-FR03 | Complementa | Precision aprobada | Maximo un JEFE; no obligatoriedad ni warning por vacancia; separar SUPERVISOR de S |
| FR-D06; registro de cambios de dominio | F16-FR04 | Complementa | Historia futura; G02 externo | Referir vigencia/historia al owner organizacion, no confundir con auditoria central |
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
| Contrato connection-roles; inventario de conexiones | F16-FR23 | Depende de | Topologia vigente preservada | default organizacion y BASE_TAREAS configurable; IDs/DTOs sin FK/JOIN cross-storage |
| Locks operacionales y reglas de cada backend | F16-FR24 | Complementa | G01/G07 sin certificar | Fence y coordinacion sin 2PC; bloquear backend no certificado |
| FR-D17; API de auditoria central | F16-FR25 | Depende de | G02: organizacion no registrada | Separar historia organizacional, evidencia operacional y proyeccion central |
| Datos historicos y tareas sin ambito | F16-FR26 | No afecta | Rollout condicionado por G08 | No inferir membresias ni backfill; altas autorizadas antes de activar gate |
| Respuestas controladas; replay operacional | F16-FR27 | Complementa | G09 tecnico | Resolver commit incierto, no duplicar mutacion ni prometer exactly-once email |
| FR-K; FR-D17; FR-F48/FR-F51/FR-T13; FR-M04; T058 | F16-FR28 | Depende de | Canales preservados; G04 acotado | Mantener excepciones de MiniTarea/reunion/enlaces; no SMTP personal para eventos |
| FR-P02; layout y metadata vigentes | F16-FR29 | Depende de | G05 externo protegido | V separado de I, 403 oficial, data-key/modal; sin cambiar servicios ni vendor |
| Plan/quickstart/regresion maestra | F16-FR30 | Complementa | Pruebas futuras | Enlazar 36 escenarios; no registrar tests ejecutados ni reabrir tareas historicas |
| Hitos/MiniTareas, avances, cierre/evidencia, comentarios, documentos, reuniones, cotizaciones, TO-DO, similitud y dashboard | FR-P06 y F16-FR07 a F16-FR09 | No afecta | Contratos de familia preservados | Solo elegibilidad en operaciones pertinentes; no gate global a lectura ni a entidades ajenas |
| Orden conceptual individual -> masiva | T200 depende de T199 | Contradicción pendiente | SYNC-C01, bloque localizado | Conservar dependencia; requerir ajuste autorizado antes de ejecutar ese bloque |

## Dependencias SYSTEM y superficies protegidas

Toda fila es **fuera del alcance de implementacion de tareas** respecto de cambios
al proveedor. Consumir una interfaz existente no autoriza modificarla.
No se introducen tareas para alterar SYSTEM bajo permiso de implementar tareas.

| Owner / contrato | Interfaz pública existente | Capacidad faltante o limite | Requiere autorización externa | Bloque afectado |
|---|---|---|---|---|
| access_control: empresa/VICMEAS | `get_valid_users_for_empresa`, `user_has_permission_for_empresa`, decorator/mixin oficiales | Membresia es dominio organizacion, no nuevo flag ni permiso; registro de la nueva Vista no verificado en DB | Cualquier registro/cambio global; no cambiar semantica V/I/S | T180-T186, G05; T188-T190 solo consumen helpers |
| acounts: autenticacion/sesiones | Sesion Django, usuario autenticado, `session['empresa_id']` y flujo Recuérdame existente | Ninguna nueva capacidad solicitada | Cualquier cambio queda fuera; no necesario para el bloque inicial | F16-FR08/F16-FR09: consumir contexto; cero cambios de login/cookies |
| auditoria | `AuditoriaService` y API idempotente para tareas | `APP_MODEL_MAP` no registra organizacion; `None` no acredita auditoria | Si, contrato/owner independiente; no shadow audit como sustituto | G02 bloquea T176 y dependientes; T203 usa API de tareas sin modificarla |
| notificaciones | `create_notification`; tareas usa `emit_task_event`/`notify_task_event` | G04: destinatarios/canales de eventos organizacionales no completos; no falta de API generica | Si se necesitara modificar proveedor; decision G04 es funcional distinta | T171/T192; T204 integra eventos de tareas postcommit |
| acounts: correo automatico | `send_email_for_purpose(empresa, purpose='notifications', ...)`; configuracion efectiva CompanyConfig/SystemConfig | No cambiar SMTP ni interpretar `email_enabled` como opt-out automatico | Toda alteracion de infraestructura de correo, fuera de este alcance | T192/T204; mantener T054 y excepciones de familia |
| settings: correo manual de perfil | `send_email_message(prefs, message)` y UserPreferences | No sirve como sustituto de correo automatico; no todo click implica correo personal | Cualquier cambio de servicio/perfil, no solicitado | Ninguna tarea F16 autoriza editar este servicio |
| settings/api/database_manager: conexiones/router | Contrato connection-roles y APIs MySQL publicas; resolver propio de tareas | Certificar G01/G06/G07; sin FK remota ni fallback a default, sin cambiar router | Si faltara capacidad SYSTEM, abrir dependencia separada, no resolver desde tareas | T170/T196/T199/T201/T206/T207 |
| Navegacion/i18n/layout | Metadata y convenciones existentes; layout/modal reutilizables | Registro, item y claves de la nueva vista requieren materializacion autorizada | Si, G05; paths globales y catalogos no editados | T185 documenta/obtiene autorizacion; no es una tarea de modificacion global |
| Configuracion y restantes CORE/SUPPORT | Contratos actuales; identidad/configuracion de sus owners | Ninguna reforma autorizada | Cualquier cambio exige scope separado | No cambiar `.env`, settings, router, middleware, auth, Docker/Nginx ni apps ajenas |

## Condiciones pendientes separadas

- **Funcionales**: G03 solo para roles historicos sin contrato publico de sustitucion;
  G04 solo para audiencia/canal organizacional aun no especificados. No reabrir Opcion B.
- **Tecnicas**: G01 exclusion bajo concurrencia/perdida de conexion; G06 esquema remoto;
  G07 baja multi-base recuperable; G08 preparacion de membresias; G09 replay/efectos
  tardios. Son exigencias de implementacion/certificacion, no nuevas decisiones de negocio.
- **SYSTEM externas**: G02 auditoria organizacional y G05 registro/navegacion/i18n.
  Necesitan autorizacion propia; no habilitarlas con una tarea de tareas.
- **Documentales**: SYNC-C01 identifica T200 -> T199 frente al orden conceptual
  individual -> masiva solicitado. La prohibicion de eliminar dependencias impide
  invertirla silenciosamente. Antes del bloque T199/T200, autorizar y documentar un
  ajuste acotado de secuencia/nucleo compartido sin duplicar logica, ampliar roles ni
  debilitar atomicidad; conservar IDs/estados y probar ambos flujos.
- **Historicas ajenas**: G10 y textos de fases anteriores (estados/flags, restauracion,
  viejas notas de notificaciones, ID FR-T02 repetido) no se corrigen ni se usan para
  autorizar cambios. Las precisiones de maestros/P1 de esta entrega son localizadas.

## Primer bloque independiente verificado

Cadena literal: **T170 -> T172 -> T173 -> T174 -> T175**.
Ninguna de estas tareas depende de T171, T176, T199/T200, G02 cerrado o una mutacion
SYSTEM. No significa que esten ejecutadas: T170 exige autorizacion futura por owner
y baseline/capacidades contrastados antes de empezar.

| Tarea | Archivos futuros / dependencia exacta | Resultado y limite |
|---|---|---|
| T170 | research de esta fase; ninguna | Registrar autorizacion y responsables G01/G02/G05/G06/G07 sin acceder a DB real |
| T172 | `organizacion/tests/test_memberships.py`; T170 | Pruebas de persistencia/consultas: triple, Empresa, vigencia e historia; no anticipar que transiciones T176 esten implementadas |
| T173 | `organizacion/models.py`; T172 | Entidades aditivas de membresia/eventos/coordinacion; Local/Departamento conservados |
| T174 | `organizacion/migrations/`; T173 | Migracion aditiva revisada, solo DB temporal para prueba, sin backfill inferido |
| T175 | `organizacion/services/memberships.py`; T174 | Consultas publicas materializadas, Empresa/elegibilidad/liderazgo; indisponibilidad no equivale a vacio |

Pruebas futuras focales: `python manage.py test organizacion.tests.test_memberships --settings=AppDocs.settings_test`
y `python manage.py check --settings=AppDocs.settings_test`, solo tras autorizacion y
verificar aislamiento temporal. Cubren persistencia/consultas del bloque; no afirmar
concurrencia certificada, transiciones auditadas, baja, UI ni lotes ya probados.
Los escenarios completos de sustitucion de JEFE y concurrencia requieren tareas
posteriores, aunque compartan fixtures o archivos de prueba.

Riesgos: constraints/aislamiento, compatibilidad del esquema, integridad de historia
y usuarios previos sin membresia. No activar FR-P06, correr migraciones reales,
cargar usuarios, tocar SYSTEM ni adelantar T176 al completar este bloque.
La autorizacion actual es solo documental; la implementacion necesita autorizacion
expresa adicional limitada a esos paths y pruebas aisladas.

## Validacion de la sincronizacion

Controles documentales: conservar todos los FR maestros previos y checkboxes,
agregar solo FR-P06; 30 F16-FR, 42 tareas pendientes, 36 escenarios; enlaces locales,
dependencias sin ciclos, CA presentes, diff completo y whitespace. Ninguna prueba
de software, check Django, migracion o acceso a bases se ejecuta en esta entrega.

El estado esperado ahora admite Markdown modificado bajo 001 y los diez documentos
previos de 003 mas esta matriz. No confundirlo con el cierre anterior que exigia
cero archivos versionados modificados. Rama/HEAD/index intactos; respaldo preexistente
sin tocar; ningun cambio fuera de las dos carpetas autorizadas.
