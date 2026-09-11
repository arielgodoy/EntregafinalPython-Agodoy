# Tasks: Control de acceso VICMEAS

## Phase 0: Gobernanza y baseline

- [x] T001 Confirmar la constitución publicada en `HEAD` y su versión local.
- [x] T002 Leer el índice operativo y los artefactos arquitectónicos obligatorios.
- [x] T003 Verificar que `specs/001-tareas-internas` permanece sin cambios.

## Phase 1: Contrato funcional

- [x] T004 Documentar la separación entre `ver` e ICMEAS en `spec.md`.
- [x] T005 Documentar el comportamiento uniforme de superusuarios.
- [x] T006 Documentar aislamiento por empresa, idempotencia y operaciones sensibles.

## Phase 2: Diseño y trazabilidad

- [x] T007 Registrar decisiones verificadas en `research.md`.
- [x] T008 Registrar entidades e invariantes en `data-model.md`.
- [x] T009 Registrar el plan conservador y límites de cambio en `plan.md`.

## Phase 3: Verificación

- [x] T010 Ejecutar pruebas focalizadas de sidebar y autorización.
- [x] T011 Ejecutar pruebas del utilitario de acceso y bootstrap cuando corresponda.
- [x] T012 Ejecutar `git diff --check` y revisar alcance del diff.

## Phase 4: Estado as-built

- [x] T013 VICMEAS, sidebar recursivo, profundidad arbitraria e i18n del sidebar están
	implementados y cubiertos por pruebas existentes.
- [x] T014 La separación `V`/`I`, el comportamiento de `is_superuser`, los utilitarios,
	bootstrap y dry-run están implementados y documentados con evidencia.
- [x] T015 Registrar contratos de `inicializar_sistema`, dry-run, asignación masiva y
	ocultamiento de vistas sin inventar REST API.
- [x] T016 Registrar la matriz requisito/código/test en `as-built.md`.

## Follow-ups no bloqueantes

- [ ] T017 Normalizar `Vista.route_name` NULL y vistas legacy ambiguas cuando exista una
	migración o limpieza autorizada.
- [ ] T018 Consolidar mappings de menús legacy con el árbol recursivo canónico.
- [ ] T019 Completar i18n de templates internos y retirar labels fallback temporales.
- [ ] T020 Registrar y aislar cualquier prueba flaky futura; no existe una identificada
	como vigente en esta revisión.

## Trazabilidad

| Requisito | Diseño | Validación |
|---|---|---|
| FR-001/FR-002 | D1/D2 | tests de sidebar y permisos |
| FR-003 | D2 | tests de mixin |
| FR-004 | D5 | tests multiempresa del utilitario |
| FR-005/FR-006 | D4 | tests de `test_access_utility` |
| FR-007 | D4 | tests de acciones sensibles |

Los tasks T001-T016 corresponden al cierre y estado ya construido; T017-T020 son deuda
futura y no bloquean la feature documentada.