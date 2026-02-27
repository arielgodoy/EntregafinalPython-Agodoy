# Corrección: selector inválido `#` en querySelector

Fecha: 2026-02-26

Resumen
-------
Al hacer clic en el acordeón de tareas en la vista de proyecto (`/control-proyectos/proyectos/<id>/`) el navegador mostraba repetidamente en consola la advertencia:

```
querySelector ignorado para selector inválido "#"
```

Causa
-----
Algunas plantillas y/o scripts generaban triggers de Bootstrap (`data-bs-toggle="collapse"`) que apuntaban a `href="#"` o `data-bs-target="#"`. Cuando Bootstrap intenta resolver el target usando `document.querySelector('#')` el navegador (o extensiones como React devtools) registra una advertencia porque `#` no es un selector CSS válido para querySelector.

Acción tomada
--------------
1. Añadí sanitización global en `templates/partials/base.html` que:
   - Intercepta llamadas a `querySelector` y `querySelectorAll` cuando el selector es exactamente `#`, devolviendo `null` o un NodeList vacío para evitar el error y el ruido en consola.
   - Sustituye `a[href="#"][data-bs-toggle]` por `href="javascript:void(0)"` durante la inicialización.
   - Revisa todos los triggers de collapse (`[data-bs-toggle="collapse"]`) y corrige `data-bs-target` vacíos o `#` usando `aria-controls` si está disponible; si no, elimina atributos peligrosos.

2. Añadí sanitización localizada en la vista problemática `control_de_proyectos/templates/control_de_proyectos/proyecto_detalle.html` que, al cargar la página, busca dentro del acordeón de tareas y:
   - Reemplaza `href="#"` por `javascript:void(0)`.
   - Si encuentra `data-bs-target="#"` en un trigger de `collapse`, elimina `data-bs-toggle`, `data-bs-target` y `aria-controls` para desactivarlo; si no, lo sustituye por `javascript:void(0)`.

3. Ajusté la lógica para que la advertencia de `querySelector('#')` no genere spam en consola (la función ahora silencia llamadas repetidas y maneja `querySelectorAll('#')`).

Archivos modificados
-------------------
- `templates/partials/base.html` — sanitización global y overrides seguros de `querySelector`/`querySelectorAll`.
- `control_de_proyectos/templates/control_de_proyectos/proyecto_detalle.html` — script de sanitización localizado dentro del acordeón de tareas.

Cómo reproducir / verificar
--------------------------
1. Iniciar el servidor Django (`python manage.py runserver`).
2. Abrir la vista del proyecto (ej. `http://127.0.0.1:8000/control-proyectos/proyectos/4/`).
3. Abrir la consola del navegador y hacer un hard-refresh (Ctrl+F5).
4. Hacer clic en un acordeón de tarea — la advertencia sobre `querySelector('#')` ya no debería aparecer repetidamente; si aparece, será una sola vez y sin spam.

Reversión / deshacer
-------------------
Si quieres revertir los cambios, restaura las versiones anteriores de los archivos listados arriba desde el control de versiones (`git checkout -- <file>`).

Notas y recomendaciones
----------------------
- Evitar usar `href="#"` en elementos interactivos; preferir `href="javascript:void(0)"` o `button` cuando no haya destino.
- Revisar plantillas y librerías externas que generen `href="#"` (ej. ejemplos de componentes). Para evitar cambios globales dañinos, aplicamos sanitización defensiva en lugar de reemplazar masivamente todos los `href="#"` en el repo.
- Si el problema reaparece, inspeccionar el elemento que provoca la llamada (`document.querySelector` stack trace) y corregir la plantilla origen.

Contacto
-------
Archivo generado automáticamente por la corrección implementada en el repositorio.
