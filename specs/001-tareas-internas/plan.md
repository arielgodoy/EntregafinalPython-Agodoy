# Implementation Plan: Tareas Internas

**Branch**: `001-tareas-internas` | **Date**: 2026-09-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-tareas-internas/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Funcionalidad inicial de tareas internas: CRUD parcial con ciclo borrador → publicada
(publicación irreversible que exige responsable válido), aislamiento por empresa activa
en sesión y control de acceso ICMEAS. Se implementa como una nueva APPLICATION_APP
`tareas`, reutilizando los patrones vigentes: CBV con `VerificarPermisoMixin`,
`LoginRequiredMixin`, scoping por `session['empresa_id']` y templates que extienden el
layout base con `data-key`.

La eliminación de tareas NO forma parte de esta primera spec (FUERA DE ALCANCE).

El registro transversal de la app (`AppDocs/app_classification.py`, `INSTALLED_APPS` en
`AppDocs/settings.py`, include en `AppDocs/urls.py`) se identifica como cambio
probablemente necesario, pero queda **PENDIENTE DE AUTORIZACIÓN EXPRESA DEL USUARIO
ANTES DE IMPLEMENTAR**. No existe autorización vigente para modificar archivos
SYSTEM/CORE.

## Technical Context

**Language/Version**: Python 3.11 (entorno local vigente) / Django 5.1.3

**Primary Dependencies**: Django 5.1.3 (CBV, ORM, forms), access_control (ICMEAS), layout base de templates vigente. Sin dependencias nuevas; sin Bootstrap modal (no hay necesidad funcional que lo requiera en esta spec).

**Storage**: Según `COPILOT/ESTADO_ACTUAL.md`: alias `default` = SQLite local clasificado SYSTEM; existe alias `DB_sistema` MySQL configurado por variables de entorno. La disponibilidad/base productiva efectiva depende del entorno y NO se infiere de los defaults locales. La feature usa la base SYSTEM que corresponda según la arquitectura/router vigente (`api.Router_Databases.MultiDatabaseRouter`), sin definir router propio ni presuponer un motor productivo.

**Testing**: Django test framework con `--settings=AppDocs.settings_test`; tests focalizados en `tareas/tests/`.

**Target Platform**: Web server-side rendered (templates Django), misma plataforma del sistema vigente.

**Project Type**: Módulo web dentro del proyecto Django multiempresa existente.

**Performance Goals**: No existen objetivos de rendimiento adicionales definidos para esta primera spec.

**Constraints**: Constitución v1.0.0 — sin cambios en SYSTEM_APPS salvo autorización expresa (NO otorgada; el registro de la app en archivos CORE queda pendiente de autorización antes de implementar); `static/js/app.js` inmutable; multiempresa e ICMEAS obligatorios; sin cambios de settings/infraestructura sin autorización.

