---

description: "Task list for the Tareas Internas master feature"
---

# Tasks: Tareas Internas - SPEC MAESTRA

**Input**: Design documents from `/specs/001-tareas-internas/`

**Prerequisites**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/web-urls.md](contracts/web-urls.md), [quickstart.md](quickstart.md)

**Tests**: Se incluyen tareas de pruebas porque la constitución del repositorio exige tests focalizados y regresión por fase. No se ejecutan durante la generación de este archivo.

**Scope rules**:

- Toda lógica futura pertenece a `tareas/`; se reutilizan ICMEAS, sesión, multiempresa, notificaciones y email existentes.
- El alta inicial de `tareas` en `AppDocs/app_classification.py`, `AppDocs/settings.py` y `AppDocs/urls.py` ya está resuelta; no se generan tareas pendientes para repetirla.
- P1 Local permanece `LEGACY API PENDIENTE`: no se crean tareas de implementación, filtros, modelos, IDs, endpoints ni sincronización.
- P2 Proveedor permanece bloqueado: `ProveedorReferencia` es únicamente un placeholder de diseño y no genera tarea de implementación.
- Cotizaciones se implementan solo hasta el punto previo a necesitar identidad real del proveedor; desde ese punto quedan bloqueadas.
- Cualquier modificación futura adicional fuera de `tareas/`, incluidos cambios en `AppDocs/*`, requiere autorización expresa y una tarea autorizada específica.
- `static/js/app.js` es vendor inmutable. No se modifica.
- No se crean migraciones, código ni cambios en otras apps durante la generación de este archivo.

## Phase 0: Setup, baseline and governance

**Purpose**: Confirmar el punto de partida, preservar compatibilidad MVP y dejar explícitos los límites de implementación.

- [x] T001 Revisar el contrato vigente de la app en `tareas/models.py`, `tareas/forms.py`, `tareas/views.py`, `tareas/urls.py` y `tareas/tests/` contra [spec.md](spec.md) y registrar incompatibilidades sin modificar código.
- [x] T002 [P] Verificar en `AppDocs/app_classification.py`, `AppDocs/settings.py` y `AppDocs/urls.py` que el alta inicial de `tareas` permanece registrada; no repetir ni ampliar esos cambios.
- [x] T003 [P] Auditar que ninguna propuesta de fase requiera modificar `access_control/`, `notificaciones/`, `acounts/`, `control_de_proyectos/`, templates globales o `static/js/app.js`; documentar cualquier dependencia bloqueada en `specs/001-tareas-internas/plan.md`.
- [x] T004 [P] Preparar la matriz de trazabilidad FR-A01…FR-R06 → fase → archivo de `tareas/` → prueba en `specs/001-tareas-internas/tasks.md` y `specs/001-tareas-internas/quickstart.md`.
- [x] T005 [P] Crear la base de pruebas compartida de empresa activa, usuario autenticado, permisos ICMEAS y fixtures MVP en `tareas/tests/factories.py` sin alterar aplicaciones externas.

## Phase 1: Foundation and MVP compatibility [US1]

**Goal**: Mantener funcional la Fase 1 existente mientras se prepara la evolución incremental del dominio.

**Independent test criteria**: Los tests actuales de `tareas` siguen cubriendo crear, editar, listar, publicar, aislamiento, 403 y 404; no se alteran PK, URLs ni la publicación irreversible.

**FR coverage**: FR-A02, FR-A05, FR-C02, FR-C03, FR-D05, FR-P01, FR-P02, FR-R06.

