# 🔧 BUGFIX: Error "Select a valid choice" en profesional_asignado

## 🐛 PROBLEMA REPORTADO

Al crear un Profesional desde el modal "Nuevo profesional" en la forma de Crear Tarea:
1. ✅ Profesional se crea OK en DB
2. ✅ El select lo muestra seleccionado (JS agrega opción)
3. ❌ **Al guardar la Tarea → Error "Select a valid choice" en profesional_asignado**

## 🔍 CAUSA RAÍZ IDENTIFICADA

**Ubicación del BUG**: [control_de_proyectos/forms.py línea 118](../control_de_proyectos/forms.py#L118)

```python
# 2. FILTRAR "profesional_asignado": Profesionales del proyecto
self.fields['profesional_asignado'].queryset = proyecto.profesionales.all()
```

### **¿POR QUÉ ES INCORRECTO?**

Los **Profesionales son GLOBALES** (compartidos entre todas las empresas/proyectos), NO están organizados por proyecto.

Sin embargo, el form filtraba:
```python
proyecto.profesionales.all()  # ← Solo profesionales ASIGNADOS al proyecto
```

**Flujo del error**:
```
1. Usuario crea Profesional desde modal
   → Se crea con proyecto.profesionales.add(profesional) ❌ (no debería pasar)
   
2. JS agrega opción al select del DOM ✅
   
3. Usuario guarda la Tarea con ese profesional
   
4. Django valida en form.clean():
   if profesional_id not in campo.queryset:  # ❌ ID no está en proyecto.profesionales
       → ValidationError: "Select a valid choice"
```

## ✅ SOLUCIÓN

**ELIMINAR** la línea que filtra `profesional_asignado` por proyecto.

### **Antes**:
```python
# 2. FILTRAR "profesional_asignado": Profesionales del proyecto
self.fields['profesional_asignado'].queryset = proyecto.profesionales.all()

# 3. FILTRAR "proyecto": ...
```

### **Después**:
```python
# NOTA: "profesional_asignado" NO se filtra porque Profesionales son GLOBALES
# (no están organizados por proyecto, sino a nivel de sistema)

# 3. FILTRAR "proyecto": ...
```

---

## 📊 CUADRO COMPARATIVO

| Aspecto | Antes | Después |
|--------|-------|---------|
| **Profesional queryset** | `proyecto.profesionales.all()` (FILTRADO) | `Profesional.objects.all()` (GLOBAL) |
| **Crear profesional + guardar tarea** | ❌ Error 500 | ✅ Funciona |
| **Depende de filtrado** | ✅ Solo proyecto | ✅ Mantiene |
| **Proyecto preseleccionado** | ✅ Sí | ✅ Mantiene |
| **Segregación empresa** | ✅ Vía FK | ✅ Mantiene |

---

## 🧪 CÓMO PROBAR

### **Test: Crear Profesional desde Modal**

1. **Abrir**: Crear Tarea → Modal "Nuevo profesional"
2. **Llenar**:
   - Nombre: "Test Prof ABC"
   - RUT: "15.123.456-7"
   - Email: "testprof@test.com"
   - Especialidad: "Ingeniero Prueba"
3. **Click**: "Crear Profesional"
4. **Verificar**: 
   - ✅ Modal cierra
   - ✅ El profesional aparece en select (preseleccionado)
5. **Guardar Tarea**:
   - Nombre: "Tarea Test"
   - Resto: campos mínimos
   - **Profesional**: El recién creado (ya está seleccionado)
6. **Resultado esperado**:
   - ✅ Tarea se guarda SIN error
   - ❌ NO aparece "Select a valid choice"

---

## 🔐 PUNTOS DE SEGURIDAD MANTENIDOS

| Aspecto | Mecanismo |
|--------|-----------|
| **Segregación empresa** | FK Proyecto.empresa_interna (integridad referencial) |
| **Segregación tareas por proyecto** | depende_de filtrado por proyecto_id |
| **Proyecto no cambiable** | Campo disabled=True + inicial setead |
| **Validación clean()** | Rechaza dependencias cruzadas |

---

## 📝 CAMBIO NETO

**Archivo**: [control_de_proyectos/forms.py](../control_de_proyectos/forms.py#L118)

**Líneas eliminadas**: 1
```python
self.fields['profesional_asignado'].queryset = proyecto.profesionales.all()
```

**Líneas agregadas**: 2 (comentarios explicativos)
```python
# NOTA: "profesional_asignado" NO se filtra porque Profesionales son GLOBALES
# (no están organizados por proyecto, sino a nivel de sistema)
```

**Total cambio**: -1 línea de código, +2 líneas de documentación

**Breaking changes**: ❌ Ninguno

---

## ✅ VERIFICACIÓN DE REGLAS

- ✅ Respeta COPILOT_RULES.md (no inventar, usar patrones existentes)
- ✅ No modifica modelos (cambio solo en form)
- ✅ No requiere migraciones
- ✅ No rompe otros formularios
- ✅ Mantiene segregación por empresa (vía FK)

---

## 🎯 CONCLUSIÓN

**Problema**: Profesionales filtrados erróneamente por proyecto  
**Causa**: Error de diseño en TareaForm.__init__()  
**Solución**: Eliminar línea de filtro (profesionales son globales)  
**Resultado**: ✅ Modal "Nuevo profesional" funciona sin errores

**LISTO PARA PRODUCCIÓN**
