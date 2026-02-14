# Migración CBV + Mixin Oficial: control_de_proyectos

## Resumen Ejecutivo

### Completado: ✅
1. **Mixin local eliminado** → Importa `VerificarPermisoMixin` oficial desde `access_control.views`
2. **Vista.nombre estandarizado** → Todos los nombres de vistas ahora usan prefijo "Control de Proyectos - "
3. **Empresa activa validado** → Implementado helper `_get_empresa_id(request)` + `build_access_request_context()` en dispatch()
4. **ActualizarAvanceTareaView creada** → Convertida de FBV a CBV heredando VerificarPermisoMixin
5. **Tests actualizados** → 6/6 tests de control_de_proyectos pasando (100%)
6. **URLs preservadas** → Mantiene nombres de endpoints exactamente igual

---

## Cambios Realizados

### A) Imports / Mixin

**Eliminado:**
```python
class VerificarPermisoMixin:  # Mixin local (51 líneas)
from access_control.decorators import PermisoDenegadoJson
from django.views.generic.edit import FormMixin
```

**Agregado:**
```python
from access_control.views import VerificarPermisoMixin  # Mixin oficial
from access_control.services.access_requests import build_access_request_context
```

**Helper agregado:**
```python
def _get_empresa_id(request):
    return request.session.get("empresa_id")
```

---

### B) Vista.nombre Estandarizado (14 vistas CBV)

| Vista Anterior | Vista Nueva |
|---|---|
| "Listar Proyectos" | "Control de Proyectos - Proyectos" |
| "Ver Detalle Proyecto" | "Control de Proyectos - Detalle de proyecto" |
| "Crear Proyecto" | "Control de Proyectos - Crear proyecto" |
| "Modificar Proyecto" | "Control de Proyectos - Editar proyecto" |
| "Eliminar Proyecto" | "Control de Proyectos - Eliminar proyecto" |
| "Crear Tarea" | "Control de Proyectos - Crear tarea" |
| "Modificar Tarea" | "Control de Proyectos - Editar tarea" |
| "Eliminar Tarea" | "Control de Proyectos - Eliminar tarea" |
| "Listar Clientes" | "Control de Proyectos - Clientes" |
| "Crear Cliente" | "Control de Proyectos - Crear cliente" |
| "Modificar Cliente" | "Control de Proyectos - Editar cliente" |
| "Listar Profesionales" | "Control de Proyectos - Profesionales" |
| "Crear Profesional" | "Control de Proyectos - Crear profesional" |
| "Modificar Profesional" | "Control de Proyectos - Editar profesional" |
| "Crear Tipo Tarea" | "Control de Proyectos - Crear tipo de tarea" |
| "SubirDocumentoTareaView" | "Control de Proyectos - Subir documento de tarea" |
| (FBV) actualizar_avance_tarea | "Control de Proyectos - Actualizar avance de tarea" |
| (FBV) sugerir_tipos_proyecto | "Control de Proyectos - Autocomplete tipos de proyecto" |
| (FBV) sugerir_especialidades | "Control de Proyectos - Autocomplete especialidades" |

---

### C) Empresa Activa: Validación Consistente

**Patrón implementado en dispatch() de vistas críticas:**

```python
def dispatch(self, request, *args, **kwargs):
    empresa_id = _get_empresa_id(request)
    if not empresa_id:
        contexto = build_access_request_context(
            request,
            self.vista_nombre,
            "No tienes permisos suficientes para acceder a esta página.",
        )
        return render(request, "access_control/403_forbidden.html", contexto, status=403)
    return super().dispatch(request, *args, **kwargs)
```

**Vistas con validación de empresa en dispatch():**
- ListarProyectosView
- CrearProyectoView  
- CrearTareaView

**Vistas con scoping en get_queryset():**
- DetalleProyectoView → filtra por empresa_interna_id
- EditarProyectoView → filtra por empresa_interna_id
- EliminarProyectoView → filtra por empresa_interna_id
- EditarTareaView → select_related('proyecto') + filtra por proyecto__empresa_interna_id
- EliminarTareaView → select_related('proyecto') + filtra por proyecto__empresa_interna_id
- SubirDocumentoTareaView → valida empresa_id en post() con get_object_or_404 scope

