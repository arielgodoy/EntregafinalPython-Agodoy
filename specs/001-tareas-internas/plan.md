# Implementation Plan: Tareas Internas - SPEC MAESTRA

**Branch**: `001-tareas-internas` | **Date**: 2026-09-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-tareas-internas/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

La app `tareas` ya contiene una Fase 1 funcional de borrador/publicada, responsable,
prioridad, empresa activa e ICMEAS. Este plan reconstruye el diseño para el dominio
completo de la SPEC MAESTRA sin mezclarlo con `control_de_proyectos.Tarea`.

La ampliación será incremental dentro de `tareas/`: identidad y ciclo de vida,
asignación/jerarquía/fechas, avance/documentos, cotizaciones, colaboración/similitud/
enlaces y dashboards. Cada fase tendrá migraciones aditivas, backfill explícito, pruebas
y focalizadas y validación independiente. Las tasks se actualizan como artefacto de ejecución
cuando una decisión SDD aprobada cambia el alcance.

P1 Local permanece `LEGACY API PENDIENTE`. Proveedor tendrá posteriormente una
`APPLICATION_APP` global local Django; P2 se reserva para su integración, validación,
identificador, conciliación y sincronización con ERP legacy.

## Technical Context

**Language/Version**: Python 3.11 (entorno local vigente) / Django 5.1.3

**Primary Dependencies**: Django 5.1.3 (CBV, ORM, forms), `access_control`/VICMEAS,
usuarios y sesión existentes, `notificaciones`, email de `acounts`, layout vigente y
JavaScript vanilla propio de `tareas` cuando sea necesario. Sin dependencias nuevas.

**Storage**: Según `COPILOT/ESTADO_ACTUAL.md`: alias `default` = SQLite local clasificado SYSTEM; existe alias `DB_sistema` MySQL configurado por variables de entorno. La disponibilidad/base productiva efectiva depende del entorno y NO se infiere de los defaults locales. La feature usa la base SYSTEM que corresponda según la arquitectura/router vigente (`api.Router_Databases.MultiDatabaseRouter`), sin definir router propio ni presuponer un motor productivo.

**Testing**: `python manage.py test --settings=AppDocs.settings_test`; tests focalizados
en `tareas/tests/` y escenarios manuales de `quickstart.md`.

**Target Platform**: Web server-side rendered (templates Django), misma plataforma del sistema vigente.

**Project Type**: Módulo web dentro del proyecto Django multiempresa existente.

**Performance Goals**: La spec no fija latencias nuevas. Se planifican índices por empresa,
estado, fechas, correlativo y relaciones; KPI y similitud consultarán solo la empresa activa
y usarán paginación cuando corresponda.

**Constraints**: lógica nueva dentro de `tareas/` bajo APPLICATION BOUNDARY; `session['empresa_id']` es obligatorio,
`Permiso.ver` controla solo visibilidad del sidebar y ICMEAS autorización funcional;
`static/js/app.js` es inmutable; no se crean maestros legacy; no se elimina
físicamente una tarea; cambios fuera de `tareas/` requieren una tarea separada con autorización y scope explícitos.

**Registration status**: El alta inicial de `tareas` en `AppDocs/app_classification.py`,
`AppDocs/settings.py` y `AppDocs/urls.py` ya fue autorizada, ejecutada, testeada y
versionada. Cualquier modificación futura adicional de esos archivos queda fuera de este
scope y requiere una tarea separada con autorización explícita. Cualquier otro archivo
externo a `tareas/` queda bloqueado por APPLICATION BOUNDARY.
Local requiere contrato legacy antes de cerrar su fase. Proveedor puede operar localmente;
solo su integración ERP requiere contrato P2.

## Constitution Check

*GATE: pass before research and re-evaluate after design.*