**Scale/Scope**: Una app nueva (`tareas`), un modelo (`Tarea`), 5 vistas CBV, 3 templates, 1 form. Sin eliminación en esta versión.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Resultado |
|---|---|---|
| I. Arquitectura existente es la referencia | Se reutilizan patrones vigentes (CBV + ICMEAS + scoping sesión + layout base + patrón de eliminación). Sin arquitectura nueva. | PASS |
| II. Documentación contextual mínima | Se consultó `COPILOT/INDICE.md`, `ESTADO_ACTUAL.md`, `ARQUITECTURA_APPS.md`, `REGLAS_CODIGO_VENDOR.md`. Sin lectura de histórico. | PASS |
| III. Clasificación y protección de apps | Nueva APPLICATION_APP `tareas`. Se identificaron posibles cambios transversales en `AppDocs/app_classification.py`, `AppDocs/settings.py` y `AppDocs/urls.py` (archivos CORE/SYSTEM) que **NO están autorizados todavía**: ninguna modificación a archivos SYSTEM/CORE puede ejecutarse hasta obtener autorización expresa del usuario. | PASS (gate condicionado: implementación bloqueada hasta autorización) |
| IV. Código vendor inmutable | `static/js/app.js` no se toca. JS propio en `tareas/static/tareas/js/`. | PASS |
| V. Multiempresa y permisos ICMEAS | Modelo con FK a `access_control.Empresa`; vistas con `VerificarPermisoMixin` + `LoginRequiredMixin`; queryset filtrado por `session['empresa_id']`; 403 con `access_control/403_forbidden.html`. | PASS |
| VI. Cambios mínimos y focalizados | Alcance: 1 app nueva autocontenida. Cambios transversales de registro identificados pero pendientes de autorización. Sin refactors ni eliminación. | PASS |
| VII. Tests y verificación de cierre | Tests focalizados en `tareas/tests/` con `settings_test`; `git diff --check` antes de cierre; sin commit/push sin autorización. | PASS |
| VIII. Specs orientadas al QUÉ | spec.md define comportamiento sin decidir implementación; este plan define el CÓMO adaptado a la arquitectura. | PASS |
| IX. Trazabilidad spec → plan → tasks | FR-001…FR-013 mapean a modelo/vistas/tests en data-model.md y serán descompuestos en tasks.md. | PASS |

**Resultado del gate**: PASS con condición — la implementación de los cambios transversales
de registro (app_classification, settings, urls) queda bloqueada hasta obtener autorización
expresa del usuario. Sin violaciones que justificar (Complexity Tracking vacío).

## Project Structure

### Documentation (this feature)

```text
specs/001-tareas-internas/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   └── web-urls.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
tareas/                                  # NUEVA APPLICATION_APP
├── __init__.py
├── apps.py                              # TareasConfig
├── admin.py                             # archivo estándar de app Django; sin trabajo requerido por esta feature
├── models.py                            # Tarea
├── forms.py                             # TareaForm
├── views.py                             # CBV con VerificarPermisoMixin (sin eliminar)
├── urls.py                              # app_name = 'tareas'
├── migrations/
│   └── __init__.py                      # migración inicial generada por makemigrations
├── templates/
│   └── tareas/
│       ├── tarea_lista.html             # listado borradores/publicadas
│       ├── tarea_form.html              # crear/editar
│       └── tarea_detalle.html           # detalle + botón publicar
└── tests/
    ├── __init__.py
    ├── test_models.py                   # reglas borrador/publicada
    ├── test_views.py                    # ICMEAS, multiempresa, publicación
    └── test_forms.py                    # validaciones de formulario

# Nota: NO se presupone JavaScript propio (p. ej. tareas/static/tareas/js/). Solo se crea
# si durante la implementación surge una necesidad concreta. static/js/app.js permanece
# vendor inmutable.

# Registro transversal — PENDIENTE DE AUTORIZACIÓN EXPRESA ANTES DE IMPLEMENTAR:
# (la elección de app nueva NO autoriza estos cambios)
# AppDocs/app_classification.py            # + "tareas" en APPLICATION_APPS
# AppDocs/settings.py                      # + "tareas" en INSTALLED_APPS (línea única)
# AppDocs/urls.py                          # + path('tareas/', include('tareas.urls', namespace='tareas'))
```

**Structure Decision**: Nueva app Django autocontenida `tareas` (APPLICATION_APP) siguiendo la
organización por capas vigente en las demás apps del proyecto (models/forms/views/urls/templates/
tests dentro de la app). No se presupone JavaScript propio; solo se creará si la implementación
lo requiere concretamente. `static/js/app.js` permanece vendor inmutable. Los cambios
transversales de registro (`AppDocs/app_classification.py`, `AppDocs/settings.py`,
`AppDocs/urls.py`) se identifican como posiblemente necesarios, **NO están autorizados** y
ninguna modificación a archivos SYSTEM/CORE puede ejecutarse hasta obtener autorización
expresa del usuario.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

Sin violaciones. No aplica.
