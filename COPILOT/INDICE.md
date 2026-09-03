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

### Arquitectura

- `COPILOT/ARQUITECTURA_APPS.md`
  - Cargar para tareas que creen, modifiquen o dependan de apps Django, settings, integraciones o cambios transversales.

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