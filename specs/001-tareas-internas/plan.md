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
focalizadas y validación independiente. No se modifica `tasks.md` en esta etapa.

P1 Local y P2 Proveedor permanecen `LEGACY API PENDIENTE`. No se crean maestros duplicados,
ni se inventan tablas, IDs, sincronización o `rut_contable`.

## Technical Context

**Language/Version**: Python 3.11 (entorno local vigente) / Django 5.1.3

**Primary Dependencies**: Django 5.1.3 (CBV, ORM, forms), `access_control`/ICMEAS,
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

**Constraints**: lógica nueva dentro de `tareas/`; ICMEAS y `session['empresa_id']` son
obligatorios; `static/js/app.js` es inmutable; no se crean maestros legacy; no se elimina
físicamente una tarea; cambios fuera de `tareas/` requieren autorización expresa.

**Registration status**: El alta inicial de `tareas` en `AppDocs/app_classification.py`,
`AppDocs/settings.py` y `AppDocs/urls.py` ya fue autorizada, ejecutada, testeada y
versionada. Cualquier modificación futura adicional de esos archivos requiere autorización
expresa. Cualquier otro archivo externo a `tareas/` queda bloqueado por la regla de detención.
Local y Proveedor requieren contrato legacy antes de cerrar sus fases.

## Constitution Check

*GATE: pass before research and re-evaluate after design.*

| Principio | Evaluación | Resultado |
|---|---|---|
| I. Arquitectura existente | Conserva la Fase 1 y consume interfaces existentes; no mezcla `Tarea` con proyectos. | PASS |
| II. Contexto mínimo | Se consultaron `COPILOT/INDICE.md`, `ESTADO_ACTUAL.md`, `ARQUITECTURA_APPS.md` y `REGLAS_CODIGO_VENDOR.md`; no se usa histórico. | PASS |
| III. Apps protegidas | La lógica queda en `tareas/`; el registro inicial ya está resuelto. Cambios futuros adicionales en archivos protegidos requieren autorización. | PASS |
| IV. Vendor | No se modifica `static/js/app.js`; cualquier JS nuevo vive en `tareas/static/tareas/`. | PASS |
| V. Seguridad y multiempresa | Toda vista/acción usa ICMEAS, empresa activa de sesión y validación de pertenencia. | PASS |
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

### Phase 4 — Cotizaciones, rondas y proveedor referenciado

- Implementar el concepto de ronda, histórico, mínimo configurable por ronda (default 3),
    fechas, observaciones y documentos asociados que no requieran identidad de proveedor.
- Documentar la regla de máximo 3 versiones por proveedor/ronda, pero no validarla ni contar
    proveedores distintos mientras P2 siga bloqueado.
- Implementar la regla general de cierre bajo el mínimo solo hasta el punto que no requiera
    identidad real; conservar histórico por ronda.
- `ProveedorReferencia` queda como **PLACEHOLDER DE DISEÑO — IMPLEMENTACIÓN BLOQUEADA POR P2**:
    no definir campos, `rut_contable`, ID externo, tabla legacy, endpoint ni sincronización;
    no generar tarea de implementación. Las cotizaciones se planifican solo hasta necesitar
    identidad real del proveedor, punto en el que quedan bloqueadas. Proveedor es una entidad
    conceptual futura; sus datos maestros, evaluación, promedio e identidad externa no son
    diseño actual de modelo ni contrato.

Phase 2 persiste `Tarea.fechas_pendientes_confirmacion` como booleano (default `False`),
lo activa al reactivar una tarea con fechas afectadas y lo desactiva al confirmar/reacomodar.
No se agregan fechas nuevas ni se depende solo de información derivada.

### Phase 5 — Colaboración, notificaciones, reuniones, similitud y enlaces

- Consumir `notificaciones` y email de `acounts`; no crear subsistema paralelo.
- Cubrir asignación, lectura, comentarios, documentos, aprobación, anulación/reactivación
    y criticidad según los canales de la spec.
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
    Tarea. Local queda deferred por P1 y Proveedor deferred por P2.
- Añadir índices y consultas paginadas por empresa; probar consistencia por nivel.
- Completar `data-key`, ICMEAS, seguridad de enlaces, auditoría, regresión MVP y diff check.

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
    llamadas externas reales.
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
| Maestro/API Proveedor | Contrato no definido | BLOQUEADO: P2 legacy |
| Otras apps, templates globales, vendor | No son necesarios | PROHIBIDO sin nueva autorización |

## Complexity Tracking

No hay violaciones constitucionales justificables. La complejidad se controla por fases y
límites explícitos; no se autoriza resolverla con un modelo monolítico o cambios transversales.

## Post-Design Constitution Check

PASS: el diseño mantiene `tareas/` como frontera funcional, conserva Fase 1, reutiliza
interfaces existentes, mantiene P1/P2 bloqueados, reconoce el alta inicial ya resuelta,
no propone cambios futuros en archivos protegidos sin autorización y deja `tasks.md` para
la siguiente etapa.
