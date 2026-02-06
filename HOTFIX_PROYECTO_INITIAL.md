# 🔧 HOTFIX: Recuperar Selección Automática del Proyecto en Crear Tarea

## 🐛 PROBLEMA

Después del fix de segregación de "Depende de", el campo "Proyecto" en el formulario quedaba **vacío** en lugar de mostrar el proyecto preseleccionado.

## ❌ ¿POR QUÉ PASÓ?

```python
# ANTES (código antiguo):
def get_form_kwargs(self):
    kwargs['initial'] = {'proyecto': proyecto_id}  # ✅ Preseleccionar
    
# AHORA (con fix de segregación):
def get_form_kwargs(self):
    kwargs['proyecto_id'] = proyecto_id  # ✅ Para filtración
    # ❌ Se perdió el 'initial'
```

El problema: Cuando hicimos el fix de segregación, pasamos `proyecto_id` al form para filtrar querysets, pero **olvidamos setear el `initial`** del campo.

---

## ✅ SOLUCIÓN (2 lugares)

### **1. TareaForm.__init__() en forms.py**

**Línea 124**: Agregar una línea después de filtrar el queryset:

```python
# 3. FILTRAR "proyecto": Solo el proyecto actual (no permitir cambio)
self.fields['proyecto'].queryset = Proyecto.objects.filter(
    pk=proyecto_para_filtro
)
self.fields['proyecto'].initial = proyecto  # ← NUEVA LÍNEA
self.fields['proyecto'].disabled = True
```

**Efecto**: El campo "Proyecto" ahora mostrará el proyecto preseleccionado.

---

### **2. CrearTareaView.get_initial() en views.py**

**Línea 161-170**: Agregar nuevo método `get_initial()`:

```python
def get_initial(self):
    """Preseleccionar proyecto si viene en URL"""
    initial = super().get_initial()
    proyecto_id = self.kwargs.get('proyecto_id')
    if proyecto_id:
        try:
            initial['proyecto'] = Proyecto.objects.get(pk=proyecto_id)
        except Proyecto.DoesNotExist:
            pass
    return initial
```

**Efecto**: Segunda línea de defensa para asegurar que el initial siempre se setea a nivel view.

---

## 📊 RESULTADO

| Aspecto | Antes | Después |
|--------|-------|---------|
| **Campo Proyecto en formulario** | ❌ Vacío | ✅ Preseleccionado |
| **Depende de filtrado** | ✅ Solo proyecto | ✅ Solo proyecto |
| **Profesional filtrado** | ✅ Del proyecto | ✅ Del proyecto |
| **Proyecto bloqueado** | ✅ Disabled | ✅ Disabled |

---

## 🧪 CÓMO PROBAR

1. **Ir a**: Proyecto (Detalle) → Crear Tarea
2. **Verificar**:
   - ✅ Campo "Proyecto" muestra el nombre del proyecto (preseleccionado)
   - ✅ Campo "Depende de" solo muestra tareas de ESE proyecto
   - ✅ Campo "Profesional" solo muestra profesionales del proyecto
   - ✅ Ningún campo permite cambiar el proyecto

3. **Extra**: Intentar POST con proyecto diferente → Debe rechazar con ValidationError

---

## 📝 CAMBIOS NETTOS

| Archivo | Líneas | Cambio |
|---------|--------|--------|
| **forms.py** | 124 | +1 (setear initial) |
| **views.py** | 161-170 | +9 (get_initial completo) |
| **Total** | | +10 líneas |

**Breaking changes**: ❌ Ninguno

---

## 🔐 SEGURIDAD MANTENIDA

```
Capas de protección:
1️⃣ UI: Queryset filtrado (solo opciones válidas)
2️⃣ Form: clean() rechaza dependencias cruzadas
3️⃣ View: Pasar proyecto_id + setear initial
4️⃣ DB: FK integridad referencial
```

---

## ✅ VERIFICACIÓN RÁPIDA

**Ejecutar**:
```bash
# Test manual:
1. Login → Proyecto P1 → "Crear Tarea"
2. Verificar campo Proyecto = P1 (preseleccionado)
3. Verificar "Depende de" = solo tareas de P1
4. OK ✅
```

---

**LISTO** 🎉 - Proyecto preseleccionado + segregación mantenida