---

### D) Conversión FBV → CBV: actualizar_avance_tarea

**Antes:**
```python
@login_required
def actualizar_avance_tarea(request, tarea_id):
    # Decorador manual con try/except
    vista_nombre = "Modificar Tarea"
    ...
```

**Después:**
```python
class ActualizarAvanceTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Control de Proyectos - Actualizar avance de tarea"
    permiso_requerido = "modificar"
    
    def post(self, request, tarea_id):
        empresa_id = _get_empresa_id(request)
        if not empresa_id: return 403
        # ... validación + actualización ...
```

**URL (sin cambios):**
```python
path('tareas/<int:tarea_id>/avance/', views.ActualizarAvanceTareaView.as_view(), name='actualizar_avance_tarea')
```

---

### E) Limpieza de Imports

**Eliminados (no usados):**
- `FormMixin` (no se usa en esta app)
- `PermisoDenegadoJson` (manejo delegado a mixin oficial)

**Comportamiento: Idéntico**

Todas las vistas AJAX mantienen:
- Mismo payload de respuestas (200/400/403/404/500)
- Mismos códigos HTTP
- Misma validación de datos
- Mismos endpoints + names

---

## Tests: Resultado

### control_de_proyectos/tests/
```
✅ test_csrf.py              (2 tests)
✅ test_permissions.py       (2 tests)
✅ test_scoping.py           (2 tests)
─────────────────────────────────────────
✅ TOTAL: 6/6 PASSING (100%)
```

### Cambios en tests:
1. `test_csrf.py`: Vista "Modificar Tarea" → "Control de Proyectos - Actualizar avance de tarea"
2. `test_permissions.py`: Vista "Modificar Tarea" → "Control de Proyectos - Actualizar avance de tarea"
3. `test_scoping.py`: Vista "Listar Proyectos" → "Control de Proyectos - Proyectos"

---

## Líneas de Código Cambiadas

```
 control_de_proyectos/views.py                  | 340 ++++++++++++++----------- 
 control_de_proyectos/urls.py                   |   2 +-
 control_de_proyectos/tests/test_csrf.py        |   4 +-
 control_de_proyectos/tests/test_permissions.py |   2 +-
 control_de_proyectos/tests/test_scoping.py     |   2 +-
 ───────────────────────────────────────────────────────────────────────────
 5 files changed, 193 insertions(+), 157 deletions(-)
```

**Resultado neto:** +36 líneas (beneficio: mixin oficial, validación empresa, mejor scoping)

---

## Validación Final

✅ **Todas las URLs preservadas:** 
- Los `name` de rutas NO cambiaron
- Los `path()` mantienen exactamente igual patrón
- Templates pueden seguir usando {% url %} sin cambios

✅ **Compatibilidad SQLite:** 
- Cero cambios en modelos
- Cero migr aciones necesarias

✅ **Producción segura:**
- No se toca login/logout ni UserPreferences
- Mixin oficial + validación empresa = seguridad reforzada
- Mismo comportamiento AJAX (respuestas idénticas)

---

## Errores Globales del Proyecto (NO de control_de_proyectos)

```
Ran 159 tests in 123.196s
FAILED (failures=1, errors=3)  ← Otros módulos
───────────────────────────────
control_de_proyectos: ✅ 6/6 PASSING
```

**Conclusión:** El módulo control_de_proyectos está completamente funcional.

---

## Entregables

1. **diff_control_proyectos_FINAL.txt** (581 líneas) → Todos los cambios detallados
2. **control_de_proyectos/views.py** → Refactorizado + mixin oficial
3. **control_de_proyectos/urls.py** → ActualizarAvanceTareaView.as_view()
4. **Tests actualizados** → 6/6 pasando con nuevos nombres de Vista
