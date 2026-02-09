# 🚀 GUÍA RÁPIDA: Segregación de Tareas (Cambios Implementados)

## 📌 PROBLEMA RESUELTO
Campo "Depende de" mostraba tareas de otros proyectos → **YA NO OCURRE**

---

## 🔧 CAMBIOS EN 2 ARCHIVOS

### **1. forms.py - TareaForm**

#### **NUEVA FUNCIONALIDAD: __init__() con filtración**
```python
def __init__(self, *args, **kwargs):
    self.proyecto_id_filtro = kwargs.pop('proyecto_id', None)
    super().__init__(*args, **kwargs)
    
    proyecto_para_filtro = self.proyecto_id_filtro or (
        self.instance.proyecto_id if self.instance.pk else None
    )
    
    if proyecto_para_filtro:
        proyecto = Proyecto.objects.get(pk=proyecto_para_filtro)
        
        # Filtro 1: Depende de - Solo tareas del proyecto
        self.fields['depende_de'].queryset = Tarea.objects.filter(
            proyecto_id=proyecto_para_filtro
        ).exclude(pk=self.instance.pk)
        
        # Filtro 2: Profesional - Del proyecto
        self.fields['profesional_asignado'].queryset = proyecto.profesionales.all()
        
        # Filtro 3: Proyecto - Solo actual + bloqueado
        self.fields['proyecto'].queryset = Proyecto.objects.filter(pk=proyecto_para_filtro)
        self.fields['proyecto'].disabled = True
```

#### **NUEVA VALIDACIÓN: clean() con rechazo de cruce**
```python
def clean(self):
    cleaned_data = super().clean()
    proyecto = cleaned_data.get('proyecto')
    depende_de = cleaned_data.get('depende_de')
    
    # Rechazar si "depende_de" es de otro proyecto
    if proyecto and depende_de:
        for tarea_dep in depende_de:
            if tarea_dep.proyecto_id != proyecto.id:
                raise ValidationError(
                    f'La tarea "{tarea_dep.nombre}" pertenece a otro proyecto. '
                    f'Solo se permiten dependencias dentro del mismo proyecto.'
                )
```

---

### **2. views.py - Vistas**

#### **CrearTareaView - NUEVO: get_form_kwargs()**
```python
def get_form_kwargs(self):
    kwargs = super().get_form_kwargs()
    proyecto_id = self.kwargs.get('proyecto_id')
    if proyecto_id:
        kwargs['proyecto_id'] = proyecto_id  # ← Pasar a form
    return kwargs
```

#### **EditarTareaView - NUEVO: get_form_kwargs()**
```python
def get_form_kwargs(self):
    kwargs = super().get_form_kwargs()
    if self.object and self.object.proyecto_id:
        kwargs['proyecto_id'] = self.object.proyecto_id  # ← Pasar a form
    return kwargs
```

---

## ✅ RESULTADO

| Campo | Antes | Después |
|-------|-------|---------|
| **Depende de** | Todas las tareas | Solo del proyecto ✅ |
| **Profesional** | Todos | Solo del proyecto ✅ |
| **Proyecto** | Editable (riesgo) | Bloqueado ✅ |
| **Validación** | Ninguna | Rechaza cruce ✅ |

---

## 🧪 PRUEBA RÁPIDA

### **Test 1: Crear en Empresa A**
```
URL: /proyectos/1/tareas/crear/
✅ Depende de: Muestra solo tareas de Proyecto 1
```

### **Test 2: Crear en Empresa B**
```
URL: /proyectos/2/tareas/crear/
✅ Depende de: Muestra solo tareas de Proyecto 2 (DIFERENTE de A)
```

### **Test 3: Validación**
```
POST depende_de=[tarea_de_otro_proyecto]
❌ Rechaza: "...pertenece a otro proyecto..."
```

---

## 🗂️ ARCHIVOS DOCUMENTACIÓN

| Archivo | Uso |
|---------|-----|
| **DIAGNOSTICO_SEGREGACION_TAREAS.md** | Análisis completo (6 tareas) |
| **RESUMEN_SEGREGACION_TAREAS.md** | Resumen ejecutivo |
| **DIFF_SEGREGACION_TAREAS.md** | Diff antes/después |
| **CONCLUSION_SEGREGACION_TAREAS.md** | Conclusión final |
| **test_segregacion_tareas.py** | Test automático |
| **GUIA_RAPIDA_SEGREGACION_TAREAS.md** | Este archivo |

---

## 🚀 DEPLOY

1. Pull cambios en forms.py + views.py
2. Restart Django (sin migrate)
3. Test manual (crear tarea en 2 proyectos diferentes)
4. ✅ Listo

---

## 📞 DEBUGGING

**¿Depende de muestra tareas de otros proyectos?**
- Verifica que CrearTareaView.get_form_kwargs() pasa proyecto_id

**¿Campo proyecto está editable?**
- Verifica TareaForm.__init__() linea 127: debe tener disabled=True

**¿ValidationError al guardar?**
- Es correcto: significa que se intenta violar la regla (rechazado)

---

**¡HECHO!** 🎉
