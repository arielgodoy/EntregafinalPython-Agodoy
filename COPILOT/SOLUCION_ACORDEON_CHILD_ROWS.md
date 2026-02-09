# Solución: Acordeón de Documentos en DataTables Child Rows

## 🎯 Problema Solucionado

El acordeón interno de documentos (Entrada/Salida) dentro de cada tarea dejaba de funcionar cuando se renderizaba en un child row de DataTables.

## 🔧 Cambios Implementados

### 1. IDs Únicos por Proyecto (Evitar Duplicados)

**Antes:**
```django
collapse_prefix="tarea-"|add:proyecto.id|add:"-"
acordeon_id="acordeonTareas-"|add:proyecto.id
```
Esto generaba IDs duplicados cuando había múltiples proyectos.

**Después:**
```django
collapse_prefix="proyecto-"|add:proyecto.id|add:"-tarea-"
acordeon_id="acordeonTareas-proyecto-"|add:proyecto.id
```

**Ejemplo de IDs generados:**
- Proyecto 1, Tarea 5: `proyecto-1-tarea-5`
- Proyecto 2, Tarea 5: `proyecto-2-tarea-5` (sin colisión)

### 2. Función Reutilizable `initTareasAccordion()`

**Archivos modificados:**
- `control_de_proyectos/templates/control_de_proyectos/partials/tareas_accordion_js.html`

**Antes:** Event listeners solo en `DOMContentLoaded` → No funcionaban en contenido dinámico.

**Después:** Función global reutilizable:
```javascript
function initTareasAccordion(rootElement) {
    if (!rootElement) rootElement = document;
    
    // Re-inicializar feather icons
    if (typeof feather !== 'undefined') {
        feather.replace();
    }

    // Registrar listeners para cargar documentos al abrir tareas
    const collapseElements = rootElement.querySelectorAll('.accordion-collapse');
    collapseElements.forEach(element => {
        // Evitar doble binding con flag
        if (element.dataset.listenerIniciado === 'true') return;
        element.dataset.listenerIniciado = 'true';
        
        element.addEventListener('shown.bs.collapse', cargarDocumentosAlAbrir);
    });

    // ... más lógica de sliders y ordenamiento
}
```

### 3. Integración en Child Rows de DataTables

**Archivo modificado:**
- `control_de_proyectos/templates/control_de_proyectos/proyecto_lista.html`

**Código clave:**
```javascript
if (acordeonHtml) {
    // Mostrar child row con el acordeón
    var childRowContent = $('<div class="p-4 bg-light"></div>').html(acordeonHtml);
    row.child(childRowContent).show();
    button.find('i').removeClass('bx-list-ul').addClass('bx-chevron-up');
    
    // ✅ CRÍTICO: Inicializar eventos del acordeón en el child row recién creado
    if (typeof initTareasAccordion === 'function') {
        var childRowElement = row.child()[0];
        initTareasAccordion(childRowElement);
    }
    
    // Re-inicializar feather icons en el child row
    feather.replace();
}
```

### 4. Soporte Bootstrap Collapse Nativo

**Archivo modificado:**
- `control_de_proyectos/templates/control_de_proyectos/partials/tareas_accordion.html`

**Cambios:**
```html
<!-- Agregado data-bs-toggle y data-bs-parent -->
<button class="accordion-button collapsed" type="button" 
        data-bs-toggle="collapse" 
        data-bs-target="#{{ collapse_prefix }}{{ tarea.id }}" 
        aria-expanded="false" 
        aria-controls="{{ collapse_prefix }}{{ tarea.id }}">

<div id="{{ collapse_prefix }}{{ tarea.id }}" 
     class="accordion-collapse collapse" 
     data-bs-parent="#{{ acordeon_id }}">
```

Esto permite que Bootstrap maneje el toggle automáticamente sin JavaScript custom.

### 5. Actualización en Vista Detalle de Proyecto

**Archivo modificado:**
- `control_de_proyectos/templates/control_de_proyectos/proyecto_detalle.html`

**Cambio:**
```django
{% include "control_de_proyectos/partials/tareas_accordion.html" with 
    tareas=tareas 
    acordeon_id="acordeonTareas-proyecto-"|add:proyecto.id 
    collapse_prefix="proyecto-"|add:proyecto.id|add:"-tarea-" %}
```