- [x] T006 [US1] Crear únicamente el scaffolding `tareas/services/__init__.py` para habilitar el paquete de servicios; no añadir lógica de negocio ni modificar otras apps.
- [x] T007 [US1] Definir el servicio de empresa activa y autorización en `tareas/services/context.py`, y refactorizar únicamente si es necesario la consulta común en `tareas/views.py`, conservando `listar_tareas`, `detalle_tarea`, `crear_tarea`, `editar_tarea` y `publicar_tarea`.
- [x] T008 [US1] Preservar el contrato de `TareaForm` en `tareas/forms.py`: responsable opcional en borrador, prioridad vigente (FR-B01, FR-B02) y exclusión de empresa/estado/creador.
- [x] T009 [US1] Mantener las plantillas MVP en `tareas/templates/tareas/tarea_lista.html`, `tareas/templates/tareas/tarea_form.html` y `tareas/templates/tareas/tarea_detalle.html`, incluyendo layout vigente, `data-key` y las exclusiones FR-R01, FR-R02, FR-R03 y FR-R04.
- [x] T010 [US1] Ampliar la regresión de modelos en `tareas/tests/test_models.py` para confirmar responsable activo, publicación irreversible, prioridad y fecha de publicación.
- [x] T011 [US1] Ampliar la regresión de vistas en `tareas/tests/test_views.py` para confirmar empresa activa, 403 ICMEAS, 404 cross-company y compatibilidad de URLs.
- [x] T012 [US1] Añadir pruebas de formularios MVP en `tareas/tests/test_forms.py` para título requerido, responsable opcional y valores de prioridad.
- [x] T013 [US1] Validar manualmente los escenarios E1–E7 de `specs/001-tareas-internas/quickstart.md` antes de habilitar fases de dominio.

## Phase 2: Identity, lifecycle and audit [US2]

**Goal**: Implementar correlativos A/B, estados completos, transiciones explícitas, cierre, anulación y restauración auditable dentro de `tareas/`.

**Independent test criteria**: Un borrador obtiene A, publica convirtiéndose en B sin duplicar PK, solo admite transiciones permitidas y anulación/reactivación conserva snapshots y auditoría.

**FR coverage**: FR-A01, FR-A06, FR-C01, FR-C03, FR-C05, FR-C06, FR-C07, FR-C08, FR-C09, FR-Q04, FR-Q06.

- [x] T014 [US2] Diseñar la ampliación de `Tarea` en `tareas/models.py` para correlativo, estados canónicos compatibles con la Fase 1 y sin definir Local legacy (FR-A01, FR-A07); Departamento y Equipo/Activo quedan fuera de esta migración hasta cerrar sus definiciones de modelo, tipo, nulabilidad, relación con Empresa y constraints (FR-A03, FR-A04).
- [x] T015 [US2] Implementar el servicio de correlativos A/B en `tareas/services/correlativos.py`: reservar un único número por empresa al crear, usar `transaction.atomic()` y bloqueo persistente adecuado, convertir A a B sobre el mismo registro al publicar, sin contador B separado ni consumo adicional.
- [x] T016 [US2] Implementar `TareaTransicion` (FK Tarea, origen, destino, acción/evento, usuario, timestamp, motivo opcional), `TareaCierre` (FK Tarea, usuario, timestamp, resultado APROBADO/RECHAZADO, comentario opcional) y `TareaAnulacionSnapshot` individual (FK Tarea, estado anterior, `fechas_pendientes_confirmacion` anterior, usuario/timestamp de anulación y usuario/timestamp de reactivación); no incluir avance, documentos, evidencias, hijos, nietos, participantes ni TareaRelacion.
- [x] T017 [US2] Implementar la máquina de estados persistentes `BORRADOR`, `ACTIVA`, `GESTION`, `PENDIENTE_APROBACION_CIERRE`, `CERRADA` y `ANULADA` en `tareas/services/lifecycle.py`; publicación, rechazo de cierre y reactivación serán eventos/acciones auditables, no estados adicionales. La señal documental `cierre_completado` será `False` en gestión normal, `True` al marcar 100%, y permanecerá `True` tras aprobar o rechazar el cierre.
- [x] T018 [US2] Implementar anulación/reactivación INDIVIDUAL de una sola tarea en `tareas/services/lifecycle.py`, usando snapshot individual y restaurando el estado anterior; la cascada jerárquica no pertenece a esta tarea.
- [x] T019 [US2] Implementar `Tarea.fechas_pendientes_confirmacion` y la restauración individual del snapshot tras reactivación, sin recalcular fechas; la confirmación/reacomodo posterior debe poder devolver el booleano a `False`. `cierre_completado` es una señal separada de lifecycle, no un porcentaje de avance.
- [x] T020 [US2] Añadir vistas protegidas de transición, anulación y reactivación en `tareas/views.py` y sus rutas en `tareas/urls.py`, sin renombrar URLs MVP.
- [x] T021 [US2] Crear templates de ciclo de vida y auditoría en `tareas/templates/tareas/` con acciones visibles según ICMEAS y textos `data-key`.
- [x] T022 [US2] Añadir tests de correlativos, transiciones, aprobación/rechazo de cierre, anulación/reactivación individual, restauración individual, fechas pendientes y auditoría en `tareas/tests/test_lifecycle.py`; la cascada padre/hijo/nieto se valida en Phase 3. La futura validación de rechazo conservará `cierre_completado=True`.
- [x] T023 [US2] Preparar la migración aditiva de esta fase en `tareas/migrations/` y su backfill idempotente: ordenar por Empresa `fecha_creacion ASC, id ASC`, asignar desde `0000001`, aplicar A a borradores y B + `ACTIVA` a `PUBLICADA`, inicializar `siguiente_numero` en máximo+1 o 1 sin tareas, detectar correlativos ya rellenados sin reasignación destructiva, añadir `cierre_completado` nullable y endurecerlo a `BooleanField(default=False)`, aplicar constraints/índices y endurecer nullability; conservar PK y excluir Departamento, Equipo/Activo, jerarquía, participantes, Local y Proveedor.
- [x] T024 [US2] Validar escenarios E8 de `specs/001-tareas-internas/quickstart.md` y actualizar solo documentaciÃ³n de fase si el comportamiento implementado difiere del contrato.