| Principio | Evaluación | Resultado |
|---|---|---|
| I. Arquitectura existente | Conserva la Fase 1 y consume interfaces existentes; no mezcla `Tarea` con proyectos. | PASS |
| II. Contexto mínimo | Se consultaron `COPILOT/INDICE.md`, `ESTADO_ACTUAL.md`, `ARQUITECTURA_APPS.md` y `REGLAS_CODIGO_VENDOR.md`; no se usa histórico. | PASS |
| III. Apps protegidas | La lógica queda en `tareas/`; el registro inicial ya está resuelto. Cambios futuros adicionales en archivos protegidos requieren autorización. | PASS |
| IV. Vendor | No se modifica `static/js/app.js`; cualquier JS nuevo vive en `tareas/static/tareas/`. | PASS |
| V. Seguridad y multiempresa | El sidebar consume `V` por empresa activa; toda vista/acción usa ICMEAS, empresa activa de sesión y validación de pertenencia. | PASS |
| VI. Cambios mínimos | Fases aditivas, sin refactor transversal ni migración monolítica. | PASS |
| VII. Tests | Cada fase agrega pruebas focalizadas y regresión completa antes de cierre. | PASS |
| VIII. Qué antes que cómo | La spec fija comportamiento; este plan fija límites, fases y diseño técnico. | PASS |
| IX. Trazabilidad | FR-A01…FR-R06 se cubren en data model, contratos, fases y quickstart; `tasks.md` queda para la siguiente etapa. | PASS |

**Gate**: PASS. El registro inicial de la app está resuelto. Permanecen bloqueadas las
dependencias legacy P1/P2 y cualquier modificación futura adicional de archivos protegidos.

## Structure Decision

La app existente `tareas/` es la única superficie funcional nueva:

```text
tareas/
├── models.py                 # entidades y estados, conservando Tarea existente
├── services/                 # transiciones, correlativos, KPI, similitud, notificaciones
├── forms.py / views.py       # flujos protegidos por ICMEAS
├── urls.py                   # contrato web por fases
├── templates/tareas/         # vistas server-side y parciales
├── static/tareas/            # JS propio únicamente si la UX lo necesita
├── migrations/               # migración aditiva por fase, nunca monolítica
└── tests/                    # regresión MVP + pruebas por dominio
```

Se conservan `Tarea`, `TareaForm`, las vistas actuales de listado/detalle/crear/editar/
publicar y sus URLs. Se ajustarán solo para ampliar estados y campos sin romper nombres
existentes. No se modifica `control_de_proyectos`, `access_control`, `notificaciones`,
`acounts`, templates globales, settings, router ni vendor.

## Technical Phases

### Phase 0 — Baseline, autorización y compatibilidad

- Capturar la regresión de Fase 1 y verificar el código actual.
- Verificar que el registro inicial de la app en los tres archivos `AppDocs/*` permanece
    intacto; cualquier modificación futura adicional requiere nueva autorización expresa.
- Mantener nombres de URLs y vistas existentes.
- Añadir pruebas de compatibilidad para correlativo, responsable, empresa activa,
    publicación irreversible e ICMEAS.
- Consumir la infraestructura VICMEAS ya existente para el sidebar: mapping explícito
    de los items de Tareas a sus Vistas y padres visibles si tienen un hijo visible.
    No implementar ni planificar VICMEAS dentro de `tareas`.

### Phase 1 — Identidad, correlativos y ciclo de vida

- Extender `Tarea` con un correlativo único por empresa, reservado al crear y transformado
    de A a B sobre el mismo registro al publicar; no existen secuencias A/B separadas.
- Usar estados persistentes `BORRADOR`, `ACTIVA`, `GESTION`, `PENDIENTE_APROBACION_CIERRE`,
    `CERRADA` y `ANULADA`; publicación, rechazo de cierre y reactivación son eventos/acciones.
- Crear historial de transiciones, eventos de publicación/rechazo, cierre/anulación y snapshot
    de una tarea para restauración.
