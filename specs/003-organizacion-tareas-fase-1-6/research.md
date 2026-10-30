# Research y registro de decisiones Fase 1.6

## Precheck y metodo

Fecha 2026-10-30; rama `main`; HEAD `196658dfb4d77b3942bde1603e1affa00fc112d2`.
`git diff` y `git diff --cached` iniciales vacios. Unico untracked inicial:
`db.sqlite3.bak_pre_L4_20261019`, preservado sin abrir ni modificar.
Solo comandos Git de lectura; no fetch/pull/checkout/commit/push, pruebas,
consultas a bases, migraciones ni instalaciones.

Se reutiliza la auditoria de cierre aportada por el propietario, resultado
**SI, CON CONDICIONES**, sobre el mismo HEAD. No se localizo un informe adicional
en `specs/` ni en la consulta de historial reciente; no se atribuyen a ese informe
detalles distintos de los aportados. Se contrastaron solo sus puntos pertinentes,
no una nueva auditoria general ni una certificacion productiva.

Instrucciones consultadas: AGENTS, AI_CONTEXT, ARCHITECTURE_MAP, AI_TASK_PATTERNS,
COPILOT_PROMPTS, instrucciones globales, indice COPILOT, arquitectura de apps,
estado actual, vendor, contrato operacional de conexiones y constitucion 1.5.0.
Contratos consultados: bloques A/D/E/K de la SPEC MAESTRA, clarificaciones de
participacion y jerarquia, data-model organizacional, conexiones, URLs, L5 y
spec VICMEAS. La clasificacion real procede de
[app_classification.py](../../AppDocs/app_classification.py).

## Evidencia del antecedente en HEAD

| Hallazgo anterior | Contraste focal actual | Clasificacion |
|---|---|---|
| organizacion existe | [models.py](../../organizacion/models.py), admin read-only, migracion 0001 y clasificacion APPLICATION | Implementado; frase "futura app" es historica |
| Local/Departamento existen | Empresa PROTECT, codigo unico por Empresa, activo/source/fechas; solo Local tiene legacy_code | Implementado, sin relacion Local -> Departamento |
| tareas tiene ambitos basicos | [models.py](../../tareas/models.py), `tipo_ambito`, local/departamento, XOR y validacion de Empresa; T092/T093 completadas | Implementado, no implica membresias |
| Membresias incompletas | organizacion solo contiene ambos maestros; sin servicios, modelos de membresia ni vista departamental | Ausente, no parcialmente habilitada |
| Regularizacion masiva ausente | [participant_storage.py](../../tareas/services/participant_storage.py) recibe un task_id por comando; busqueda de regularizacion masiva sin coincidencias | Ausente |
| Atomicidad individual | Django `_execute` abre atomic por comando; MySQL abre conexion/transaccion y notifica al salir | Implementado por tarea, insuficiente para lote |
| Decisiones fuera de specs | Opcion B, roles organizacionales, sustitucion JEFE y lote aportados por prompt | Aprobadas, incorporadas en este complemento |
| No redisenar roles/estados | FR-D13..D17, `PUBLIC_ROLES`, `TareaParticipante.Rol` y restricciones de lifecycle | Vigente; no contradiccion que obligue a rediseno |

No se inspecciono la DB: no se afirma que exista o no una fila manual `Vista` en
un entorno. Lo verificado es ausencia de rutas/metadatos/contrato previo con el
literal `Tareas - Maestro de departamentos` en los archivos buscados.

## Decisiones consolidadas

| ID | Decision y fundamento | Alternativa descartada |
|---|---|---|
| F16-D01 | Conservar maestros canónicos; evidencia T092/T093 y prompt 4.1 | Duplicar Local/Departamento o inventar padre Local |
| F16-D02 | Membresia actual unica mas historial append-only; roles JEFE/SUPERVISOR/STAFF, maximo un JEFE | Borrar anterior o mezclar roles VICMEAS/tarea |
| F16-D03 | Sustitucion JEFE explicita y atomica en organizacion, motivo obligatorio | Degradacion automatica o reemplazo silencioso |
| F16-D04 | Opcion B transversal a LOCAL/DEPARTAMENTO/sin ambito, validaciones acumulativas | Exigir mismo Departamento o eximir tareas sin ambito |
| F16-D05 | Traslado/perdida/recuperacion no alteran asignaciones existentes; elegibilidad se deriva | Cascadas de borrado/reasignacion o privilegios congelados |
| F16-D06 | Baja logica departamental con revision y bloqueo por tareas pendientes; historia cerrada intacta | Borrar Departamento o trasladar historico |
| F16-D07 | Lote explicito origen/destino/rol/tareas/motivo, preview + confirmacion | Sustitucion global implicita, commit parcial |
| F16-D08 | Evidencia individual y UUID comun dentro de BASE_TAREAS; efectos despues de commit | Secuencia de servicios individuales que notifica/commitea por tarea |
| F16-D09 | IDs/DTOs, resolver privado tareas, servicios publicos organizacion; no ciclo inverso | JOIN remoto, nuevo router, copia de maestros |
| F16-D10 | Fence organizacional mantenido hasta commit operacional; certificacion por backend | Doble lectura/version sin lock como supuesta garantia |
| F16-D11 | Reutilizar auditoria/notificaciones base y separar dominio de proyeccion central | SMTP propio, auditoria transversal paralela, atomicidad distribuida ficticia |
| F16-D12 | UI/permisos actuales y dependencias externas explicitas; arranque sin backfill inferido | Crear permisos por rol, editar CORE/catalogos sin autorizacion |