## Phase 3: Assignment, hierarchy, dates and mini-tasks [US3]

**Goal**: Añadir responsables, roles, participantes, jerarquía padre/hijo/nieto, fechas, atrasos, reprogramación y mini-tareas.

**Independent test criteria**: Una tarea admite asignación individual/equipo, una jerarquía máxima de dos niveles, fechas auditables y mini-tareas que bloquean cierre sin ponderar avance.

**FR coverage**: FR-B03, FR-B04, FR-D01, FR-D02, FR-D03, FR-D04, FR-D05, FR-D06, FR-D07, FR-D08, FR-D09, FR-D10, FR-E01, FR-E02, FR-E03, FR-E04, FR-E05, FR-E06, FR-E07, FR-E08, FR-E09, FR-F07, FR-G01, FR-G02, FR-G03, FR-G04, FR-G05.

- [ ] T025 [US3] Implementar `TareaParticipante`, roles, invitados y confirmación de lectura en `tareas/models.py` o servicios propios, validando usuarios activos y empresa activa.
- [ ] T026 [US3] Implementar reasignación trazable en `tareas/services/assignment.py`, incluyendo responsable anterior/nuevo, usuario, fecha y motivo.
- [ ] T027 [US3] Implementar asignación independiente por responsable y asignación masiva en `tareas/services/assignment.py`, conservando nombre propio y fecha común por tarea.
- [ ] T028 [US3] Implementar `TareaRelacion` con padre/hijo/nieto y límite de dos niveles en `tareas/services/hierarchy.py`, extender la anulación/reactivación individual de T018 a hijos y nietos mediante cascada real, e integrar participantes cuando corresponda; el cambio de departamento solo se permite cuando su definición esté cerrada, sin inventar Local.
- [ ] T029 [US3] Implementar navegación vertical y validación de cierre bloqueado por descendientes en `tareas/views.py`, `tareas/urls.py` y templates propios.
- [ ] T030 [US3] Implementar vencimiento por días, atraso acumulado, causas cerradas y reprogramación con justificación obligatoria en `tareas/services/scheduling.py`.
- [ ] T031 [US3] Implementar `MiniTarea` con una persona, checkbox hecho/no hecho y bloqueo de cierre en `tareas/models.py` y `tareas/services/closure.py`.
- [ ] T032 [US3] Añadir tests de asignación, usuarios inactivos, participantes, lectura, reasignación, jerarquía, fechas, atraso, reprogramación y mini-tareas en `tareas/tests/test_assignment.py`, `tareas/tests/test_hierarchy.py` y `tareas/tests/test_scheduling.py`.
- [ ] T033 [US3] Preparar migraciones aditivas de asignación, jerarquía, fechas y mini-tareas en `tareas/migrations/`, preservando snapshots y datos existentes; no ejecutar migraciones durante esta generación.
- [ ] T034 [US3] Validar escenarios E9 de `specs/001-tareas-internas/quickstart.md` y documentar cualquier bloqueo de integración externa sin implementar P1 Local.

## Phase 4: Progress, milestones, documents and evidence [US4]

**Goal**: Implementar avance manual/ponderado, hitos normalizados, documentos, historial y evidencia de cierre.