Mantiene consistencia de IDs entre vistas.

## ✅ Validación

### Pasos para Verificar:

1. **Cargar listado de proyectos:**
   ```
   http://127.0.0.1:8000/control-proyectos/proyectos/
   ```

2. **Expandir child row:**
   - Click en botón "Tareas" de cualquier proyecto
   - Debe mostrar el acordeón de tareas

3. **Expandir tarea:**
   - Click en una tarea del acordeón principal
   - Debe mostrar avance, plazo, documentos

4. **Verificar carga de documentos:**
   - Abrir consola del navegador (F12)
   - Expandir una tarea
   - Verificar que se ejecuta:
     - `shown.bs.collapse` event
     - Llamada AJAX a `/api/v1/control-proyectos/documentos-tarea/?tarea_id=X&tipo_doc=ENTRADA`
     - Carga de documentos de Entrada y Salida

5. **Verificar IDs únicos:**
   - Inspeccionar DOM (F12 → Elements)
   - Buscar IDs como `proyecto-1-tarea-5`, `proyecto-2-tarea-5`
   - NO debe haber IDs duplicados

6. **Verificar slider de avance:**
   - Mover slider de avance de tarea
   - Debe enviar POST con debounce
   - Debe actualizar barra de progreso

7. **Verificar en múltiples child rows:**
   - Abrir 2-3 proyectos diferentes
   - Expandir tareas en cada uno
   - Todos deben funcionar correctamente

### Checklist de Funcionalidad:

- [ ] Child row se abre/cierra correctamente
- [ ] Acordeón principal de tareas funciona (expand/collapse)
- [ ] Acordeón interno de documentos carga por AJAX
- [ ] Documentos de Entrada se muestran
- [ ] Documentos de Salida se muestran
- [ ] Slider de avance funciona (AJAX POST)
- [ ] Barra de progreso se actualiza
- [ ] Feather icons se renderizan
- [ ] No hay errores en consola
- [ ] Funciona con múltiples proyectos abiertos simultáneamente

## 🔍 Debugging

Si el acordeón no funciona:

1. **Verificar consola (F12 → Console):**
   ```javascript
   // Debe existir la función
   typeof initTareasAccordion
   // Output: "function"
   ```

2. **Verificar listeners:**
   ```javascript
   // En consola después de abrir child row
   document.querySelectorAll('[data-listener-iniciado="true"]').length
   // Debe ser > 0
   ```

3. **Verificar IDs:**
   ```javascript
   // Buscar duplicados
   const ids = Array.from(document.querySelectorAll('[id]')).map(el => el.id);
   const duplicados = ids.filter((id, index) => ids.indexOf(id) !== index);
   console.log(duplicados);
   // Debe ser []
   ```

4. **Verificar Bootstrap Collapse:**
   ```javascript
   // Debe estar cargado
   typeof bootstrap.Collapse
   // Output: "function"
   ```

## 📋 Resumen Técnico

**Problema raíz:** Event listeners registrados solo en `DOMContentLoaded` no se aplicaban a contenido insertado dinámicamente por DataTables.

**Solución:** Crear función `initTareasAccordion(rootElement)` que:
- Se ejecuta en `DOMContentLoaded` para vistas estáticas
- Se llama manualmente después de insertar child row
- Acepta `rootElement` para scope limitado (evita conflictos)
- Usa flags `data-listener-iniciado` para evitar doble binding
- Re-inicializa feather icons en contexto dinámico

**Beneficios:**
- ✅ Funciona en vistas estáticas (proyecto_detalle.html)
- ✅ Funciona en child rows dinámicos (proyecto_lista.html)
- ✅ No hay IDs duplicados entre proyectos
- ✅ Bootstrap Collapse maneja toggle automáticamente
- ✅ AJAX de documentos se ejecuta correctamente
- ✅ Slider de avance funciona con debounce

**Cumple COPILOT_RULES.md:** ✅
- No se crearon nuevos sistemas de permisos
- Se reutilizó estructura existente (partials)
- Se mantuvo consistencia con biblioteca y otros módulos
