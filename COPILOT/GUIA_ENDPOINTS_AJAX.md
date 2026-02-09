# 📚 Guía de Patrones para Endpoints AJAX con Permisos

## ¿Cuándo aplicar cada patrón?

### 1️⃣ Class-Based Views (CBV) - Usar VerificarPermisoMixin

```python
from access_control.decorators import VerificarPermisoMixin

class MiVistaView(VerificarPermisoMixin, LoginRequiredMixin, UpdateView):
    """
    CBV que hereda de VerificarPermisoMixin
    El mixin maneja permisos automáticamente en dispatch()
    """
    model = MiModelo
    form_class = MiForm
    vista_nombre = "Mi Vista"
    permiso_requerido = "modificar"
    
    def form_valid(self, form):
        # Lógica después de validar permisos
        return super().form_valid(form)
```

**Cuándo usar:**
- Views con templates HTML
- Respuestas HTML (no JSON)
- Cambios en múltiples campos del modelo
- Flows complejos con múltiples pasos

---

### 2️⃣ Function-Based Views (FBV) para Endpoints AJAX - Patrón Try/Except

```python
from access_control.decorators import verificar_permiso, PermisoDenegadoJson

@login_required
def mi_endpoint_ajax(request, resource_id):
    """
    FBV para endpoints AJAX
    Retorna JSON, no HTML
    """
    # Paso 1: Validar permisos usando try/except
    vista_nombre = "Mi Vista"
    permiso_requerido = "modificar"
    
    try:
        # Crear el decorador
        decorador = verificar_permiso(vista_nombre, permiso_requerido)
        
        # Aplicar el decorador a una función dummy
        @decorador
        def view_func(req, *args, **kwargs):
            return None
        
        # Ejecutar para validar (puede lanzar PermisoDenegadoJson)
        view_func(request, resource_id)
        
    except PermisoDenegadoJson as e:
        # Retornar JSON 403 si no tiene permisos
        return JsonResponse(
            {'success': False, 'error': str(e.mensaje)},
            status=403
        )
    
    # Paso 2: Si llegó aquí, tiene permisos. Continuar con lógica
    if request.method != 'POST':
        return JsonResponse(
            {'success': False, 'error': 'Solo se permite POST'},
            status=405
        )
    
    try:
        # Paso 3: Obtener datos
        data = json.loads(request.body)
        
        # Paso 4: Validar datos
        if not data.get('campo_requerido'):
            return JsonResponse(
                {'success': False, 'error': 'Campo requerido'},
                status=400
            )
        
        # Paso 5: Realizar cambios
        objeto = MiModelo.objects.get(pk=resource_id)
        objeto.campo = data['campo_requerido']
        objeto.save()
        
        # Paso 6: Retornar éxito
        return JsonResponse({
            'success': True,
            'mensaje': 'Actualizado correctamente'
        }, status=200)
    
    except MiModelo.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Recurso no encontrado'},
            status=404
        )
    except json.JSONDecodeError:
        return JsonResponse(
            {'success': False, 'error': 'JSON inválido'},
            status=400
        )
    except Exception as e:
        return JsonResponse(
            {'success': False, 'error': f'Error: {str(e)}'},
            status=500
        )
```

**Cuándo usar:**
- Endpoints AJAX que retornan JSON
- Actualizaciones parciales de un recurso
- Operaciones rápidas sin templates
- APIs internas del sitio

---

## 🔄 Ejemplo Real: `actualizar_avance_tarea()`

### Ubicación
- **Archivo**: `control_de_proyectos/views.py`
- **Líneas**: 476-555
- **URL**: `POST /control-proyectos/tareas/<id>/avance/`

### Estructura
```python
@login_required
def actualizar_avance_tarea(request, tarea_id):
    # 1️⃣ Validar permisos (try/except)
    # 2️⃣ Validar método HTTP (POST)
    # 3️⃣ Obtener recurso
    # 4️⃣ Validar multiempresa
    # 5️⃣ Parsear JSON
    # 6️⃣ Validar datos (rango 0-100)
    # 7️⃣ Guardar cambios
    # 8️⃣ Retornar JSON
```

### Flujo de Validaciones
```
Usuario hace POST
  ↓
¿Autenticado? → No → 401 (django lo maneja)
  ↓ Sí
¿Tiene permiso "modificar"? → No → 403 JSON
  ↓ Sí
¿Método POST? → No → 405 JSON
  ↓ Sí
¿JSON válido? → No → 400 JSON
  ↓ Sí
¿Tarea existe? → No → 404 JSON
  ↓ Sí
¿Pertenece a empresa activa? → No → 403 JSON
  ↓ Sí
¿Porcentaje 0-100? → No → 400 JSON
  ↓ Sí
Guardar → 200 JSON {'success': true}
```