**Independent test criteria**: La fórmula ponderada es reproducible, agregar hitos redistribuye sin alterar cumplimientos, mini-tareas no ponderan y documentos/evidencias conservan historial.

**FR coverage**: FR-F01, FR-F02, FR-F03, FR-F04, FR-F05, FR-F06, FR-F07, FR-H01, FR-H02, FR-H03, FR-H04, FR-H05, FR-H06, FR-Q01, FR-Q02.

- [ ] T035 [US4] Implementar `Avance` y modos manual/ponderado en `tareas/models.py` y `tareas/services/progress.py`.
- [ ] T036 [US4] Implementar `Hito` con peso relativo, orden por fecha de creación y cálculo `sum(cumplimiento * peso) / sum(pesos)` en `tareas/services/progress.py`.
- [ ] T037 [US4] Implementar redistribución al agregar hitos sin alterar cumplimientos anteriores en `tareas/services/progress.py`.
- [ ] T038 [US4] Implementar tipos de documento, archivo/URL, fechas informativas, historial y evidencia configurable en `tareas/models.py` y `tareas/services/documents.py`.
- [ ] T039 [US4] Integrar evidencia, mini-tareas, descendientes y cotizaciones disponibles como validaciones de cierre en `tareas/services/closure.py`, sin resolver identidad de proveedor.
- [ ] T040 [US4] Añadir vistas, formularios y templates de hitos, avance, documentos y evidencia en `tareas/forms.py`, `tareas/views.py` y `tareas/templates/tareas/`.
- [ ] T041 [US4] Añadir tests de fórmula, redistribución, orden, archivos/URLs, historial, evidencia y bloqueos de cierre en `tareas/tests/test_progress.py` y `tareas/tests/test_documents.py`.
- [ ] T042 [US4] Preparar migraciones aditivas de avance, hitos, documentos y evidencia en `tareas/migrations/`, sin crear migraciones durante esta generación.
- [ ] T043 [US4] Validar escenarios E10 de `specs/001-tareas-internas/quickstart.md`.

## Phase 5: Quotations and blocked external provider boundary [US5]

**Goal**: Implementar rondas e histórico de cotizaciones hasta el límite exacto donde se requiere identidad real de proveedor.

**Independent test criteria**: Se pueden crear rondas, aplicar mínimo 3 por defecto, conservar la regla documentada de máximo 3 versiones por proveedor/ronda y bloquear cierre según la dependencia disponible; la validación efectiva por proveedor queda `DEFERRED — BLOQUEADA POR P2 LEGACY`, sin IDs temporales ni proveedores ficticios.

**FR coverage**: FR-I01 `[PARCIAL — IMPLEMENTABLE AHORA hasta ronda/mínimo]`, FR-I02 `[PARCIAL — regla documentada; validación DEFERRED POR P2]`, FR-I03 `[IMPLEMENTABLE AHORA]`, FR-I04 `[IMPLEMENTABLE AHORA]`, FR-I05 `[DEFERRED — BLOQUEADO POR P2 LEGACY]`, FR-I06 `[DEFERRED — BLOQUEADO POR P2 LEGACY]`, FR-I07 `[DEFERRED — BLOQUEADO POR P2 LEGACY]`, FR-I08 `[PARCIAL — cierre general ahora; conteo por proveedor DEFERRED POR P2]`, FR-J01 `[DEFERRED — BLOQUEADO POR P2 LEGACY]`, FR-J02 `[DEFERRED — BLOQUEADO POR P2 LEGACY]`, FR-J03 `[DEFERRED — BLOQUEADO POR P2 LEGACY]`, FR-J04 `[DEFERRED — BLOQUEADO POR P2 LEGACY]`, FR-J05 `[DEFERRED — BLOQUEADO POR P2 LEGACY]`, FR-Q03 `[PARCIAL — regla general de cierre implementable; contar proveedores distintos DEFERRED POR P2]`, FR-Q05 `[DEFERRED — BLOQUEADO POR P2 LEGACY]`.

