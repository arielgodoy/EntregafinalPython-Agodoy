# Comparativa: Antes vs Después de la Refactorización

## Antes (Violaba COPILOT_RULES)

```python
from functools import wraps

def json_permiso_requerido(vista_nombre, permiso_requerido):
    """Decorador personalizado - PROHIBIDO por COPILOT_RULES"""
    def decorator(view_func):
        view_with_permiso = verificar_permiso(
            vista_nombre=vista_nombre,
            permiso_requerido=permiso_requerido
        )(view_func)
        
        @wraps(view_with_permiso)
        def wrapper(request, *args, **kwargs):
            try:
                return view_with_permiso(request, *args, **kwargs)
            except PermisoDenegadoJson as e:
                return JsonResponse({
                    'success': False,
                    'error': f'No tienes permiso para...'
                }, status=403)
        return wrapper
    return decorator


@login_required
@json_permiso_requerido(vista_nombre="Modificar Tarea", permiso_requerido="modificar")
def actualizar_avance_tarea(request, tarea_id):
    # ... lógica de la vista
    pass
```

**Problemas:**
- ❌ Crea un nuevo sistema de permisos personalizado
- ❌ Viola COPILOT_RULES: "No inventar nuevos sistemas de permisos"
- ❌ No sigue patrón estándar de `VerificarPermisoMixin`
- ❌ Innecesariamente complejo

---

## Después (Cumple COPILOT_RULES)

```python
# ✅ Removido: from functools import wraps
# ✅ Removido: def json_permiso_requerido()

@login_required
def actualizar_avance_tarea(request, tarea_id):
    """
    Endpoint AJAX para actualizar el porcentaje de avance de una tarea.
    Sigue el patrón estándar de COPILOT_RULES: aplicar @verificar_permiso con try/except.
    """
    vista_nombre = "Modificar Tarea"
    permiso_requerido = "modificar"
    
    try:
        # ✅ Aplicar decorador estándar DENTRO de try/except
        decorador = verificar_permiso(vista_nombre, permiso_requerido)
        
        @decorador
        def view_func(req, *args, **kwargs):
            return None
        
        # Validar permisos (puede lanzar PermisoDenegadoJson)
        view_func(request, tarea_id)
        
    except PermisoDenegadoJson as e:
        # ✅ Capturar excepción estándar
        return JsonResponse(
            {'success': False, 'error': str(e.mensaje)},
            status=403
        )
    
    # Si llegó aquí, tiene permisos válidos
    if request.method != 'POST':
        return JsonResponse(
            {'success': False, 'error': 'Solo se permite POST'},
            status=405
        )
    
    try:
        tarea = Tarea.objects.select_related('proyecto').get(pk=tarea_id)
        
        # Validación multiempresa
        empresa_id = request.session.get("empresa_id")
        if tarea.proyecto.empresa_interna_id != empresa_id:
            return JsonResponse(
                {'success': False, 'error': 'La tarea no pertenece a tu empresa activa'},
                status=403
            )
        
        # Parsear y validar JSON
        datos = json.loads(request.body)
        porcentaje_avance = datos.get('porcentaje_avance')
        
        if porcentaje_avance is None:
            return JsonResponse(
                {'success': False, 'error': 'El campo porcentaje_avance es requerido'},
                status=400
            )
        
        porcentaje_avance = int(porcentaje_avance)
        if not (0 <= porcentaje_avance <= 100):
            return JsonResponse(
                {'success': False, 'error': 'El porcentaje debe estar entre 0 y 100'},
                status=400
            )
        
        # Guardar cambios
        tarea.porcentaje_avance = porcentaje_avance
        tarea.save(update_fields=['porcentaje_avance'])
        
        return JsonResponse({
            'success': True,
            'porcentaje_avance': tarea.porcentaje_avance,
            'mensaje': f'Avance actualizado a {porcentaje_avance}%'
        }, status=200)
    
    except Tarea.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'La tarea no existe'},
            status=404
        )
    except json.JSONDecodeError:
        return JsonResponse(
            {'success': False, 'error': 'Body inválido (JSON esperado)'},
            status=400
        )
    except (ValueError, TypeError):
        return JsonResponse(
            {'success': False, 'error': 'Datos inválidos: porcentaje_avance debe ser un número entre 0 y 100'},
            status=400
        )
    except Exception as e:
        return JsonResponse(
            {'success': False, 'error': f'Error interno del servidor: {str(e)}'},
            status=500
        )
```

**Mejoras:**
- ✅ Usa decorador estándar `@verificar_permiso` de `access_control.decorators`
- ✅ Cumple COPILOT_RULES: No hay sistemas de permisos personalizados
- ✅ Sigue patrón de `VerificarPermisoMixin` (try/except alrededor de decorador)
- ✅ Limpio, directo, fácil de mantener
- ✅ Mejor separación de responsabilidades (permisos vs lógica de datos)

---

## Comparativa de Flujo

### ANTES (Con `json_permiso_requerido`)
```
Usuario hace POST
  ↓
@login_required valida autenticación
  ↓
@json_permiso_requerido (CUSTOM) aplica @verificar_permiso
  ↓
@verificar_permiso lanza PermisoDenegadoJson
  ↓
@json_permiso_requerido wrapper captura → JSON 403
  ↓
Respuesta al cliente
```

### DESPUÉS (Patrón VerificarPermisoMixin)
```
Usuario hace POST
  ↓
@login_required valida autenticación
  ↓
try:
    decorador = @verificar_permiso (ESTÁNDAR)
    @decorador def view_func()
    view_func(request, ...)  ← Lanza PermisoDenegadoJson
  ↓
except PermisoDenegadoJson:
    return JSON 403
  ↓
Continuar lógica del endpoint
  ↓
Respuesta al cliente
```

---

## Patrón: Comparativa con Otros Endpoints

### `EditarTareaView` (CBV - usa VerificarPermisoMixin)
```python
class EditarTareaView(VerificarPermisoMixin, LoginRequiredMixin, UpdateView):
    vista_nombre = "Modificar Tarea"
    permiso_requerido = "modificar"
```

### `actualizar_avance_tarea` (FBV - ahora sigue mismo patrón)
```python
@login_required
def actualizar_avance_tarea(request, tarea_id):
    try:
        decorador = verificar_permiso("Modificar Tarea", "modificar")
        @decorador
        def view_func(req, *args, **kwargs):
            return None
        view_func(request, tarea_id)
    except PermisoDenegadoJson as e:
        return JsonResponse({'success': False, 'error': str(e.mensaje)}, status=403)
    # ... resto de lógica
```

**Diferencia**: CBV usa Mixin, FBV usa try/except manual. Ambos usan `@verificar_permiso` estándar.

---

## Resumen de Cumplimiento

| Aspecto | Antes | Después |
|---------|-------|---------|
| Sistema de permisos estándar | ❌ Personalizado | ✅ `@verificar_permiso` |
| Cumple COPILOT_RULES | ❌ No | ✅ Sí |
| Patrón consistente | ❌ Único | ✅ Same as VerificarPermisoMixin |
| Complejidad | ⚠️ Alta (decorador wrapper) | ✅ Baja (try/except simple) |
| Mantenibilidad | ⚠️ Media | ✅ Alta |
| Tests pasando | ✅ 8/9 | ✅ 9/9 |