- Añadir la señal persistente `Tarea.cierre_completado` (`BooleanField(default=False)`) como
    condición de lifecycle equivalente al 100% para solicitar cierre; no representa avance
    porcentual general, pesos, hitos ni el futuro modelo `Avance`.
- Backfill determinista e idempotente de MVP: por Empresa ordenar `fecha_creacion ASC, id ASC`,
    asignar desde `0000001`, aplicar prefijo A a `BORRADOR` y B a `PUBLICADA` más estado `ACTIVA`,
    conservar PK y no reasignar destructivamente correlativos ya rellenados.
- Departamento y Equipo/Activo quedan fuera de la migración Phase 2 hasta cerrar su definición
    de modelo, tipo, relación con Empresa, nulabilidad y constraints.

### Phase 2 — Asignación, jerarquía, fechas y mini-tareas

- Modelar roles, participantes, invitados, lectura y reasignaciones; solo usuarios activos
    y dentro de la empresa activa.
- La cascada padre/hijo/nieto queda deferred para esta fase: Phase 2 implementa anulación y
    reactivación de una sola tarea, snapshot/restauración y contrato extensible. La relación,
    participantes y cascada real se implementan en Phase 3.
- Modelar asignación individual/masiva, vencimiento por días, atraso acumulado, causas,
    reprogramación con justificación y auditoría.
- Modelar mini-tareas checkbox con una persona, sin ponderación y bloqueantes del cierre.

### Phase 2 boundary for lifecycle

Phase 2 solo implementa el ciclo de una tarea: estados canónicos, eventos, auditoría,
correlativo único y snapshot/restauración individual. La relación padre/hijo/nieto,
participantes y cascada real se difieren a Phase 3; T018 no puede considerarse completa
en Phase 2 respecto de la jerarquía, pero sí puede completarse para una tarea individual.

### Phase 2 schema freeze

La migración prevista de Phase 2 contiene exactamente, en orden: (1) `Tarea.correlativo`
nullable; (2) `Tarea.fechas_pendientes_confirmacion` nullable; (3) `Tarea.cierre_completado`
nullable; (4) `CorrelativoEmpresa` con una fila única por Empresa y `siguiente_numero`
inicial 1; (5) `TareaTransicion`,
`TareaCierre` y `TareaAnulacionSnapshot` individuales; (5) choices de estado canónico;
(6) backfill idempotente de correlativo y `PUBLICADA`→`ACTIVA`; (7) constraint única
`(empresa, correlativo)` e índice equivalente; (8) endurecimiento de nullability/defaults.
No incluye Departamento, Equipo/Activo, TareaRelacion, participantes, Local, Proveedor,
documentos, evidencias, hitos, mini-tareas ni otras entidades de fases posteriores.

### Phase 3 — Avance, hitos, documentos y evidencia

- Añadir avance manual y avance por hitos.
- Usar pesos relativos normalizados: `sum(cumplimiento * peso) / sum(pesos)`; agregar un
    hito redistribuye sin cambiar cumplimientos anteriores.
- Añadir evidencia configurable, documentos por tipo como archivo o URL, fechas
    informativas e historial; no automatizar vencimientos documentales.
- Probar precisión, orden por creación, mini-tareas pendientes y reglas de cierre.

### Phase 4 — Cotizaciones, rondas y maestro local de proveedores

- Implementar y conservar el contrato PRE-P2 de rondas, histórico, mínimo configurable,
    fechas, observaciones, documentos y cierre general.
- Crear posteriormente la `APPLICATION_APP proveedores` con maestro global Django y RUT
    opcional normalizado, único global e inactivación lógica.
- Evolucionar `Cotizacion.proveedor` como FK nullable, exigirlo solo para nuevas cotizaciones,
    validar tres versiones por `(ronda, proveedor)` y contar proveedores distintos vigentes.
- Mantener P2 exclusivamente para lookup, validación, identificador, conciliación,
    sincronización y actualización desde ERP legacy.