- [ ] T044 [US5] Implementar `RondaCotizacion` con histórico, mínimo configurable por ronda y default 3 en `tareas/models.py` y `tareas/services/quotations.py`.
- [ ] T045 [US5] Implementar la estructura interna de `Cotizacion` sin identidad externa, junto con estados de ronda, fechas, observaciones y documentos asociados que no requieran proveedor real en `tareas/services/quotations.py`; documentar la regla de máximo 3 versiones por proveedor sin validarla.
- [ ] T046 [US5] Implementar la regla general de cierre por mínimo de cotizaciones y apertura de nuevas rondas en `tareas/services/closure.py` y `tareas/services/quotations.py`, deteniéndose antes de contar proveedores distintos o evaluar identidad real.
- [ ] T047 [US5] Detener la implementación de cotizaciones en `tareas/services/quotations.py` exactamente antes de requerir identidad real de proveedor; documentar el punto de bloqueo P2 en `specs/001-tareas-internas/contracts/web-urls.md`.
- [ ] T048 [US5] Mantener `ProveedorReferencia` únicamente como **PLACEHOLDER DE DISEÑO — IMPLEMENTACIÓN BLOQUEADA POR P2** en `specs/001-tareas-internas/data-model.md`; no crear modelo, campos, ID, endpoint, tabla, sincronización ni tarea adicional.
- [ ] T049 [US5] No implementar maestro, filtros de elegibilidad, endpoint ni sincronización de Local; conservar P1 como `LEGACY API PENDIENTE` (FR-A07, FR-R05) en la documentación de fase.
- [ ] T050 [US5] Añadir tests de rondas, mínimos, estados, fechas, observaciones, documentos asociados, histórico y bloqueo P2 en `tareas/tests/test_quotations.py`; no probar identidad, conteo o máximo efectivo por proveedor.
- [ ] T051 [US5] Preparar migraciones aditivas únicamente para la parte interna de cotizaciones en `tareas/migrations/`, sin modelar identidad legacy de proveedor y sin ejecutar migraciones durante esta generación.
- [ ] T052 [US5] Validar escenarios E11 de `specs/001-tareas-internas/quickstart.md` y registrar el bloqueo antes de identidad real de proveedor.

## Phase 6: Collaboration, similarity, links and dashboards [US6]

**Goal**: Integrar notificaciones/email existentes, reuniones, similitud histórica, enlaces autenticados y dashboards con ocho KPI.

**Independent test criteria**: Eventos críticos reutilizan los canales existentes, similitud usa 80% por empresa para evaluaciones nuevas, enlaces respetan ICMEAS/empresa y los ocho KPI son consistentes.

**FR coverage**: FR-K01, FR-K02, FR-K03, FR-K04, FR-L01, FR-L02, FR-L03, FR-L04, FR-L05, FR-L06, FR-L07, FR-M01, FR-M02, FR-M03, FR-M04, FR-M05, FR-M06, FR-M07, FR-N01, FR-N02, FR-N03, FR-N04, FR-N05, FR-N06, FR-N07, FR-N08, FR-N09, FR-O01, FR-O02, FR-O03, FR-O04, FR-P03, FR-P04, FR-P05.

- [ ] T053 [US6] Implementar adaptadores locales en `tareas/services/notifications.py` para consumir `notificaciones` y email de `acounts`, sin modificar esas apps ni crear subsistema paralelo.
- [ ] T054 [US6] Integrar notificaciones de asignación, lectura, comentarios, documentos, cambios, aprobación, anulación y reactivación en los servicios de `tareas/`.
- [ ] T055 [US6] Implementar `ReunionRevision` y relación con tareas en `tareas/models.py`, `tareas/services/meetings.py`, `tareas/forms.py` y vistas propias.
- [ ] T056 [US6] Implementar origen/derivación y `EvaluacionSimilitud` incluyendo tareas cerradas en `tareas/services/similarity.py`, manteniendo cada tarea nueva como registro separado.
- [ ] T057 [US6] Implementar `UmbralSimilitudEmpresa` con default 80%, autorización de cambios y aplicación solo a nuevas evaluaciones en `tareas/services/similarity.py`.
- [ ] T058 [US6] Implementar `EnlaceTarea` y auditoría de acceso en `tareas/services/links.py`, exigiendo autenticación, empresa activa, lectura e ICMEAS; no permitir usuarios externos.
- [ ] T059 [US6] Implementar dashboard usuario y jefatura/general en `tareas/services/kpi.py` y `tareas/views.py` con exactamente ocho KPI en las dimensiones ACTIVAS General, Empresa, Departamento, Usuario y Tarea; Local queda DEFERRED por P1 y Proveedor DEFERRED por P2.
- [ ] T060 [US6] Implementar templates propios de reuniones, similitud, enlaces y dashboards en `tareas/templates/tareas/`, con DataTables/modal según contrato y `data-key`.
- [ ] T061 [US6] Añadir tests con mocks de notificaciones/email, reuniones, similitud 80%/por empresa, enlaces cross-company y ocho KPI por dimensión en `tareas/tests/test_collaboration.py`, `tareas/tests/test_similarity.py` y `tareas/tests/test_kpi.py`.
- [ ] T062 [US6] Preparar migraciones aditivas de colaboración, similitud, enlaces y configuración de umbral en `tareas/migrations/`, sin tocar proveedores/locales ni ejecutar migraciones durante esta generación.
- [ ] T063 [US6] Validar escenarios E12–E13 de `specs/001-tareas-internas/quickstart.md`, manteniendo Local/Proveedor bloqueados en drill-down.

