# Indice de documentacion operativa

Antes de una tarea, consultar este indice y cargar unicamente la documentacion especializada aplicable.

Las reglas globales viven en `.github/copilot-instructions.md`.

`COPILOT/` contiene documentacion operativa vigente. `COPILOT/historico/` contiene analisis, implementaciones, diagnósticos, bugfixes y referencias historicas.

No leer `COPILOT/historico/` por defecto.

Consultar `COPILOT/historico/` unicamente cuando sea necesario investigar una implementacion anterior, un incidente resuelto o una decision historica.

## DOCUMENTACION VIGENTE

- `INDICE.md`: indice de la documentacion operativa actual.
- `ESTADO_ACTUAL.md`: fotografia tecnica vigente del sistema y punto de entrada para conocer su estado actual.
- `REGLAS_CODIGO_VENDOR.md`: regla vigente para archivos vendor e infraestructura.
- `LOGIN_RECUERDAME_SESIONES.md`: comportamiento y seguridad de sesiones del login.
- `ARQUITECTURA_APPS.md`: clasificacion tecnica de apps, proteccion de SYSTEM_APPS y deuda arquitectonica.
- `THEME_PREFERENCES.md`: arquitectura vigente de preferencias visuales por usuario.

## HISTORICO / REFERENCIA

Los documentos historicos ya no forman parte del flujo normal de lectura. Se conservan en:

- `COPILOT/historico/`

Incluye reportes, comparativas, diagnósticos, implementaciones, soluciones, verificaciones y resúmenes de trabajo previo.

## REGLA DE LECTURA

- Leer solo la documentacion vigente necesaria para la tarea actual.
- Usar `COPILOT/historico/` solo para investigar decisiones previas, incidentes resueltos o patrones implementados en el pasado.
- No cargar toda la carpeta `COPILOT/` ni toda la carpeta historica por defecto.

Para patrones generales de implementacion, revisar primero las reglas globales y la documentacion operativa vigente.

## POLÍTICA DE CONTEXTO MÍNIMO / TOKEN EFFICIENCY

### 1. Principio general

Usar el MÍNIMO CONTEXTO SUFICIENTE para resolver la tarea actual.

No releer automáticamente todos los documentos COPILOT o Spec Kit en cada intervención.

El contexto se amplía SOLO si aparece:

- ambigüedad;
- contradicción;
- dependencia no resuelta;
- necesidad de tocar otra app;
- cambio arquitectónico;
- migración delicada;
- seguridad/CORE.

### 2. Orden de lectura normal

Para una tarea normal:

1. `COPILOT/INDICE.md`;
2. bloque exacto de `tasks.md`;
3. FR/SC exactos relacionados;
4. sección exacta de `data-model.md` si afecta schema;
5. archivos de código directamente afectados.

NO leer completos por defecto:

- `spec.md`;
- `plan.md`;
- `research.md`;
- `quickstart.md`;
- contracts completos;
- otros documentos COPILOT.

Preferir búsqueda por identificador (`T028`, `FR-E05`, `TareaRelacion`, `anulada`)
antes que leer el documento completo.

### 3. APPLICATION_APP

Para una APPLICATION_APP, buscar primero dentro de la propia app.

Solo leer otra app cuando:

- se consume una interfaz/helper existente concreto;
- existe una dependencia demostrada.

NO hacer búsquedas globales del repo por defecto.

### 4. SYSTEM/CORE

Las reglas reforzadas de SYSTEM/CORE se mantienen.

Cuando una tarea realmente modifica CORE, puede ampliarse contexto según
`COPILOT/ARQUITECTURA_APPS.md`.

La eficiencia de tokens NO reduce protecciones arquitectónicas.

### 5. Spec Kit

Spec Kit sigue siendo la fuente funcional. Pero:

- `tasks.md` dirige la unidad actual;
- `spec.md` se consulta por FR/SC exactos;
- `data-model.md` por entidades exactas;
- `plan.md` solo cuando hace falta decisión técnica;
- `research.md` solo cuando hay decisión/ambigüedad que lo requiera;
- `quickstart.md` principalmente para validación/E2E;
- contracts solo cuando se modifica esa interfaz.

NO releer los siete artefactos en cada task.

### 6. Reutilizar contexto de la misma sesión

Si un documento ya fue leído en la intervención actual y no cambió: NO volver a leerlo.

Si acaba de verificarse un contrato, reutilizar esa información durante la misma tarea.

