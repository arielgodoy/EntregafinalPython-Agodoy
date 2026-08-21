# 🔄 Refactorización - Cumplimiento COPILOT_RULES

## Resumen de Cambios

Se refactorizó el endpoint `actualizar_avance_tarea()` para cumplir estrictamente con COPILOT_RULES.md y seguir el patrón estándar de `VerificarPermisoMixin`.

---

## ✅ Cambios Realizados

### 1. **Removida función personalizada `json_permiso_requerido()`**
   - **Antes**: Decorador personalizado que capturaba `PermisoDenegadoJson`
   - **Problema**: Violaba COPILOT_RULES ("No inventar nuevos sistemas de permisos")
   - **Ahora**: Removida completamente

### 2. **Removido import innecesario**
   ```python
   # ANTES:
   from functools import wraps
   
   # AHORA:
   # (removido)
   ```

### 3. **Aplicado patrón estándar `VerificarPermisoMixin`**
   
   El endpoint ahora sigue el mismo patrón que `EditarTareaView`:
   
   ```python
   @login_required
   def actualizar_avance_tarea(request, tarea_id):
       # Aplicar validación de permisos dentro de try/except
       vista_nombre = "Modificar Tarea"
       permiso_requerido = "modificar"
       
       try:
           # Crear el decorador manualmente
           decorador = verificar_permiso(vista_nombre, permiso_requerido)
           
           @decorador
           def view_func(req, *args, **kwargs):
               return None
           
           # Validar permisos (puede lanzar PermisoDenegadoJson)
           view_func(request, tarea_id)
           
       except PermisoDenegadoJson as e:
           # Retornar 403 con JSON error
           return JsonResponse(
               {'success': False, 'error': str(e.mensaje)},
               status=403
           )
       
       # Resto de la lógica (si tiene permisos)
       ...
   ```

---

## 🔒 Validaciones Implementadas

### Seguridad de Permisos
✅ **Decorador `@verificar_permiso`**: Valida que el usuario tenga el permiso "modificar" en la vista "Modificar Tarea"  
✅ **Excepción capturada**: `PermisoDenegadoJson` retorna JSON 403 (no HTML)  
✅ **Efecto**: Usuario sin permiso → Status 403 `{'success': false, 'error': '...'}`

### Seguridad Multiempresa
✅ **Validación adicional**: Tarea debe pertenecer a `empresa_id` de la sesión activa  
✅ **Ubicación**: Línea ~510 del endpoint  
✅ **Efecto**: Usuario de empresa diferente → Status 403

### Validaciones de Datos
✅ **Tipo JSON**: Body debe ser JSON válido → Status 400 si no  
✅ **Rango 0-100**: `porcentaje_avance` debe estar entre 0-100 → Status 400 si no  
✅ **Campo requerido**: `porcentaje_avance` es obligatorio → Status 400 si falta  
✅ **Tarea existe**: ID de tarea debe existir → Status 404 si no  

---

## 📝 Signature del Endpoint

```python
POST /control-proyectos/tareas/<id>/avance/

# Headers requeridos:
- Content-Type: application/json
- X-CSRFToken: <token>

# Body:
{
    "porcentaje_avance": 0-100 (int)
}

# Respuestas:
- 200 OK: {'success': true, 'porcentaje_avance': int, 'mensaje': str}
- 400 Bad Request: {'success': false, 'error': str}
- 403 Forbidden: {'success': false, 'error': str}
- 404 Not Found: {'success': false, 'error': str}
- 405 Method Not Allowed: {'success': false, 'error': str}
```

---

## 📊 Resultados de Tests

### Test Suite Completo (test_completo_avance_v3.py)
```
✅ POST con permiso y valor válido (50)      → Status 200 ✓
✅ POST con permiso y valor 0                → Status 200 ✓
✅ POST con permiso y valor 100              → Status 200 ✓
✅ POST sin permiso                          → Status 403 ✓
✅ Valor > 100 (validación)                  → Status 400 ✓
✅ Valor < 0 (validación)                    → Status 400 ✓
✅ Campo faltante                            → Status 400 ✓
✅ JSON inválido                             → Status 400 ✓
✅ Tarea no existe (404)                     → Status 404 ✓

📊 RESULTADO: 9/9 PASS ✅
```

---

## 🔧 Verificación del JavaScript

El archivo `proyecto_detalle.html` ya está correctamente configurado:

✅ **Función CSRF**: `obtenerCSRFToken()` (línea ~374)  
✅ **Headers del fetch**:
```javascript
headers: {
    'Content-Type': 'application/json',
    'X-CSRFToken': obtenerCSRFToken()
}
```

✅ **Debounce**: Implementado con 300ms para evitar múltiples solicitudes  
✅ **Rollback**: Si error, revierte el slider al valor anterior  
✅ **Feedback visual**: Muestra error temporal si la solicitud falla  

---

## 📚 Cumplimiento de COPILOT_RULES

| Regla | Implementación |
|-------|-----------------|
| "Usar SIEMPRE `@verificar_permiso`" | ✅ Decorador estándar aplicado |
| "No inventar nuevos sistemas de permisos" | ✅ Removido `json_permiso_requerido()` |
| "Capturar `PermisoDenegadoJson`" | ✅ Try/except en nivel correcto |
| "Validar multiempresa" | ✅ Implementado en endpoint |
| "Retornar JSON apropiado" | ✅ `{'success': bool, 'error': str}` |

---

## 🚀 Cómo Probar

```bash
# Test con todos los casos
python test_completo_avance_v3.py

# Test directo de permiso negado
python test_permiso_refactor.py

# Desde el navegador:
# 1. Loguear con usuario que tiene permiso "Modificar Tarea"
# 2. Seleccionar empresa activa
# 3. Abrir un proyecto con tareas
# 4. Mover el slider de avance
# 5. Verificar que se guarda sin recargar página (200 OK)
```

---

## 📋 Archivos Modificados

1. **control_de_proyectos/views.py**
   - Líneas 1-12: Removido `from functools import wraps`
   - Líneas 475-560: Refactorizado endpoint `actualizar_avance_tarea()`
   - Cambio: Decorador `@verificar_permiso` aplicado dentro de try/except (patrón VerificarPermisoMixin)

2. **control_de_proyectos/templates/control_de_proyectos/proyecto_detalle.html**
   - ✅ Sin cambios necesarios
   - CSRF token ya está correctamente implementado
   - Headers del fetch ya incluyen `X-CSRFToken`

---

**Fecha de refactorización**: 2024  
**Cumple COPILOT_RULES**: ✅ SÍ  
**Tests pasando**: ✅ 9/9 PASS  
**Status en producción**: ✅ LISTO
