# Importacion RPETC a Django

## Responsabilidad

`gestiondte.services.rpetc_importer` recibe una tarea y un resultado ya obtenidos y parseados. No ejecuta HTTP, OAuth, polling ni descarga de archivos.

La importacion se ejecuta en una sola transaccion `atomic()`.

## Identidad de cesion

La busqueda usa la misma identidad conservadora de la base:

- `id_cesion`
- `deudor_rut`
- `deudor_dv`
- `tipo_doc`
- `folio_doc`

`id_cesion` se conserva como string y no se considera unique global ni primary key.

## Capas de persistencia

- `TareaRPETC`: una ejecucion concreta solicitada al SII.
- `CesionRPETC`: entidad de negocio normalizada.
- `TareaCesionRPETC`: cada aparicion de una cesion en una tarea y su rol de consulta.
- `CesionRPETCHistorial`: transiciones de estado, no apariciones repetidas.

## Idempotencia

Reprocesar la misma tarea no duplica `TareaRPETC`, `CesionRPETC`, vinculos ni estados historicos.

Una nueva tarea que devuelve la misma cesion reutiliza la cesion existente y crea solamente su vinculo de aparicion. Si el estado cambia, se actualiza el estado actual y se crea una transicion historica.

La misma cesion puede asociarse a tareas de distintas empresas y perspectivas sin duplicar la entidad de negocio.

## Normalizacion

Los RUT se separan en cuerpo y DV, conservando ceros iniciales y normalizando el DV a mayusculas. Folios, identificadores y montos se reciben como strings antes de convertirlos de forma controlada.

Los montos validos se convierten a `Decimal`; los montos invalidos abortan la transaccion. Las fechas siguen los formatos observados en TXT: fechas ISO para `DateField` y timestamp ISO para `DateTimeField`.

## Actualizacion conservadora

Un valor nuevo vacio no reemplaza un dato existente. Un valor no vacio si puede actualizarlo. Esto evita perder emails, razones sociales, montos o fechas cuando una respuesta posterior omite un campo.

Los emails se persisten como campos nullable, sin indices, unique ni inclusion en `__str__` o logs.

## Parametros SII

Si `parametros` es un dict/lista o JSON valido, se guarda en `JSONField`. La representacion original se conserva en `parametros_raw`. Un JSON invalido no aborta la importacion.

## Errores

Errores estructurales criticos abortan la transaccion, incluyendo:

- `ID_CESION` vacio;
- tipo de documento ausente;
- folio ausente;
- estado ausente;
- fecha no valida;
- monto no valido;
- periodo de tarea no valido.

Las columnas extra del parser no se persisten en el modelo normalizado.