### 7. Tests

Evitar ejecuciones redundantes.

Flujo normal:

tests focalizados → suite de la app → regresión transversal necesaria

UNA vez cada nivel.

No repetir una suite verde sin:

- cambio posterior de código;
- migración posterior;
- razón explícita.

### 8. Git

Durante desarrollo normal:

git status --short --branch
git diff --check

Fetch/hash/divergencia/log remoto: solo cuando se prepara commit/push o cuando sea
necesario.

### 9. Auditorías

No hacer una auditoría completa después de cada microtarea.

Auditoría exhaustiva solo para:

- cierre de fase;
- CORE;
- migración de datos;
- cambio arquitectónico;
- ambigüedad importante;
- solicitud expresa.

Para tasks normales, tests + diff + contrato focal son suficientes.

### 10. Informes

Los informes finales deben ser compactos.

Por defecto informar solo:

- archivos modificados;
- comportamiento implementado;
- tests;
- migración si existe;
- task status;
- gaps/bloqueos;
- commit/push status.

No repetir toda la spec ni explicar nuevamente decisiones ya congeladas.

### 11. Escalamiento

Si el contexto mínimo NO alcanza, declarar:

```text
CONTEXT_ESCALATION:
<razón>
```

y recién entonces leer el documento adicional necesario.

### 12. Prohibición

No sacrificar exactitud, seguridad, aislamiento multiempresa, ICMEAS, reglas CORE, tests
ni stop conditions para ahorrar tokens.

Token efficiency significa:

"no leer/procesar información irrelevante"

NO:

"hacer menos validación necesaria".

### 13. Aplicación al proyecto actual

Para Phase 3 de `tareas`, desde ahora el flujo normal debe ser:

INDICE → task exacta (ej. T028) → FR-E exactos → sección TareaRelacion/data-model →
código tareas relacionado

y SOLO escalar a `plan.md`, `research.md` o `quickstart.md` si aparece una necesidad
concreta.

### 14. Regla de preservación

Esta política no modifica ni debilita ninguna otra regla existente de este índice.

### Arquitectura

- `COPILOT/ARQUITECTURA_APPS.md`
  - Cargar para tareas que creen, modifiquen o dependan de apps Django, settings, integraciones o cambios transversales.
  - Incluye la regla permanente de **autocontención de APPLICATION_APPS** (una app nueva no modifica otras apps ni archivos globales salvo el registro técnico mínimo, con regla de detención).

### Theme / Frontend

- `COPILOT/THEME_PREFERENCES.md`
  - Arquitectura vigente de preferencias visuales por usuario.
  - Cargar para tareas relacionadas con theme, customizer, dark/light, sidebar, layout, preloader o persistencia visual.

## Mantenimiento de documentación al cerrar desarrollos

Cuando una funcionalidad, refactor, fix o cambio relevante quede terminado y validado,
Copilot debe evaluar antes del cierre de la tarea si modifica el contexto técnico
vigente del proyecto.

Debe actualizar la documentación cuando el cambio afecte de forma relevante:

- arquitectura;
- modelos o persistencia;
- bases de datos;
- autenticación o sesiones;
- permisos o seguridad;
- APIs o integraciones;
- infraestructura o configuración;
- comportamiento multiempresa;
- funcionalidades base del sistema;
- decisiones arquitectónicas;
- estado o pendientes estratégicos.

Reglas:

1. Si cambia el estado general del sistema, actualizar `COPILOT/ESTADO_ACTUAL.md`.
2. Si existe un documento especializado para el área modificada, actualizarlo y
   referenciarlo desde `ESTADO_ACTUAL.md` cuando corresponda, evitando duplicación.
3. Si se crea un nuevo documento vigente, agregarlo a `COPILOT/INDICE.md`.
4. Si un documento deja de representar el estado vigente, moverlo o clasificarlo
   como histórico cuando corresponda; no dejar dos fuentes vigentes contradictorias.
5. No actualizar `ESTADO_ACTUAL.md` por cambios menores, correcciones locales,
   ajustes visuales, textos o bugfixes que no alteren el estado general del sistema.
6. La documentación debe representar el estado final validado, no pasos intermedios
   de implementación.
7. No documentar secretos, credenciales, tokens ni datos sensibles.

Antes del commit final de un cambio relevante, Copilot debe indicar explícitamente:

- si corresponde actualizar documentación;
- qué documento debe actualizarse;
- o por qué el cambio no requiere actualización documental.