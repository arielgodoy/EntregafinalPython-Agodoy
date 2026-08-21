# Indice de documentacion operativa

Antes de una tarea, consultar este indice y cargar unicamente la documentacion especializada aplicable.

Las reglas globales viven en `.github/copilot-instructions.md`.

`COPILOT/` contiene documentacion operativa vigente. `COPILOT/historico/` contiene analisis, implementaciones, diagnósticos, bugfixes y referencias historicas.

No leer `COPILOT/historico/` por defecto.

Consultar `COPILOT/historico/` unicamente cuando sea necesario investigar una implementacion anterior, un incidente resuelto o una decision historica.

## DOCUMENTACION VIGENTE

- `INDICE.md`: indice de la documentacion operativa actual.
- `REGLAS_CODIGO_VENDOR.md`: regla vigente para archivos vendor e infraestructura.
- `LOGIN_RECUERDAME_SESIONES.md`: comportamiento y seguridad de sesiones del login.

## HISTORICO / REFERENCIA

Los documentos historicos ya no forman parte del flujo normal de lectura. Se conservan en:

- `COPILOT/historico/`

Incluye reportes, comparativas, diagnósticos, implementaciones, soluciones, verificaciones y resúmenes de trabajo previo.

## REGLA DE LECTURA

- Leer solo la documentacion vigente necesaria para la tarea actual.
- Usar `COPILOT/historico/` solo para investigar decisiones previas, incidentes resueltos o patrones implementados en el pasado.
- No cargar toda la carpeta `COPILOT/` ni toda la carpeta historica por defecto.

Para patrones generales de implementacion, revisar primero las reglas globales y la documentacion operativa vigente.
