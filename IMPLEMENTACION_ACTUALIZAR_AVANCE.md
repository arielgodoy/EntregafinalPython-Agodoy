# ✅ Implementación Completada: Actualizar Avance de Tareas (Inline)

## 📋 Resumen

Se implementó funcionalidad para editar el porcentaje de avance de tareas directamente desde la vista de detalle del proyecto, usando un slider interactivo tipo Bootstrap 5 que se comunica con el servidor mediante AJAX.

---

## 🎯 Características Implementadas

### Frontend
✅ Slider `<input type="range">` con Bootstrap 5 (`form-range`)  
✅ Display de % actualizado en tiempo real  
✅ Guardado automático (debounce 300ms) al soltar el slider  
✅ Revert automático si falla el guardado  
✅ Alerta roja temporal si hay error  
✅ Slider deshabilitado para tareas TERMINADAS (readonly)  
✅ Barra de progreso visual que se actualiza automáticamente  

### Backend
✅ Endpoint AJAX: `POST /control-proyectos/tareas/<id>/avance/`  
✅ Validación de permisos (reutiliza vista "Modificar Tarea")  
✅ Validación multiempresa  
✅ Validación rango 0-100  
✅ Errores JSON correctamente manejados (nunca 500)  
✅ CSRF protection  

---

## 📁 Archivos Modificados

### 1. `control_de_proyectos/views.py`
- ✅ Agregado import: `from functools import wraps`
- ✅ Creado decorador: `json_permiso_requerido()` 
- ✅ Creada FBV: `actualizar_avance_tarea(request, tarea_id)`

### 2. `control_de_proyectos/urls.py`
- ✅ Nueva ruta: `path('tareas/<int:tarea_id>/avance/', views.actualizar_avance_tarea, name='actualizar_avance_tarea')`

### 3. `control_de_proyectos/templates/control_de_proyectos/proyecto_detalle.html`
- ✅ HTML del slider integrado en cada acordeón de tarea
- ✅ JavaScript para manejo AJAX + revert + display dinámico
- ✅ Integración con barra de progreso visual existente

---

## 🔧 Endpoint Details

```
POST /control-proyectos/tareas/<id>/avance/

Headers:
  Content-Type: application/json
  X-CSRFToken: <token>

Request Body:
{
  "porcentaje_avance": 0-100
}

Response Success (200):
{
  "success": true,
  "porcentaje_avance": 50,
  "mensaje": "Avance actualizado a 50%"
}

Response Error (4xx):
{
  "success": false,
  "error": "Descripción del error"
}
```

### HTTP Status Codes
| Status | Caso |
|--------|------|
| 200 | Éxito |
| 400 | Validación falla (valor inválido, JSON inválido, etc) |
| 403 | Sin permisos O tarea de otra empresa |
| 404 | Tarea no existe |
| 405 | Método no es POST |

---

## 🔐 Permisos Requeridos

El endpoint usa la vista existente **"Modificar Tarea"** para validar permisos.

**Requisito**: Usuario debe tener permiso `modificar` en la vista "Modificar Tarea" para la empresa activa.

### Asignación Automática
Se proporciona script `asignar_permisos_avance.py` que asigna automáticamente permisos a todos los usuarios que tengan acceso a "Ver Detalle Proyecto":

```bash
python asignar_permisos_avance.py
```

O manualmente en Django admin:
```
Access Control > Permisos
- Usuario: [usuario]
- Vista: Modificar Tarea
- Empresa: [empresa]
- ☑ modificar
```

---

## 🧪 Tests

Todos los 9 tests pasan correctamente:

```
✅ POST con permiso y valor válido (50) → 200
✅ POST con permiso y valor 0 → 200
✅ POST con permiso y valor 100 → 200
✅ POST sin permiso → 403
✅ Valor > 100 → 400
✅ Valor < 0 → 400
✅ Campo faltante → 400
✅ JSON inválido → 400
✅ Tarea no existe → 404
```

Ejecutar tests:
```bash
python test_completo_avance.py      # Test completo (9 casos)
python test_avance_validacion.py    # Test de validación (8 casos)
python test_permiso_json.py         # Test de permisos (1 caso)
```

---

## 🚀 Flujo de Uso

1. Usuario accede a detalle de proyecto
2. Expande acordeón de una tarea (NO TERMINADA)
3. Ve slider con avance actual
4. Mueve slider → % se actualiza en tiempo real
5. Suelta slider → POST AJAX (debounce 300ms)
6. ✅ Éxito: Barra visual se actualiza con nuevo color/ancho
7. ❌ Falla: Slider revierte + alerta roja temporal

---

## 🛡️ Seguridad Implementada

✅ `@login_required`: Usuario debe estar autenticado  
✅ `@json_permiso_requerido()`: Validación de permisos (403 JSON)  
✅ Validación multiempresa: Tarea debe ser de empresa activa  
✅ Validación rango: 0-100  
✅ Validación JSON: Parseo y campo requerido  
✅ CSRF protection: Automática Django + header  
✅ Errores correctamente manejados: Nunca 500 por permisos  

---

## 💡 Notas Técnicas

### Decorador `json_permiso_requerido()`
Envuelve `@verificar_permiso()` para capturar `PermisoDenegadoJson` y retornar JsonResponse 403 en lugar de error 500:

```python
def json_permiso_requerido(vista_nombre, permiso_requerido):
    def decorator(view_func):
        view_with_permiso = verificar_permiso(...)(view_func)
        @wraps(view_with_permiso)
        def wrapper(request, *args, **kwargs):
            try:
                return view_with_permiso(request, *args, **kwargs)
            except PermisoDenegadoJson as e:
                return JsonResponse({'success': False, ...}, status=403)
        return wrapper
    return decorator
```

### JavaScript Debounce
Evita múltiples peticiones al mover rápidamente el slider:
```javascript
const guardarAvanceDebounced = debounce(function(slider) {
    // Lógica de guardado
}, 300);  // 300ms de espera
```

---

## ✨ Mejoras Futuras (Opcionales)

- [ ] Agregar notificación visual "Guardando..." en slider
- [ ] Historial de cambios de avance (auditoría)
- [ ] Actualización automática de estado si avance == 100
- [ ] Validación de dependencias antes de incrementar avance
- [ ] Integración con notificaciones WebSocket
- [ ] CSV/Excel export con historial

---

## 📞 Soporte

En caso de problemas:

1. Verificar permisos: `python manage.py shell`
   ```python
   from access_control.models import Permiso
   Permiso.objects.filter(vista__nombre='Modificar Tarea').values_list('usuario__username', 'empresa__codigo', 'modificar')
   ```

2. Ejecutar script de permisos: `python asignar_permisos_avance.py`

3. Limpiar datos de test: `python manage.py flush` (cuidado: borra BD completa)

---

**Última actualización**: 07 de febrero de 2026  
**Estado**: ✅ PRODUCCIÓN  
**Tests**: 9/9 PASS
