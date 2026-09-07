---

description: "Task list for feature implementation"
---

# Tasks: Tareas Internas

**Input**: Design documents from `/specs/001-tareas-internas/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: La spec no solicita TDD, pero la constitución (Principio VII) exige tests focalizados. Se incluyen tareas de test DESPUÉS de la implementación de cada historia (no test-first).

**Organization**: Tasks agrupadas por user story para implementación y prueba independiente.

**Bloqueo transversal (Constitución III)**: T003–T005 modifican archivos CORE/SYSTEM
(`AppDocs/app_classification.py`, `AppDocs/settings.py`, `AppDocs/urls.py`) y **NO pueden
ejecutarse hasta obtener autorización expresa del usuario**. Ninguna tarea posterior puede
verificarse con `runserver`/tests de vistas hasta completar T003–T005.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Inicialización de la nueva APPLICATION_APP `tareas` y su registro (registro bloqueado por autorización)

- [X] T001 Crear estructura de la app `tareas`: tareas/__init__.py, tareas/apps.py (TareasConfig, name="tareas"), tareas/admin.py (archivo estándar vacío, sin registro requerido), tareas/migrations/__init__.py, tareas/tests/__init__.py, tareas/templates/tareas/
- [X] T002 [P] Crear módulos base vacíos con docstring de propósito: tareas/models.py, tareas/forms.py, tareas/views.py, tareas/urls.py (app_name = 'tareas')
- [X] T003 ✅ AUTORIZADA Y EJECUTADA 2026-09-07 — agregar "tareas" a APPLICATION_APPS en AppDocs/app_classification.py. Alcance exacto autorizado: únicamente añadir "tareas" a la tupla APPLICATION_APPS. Autorización expresa otorgada por el usuario el 2026-09-07.
- [X] T004 ✅ AUTORIZADA Y EJECUTADA 2026-09-07 — agregar "tareas" a INSTALLED_APPS en AppDocs/settings.py. Alcance exacto autorizado: únicamente añadir 'tareas' a INSTALLED_APPS. Autorización expresa otorgada por el usuario el 2026-09-07.
- [X] T005 ✅ AUTORIZADA Y EJECUTADA 2026-09-07 — agregar path('tareas/', include('tareas.urls', namespace='tareas')) en AppDocs/urls.py. Alcance exacto autorizado: únicamente esa línea de include. Autorización expresa otorgada por el usuario el 2026-09-07.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Modelo de datos y migración que todas las historias requieren. DEBE completarse antes de cualquier user story.

- [X] T006 Implementar modelo Tarea en tareas/models.py según specs/001-tareas-internas/data-model.md: campos titulo, descripcion, prioridad (choices aprobados SIMPLE/NORMAL/URGENTE/CRITICA; jerarquía crítica > urgente > normal > simple; default NORMAL aprobado por el usuario; sin comportamientos adicionales por prioridad), estado (choices BORRADOR/PUBLICADA, default BORRADOR), responsable (FK auth.User, null/blank, PROTECT, related_name="tareas_responsable"), empresa (FK access_control.Empresa, PROTECT, related_name="tareas"), creada_por (FK auth.User, PROTECT, related_name="tareas_creadas"), fecha_creacion (auto_now_add), fecha_publicacion (null/blank); índices (empresa, estado) y (empresa, fecha_creacion); clean() SOLO con reglas respaldadas por spec/clarifications: publicada requiere responsable válido/activo (FR-007/FR-008, Q1), fecha_publicacion fijada e inmutable (FR-008), sin transición PUBLICADA→BORRADOR (Q2), empresa asignada al crear y no editable desde el request (FR-003)
- [X] T007 Implementar método publicar() del modelo en tareas/models.py: valida responsable asignado y activo (is_active=True), fija estado=PUBLICADA y fecha_publicacion=timezone.now(); lanza ValidationError sin persistir si el responsable falta o es inválido
- [X] T008 ✅ COMPLETADA 2026-09-07 — Migración inicial generada con autorización expresa (alcance original: solo GENERAR `0001_initial.py` con `makemigrations`, verificado con `manage.py check`). Posteriormente el **usuario** aplicó las migraciones en el **entorno local** (no producción) para levantar y probar la app. Verificación 2026-09-07: `tareas.0001_initial` figura como aplicada en la base local y **no quedan migraciones pendientes** en la base local. (La generación fue autorizada a Copilot; la aplicación local fue realizada por el usuario, no por Copilot.)
- [X] T009 [P] Tests de modelo en tareas/tests/test_models.py: crear con solo título queda en BORRADOR; publicar sin responsable falla (ValidationError); publicar con responsable inactivo falla (Q1); publicar con responsable activo fija estado y fecha_publicacion (FR-008); edición post-publicación sin responsable válido falla; transición PUBLICADA→BORRADOR imposible (Q2); prioridad acepta únicamente los valores aprobados (simple/normal/urgente/crítica) y su default es NORMAL (aprobado)

**Checkpoint**: modelo + migración listos; ninguna user story puede comenzar sin esto.

---

## Phase 3: User Story 1 — Crear y mantener borradores de tareas (Priority: P1) 🎯 MVP

**Goal**: Un usuario autorizado crea una tarea con solo título; nace en borrador asociada a la empresa activa y puede editarla indefinidamente sin publicarla.

**Independent Test**: Crear una tarea con solo título → aparece en el listado como borrador con fecha de creación y empresa activa; editarla → permanece en borrador sin fecha de publicación.

### Implementation for User Story 1

- [X] T010 [US1] Implementar TareaForm en tareas/forms.py: campos titulo (requerido), descripcion, prioridad (choices SIMPLE/NORMAL/URGENTE/CRITICA según definición aprobada; sin default presupuesto), responsable (opcional); excluir estado, empresa, creada_por, fecha_publicacion del formulario; validación que delega en model.clean()
- [X] T011 [US1] Implementar CrearTareaView (VerificarPermisoMixin, LoginRequiredMixin, CreateView) en tareas/views.py: vista_nombre="Tareas - Crear tarea", permiso_requerido="crear"; asigna empresa desde request.session["empresa_id"] y creada_por desde request.user en form_valid; redirect a detalle
- [X] T012 [US1] Implementar ListarTareasView (VerificarPermisoMixin, LoginRequiredMixin, ListView) en tareas/views.py: vista_nombre="Tareas - Listado", permiso_requerido="ingresar"; get_queryset filtra por session["empresa_id"], ordena por fecha_creacion descendente; contexto distingue borradores/publicadas
- [X] T013 [US1] Implementar DetalleTareaView (VerificarPermisoMixin, LoginRequiredMixin, DetailView) en tareas/views.py: vista_nombre="Tareas - Detalle", permiso_requerido="ingresar"; get_queryset filtrado por empresa activa (404 si pertenece a otra empresa)
- [X] T014 [US1] Implementar EditarTareaView (VerificarPermisoMixin, LoginRequiredMixin, UpdateView) en tareas/views.py: vista_nombre="Tareas - Editar tarea", permiso_requerido="modificar"; queryset filtrado por empresa activa; mantiene empresa/creada_por originales
- [X] T015 [US1] Registrar rutas en tareas/urls.py según contracts/web-urls.md: listar_tareas, detalle_tarea, crear_tarea, editar_tarea (publicar se agrega en US2)
- [X] T016 [P] [US1] Crear template tareas/templates/tareas/tarea_lista.html extendiendo el layout base vigente (base.html + sidebar/topbar), textos con data-key, tabla con columnas título/prioridad/estado/responsable/fecha_creacion, sin decisiones de paginación no requeridas
- [X] T017 [P] [US1] Crear template tareas/templates/tareas/tarea_form.html extendiendo el layout base, campos del TareaForm con data-key, errores de campo visibles, POST tradicional (no AJAX)
- [X] T018 [P] [US1] Crear template tareas/templates/tareas/tarea_detalle.html extendiendo el layout base, muestra todos los campos con data-key, placeholders para acciones (publicar se conecta en US2)
- [X] T019 [US1] Tests de vistas US1 en tareas/tests/test_views.py: crear con solo título guarda BORRADOR con empresa de sesión y fecha_creacion; editar borrador persiste cambios sin fecha_publicacion; queryset excluye tareas de otras empresas; sin permiso ICMEAS se reproduce exactamente el comportamiento vigente del sistema (verificado previamente en access_control/decorators.py y vistas existentes); ausencia de empresa activa → comportamiento vigente del decorador verificar_permiso (verificado en código, no asumido)
- [X] T020 [US1] Tests de formulario en tareas/tests/test_forms.py: titulo requerido; responsable opcional en borrador; prioridad rechaza valores fuera de simple/normal/urgente/crítica; default de prioridad es NORMAL (aprobado)

**Checkpoint**: US1 completamente funcional y testeable de forma independiente (crear/listar/ver/editar borradores).

---

## Phase 4: User Story 2 — Publicar tareas (Priority: P2)

**Goal**: Publicar un borrador exige responsable válido; al publicar se registra fecha de publicación y la tarea pasa a publicada (irreversible).

**Independent Test**: Publicar borrador sin responsable → rechazado con mensaje claro, permanece borrador; publicar borrador con responsable activo → publicada con fecha_publicacion registrada; publicar con responsable desactivado → rechazado.

### Implementation for User Story 2

- [X] T021 [US2] Implementar PublicarTareaView (VerificarPermisoMixin, LoginRequiredMixin, View) en tareas/views.py: vista_nombre="Tareas - Publicar tarea", permiso_requerido="modificar"; POST invoca tarea.publicar(); éxito → redirect a detalle con mensaje de éxito; ValidationError → respuesta con mensaje claro (tarea permanece BORRADOR); 404 si la tarea es de otra empresa
- [X] T022 [US2] Agregar ruta publicar_tarea en tareas/urls.py según contracts/web-urls.md
- [X] T023 [US2] Conectar botón Publicar en tareas/templates/tareas/tarea_detalle.html: visible solo cuando estado=BORRADOR; POST con CSRF; mensajes de éxito/error visibles; sin acción de retorno a borrador en publicadas
- [X] T024 [US2] Tests de publicación en tareas/tests/test_views.py: publicar sin responsable → rechazo y permanece borrador; publicar con responsable inactivo → rechazo (Clarification Q1); publicar con responsable activo → PUBLICADA con fecha_publicacion; publicar tarea ya publicada → sin efecto/error controlado; publicar tarea de otra empresa → 404; sin permiso modificar → 403

**Checkpoint**: US2 funcional e independientemente testeable; ciclo borrador → publicada completo.

---

## Phase 5: User Story 3 — Gestionar tareas por empresa y permisos (Priority: P3)

**Goal**: El listado y las operaciones quedan estrictamente acotados a la empresa activa; el acceso se rige por ICMEAS con vistas visibles en el menú y 403 con solicitud de acceso.

**Independent Test**: Con dos empresas, al cambiar la empresa activa el listado solo muestra tareas de la nueva empresa; usuario sin permiso de ingreso recibe 403 con página de solicitud de acceso; acceso directo a tarea de otra empresa → 404.

### Implementation for User Story 3

- [X] T025 [US3] Verificar/reforzar aislamiento en tareas/views.py: todas las vistas (lista, detalle, editar, publicar) filtran por session["empresa_id"]. Para ausencia de empresa activa y denegación de permiso, reutilizar EXACTAMENTE el comportamiento vigente del sistema (VerificarPermisoMixin / decorador verificar_permiso), previamente verificado en el código de access_control y en vistas existentes; NO inventar respuestas 403/redirect ni contextos propios
- [X] T026 [US3] ✅ VERIFICACIÓN COMPLETADA 2026-09-07 (solo lectura, sin cambios de código). Resultado:
  - **Registro de Vista**: una Vista se auto-crea al primer acceso a la vista protegida — el decorador `verificar_permiso` ([access_control/decorators.py:67-69](access_control/decorators.py)) hace `Vista.objects.get_or_create(nombre=vista_nombre)` si no existe. No requiere seed/alta explícita. Las 5 vistas de `tareas` ("Tareas - Listado/Detalle/Crear/Editar/Publicar") se auto-crean en el primer acceso autenticado.
  - **Menú**: la aparición en el sidebar NO depende de Vista sino de entradas hardcodeadas en `templates/partials/sidebar.html`. `get_navigable_vistas`/`get_user_navigable_vistas` (access_control/services/empresa_activa.py) se usan para "vista inicial del usuario"/preferencias, NO para poblar el menú principal.
  - **¿`tareas` aparece en el menú?**: NO. `templates/partials/sidebar.html` no tiene entrada para `tareas`; la app solo es accesible por URL directa.
  - **Qué habría que tocar para mostrarla en el menú**: `templates/partials/sidebar.html` (agregar bloque de navegación). Es un **template global protegido** (listado en AGENTS.md como archivo base protegido).
  - **SYSTEM/CORE**: `templates/partials/sidebar.html` es template global protegido → cualquier edición requiere **autorización expresa del usuario**. No se modificó.
  - **INTEGRACIÓN MENÚ IMPLEMENTADA 2026-09-07** (autorización expresa otorgada): se agregó el bloque "Menú Tareas" en `templates/partials/sidebar.html` tras "Control Operacional", siguiendo el patrón visual de las demás APPLICATION_APPS (li.nav-item > a.menu-link + div.collapse.menu-dropdown > ul.nav > li.nav-item), usando el namespace `tareas:` existente y data-key i18n (`menu.tareas`, `menu.tareas.list`, `menu.tareas.create`). Entradas: "Listado de Tareas" (`tareas:listar_tareas`) y "Crear Tarea" (`tareas:crear_tarea`). Validación: 4/4 tests de dashboard OK, `git diff --check` limpio. No se tocó access_control ni otras apps.
- [X] T027 [US3] Tests de aislamiento y permisos en tareas/tests/test_views.py: dos empresas → listado muestra solo tareas de la empresa activa; cambio de empresa activa cambia el contenido del listado; acceso directo a tarea de otra empresa → 404; usuario sin Permiso.ingresar → respuesta de acceso denegado vigente del sistema (la exactamente verificada en access_control); sin empresa activa → comportamiento vigente verificado del decorador (no asumido)

**Checkpoint**: US3 funcional; aislamiento multiempresa e ICMEAS verificados end-to-end.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Mejoras transversales que afectan a múltiples historias

- [X] T028 [P] ✅ COMPLETADA 2026-09-07 — Se reportaron las claves i18n nuevas y se agregaron las 30 claves actualmente usadas (3 `menu.tareas.*` + 27 `tareas.*`) a `static/lang/sp.json` y `static/lang/en.json`. La edición de ambos diccionarios fue autorizada expresamente por el usuario. Las 2 claves `tareas.publish.*` NO se agregaron porque todavía no son consumidas por el código (solo documentadas en contracts). Ambos JSON fueron validados como parseables; `git diff --check` limpio.
- [X] T029 [P] Ejecutar suite de tests focalizada: `python manage.py test tareas --settings=AppDocs.settings_test` y `python manage.py check`. Los fallos dentro del alcance autorizado pueden corregirse; cualquier fallo que requiera ampliar alcance o modificar archivos SYSTEM/CORE debe REPORTARSE y DETENERSE hasta obtener nueva autorización expresa del usuario
- [X] T030 Ejecutar regresiones relacionadas: tests de access_control y dashboard (menú) con `--settings=AppDocs.settings_test` para verificar que el registro de la app no rompe nada
- [X] T031 Verificación de cierre: `git diff --check` y revisión del diff completo; confirmar que los únicos cambios CORE son los autorizados en T003–T005; SIN commit ni push sin autorización expresa del usuario
- [ ] T032 Ejecutar escenarios manuales E1–E7 de specs/001-tareas-internas/quickstart.md con el servidor local y registrar resultados

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias — pero T003–T005 bloqueadas por autorización expresa
- **Foundational (Phase 2)**: depende de T001–T005; bloquea todas las user stories
- **User Story 1 (Phase 3)**: depende de Phase 2
- **User Story 2 (Phase 4)**: depende de Phase 2 (usa modelo/publicar); integrable tras US1
- **User Story 3 (Phase 5)**: depende de Phase 2; refuerza vistas de US1/US2
- **Polish (Phase 6)**: depende de todas las stories completadas

### User Story Dependencies

- **US1 (P1)**: sin dependencias de otras stories → MVP
- **US2 (P2)**: requiere el modelo (Foundational) y las vistas base (US1) para exponer la acción
- **US3 (P3)**: transversal a US1/US2; no introduce vistas nuevas, solo garantías

### Within Each User Story

- Modelo/migración (Foundational) → vistas → urls → templates → tests
- Tests se escriben después de la implementación de la story (constitución VII: tests focalizados, no TDD obligatorio)

### Parallel Opportunities

- T002 puede ejecutarse en paralelo con T001 (archivos distintos)
- T009 (tests de modelo) tras T006–T007, en paralelo con vistas US1 una vez migrado
- T016, T017, T018 (templates) en paralelo entre sí
- T028, T029 en paralelo (reportes/tests distintos)
- US2 y US3 pueden desarrollarse en paralelo tras US1 si hay dos desarrolladores

---

## Parallel Example: User Story 1

```text
# Lanzar los tres templates juntos (archivos distintos):
Task: T016 tarea_lista.html
Task: T017 tarea_form.html
Task: T018 tarea_detalle.html

