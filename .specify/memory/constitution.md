<!--
Sync Impact Report
- Version change: ninguna (plantilla inicial sin principios ratificados) → 1.0.0
  (creación y ratificación de la constitución inicial del proyecto).
- Modified principles: no aplica; se definen 9 principios iniciales derivados de
  .github/copilot-instructions.md, COPILOT/INDICE.md, COPILOT/ESTADO_ACTUAL.md,
  COPILOT/ARQUITECTURA_APPS.md y COPILOT/REGLAS_CODIGO_VENDOR.md.
- Added sections: Core Principles (9 principios); Gobernanza con documentación de
  referencia.
- Removed sections: ninguna (la plantilla inicial no contenía secciones ratificadas).
- Follow-up TODOs: ninguno.
- Enmienda 2026-09-07 (v1.1.0, MINOR): se añade al Principio III la referencia al
  principio de AUTOCONTENCIÓN de APPLICATION_APPS (regla permanente en
  COPILOT/ARQUITECTURA_APPS.md). Es adición de guía que expande un principio existente,
  sin redefiniciones incompatibles; el detalle operativo permanece en ARQUITECTURA_APPS.md
  (no se duplica).
- Enmienda 2026-09-07 (v1.2.0, MINOR): se formaliza en el Principio V la separación
  entre visibilidad VICMEAS y autorización ICMEAS, incluyendo el uso de `ver`, la
  evaluación uniforme de `is_superuser` y la prohibición de usar `ver` como autorización.
-->

# AppDocs Constitution

Esta constitución es una capa de principios generales para todo desarrollo futuro con
Spec Kit sobre el proyecto Django existente. NO define una arquitectura nueva ni
reemplaza las reglas vigentes del repositorio. Las reglas operativas detalladas viven
en `.github/copilot-instructions.md` y `COPILOT/`; este documento las resume y las
referencia, no las duplica.

## Core Principles

### I. La arquitectura existente es la referencia (NON-NEGOTIABLE)

El proyecto Django actual ES la arquitectura de referencia. Las specs se adaptan al
sistema, nunca al revés. Toda propuesta MUST respetar la estructura, patrones y
decisiones vigentes descritos en `COPILOT/ESTADO_ACTUAL.md`.
Rationale: el sistema está en operación; los cambios disruptivos no solicitados están
prohibidos.

### II. Documentación contextual mínima (NON-NEGOTIABLE)

Antes de implementar una feature se MUST consultar `COPILOT/INDICE.md` y cargar
únicamente la documentación especializada aplicable a la tarea. NO se lee
`COPILOT/historico/` por defecto; solo para investigar implementaciones anteriores,
incidentes resueltos o decisiones históricas.
Rationale: lectura focalizada evita contexto obsoleto y decisiones basadas en
documentos históricos.

### III. Clasificación y protección de apps (NON-NEGOTIABLE)

Se MUST respetar la clasificación SYSTEM_APPS / CORE_SYSTEM_APPS /
SYSTEM_SUPPORT_APPS / APPLICATION_APPS, cuya fuente técnica de verdad es
`AppDocs/app_classification.py`. Las SYSTEM_APPS NO pueden modificarse sin
autorización expresa del usuario que identifique la app y el alcance concreto. Las
CORE_SYSTEM_APPS tienen protección reforzada según `COPILOT/ARQUITECTURA_APPS.md`
(confirmar autorización, enumerar archivos, explicar impacto transversal, cambio
mínimo, tests y `git diff --check`). La lectura y el diagnóstico son libres; la
escritura requiere autorización.

Además, toda nueva APPLICATION_APP MUST ser AUTOCONTENIDA: su lógica funcional vive en
su propia carpeta y solo puede tocar archivos externos para el registro técnico mínimo
(`AppDocs/app_classification.py`, `AppDocs/settings.py`, `AppDocs/urls.py`). Para
consumir funcionalidad de otras apps, usa sus interfaces existentes desde su carpeta,
sin modificarlas. La regla completa y su regla de detención están en
`COPILOT/ARQUITECTURA_APPS.md` (sección "Autocontencion de APPLICATION_APPS").
Rationale: la infraestructura transversal es compartida por todo el sistema.

### IV. Código vendor inmutable (NON-NEGOTIABLE)

`static/js/app.js` es código vendor inmutable: NO se edita, parchea, reformatea,
minifica ni se usa para funcionalidades nuevas. Si una solución parece requerir
modificarlo, el agente MUST detenerse y proponer una alternativa externa según
`COPILOT/REGLAS_CODIGO_VENDOR.md`.
Rationale: modificar vendor rompe componentes y mezcla código propio con código base.

