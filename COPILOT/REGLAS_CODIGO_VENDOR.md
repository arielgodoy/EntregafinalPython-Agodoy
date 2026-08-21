# Reglas de codigo vendor e infraestructura

## static/js/app.js — ARCHIVO VENDOR INMUTABLE

`static/js/app.js` pertenece al codigo base/vendor del template y debe considerarse inmutable.

Regla obligatoria:

- NO modificar `static/js/app.js`.

Esto incluye:

- no editar codigo;
- no parchear funciones;
- no agregar logica;
- no eliminar logica;
- no reformatear;
- no volver a minificar;
- no cambiar comportamiento interno;
- no utilizarlo como lugar para implementar funcionalidades nuevas.

El archivo contiene logica base del theme/template. Modificarlo puede romper componentes existentes, introducir regresiones, dificultar futuras actualizaciones y mezclar codigo propio con codigo vendor.

Cuando una funcionalidad parezca requerir cambios en `app.js`, la solucion debe buscarse primero mediante codigo controlado por el proyecto:

- `static/js/theme_config.js` u otro JavaScript propio;
- templates Django;
- context processors;
- views o backend;
- atributos `data-*` del HTML;
- overrides controlados;
- eventos DOM;
- limpieza o control de `localStorage`/`sessionStorage`;
- scripts cargados antes o despues del vendor cuando corresponda.

Si `app.js` sobrescribe una configuracion propia del sistema, debe interceptarse, neutralizarse o reaplicarse mediante codigo propio. No debe modificarse `app.js` para corregirlo.

## Regla de detencion

Si una solicitud no puede implementarse razonablemente sin modificar `static/js/app.js`, el agente debe detenerse antes de editar y explicar:

1. que comportamiento de `app.js` interfiere;
2. por que no puede resolverse externamente;
3. que alternativas existen;
4. que riesgo tendria modificar el archivo.

Se requiere autorizacion explicita del usuario antes de intervenir `app.js`.

## Preferencias visuales

Para preferencias visuales del usuario, `app.js` no es fuente de verdad. La arquitectura preferida es:

Base de datos -> preferencias del usuario -> Django -> JSON renderizado -> `theme_config.js`/JS propio -> atributos `data-*` -> theme/template

`localStorage` y `sessionStorage` tampoco deben tener autoridad sobre una preferencia persistida en el servidor. Si el codigo vendor utiliza esos mecanismos legacy, la integracion debe resolverse externamente sin editar `app.js`.