Phase 2 persiste `Tarea.fechas_pendientes_confirmacion` como booleano (default `False`),
lo activa al reactivar una tarea con fechas afectadas y lo desactiva al confirmar/reacomodar.
No se agregan fechas nuevas ni se depende solo de información derivada.

### Phase 5 — Colaboración, notificaciones, reuniones, similitud y enlaces

- Consumir `notificaciones` y email de `acounts`; no crear subsistema paralelo.
- Integrar T054 para asignación, lectura, documentos, aprobación,
    anulación/reactivación y criticidad según la spec. Su cierre total, incluida la
    notificación de Comentarios, depende del dominio, servicios y UI de Phase 8.
- Modelar reuniones de revisión, agenda, modalidad, convocatoria y comentarios.
- Modelar origen/derivación y similitud histórica incluyendo cerradas; advertir al publicar
    desde el umbral por empresa (default 80%), registrar confirmación y mantener la tarea nueva.
- Crear enlaces parametrizados autenticados en lectura, con ICMEAS, empresa activa y
    registro de acceso/notificación; no usuarios externos.

### Phase 6 — Dashboards, KPI y endurecimiento

- Construir dashboards con filtros, DataTables, modal de información y drill-down permitido.
- Implementar exactamente ocho KPI: total por estado, atrasadas, próximas a vencer, sin
    movimiento, esperando aprobación, carga abierta por responsable, cumplimiento y tiempo
    promedio de cierre. Repetirlos únicamente en General, Empresa, Departamento, Usuario y
    Tarea. Local queda deferred por P1; Proveedor podrá incorporarse desde su maestro local.
- Añadir índices y consultas paginadas por empresa; probar consistencia por nivel.
- Completar `data-key`, ICMEAS, seguridad de enlaces, auditoría, regresión MVP y diff check.

### Phase 8 — Comentarios de Tarea (T095–T102)

Esta extensión se ejecuta después de la Phase 7 de validación transversal registrada
en `tasks.md`; no reabre ni renumera fases históricas.

- Mantener Comentarios dentro de `tareas/`, relacionados 1:N con `Tarea`, sin estado ni
    transición propia.
- Reutilizar `TareaParticipante` como único vínculo de acceso; VICMEAS usa `Tareas`:
    `ingresar` para lectura, `modificar` para crear/editar/vincular y `supervisor` (S)
    para ocultar/restaurar. Creador/responsable no tienen bypass del vínculo.
- Reutilizar `DocumentoTarea` para un máximo de cinco adjuntos por Comentario; no duplicar
    archivos ni emitir notificación `documento_agregado` adicional por una carga inline.
- Conservar versiones inmutables del texto y conjunto de relaciones `DocumentoTarea`, con
    `PROTECT`; no copiar archivos. Edición del autor hasta una hora desde creación original;
    ocultar/restaurar requiere S y motivo obligatorio. Historial detallado solo autor/S.
- Extender la fila única existente `TareaLectura` con cursor `(created_at, pk)`; páginas
    cronológicas de 20 avanzan solo lo cargado. Registrar períodos de inactividad por lector/
    Tarea desde `tareas` al observar `User.is_active`, sin filas por Comentario ni cambios
    a sesiones. Los ocultos pendientes usan tombstone neutro en la bitácora.
- Permitir mutaciones solo en estados publicados operativos; cerrada/anulada es lectura.
    Revalidar en backend Empresa, vínculo, VICMEAS y lifecycle justo antes de persistir.
- Integrar T054 para crear/editar/ocultar/restaurar; solo crear incrementa no leídos. Usar
    notificaciones existentes y email automático para prioridad `CRITICA`.
- La tarjeta server-rendered pagina 20, ofrece cámara móvil, burbuja `1..9`/`9+` y foco
    inicial en primer pendiente. Sin filtros, búsqueda propia, threads, app o chat separados;
    respeta i18n y FR-T01…FR-T10.

## Migration Strategy