### V. Multiempresa y permisos VICMEAS/ICMEAS (NON-NEGOTIABLE)

Se MUST mantener la arquitectura multiempresa existente (empresa activa en sesión) y
el sistema de permisos VICMEAS/ICMEAS. VICMEAS se compone de `V` (`ver`) más las
acciones ICMEAS: `I` (`ingresar`), `C` (`crear`), `M` (`modificar`), `E` (`eliminar`),
`A` (`autorizar`) y `S` (`supervisor`). `V` controla exclusivamente la visibilidad
del item navegable en el sidebar para la empresa activa; las acciones ICMEAS controlan
la autorización efectiva de cada vista y operación mediante `VerificarPermisoMixin` /
`@verificar_permiso` con `vista_nombre` y `permiso_requerido`. `is_superuser` no concede
bypass visual del sidebar ni autorización backend por sí mismo; el backend continúa
evaluando sus reglas ICMEAS explícitas, incluida la semántica existente de `supervisor`.
Está prohibido usar `V` como sustituto de `I` o de cualquier otra acción ICMEAS, y `V`
no participa en la decisión de autorización backend. NO se usan permisos por defecto de
Django, las decisiones de permiso no dependen de textos traducidos ni se omiten las
validaciones de pertenencia a la empresa activa.
Rationale: son los mecanismos de seguridad y aislamiento vigentes del sistema.

### VI. Cambios mínimos y focalizados

Se prefieren cambios mínimos, focalizados y compatibles con la arquitectura
existente. Se evitan refactors no solicitados, renombrados de URLs en uso y
reorganizaciones estructurales. NO se crean migraciones ni se modifican settings,
infraestructura, Docker, Nginx, bases de datos o componentes transversales salvo que
la feature y una autorización vigente lo requieran expresamente.
Rationale: minimizar el área de impacto protege un sistema en operación parcial.

### VII. Tests y verificación de cierre

Toda implementación MUST incluir tests focalizados cuando corresponda y ejecutar las
regresiones relacionadas (`python manage.py test --settings=AppDocs.settings_test`).
Antes del cierre se MUST ejecutar `git diff --check` y revisar el diff completo del
alcance modificado. NO se hace commit ni push sin autorización expresa del usuario.
Rationale: la verificación local es la única barrera antes de un sistema en uso real.

### VIII. Specs orientadas al QUÉ

Las especificaciones MUST describir QUÉ debe hacer la funcionalidad (comportamiento,
criterios de aceptación, restricciones) antes de decidir CÓMO implementarla. El CÓMO
se define en el plan, adaptado a la arquitectura existente (Principio I).
Rationale: separar QUÉ de CÓMO evita que decisiones técnicas prematuras contradigan
el sistema vigente.

### IX. Trazabilidad spec → plan → tasks

`spec.md`, `plan.md` y `tasks.md` MUST mantener trazabilidad entre requerimientos,
decisiones técnicas, implementación y pruebas. Cada requerimiento de la spec debe ser
alcanzable hasta sus tareas y sus tests.
Rationale: la trazabilidad permite auditar cobertura y detectar trabajo no
especificado.

## Gobernanza

- `.github/copilot-instructions.md` y `COPILOT/` contienen las reglas operativas
  detalladas y vigentes del proyecto. Esta constitución NO duplica esa documentación:
  resume principios obligatorios y referencia los documentos especializados.
- Documentación de referencia: `COPILOT/INDICE.md` (índice y regla de lectura),
  `COPILOT/ESTADO_ACTUAL.md` (estado técnico vigente), `COPILOT/ARQUITECTURA_APPS.md`
  (protección de apps), `COPILOT/REGLAS_CODIGO_VENDOR.md` (código vendor).
- Ante contradicción entre una tarea/spec y estos principios, NO asumir que Spec Kit
  autoriza modificar arquitectura protegida: detenerse y señalar el conflicto al
  usuario. Ante contradicción documental, prevalece el orden definido en
  `COPILOT/ESTADO_ACTUAL.md`: código/configuración actual → documentación vigente →
  `ESTADO_ACTUAL.md` → histórico.
- Enmiendas a esta constitución: requieren autorización expresa del usuario, bump de
  versión semántico (MAJOR: eliminación o redefinición incompatible de principios;
  MINOR: nuevo principio o sección; PATCH: aclaraciones sin cambio semántico) y
  actualización del Sync Impact Report al inicio de este archivo.

**Version**: 1.2.0 | **Ratified**: 2026-09-07 | **Last Amended**: 2026-09-07
