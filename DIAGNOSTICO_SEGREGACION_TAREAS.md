# ✅ DIAGNÓSTICO Y FIX: Segregación de Datos en Crear Tarea

## 📋 PROBLEMA IDENTIFICADO

**Ubicación**: [control_de_proyectos/forms.py](control_de_proyectos/forms.py#L67-L115) - `TareaForm`

**Síntomas**:
- Campo "Depende de" mostraba tareas de TODOS los proyectos/empresas
- Profesional asignado: sin filtro por empresa
- Campo Proyecto: podía cambiar el proyecto (sin restricción)

**Root cause**:
1. TareaForm NO tenía método `__init__()` personalizado
2. CrearTareaView/EditarTareaView NO pasaban `proyecto_id` al formulario
3. Queryset de campos estaban usando default (sin filtración)

---

## 🔍 DIAGNÓSTICO DETALLADO

### **Tarea 1: Vista Crear Tarea**
- **Archivo**: [control_de_proyectos/views.py](control_de_proyectos/views.py#L147)
- **Clase**: `CrearTareaView` (línea 147)
- **URL**: `/proyectos/<int:proyecto_id>/tareas/crear/`
- **Herencia**: VerificarPermisoMixin + LoginRequiredMixin + CreateView

### **Tarea 2: Form y Campo "Depende de"**
- **Archivo**: [control_de_proyectos/forms.py](control_de_proyectos/forms.py#L67-L115)
- **Clase**: `TareaForm`
- **Campo problemático**: `depende_de` (línea 96)
  ```python
  'depende_de': forms.CheckboxSelectMultiple(),
  ```
- **Modelo relación**: `Tarea.depende_de = ManyToManyField('self', ...)`
- **BUG**: Sin queryset filtrado en `__init__()`

### **Tarea 3: Filtro "Depende de"**
- **Debe**: Mostrar SOLO tareas del MISMO proyecto
- **Mecanismo**: Recibir `proyecto_id` desde URL y filtrar en form `__init__()`

### **Tarea 4: Filtro "Profesional asignado"**
- **Modelo**: `Proyecto.profesionales` es M2M a `Profesional`
- **Debe**: Mostrar profesionales asociados al proyecto
- **Filtro**: `proyecto.profesionales.all()`

### **Tarea 5: Filtro "Proyecto"**
- **Debe**: Mostrar SOLO el proyecto actual (no cambiar)
- **Solución**: `disabled=True` en el campo

---

## 🔧 CAMBIOS IMPLEMENTADOS

### **1. TareaForm - Agregar `__init__()` con filtros**

**Archivo**: [control_de_proyectos/forms.py](control_de_proyectos/forms.py#L67-L115)

```python
def __init__(self, *args, **kwargs):
    # Guardar proyecto_id para filtración (pasado por la vista)
    self.proyecto_id_filtro = kwargs.pop('proyecto_id', None)
    super().__init__(*args, **kwargs)
    
    # Determinar proyecto de filtro
    proyecto_para_filtro = self.proyecto_id_filtro or (
        self.instance.proyecto_id if self.instance.pk else None
    )
    
    if proyecto_para_filtro:
        try:
            proyecto = Proyecto.objects.get(pk=proyecto_para_filtro)
            
            # 1. FILTRAR "depende_de": Solo tareas del MISMO proyecto
            self.fields['depende_de'].queryset = Tarea.objects.filter(
                proyecto_id=proyecto_para_filtro
            ).exclude(pk=self.instance.pk if self.instance.pk else None)
            
            # 2. FILTRAR "profesional_asignado": Profesionales del proyecto
            self.fields['profesional_asignado'].queryset = proyecto.profesionales.all()
            
            # 3. FILTRAR "proyecto": Solo el proyecto actual (no permitir cambio)
            self.fields['proyecto'].queryset = Proyecto.objects.filter(
                pk=proyecto_para_filtro
            )
            self.fields['proyecto'].disabled = True
            
        except Proyecto.DoesNotExist:
            pass
```

**Validación adicional en `clean()`**:
```python
# Validar que "depende_de" solo contenga tareas del MISMO proyecto
if proyecto and depende_de:
    for tarea_dep in depende_de:
        if tarea_dep.proyecto_id != proyecto.id:
            raise ValidationError(
                f'La tarea "{tarea_dep.nombre}" pertenece a otro proyecto. '
                f'Solo se permiten dependencias dentro del mismo proyecto.'
            )
```

---

### **2. CrearTareaView - Pasar proyecto_id al formulario**

**Archivo**: [control_de_proyectos/views.py](control_de_proyectos/views.py#L147-L175)

```python
def get_form_kwargs(self):
    """Pasar proyecto_id al formulario para filtración de campos"""
    kwargs = super().get_form_kwargs()
    proyecto_id = self.kwargs.get('proyecto_id')
    if proyecto_id:
        kwargs['proyecto_id'] = proyecto_id  # ← NUEVO
    return kwargs
```

---

### **3. EditarTareaView - Pasar proyecto_id al formulario**

**Archivo**: [control_de_proyectos/views.py](control_de_proyectos/views.py#L179-L195)

```python
def get_form_kwargs(self):
    """Pasar proyecto_id al formulario para filtración de campos"""
    kwargs = super().get_form_kwargs()
    if self.object and self.object.proyecto_id:
        kwargs['proyecto_id'] = self.object.proyecto_id  # ← NUEVO
    return kwargs
```

---

## 📊 COMPARATIVA ANTES/DESPUÉS

| Aspecto | Antes | Después |
|--------|-------|---------|
| **Depende de** | Todas las tareas del sistema | Solo tareas del proyecto actual |
| **Profesional asignado** | Todos los profesionales | Solo asociados al proyecto |
| **Proyecto** | Campo editable (riesgo) | Deshabilitado (seguro) |
| **Validación server-side** | No existía | Rechaza si tarea es de otro proyecto |
| **Segregación Empresa** | ❌ Violada | ✅ Respetada (a través de proyecto) |

---

## ✅ CHECKLIST DE VERIFICACIÓN

### **Test 1: Crear Tarea en Empresa A**
```
1. Ir a: Empresa A → Proyecto P1
2. Crear nueva tarea:
   - Nombre: "Tarea Test A1"
   - Proyecto: [auto = P1]
   - Depende de: [checkbox] → ¿Aparecen SOLO tareas de P1?
   - Profesional: [dropdown] → ¿Aparecen SOLO profesionales de P1/Empresa A?

✅ ESPERADO: Solo opciones de P1 + Empresa A
❌ FALLA SI: Aparecen tareas de P2, P3 u otras empresas
```

### **Test 2: Verificar "Proyecto" deshabilitado**
```
1. Abrir formulario crear tarea (Empresa A → P1)
2. Campo "Proyecto":
   - ¿Está deshabilitado (gris, no seleccionable)?
   - ¿Muestra P1 pre-rellenado?

✅ ESPERADO: Campo bloqueado + P1 visible
❌ FALLA SI: Campo editable o permite cambiar proyecto
```

### **Test 3: Crear Tarea en Empresa B (otro perfil/sesión)**
```
1. Cambiar a Empresa B en session (o login otro usuario)
2. Crear tarea en Empresa B → Proyecto P2
3. Campo "Depende de": ¿Muestra tareas de P2 o de P1?

✅ ESPERADO: Solo tareas de P2
❌ FALLA SI: Aparecen tareas de P1 (violación segregación)
```

### **Test 4: Validación Server-Side de Dependencias**
```
1. Crear dos proyectos en misma empresa: P1 (Tarea T1.1), P2 (Tarea T2.1)
2. Intentar crear tarea en P1 con "Depende de: T2.1" (del otro proyecto)
   - Vía UI: No debería aparecer T2.1 en checkbox
   - Vía API (si existe): Debe rechazar con ValidationError

✅ ESPERADO: T2.1 NO visible + si se envía fuerza server rechaza
❌ FALLA SI: Aparece T2.1 o permite dependencia cruzada
```

### **Test 5: Editar Tarea (conservar filtros)**
```
1. Crear Tarea T1 en P1 con "Depende de: ninguna"
2. Editar T1:
   - ¿Aparecen los mismos filtros de proyecto + depende_de?
   - ¿Puede cambiar proyecto? (No debería)

✅ ESPERADO: Filtros iguales + proyecto bloqueado
❌ FALLA SI: Permite cambiar proyecto o ve tareas de otros
```

### **Test 6: Validar con SQL**
```sql
-- En SQLite: Verificar que tareas creadas están segregadas por proyecto
SELECT 
  t.id, t.nombre, t.proyecto_id, p.nombre as proyecto,
  p.empresa_interna_id, e.nombre as empresa
FROM control_de_proyectos_tarea t
JOIN control_de_proyectos_proyecto p ON t.proyecto_id = p.id
JOIN access_control_empresa e ON p.empresa_interna_id = e.id
WHERE t.nombre LIKE '%Test%'
ORDER BY e.id, p.id;

-- Verificar dependencias (no deben cruzar proyectos)
SELECT 
  t1.id as tarea_id, t1.nombre,
  t1.proyecto_id, t2.proyecto_id as depende_proyecto_id
FROM control_de_proyectos_tarea_depende_de rel
JOIN control_de_proyectos_tarea t1 ON rel.from_tarea_id = t1.id
JOIN control_de_proyectos_tarea t2 ON rel.to_tarea_id = t2.id
WHERE t1.proyecto_id != t2.proyecto_id;

-- Debe retornar 0 filas (sin dependencias cruzadas)
```

---

## 🛡️ PUNTOS DE SEGURIDAD

| Punto | Implementación |
|-------|-----------------|
| **Queryset server-side** | ✅ TareaForm `__init__()` filtra por proyecto |
| **Validación clean()** | ✅ Rechaza si depende_de no es del mismo proyecto |
| **Campo proyecto bloqueado** | ✅ `disabled=True` previene cambio cliente |
| **Paso de proyecto_id** | ✅ Via `get_form_kwargs()` desde URL |
| **Segregación empresa** | ✅ A través de proyecto.empresa_interna (FK) |

---

## 📝 RESUMEN TÉCNICO

**Archivos modificados**: 2
- [control_de_proyectos/forms.py](control_de_proyectos/forms.py)
- [control_de_proyectos/views.py](control_de_proyectos/views.py)

**Líneas agregadas**: ~50
**Líneas eliminadas**: 0
**Breaking changes**: Ninguno

**Patrones usados**:
- `__init__()` personalizado en ModelForm (patrón Django estándar)
- `get_form_kwargs()` para pasar contexto (patrón CBV estándar)
- `disabled=True` para campos inmutables (seguridad cliente)
- `ValidationError` en clean() (validación server-side)

**Cumplimiento COPILOT_RULES.md**:
- ✅ No inventar nuevos sistemas
- ✅ Usar patrones de `biblioteca` (no hay diferencia)
- ✅ Usar decoradores `verificar_permiso()` (ya presente)
- ✅ Cambios mínimos, no-breaking

---

## 🚀 PRÓXIMOS PASOS (si aplica)

1. **Ejecutar checklist de tests** (6 items arriba)
2. **Revisar logs** si hay ValidationError (expected si se intenta violar regla)
3. **Documentar casos edge**: ¿Qué pasa si proyecto se elimina? (casaca a través de FK)
4. **Considerar**: Agregar validación similar a otros formularios que usen Proyecto (si existen)

---

## ✨ CONCLUSIÓN

La solución implementa **segregación de datos por proyecto** a nivel:
- ✅ **ORM** (queryset filtrado en form)
- ✅ **Validación** (clean() rechaza violaciones)
- ✅ **UI** (campo bloqueado, solo opciones válidas visibles)
- ✅ **Seguridad** (server-side, no confiar en cliente)

**Estado**: 🟢 LISTO PARA TESTEAR
