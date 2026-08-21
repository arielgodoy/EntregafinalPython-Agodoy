# Preferencias visuales del Theme por usuario

## Estado

**VIGENTE / ARQUITECTURA BASE DEL SISTEMA**

Este documento define el funcionamiento oficial de las preferencias visuales del theme.

Las preferencias visuales pertenecen al **usuario**, no a la empresa activa ni al navegador.

---

## 1. Objetivo

Las preferencias visuales deben seguir al usuario entre:

- equipos;
- navegadores;
- sesiones;
- empresas.

Ejemplo:

Usuario A configura `data-bs-theme=dark` en Chrome.

La preferencia se guarda en la base de datos.

Si el mismo usuario inicia sesión desde otro navegador o equipo, el sistema debe cargar `dark`.

Si cambia de empresa activa, debe continuar utilizando `dark`.

Si modifica la preferencia desde un navegador, otro navegador con el mismo usuario obtiene el nuevo valor al realizar una nueva carga de página.

---

## 2. Fuente de verdad

La fuente de verdad de las preferencias visuales es:

`settings.models.UserPreferences`

Relación:

`UserPreferences(user)`

La empresa activa **NO forma parte de la identificación de las preferencias visuales**.

Arquitectura:

UserPreferences
→ Django
→ context processor
→ theme_preferences JSON
→ theme_config.js
→ atributos data-* de `<html>`

---

## 3. Preferencias administradas

Las preferencias visuales administradas incluyen:

- `data-layout`
- `data-bs-theme`
- `data-sidebar-visibility`
- `data-layout-width`
- `data-layout-position`
- `data-topbar`
- `data-sidebar-size`
- `data-layout-style`
- `data-sidebar`
- `data-sidebar-image`
- `data-preloader`

Los nombres Python correspondientes se almacenan en `UserPreferences`.

---

## 4. Carga desde Django

El context processor ubicado en:

`settings/context_processors.py`

obtiene las preferencias utilizando el usuario autenticado.

No debe utilizar `empresa_id` para determinar el theme.

Cuando el usuario no tiene preferencias persistidas, se entregan los defaults oficiales del sistema.

Un GET normal no debe crear innecesariamente un registro de preferencias.

---

## 5. Guardado

El endpoint de guardado se encuentra en:

`settings/views.py`

La vista guarda las preferencias en:

`UserPreferences`

El endpoint debe mantener el sistema de seguridad existente:

- usuario autenticado;
- método POST;
- permisos ICMEAS mediante `access_control`.

La empresa activa puede ser necesaria para la autorización ICMEAS, pero **NO determina dónde ni cuáles preferencias visuales se almacenan**.

---

## 6. theme_config.js

Archivo:

`static/js/theme_config.js`

Es el código propio encargado de integrar las preferencias persistentes con el theme.

Responsabilidades:

1. Leer el JSON generado por Django.
2. Aplicar las preferencias al elemento `<html>`.
3. Mantener al servidor como autoridad.
4. Evitar que `localStorage` imponga preferencias antiguas.
5. Mantener `sessionStorage` como espejo de compatibilidad.
6. Detectar cambios visuales realizados mediante el customizer.
7. Guardar esos cambios en `UserPreferences`.
8. Gestionar el Reset de preferencias.

---

## 7. localStorage

`localStorage` **NO es fuente de verdad para las preferencias visuales**.

Las claves visuales legacy deben ser ignoradas o eliminadas.

No implementar nuevamente:

localStorage
→ preferencias visuales
→ `<html>`

El navegador no debe poder sobrescribir las preferencias recibidas desde Django.

`localStorage` puede seguir utilizándose para otras funcionalidades ajenas al theme cuando corresponda, por ejemplo configuraciones vendor existentes.

---

## 8. sessionStorage

`sessionStorage` se mantiene únicamente como **espejo de compatibilidad con el theme vendor**.

Flujo permitido:

UserPreferences
→ Django
→ theme_config.js
→ sessionStorage
→ app.js

Flujo NO permitido:

sessionStorage
→ fuente persistente
→ UserPreferences

Al cargar una página, `theme_config.js` actualiza primero `sessionStorage` con los valores recibidos desde Django.

De esta forma, el código vendor consume una copia actualizada de las preferencias del usuario.

---

## 9. app.js — Vendor inmutable

Archivo:

`static/js/app.js`

**NO MODIFICAR.**

Es un archivo vendor considerado inmutable por las reglas globales del proyecto.

No implementar funcionalidades nuevas allí.

No parchearlo para resolver preferencias visuales.

La compatibilidad debe resolverse externamente mediante:

- Django;
- `UserPreferences`;
- `theme_config.js`;
- templates;
- otros scripts propios cuando sean necesarios.

Consultar además:

`COPILOT/REGLAS_CODIGO_VENDOR.md`

---

## 10. layout.js

Archivo:

`static/js/layout.js`

No debe actuar como sistema de persistencia de preferencias visuales.

Actualmente no debe:

- leer preferencias desde `localStorage`;
- leer preferencias desde `sessionStorage`;
- guardar preferencias;
- restaurar atributos visuales desde storage.

La persistencia pertenece al circuito:

`UserPreferences + theme_config.js`

Existe una copia del layout original del theme únicamente como referencia técnica:

`static/js/layoutORIGINAL.js`

No utilizar automáticamente esa copia para reemplazar `layout.js`.

El layout original contiene comportamiento legacy basado en `sessionStorage` que no corresponde al modelo actual de persistencia.