No se crea una migración monolítica. Cada fase usa migración de esquema aditiva, backfill
idempotente, validación, activación del flujo y rollback lógico. Las migraciones productivas
requieren revisión y autorización separada.

El backfill nunca borra ni duplica tareas MVP. Por cada Empresa ordena `fecha_creacion ASC, id ASC`
y asigna una única secuencia desde `0000001`; `BORRADOR` recibe A y `PUBLICADA` recibe B +
`ACTIVA`. `CorrelativoEmpresa.siguiente_numero` queda en máximo asignado + 1, o 1 sin tareas;
publicar no lo incrementa. El proceso detecta valores ya rellenados y no los reasigna
destructivamente. Phase 2 agrega, en este orden: `correlativo`
nullable, `fechas_pendientes_confirmacion` nullable, estados/eventos, `TareaTransicion`,
`TareaCierre`, `TareaAnulacionSnapshot` y `CorrelativoEmpresa`; asigna una única secuencia
numérica por tarea, mapea `BORRADOR` a A y `PUBLICADA` a B + `ACTIVA`, y solo después aplica
constraints, índice `(empresa, correlativo)` y nullabilidad final. Conserva PK, empresa,
creador, responsable, prioridad, estado lógico y fechas; reporta colisiones. No se incluyen
Departamento, Equipo/Activo, jerarquía, participantes, Local ni Proveedor. No se modifica
ninguna migración de otra app.

## Test Strategy

- Regresión MVP: modelos, formularios, vistas, publicación, empresa activa, 403/404 e
    inmutabilidad.
- Seguridad: aislamiento por empresa, ICMEAS, usuarios inactivos, enlaces autenticados y
    ausencia de acceso externo.
- Dominio: A/B, estados, auditoría, cascada, restauración, fechas pendientes, mini-tareas,
    hitos, documentos, reprogramación y cierres bloqueados.
- Integraciones: mocks para notificaciones/email y adaptadores legacy; sin credenciales ni
    llamadas externas reales. Comentarios reutiliza mocks T053/T054 y valida que lectura no
    notifica y que adjuntos no duplican el evento de documento.
- KPI/similitud: fixtures por empresa; ocho KPI por dimensión; 80% por defecto y cambios
    por empresa solo para evaluaciones nuevas.
- Cada fase ejecuta tests focalizados y luego `python manage.py test --settings=AppDocs.settings_test`.

## External Changes and Blocks

| Superficie | Motivo | Estado |
|---|---|---|
| `AppDocs/app_classification.py` | Alta inicial de `tareas` | RESUELTO: autorizado, ejecutado, testeado y versionado; cambios futuros requieren autorización |
| `AppDocs/settings.py` | Alta inicial en `INSTALLED_APPS` | RESUELTO: autorizado, ejecutado, testeado y versionado; cambios futuros requieren autorización |
| `AppDocs/urls.py` | Include inicial de URLs | RESUELTO: autorizado, ejecutado, testeado y versionado; cambios futuros requieren autorización |
| `/api/v1/maestros/locales/` | Elegibilidad Local incompleta | BLOQUEADO: P1 legacy |
| Maestro/API Proveedor | Maestro local aprobado; integración ERP pendiente | LOCAL PLANIFICADO / P2 legacy |
| Otras apps, templates globales, vendor | No son necesarios | PROHIBIDO sin nueva autorización |

## Complexity Tracking

No hay violaciones constitucionales justificables. La complejidad se controla por fases y
límites explícitos; no se autoriza resolverla con un modelo monolítico o cambios transversales.

## Post-Design Constitution Check

PASS: el diseño mantiene `tareas/` como frontera funcional, conserva Fase 1, reutiliza
interfaces existentes, mantiene P1 bloqueado y limita P2 a integración ERP, reconoce el alta inicial ya resuelta,
no propone cambios futuros en archivos protegidos sin autorización y deja `tasks.md` para
la siguiente etapa.