## Phase 7: Polish and cross-cutting validation

**Purpose**: Cerrar trazabilidad, seguridad, compatibilidad y documentación sin ampliar alcance.

- [ ] T064 [P] Actualizar claves i18n nuevas en documentación de `specs/001-tareas-internas/contracts/web-urls.md`; cualquier edición de diccionarios globales queda bloqueada y requiere autorización separada.
- [ ] T065 [P] Ejecutar revisión de permisos ICMEAS, empresa activa, aislamiento, respuestas controladas y ausencia de exposición de credenciales en `tareas/`.
- [ ] T066 [P] Revisar que ningún archivo de `tareas/` importe o modifique `static/js/app.js`, `common/utils.py`, `api/Router_Databases.py` u otra infraestructura protegida.
- [ ] T067 Ejecutar la suite completa `python manage.py test --settings=AppDocs.settings_test` y `python manage.py check` después de implementar las fases autorizadas.
- [ ] T068 Ejecutar `git diff --check` y revisar el diff completo; detenerse si aparece cualquier cambio fuera de `tareas/` o de documentación autorizada.
- [ ] T069 Confirmar en `specs/001-tareas-internas/quickstart.md` los escenarios ejecutados y mantener P1/P2 como bloqueos explícitos hasta autorización de sus contratos.

## Success criteria traceability

Esta matriz define qué tareas y escenarios deberán validar cada criterio. La presencia de
una referencia no significa que el criterio ya esté ejecutado o aprobado.

| Success Criterion | Tareas / escenario de validación | Estado |
|---|---|---|
| SC-001 | T006-T013 / E1 | Pendiente de ejecución |
| SC-002 | T010-T013 / E3 | Pendiente de ejecución |
| SC-003 | T011-T013 / E6 | Pendiente de ejecución |
| SC-004 | T010-T013 / E1-E4 | Pendiente de ejecución |
| SC-005 | T008-T013 / E2 | Pendiente de ejecución |
| SC-006 | T017-T024, T031, T039, T046 / E8-E11 | Pendiente de ejecución; P2 limita validaciones por proveedor |
| SC-007 | T053-T055, T061 / E12 | Pendiente de ejecución |
| SC-008 | T059-T063 / E13 | Pendiente de ejecución; Local/Proveedor deferred |
| SC-009 | T056-T057, T061 / E12 | Pendiente de ejecución |
| SC-010 | T014-T015, T022 / E8 | Pendiente de ejecución |

## Functional blocks to user stories matrix

| Spec block | User story | Technical phase |
|---|---|---|
| A. Identidad, correlativos y contexto | US1, US2 | Phase 1, Phase 2 |
| B. Tipos y clasificación | US1, US3, US6 | Phase 1, Phase 3, Phase 6 |
| C. Ciclo de vida y cierre | US2, US3, US4 | Phase 2, Phase 3, Phase 4 |
| D. Asignación, responsables y participantes | US3 | Phase 3 |
| E. Jerarquía de trabajo | US3 | Phase 3 |
| F. Avance, hitos y mini-tareas | US3, US4 | Phase 3, Phase 4 |
| G. Fechas, atrasos y reprogramación | US3 | Phase 3 |
| H. Documentos y evidencias | US4 | Phase 4 |
| I. Cotizaciones | US5 | Phase 5; límite P2 |
| J. Proveedores | US5 | Phase 5; todo deferred por P2 |
| K. Notificaciones y email | US6 | Phase 6 |
| L. Dashboards y KPI | US6 | Phase 6; dimensiones activas/deferred explícitas |
| M. Reuniones de revisión | US6 | Phase 6 |
| N. Origen, derivación y similitud | US6 | Phase 6 |
| O. Equipos / máquinas | US2, US3 | Phase 2, Phase 3 |
| P. Seguridad, multiempresa y enlaces | US1, US3, US6 | Phase 1, Phase 3, Phase 6 |
| Q. Reglas de cierre | US2, US3, US4, US5 | Phase 2-5; P2 limita proveedor |
| R. Exclusiones actuales | US1, US5, US6 | Phases 1, 5, 6; constraints |