---

## 11. ThemePreferences legacy

`ThemePreferences` permanece actualmente en el proyecto por compatibilidad/histórico.

**NO es la fuente de verdad del theme actual.**

No utilizar `ThemePreferences` para nuevas funcionalidades visuales.

No volver a implementar:

usuario + empresa
→ ThemePreferences

para determinar el theme.

La arquitectura vigente es:

usuario
→ UserPreferences

No eliminar el modelo legacy ni crear migraciones relacionadas sin una tarea específica y autorización.

---

## 12. Multiempresa

Las preferencias visuales son independientes de la empresa activa.

Ejemplo:

Usuario A:

Empresa 01
→ dark

cambia a:

Empresa 02
→ dark

El cambio de empresa no debe modificar:

- theme;
- layout;
- sidebar;
- topbar;
- preloader;
- demás preferencias visuales personales.

La empresa activa sigue aplicando normalmente para permisos, datos y demás funcionalidades multiempresa.

---

## 13. Separación entre usuarios

Las preferencias deben estar aisladas por usuario.

Ejemplo:

Usuario A
→ dark

Logout.

Usuario B
→ light

Aunque ambos utilicen el mismo navegador y la misma pestaña, Usuario B debe recibir `light`.

Durante la nueva carga:

UserPreferences de Usuario B
→ theme_config.js
→ sobrescribe el espejo de sessionStorage
→ app.js consume los valores de Usuario B.

---

## 14. Sincronización entre navegadores/equipos

No existe sincronización push en tiempo real entre navegadores.

La persistencia está centralizada en la base de datos.

Ejemplo validado:

Navegador 1
→ usuario cambia dark/light
→ UserPreferences se actualiza.

Navegador 2
→ mismo usuario
→ F5 / nueva navegación
→ Django consulta UserPreferences
→ recibe la nueva preferencia.

Este es el comportamiento esperado.

---

## 15. Customizer

Cuando el usuario modifica una opción desde el customizer:

Customizer
→ modifica atributo del `<html>`
→ MutationObserver
→ actualiza sessionStorage como espejo
→ debounce
→ POST al backend
→ UserPreferences

`sessionStorage` no dispara nuevamente el MutationObserver, por lo que no debe generarse un loop por actualizar el espejo.

---

## 16. Reset

El botón Reset debe:

1. aplicar los defaults oficiales;
2. limpiar las claves visuales legacy relevantes;
3. actualizar los atributos del `<html>`;
4. construir el payload completo;
5. guardar los defaults en `UserPreferences`;
6. esperar el guardado;
7. recargar la página.

Después del Reset, los defaults deben seguir al usuario también en otros navegadores/equipos después de una nueva carga.

---

## 17. Preloader

`data-preloader` forma parte de las preferencias personales.

Su valor se almacena en `UserPreferences`.

Debe respetar el mismo circuito:

UserPreferences
→ Django
→ theme_config.js
→ `data-preloader`

No crear una persistencia independiente para el preloader.

---

## 18. Restricciones para futuros desarrollos

Al modificar el sistema de preferencias:

- NO modificar `static/js/app.js`.
- NO volver a utilizar `localStorage` como autoridad visual.
- NO hacer depender el theme de `empresa_id`.
- NO utilizar `ThemePreferences` como fuente efectiva.
- NO crear un segundo sistema de persistencia.
- NO reemplazar el layout principal del theme.
- Mantener permisos ICMEAS en endpoints.
- Mantener i18n según las reglas globales.
- Realizar cambios mínimos.
- Agregar/actualizar tests focalizados.
- Ejecutar `manage.py check` cuando el entorno lo permita.

---

## 19. Validación funcional realizada

La implementación fue probada manualmente con resultado correcto.

Se validó:

- persistencia después de F5;
- cambio dark/light;
- cambio de empresa;
- Reset;
- preferencias visuales adicionales;
- mismo usuario en diferentes navegadores;
- persistencia centralizada en base de datos.

Prueba especialmente relevante:

1. El mismo usuario inició sesión en dos navegadores.
2. Se modificó una preferencia en el navegador A.
3. El navegador B conservó su estado hasta una nueva carga.
4. Al ejecutar F5 en el navegador B, cargó la nueva preferencia.

Esto confirma:

**UserPreferences en la base de datos es la fuente persistente de verdad.**

---

## 20. Pendientes conocidos

No mezclar estos pendientes con cambios normales del sistema de preferencias:

### Gradient sidebar

El customizer contiene:

- `gradient`
- `gradient-2`
- `gradient-3`
- `gradient-4`

pero los choices del modelo no necesariamente representan todas esas variantes.

Debe tratarse como una tarea separada antes de modificar modelos o crear migraciones.

### Entorno de tests

Existe un problema preexistente en la configuración de migraciones del entorno de tests relacionado con `MIGRATION_MODULES` y `access_control`.

Debe resolverse como tarea independiente.

No modificar migraciones de producción como solución indirecta.

---

## Regla final

Para cualquier desarrollo futuro relacionado con el theme:

**Usuario = propietario de las preferencias.**

**UserPreferences = fuente de verdad.**

**Django = origen de la configuración al cargar la página.**

**theme_config.js = integración propia con el theme.**

**sessionStorage = espejo legacy.**

**localStorage = no autoritativo para preferencias visuales.**

**ThemePreferences = legacy.**

**app.js = vendor inmutable.**