F16-D01 a D09, D11 y D12 consolidan reglas aprobadas y restricciones vigentes.
F16-D10 y la forma de persistencia son **diseno tecnico propuesto**, no evidencia
de implementacion ni nueva decision de negocio.

## Reconciliacion documental acotada

| Discrepancia | Resolucion para esta fase |
|---|---|
| ARQUITECTURA_APPS/data-model dicen "organizacion aun no existe" | Etiqueta historica de etapa anterior; T092/T093 y codigo prevalecen para estado real; no editar documentos fuera de alcance |
| FR-D06 dice "cuando corresponda" un jefe | Maximo un JEFE activo y cero sin warning, conforme al prompt; no exigir cobertura obligatoria |
| SPEC/URLs antiguas hablan de bypass visual superuser | Codigo actual y spec 002 separan V/ICMEAS sin bypass visual; no usar ese texto historico para crear privilegios |
| URLs antiguas separan Vistas de detalle/editar | Metadata actual usa `Tareas` para la superficie principal; no crear Vistas desde tablas historicas |
| Regla generica ForeignKey Empresa frente a storage externo | En organizacion/default se mantienen FKs; en BASE_TAREAS remoto solo IDs externos, conforme contrato especifico de conexiones |
| Connection Roles prohibe importar otra app como infraestructura | Integracion de dominio canónica explicitamente prevista por T092/T093, no importacion de router privado; tareas consume API publica de organizacion, nunca a la inversa |
| Contrato de conexiones dice runtime pendiente | Los adapters actuales existen; no declarar pendientes todos los storages ni certificar todos sus backends por ese hecho |
| "Auditoria individual" frente a deuda de participantes FR-D17 | Nuevo historial de dominio transaccional para regularizacion; proyeccion central separada. No declarar saldada toda deuda historica |

No se reescribe la SPEC MAESTRA ni se cambia la constitucion para resolver estas
diferencias. La especificidad de los contratos de maestros y del prompt permite
documentar esta integracion de dominio sin transformar organizacion en infraestructura
de conexion compartida.

## Dependencias, riesgos y decisiones realmente ausentes

| ID | Nivel/tipo | Evidencia, impacto y condicion de salida |
|---|---|---|
| F16-G01 | Alto, tecnico | Fence entre default y BASE_TAREAS no existe. Certificar exclusión de escrituras de membresia/Departamento, incluso admin/commands, y orden global de locks; bloquear lote si backend no puede garantizarlo |
| F16-G02 | Bloqueante para mutaciones organizacionales, dependencia externa | `AuditoriaService.APP_MODEL_MAP` no registra organizacion; `log_event` devuelve None para app desconocida. Historial de dominio no autoriza crear auditoria shadow. Solicitar capacidad central minima en auditoria con tarea/autorizacion separada; US1 puede preparar modelos/consultas mientras tanto |
| F16-G03 | Bloqueante para roles no soportados, funcional | FR-D15 solo permite alta/cambio publico PARTICIPANTE/INVITADO_OBSERVADOR; responsable usa su campo. No consta autorizacion de sustitucion publica SUPERVISOR/AUTORIZADOR ni reemplazo CREADOR. Mantener bloqueo explicito por rol; cerrar politica antes de habilitarlos, sin redisenar roles |
| F16-G04 | Bloqueante para notificaciones organizacionales completas, funcional | El prompt exige notificar perdida/recuperacion, pero T054 solo detalla eventos de tareas. Falta precisar destinatarios/canal de traslado/suspension/perdida y si recuperacion notifica al propio actor. Recuperacion incluye al afectado por mandato expreso; no inventar alertas a todos los jefes o correos masivos |
| F16-G05 | Alto, autorizacion externa | Navegacion, catalogos i18n y registro global de nuevas rutas pueden requerir access_control/AppDocs/static. Preparar metadata propia; ejecutar cambios externos solo con alcance expreso separado |
| F16-G06 | Alto, tecnico | Schema incremental MySQL no se resuelve con migracion Django; disenar extension operacional/adapters y preflight sin ejecutar DDL ahora |
| F16-G07 | Alto, tecnico | Baja de Departamento cruza bases; no es una transaccion distribuida. Fence, protocolo reiniciable y revalidacion final; no finalizar ante bloqueo o estado incierto |
| F16-G08 | Alto, despliegue | Usuarios existentes sin membresias perderan operacion al activar Opcion B. Inventario/alta autorizada previa, sin inferir membresias de participaciones |
| F16-G09 | Medio, tecnico | Fallos tras commit, perdida de respuesta, auditoria o email fallidos; UUID y evidencia durable, reconciliacion controlada; exactamente-una-vez email no esta garantizado por infraestructura actual |
| F16-G10 | Bajo, documental | Etiquetas historicas desactualizadas fuera de specs y en maestra; quedan identificadas, no se corrigen por ampliacion de alcance |

F16-G03/G04 no obligan a redisenar roles/estados/asignaciones. Son precisiones
ausentes que bloquean solo sus partes; no se reabre Opcion B ni ninguna decision
ya expresamente aprobada. No se declara "sin pendientes funcionales".

## Herramientas Spec Kit y limites de ejecucion

Se siguieron las estructuras de spec/plan/tasks y se leyo la constitucion.
`.specify/extensions.yml` no existe: hooks before/after plan/tasks no aplican.
No se ejecuta `setup-plan.ps1` ni `setup-tasks.ps1`: el helper compartido
`Get-FeaturePathsEnv` persiste `.specify/feature.json` al usar una nueva carpeta.
Eso excederia el permiso exclusivo `specs/`. Se crean los artefactos manualmente
sin cambiar estado Spec Kit, rama ni archivos globales. No se usan agentes de
investigacion externos ni se transmite codigo a terceros.