## KPI dimensions boundary

- **ACTIVAS AHORA**: General, Empresa, Departamento, Usuario y Tarea.
- **DEFERRED**: Local por P1; Proveedor por P2.
- El catálogo es cerrado: total por estado, atrasadas, próximas a vencer, sin movimiento,
  esperando aprobación, carga abierta por responsable, porcentaje de cumplimiento y tiempo
  promedio de cierre.

## Dependencies and execution order

### Phase dependencies

- Phase 0: sin dependencia de implementación; establece baseline y límites.
- Phase 1: depende de Phase 0; preserva y prepara el MVP.
- Phase 2: depende de Phase 1; habilita estados, correlativos y auditoría.
- Phase 3: depende de Phase 2; usa ciclo, auditoría y cierre.
- Phase 4: depende de Phase 3; usa avance, mini-tareas y cierre.
- Phase 5: depende de Phase 4; se detiene antes de identidad real de proveedor.
- Phase 6: depende de Phase 2 y de los servicios de cierre/consulta disponibles; Local/Proveedor permanecen bloqueados.
- Phase 7: depende de las fases implementadas y autorizadas.

### Parallel opportunities

- T002–T005 pueden ejecutarse en paralelo como auditorías/documentación independientes.
- T010–T012 pueden ejecutarse en paralelo después de estabilizar los contratos MVP.
- T016, T020 y T021 pueden paralelizarse por archivos tras definir estados.
- T025–T027 pueden paralelizarse con T030 y T031 una vez establecida la base de Phase 3.
- T035–T038 pueden paralelizarse por dominio, antes de T039.
- T044–T046 pueden paralelizarse por ronda, cotización y cierre; T047 es el checkpoint obligatorio.
- T053–T058 pueden paralelizarse por integración; T059–T060 dependen de los contratos de lectura.
- T064–T066 son revisiones independientes antes del cierre T067–T069.

## Blocked tasks and authorization boundaries

- No hay tareas de implementación para P1 Local.
- No hay tareas de implementación para P2, `ProveedorReferencia` o identidad externa de proveedor.
- T047–T052 son el límite bloqueado de cotizaciones frente a P2.
- Cualquier modificación futura adicional en `AppDocs/app_classification.py`, `AppDocs/settings.py` o `AppDocs/urls.py` requiere autorización expresa; su alta inicial ya está resuelta y no es tarea pendiente.
- Cualquier modificación futura de otras apps, templates globales, diccionarios i18n globales o infraestructura requiere autorización expresa y detención previa.

## Implementation strategy

1. Ejecutar Phase 0 y conservar la regresión MVP.
2. Implementar Phase 1 y validar correlativos/estados/auditoría antes de seguir.
3. Entregar Phase 2–4 como incrementos independientes de dominio.
4. Implementar cotizaciones solo hasta T047; no cruzar el límite P2.
5. Implementar colaboración, similitud, enlaces y KPI con mocks y aislamiento por empresa.
6. Ejecutar Polish y regresión completa únicamente después de implementar fases autorizadas.

**Suggested MVP scope**: Phase 0 + Phase 1, preservando la funcionalidad MVP existente y entregando correlativos A/B, ciclo de vida auditable y compatibilidad multiempresa/ICMEAS.

**Test criteria by story**:

- US1: Fase 1 MVP compatible y regresión de borrador/publicada.
- US2: correlativos, estados, cierre, anulación/reactivación y auditoría.
- US3: participantes, jerarquía, fechas, reprogramación y mini-tareas.
- US4: avance, hitos, documentos y evidencia.
- US5: rondas/mínimos de cotización hasta el bloqueo de identidad P2.
- US6: colaboración, similitud, enlaces y ocho KPI.
