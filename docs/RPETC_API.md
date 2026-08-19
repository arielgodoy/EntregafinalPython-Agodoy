# Contrato confirmado API-RPETC

## Produccion

Base URL: `https://api.sii.cl/api/api-rpetc`

La autenticacion OAuth se reutiliza desde `gestiondte.services.sii_auth`.
No se documentan credenciales ni tokens.

## Cesiones por deudor

- Metodo: `GET`
- Path: `/recurso/v1/tarea/{rutDeudor}-{dvDeudor}/cesiones.deudor`
- Scope: `RTC_TAR`
- Query requeridos: `desde`, `hasta`, `formato`
- Fecha: `DDMMYYYY`
- Rango maximo: un mes
- Formatos: `TXT` o `XML`
- Filtros opcionales: `rutCedente`, `dvCedente`, `rutCesionario`, `dvCesionario`

## Estado

- Metodo: `GET`
- Path: `/recurso/v1/estado/{rutAutenticado}-{dvAutenticado}/{idTarea}`
- Scope: `RTC_PRO_EST`
- Estados: `CREADO`, `EN_PROCESO`, `TERMINADO`, `FALLO`
- La respuesta inicial de la tarea entrega `rutAutenticado` y `dvAutenticado`; esos valores se conservan para las consultas siguientes.

## Resultado

- Metodo: `GET`
- Path: `/recurso/v1/resultado/{rutAutenticado}-{dvAutenticado}/{idTarea}`
- Scope: `RTC_PRO_RES`
- Respuesta exitosa: `application/octet-stream`
- El cliente retorna bytes y metadata HTTP; no persiste archivos automáticamente.

## TXT confirmado

La respuesta TXT observada usa UTF-8 y delimitador `;`:

1. `DATOS_CONSULTA` con metadata `clave=valor`.
2. Encabezados de columnas.
3. Registros tabulares.

Columnas observadas:

`VENDEDOR`, `ESTADO_CESION`, `DEUDOR`, `MAIL_DEUDOR`, `TIPO_DOC`, `NOMBRE_DOC`, `FOLIO_DOC`, `FCH_EMIS_DTE`, `MNT_TOTAL`, `CEDENTE`, `RZ_CEDENTE`, `MAIL_CEDENTE`, `CESIONARIO`, `RZ_CESIONARIO`, `MAIL_CESIONARIO`, `FCH_CESION`, `MNT_CESION`, `FCH_VENCIMIENTO`, `ID_CESION`.