# Tests tras vistas:
Task: T019 test_views.py (US1)  ∥  Task: T020 test_forms.py
```

## Parallel Example: User Story 2

```text
Task: T021 PublicarTareaView (views.py) → T022 urls.py → T023 botón en template
Task: T024 tests de publicación (tras T021)
```

## Parallel Example: User Story 3

```text
Task: T025 aislamiento en views.py  ∥  T026 verificación menú ICMEAS (solo lectura)
Task: T027 tests de aislamiento (tras T025)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Completar Phase 1: Setup (T001–T002; T003–T005 tras autorización expresa)
2. Completar Phase 2: Foundational (T006–T009)
3. Completar Phase 3: User Story 1 (T010–T020)
4. **STOP and VALIDATE**: tests de US1 + escenarios E1–E2 de quickstart.md
5. Valor entregado: registro y edición de borradores multiempresa con ICMEAS

### Incremental Delivery

1. Setup + Foundational → base lista
2. US1 → validar independientemente → MVP
3. US2 → validar publicación (E3–E5) → incremento 2
4. US3 → validar aislamiento/permisos (E6–E7) → feature completa
5. Polish → cierre (sin commit/push sin autorización)

### Notas de gobernanza

- T003–T005 y T031: ninguna modificación SYSTEM/CORE ni commit/push sin autorización expresa del usuario (constitución III, VII).
- Eliminación de tareas: FUERA DE ALCANCE (FR-012/FR-013); no existe tarea de eliminación.
- `static/js/app.js`: vendor inmutable; no existe tarea que lo toque. JavaScript propio solo si una necesidad concreta surge durante la implementación.
- `admin.py`: archivo estándar creado en T001; sin registro requerido por esta feature.