---

## ❌ Patrones a EVITAR

### ❌ NO HACER: Crear decoradores personalizados

```python
# ❌ MALO - Viola COPILOT_RULES
def mi_decorador_personalizado(vista_nombre, permiso):
    def decorator(view_func):
        def wrapper(request, *args, **kwargs):
            # Lógica de permisos personalizada
            pass
        return wrapper
    return decorator

@login_required
@mi_decorador_personalizado("Vista", "permiso")
def mi_vista(request):
    pass
```

**Por qué no:**
- Violate COPILOT_RULES: "No inventar nuevos sistemas de permisos"
- Duplica lógica ya existente en `@verificar_permiso`
- Difícil de mantener
- Inconsistencia con otros endpoints

---

### ❌ NO HACER: Ignorar multiempresa

```python
# ❌ MALO - No valida empresa del usuario
def actualizar_tarea(request, tarea_id):
    tarea = Tarea.objects.get(pk=tarea_id)
    tarea.nombre = request.POST.get('nombre')
    tarea.save()
    return redirect('detail', pk=tarea_id)
```

**Problema:**
- Usuario puede modificar tareas de otras empresas
- Violación de seguridad multiempresa

**Correcto:**
```python
# ✅ CORRECTO - Valida empresa activa
empresa_id = request.session.get("empresa_id")
if tarea.proyecto.empresa_id != empresa_id:
    return JsonResponse({'error': 'No autorizado'}, status=403)
```

---

### ❌ NO HACER: Retornar HTML en endpoints AJAX

```python
# ❌ MALO
def actualizar_ajax(request):
    if error:
        return render(request, 'error.html')  # ❌ HTML no es JSON
    return JsonResponse({'data': 'ok'})
```

**Problema:**
- JavaScript espera JSON, recibe HTML
- Fallos silenciosos en el frontend

**Correcto:**
```python
# ✅ CORRECTO - Siempre JSON
def actualizar_ajax(request):
    if error:
        return JsonResponse({'success': False, 'error': '...'}, status=400)
    return JsonResponse({'success': True, 'data': 'ok'}, status=200)
```

---

## 📋 Checklist para Nuevo Endpoint AJAX

- [ ] ¿Usa `@login_required`?
- [ ] ¿Usa `@verificar_permiso` o try/except? (nunca decorador personalizado)
- [ ] ¿Captura `PermisoDenegadoJson`?
- [ ] ¿Retorna JSON (no HTML)?
- [ ] ¿Valida método HTTP (POST/PUT)?
- [ ] ¿Parsea JSON correctamente?
- [ ] ¿Valida datos de entrada?
- [ ] ¿Valida multiempresa?
- [ ] ¿Retorna status codes correctos? (200/400/403/404/500)
- [ ] ¿Tiene try/except para excepciones?
- [ ] ¿Tests unitarios?
- [ ] ¿CSRF token en frontend?

---

## 🧪 Estructura de Tests Recomendada

```python
def test_endpoint_con_permiso_200():
    """Usuario con permiso actualiza → 200 OK"""
    client = Client()
    user = User.objects.create_user(username='test', password='pass')
    client.force_login(user)
    
    session = client.session
    session['empresa_id'] = empresa.id
    session.save()
    
    response = client.post(url, data=json.dumps(body), content_type='application/json')
    assert response.status_code == 200
    assert response.json()['success'] == True

def test_endpoint_sin_permiso_403():
    """Usuario sin permiso → 403 Forbidden"""
    # ... setup usuario sin permisos ...
    response = client.post(url, ...)
    assert response.status_code == 403
    assert response.json()['success'] == False

def test_endpoint_datos_invalidos_400():
    """Datos inválidos → 400 Bad Request"""
    response = client.post(url, data=json.dumps({'campo_invalido': 'x'}))
    assert response.status_code == 400

def test_endpoint_recurso_no_existe_404():
    """Recurso no existe → 404 Not Found"""
    response = client.post(url.replace('1', '99999'), ...)
    assert response.status_code == 404
```

---

## 📚 Referencias

- [COPILOT_RULES.md](../COPILOT_RULES.md) - Reglas generales de desarrollo
- [access_control/decorators.py](../access_control/decorators.py) - Decorador `@verificar_permiso`
- [control_de_proyectos/views.py](../control_de_proyectos/views.py#L476) - Ejemplo real: `actualizar_avance_tarea()`
- [REFACTOR_COPILOT_RULES.md](REFACTOR_COPILOT_RULES.md) - Caso de estudio completo

---

**Última actualización**: 2024  
**Autor**: GitHub Copilot  
**Estado**: Activo y en uso
