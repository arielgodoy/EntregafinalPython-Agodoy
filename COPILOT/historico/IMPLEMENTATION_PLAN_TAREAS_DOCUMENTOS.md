# 🎯 PLAN DE INTEGRACIÓN: Sistema Biblioteca → Control de Proyectos

## OBJETIVO
Implementar almacenamiento de archivos en tareas usando el patrón de **biblioteca** para:
- ✅ Guardar archivos en servidor (media/)
- ✅ Organizar por proyecto/tarea
- ✅ Validar tipos de archivo
- ✅ Generar rutas automáticas
- ✅ Permite descarga/respaldo

---

## 1. ESTADO ACTUAL

### ✅ YA EXISTE en models.py:
```python
class TareaDocumento(models.Model):
    tarea = ForeignKey(Tarea, CASCADE)
    archivo = FileField(upload_to='tareas_documentos/%Y/%m/%d/')
    url_documento = URLField()
    documento_biblioteca = ForeignKey('biblioteca.Documento')
    # + campos de estado, fecha, observaciones
```

### ✅ MODELOS RELACIONADOS:
- `DocumentoRequeridoTipoTarea` → Define qué documentos necesita cada tipo de tarea
- `Tarea` → Campos Gantt ya agregados
- `TipoTarea` → Creado previamente

---

## 2. LO QUE FALTA IMPLEMENTAR

### Paso 1: Función de ruta personalizada
```python
# EN: control_de_proyectos/models.py

import os
from django.utils.timezone import now

def archivo_tarea_path(instance, filename):
    """
    Genera ruta: media/tareas_documentos/[PROYECTO]_[TAREA]/[NOMBRE].[ext]
    Ejemplo: tareas_documentos/Sistema_Web/Diseño_UI/mockup_inicio.pdf
    """
    proyecto = instance.tarea.proyecto.nombre.replace(" ", "_").replace("/", "-")
    tarea = instance.tarea.nombre.replace(" ", "_").replace("/", "-")
    extension = os.path.splitext(filename)[1]
    
    nombre_limpio = f"{instance.tarea.nombre}_{now().strftime('%Y%m%d%H%M%S')}{extension}"
    
    return f"tareas_documentos/{proyecto}/{tarea}/{nombre_limpio}"


def validate_file_extension_tareas(value):
    """Validar extensiones permitidas para documentos de tareas"""
    extensiones_permitidas = ('.pdf', '.doc', '.docx', '.xlsx', '.xls', 
                              '.jpg', '.jpeg', '.png', '.gif', '.zip', '.rar')
    if not value.name.lower().endswith(extensiones_permitidas):
        raise ValidationError(
            'Formato no admitido. Permitidos: PDF, DOC, DOCX, XLSX, XLS, JPG, PNG, ZIP, RAR'
        )
```

### Paso 2: Actualizar modelo TareaDocumento
```python
# EN: control_de_proyectos/models.py

class TareaDocumento(models.Model):
    # ... campos existentes ...
    
    # CAMBIAR ESTO:
    # archivo = models.FileField(upload_to='tareas_documentos/%Y/%m/%d/', blank=True)
    
    # POR ESTO:
    archivo = models.FileField(
        upload_to=archivo_tarea_path,  # ← función personalizada
        validators=[validate_file_extension_tareas],  # ← validación
        blank=True
    )
    
    def __str__(self):
        return f"{self.nombre_documento} - {self.tarea.nombre}"
    
    class Meta:
        ordering = ['tarea', '-fecha_creacion']
        verbose_name = "Documento Tarea"
        verbose_name_plural = "Documentos Tarea"
```

### Paso 3: Crear Formulario para subir documentos
```python
# EN: control_de_proyectos/forms.py

from django import forms
from .models import TareaDocumento

class TareaDocumentoForm(forms.ModelForm):
    class Meta:
        model = TareaDocumento
        fields = ['nombre_documento', 'tipo_doc', 'archivo', 'url_documento', 'observaciones']
        widgets = {
            'nombre_documento': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre del documento'
            }),
            'tipo_doc': forms.Select(attrs={'class': 'form-select'}),
            'archivo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.doc,.docx,.xlsx,.xls,.jpg,.jpeg,.png,.gif,.zip,.rar'
            }),
            'url_documento': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'O proporcione una URL'
            }),
            'observaciones': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Observaciones adicionales'
            }),
        }
```

### Paso 4: Crear Vista AJAX para subir documentos
```python
# EN: control_de_proyectos/views.py

from django.views.generic import View
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

class SubirDocumentoTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Subir Documentos Tarea"
    permiso_requerido = "modificar"
    
    def post(self, request, tarea_id):
        try:
            tarea = get_object_or_404(Tarea, pk=tarea_id)
            
            form = TareaDocumentoForm(request.POST, request.FILES)
            if form.is_valid():
                documento = form.save(commit=False)
                documento.tarea = tarea
                documento.responsable = request.user
                documento.save()
                
                return JsonResponse({
                    'success': True,
                    'documento_id': documento.id,
                    'nombre': documento.nombre_documento,
                    'archivo_url': documento.archivo.url if documento.archivo else None,
                    'estado': documento.estado,
                    'message': 'Documento cargado exitosamente'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'errors': form.errors
                }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
```

### Paso 5: Agregar ruta en urls.py
```python
# EN: control_de_proyectos/urls.py

path('tareas/<int:tarea_id>/documentos/subir/', 
     views.SubirDocumentoTareaView.as_view(), 
     name='subir_documento_tarea'),
```

### Paso 6: Actualizar el modal en tarea_form.html
```html
<!-- EN: tarea_form.html - Actualizar el Modal Subir Documento -->

<div class="modal-body">
    <form id="formSubirDocumento" enctype="multipart/form-data">
        {% csrf_token %}
        <input type="hidden" id="documento_id" name="documento_id">
        
        <div class="mb-3">
            <label for="nombre_documento" class="form-label">Nombre <span class="text-danger">*</span></label>
            <input type="text" class="form-control" id="nombre_documento" name="nombre_documento" required>
        </div>
        
        <div class="mb-3">
            <label for="tipo_doc" class="form-label">Tipo <span class="text-danger">*</span></label>
            <select class="form-select" id="tipo_doc" name="tipo_doc" required>
                <option value="">-- Seleccionar --</option>
                <option value="ENTRADA">Documento de Entrada</option>
                <option value="SALIDA">Documento de Salida</option>
            </select>
        </div>
        
        <div class="mb-3">
            <label for="documento_archivo" class="form-label">Archivo <span class="text-danger">*</span></label>
            <input type="file" class="form-control" id="documento_archivo" name="archivo" required
                   accept=".pdf,.doc,.docx,.xlsx,.xls,.jpg,.jpeg,.png,.gif,.zip,.rar">
            <small class="text-muted">PDF, DOC, DOCX, XLSX, XLS, JPG, PNG, ZIP, RAR (Máx. 50MB)</small>
        </div>
        
        <div class="mb-3">
            <label for="url_documento" class="form-label">O URL del Documento</label>
            <input type="url" class="form-control" id="url_documento" name="url_documento" 
                   placeholder="https://ejemplo.com/documento">
        </div>
        
        <div class="mb-3">
            <label for="observaciones" class="form-label">Observaciones</label>
            <textarea class="form-control" id="observaciones" name="observaciones" rows="2"></textarea>
        </div>
    </form>
    <div id="alertSubirDocumento" class="alert d-none" role="alert"></div>
</div>
```

### Paso 7: Actualizar función guardarDocumento() en JavaScript
```javascript
// EN: tarea_form.html - Script section

function guardarDocumento() {
    const form = document.getElementById('formSubirDocumento');
    const tareaId = {{ form.instance.pk|default:'null' }};
    
    if (!tareaId) {
        mostrarAlerta('alertSubirDocumento', 'Debe guardar la tarea primero', 'warning');
        return;
    }
    
    const formData = new FormData(form);
    const archivo = document.getElementById('documento_archivo').files[0];
    const url = document.getElementById('url_documento').value;
    const nombre = document.getElementById('nombre_documento').value;
    
    if (!archivo && !url) {
        mostrarAlerta('alertSubirDocumento', 'Debe proporcionar un archivo o URL', 'warning');
        return;
    }
    
    if (!nombre) {
        mostrarAlerta('alertSubirDocumento', 'Debe proporcionar un nombre', 'warning');
        return;
    }
    
    fetch(`/control-de-proyectos/tareas/${tareaId}/documentos/subir/`, {
        method: 'POST',
        body: formData,
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            mostrarAlerta('alertSubirDocumento', data.message, 'success');
            
            // Agregar documento a la tabla
            agregarDocumentoATabla(data);
            
            setTimeout(() => {
                cerrarModal('modalSubirDocumento');
                form.reset();
            }, 1000);
        } else {
            mostrarAlerta('alertSubirDocumento', 
                         data.error || 'Error al cargar el documento', 'danger');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        mostrarAlerta('alertSubirDocumento', 'Error al procesar la solicitud', 'danger');
    });
}

function agregarDocumentoATabla(data) {
    // Agregar el documento recientemente cargado a la tabla
    const containerId = data.tipo_doc === 'ENTRADA' ? 'documentosEntrada' : 'documentosSalida';
    const container = document.getElementById(containerId);
    
    const nuevoHTML = `
        <div class="col-md-6">
            <div class="card border-left-info h-100">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <h6 class="card-title mb-0">
                            <i class="bx bx-file"></i> ${data.nombre}
                        </h6>
                        <span class="badge bg-info">${data.estado}</span>
                    </div>
                    <div class="mt-3">
                        ${data.archivo_url ? `
                            <a href="${data.archivo_url}" target="_blank" class="btn btn-sm btn-outline-secondary">
                                <i class="bx bx-download"></i> Descargar
                            </a>
                        ` : ''}
                    </div>
                </div>
            </div>
        </div>
    `;
    
    container.insertAdjacentHTML('beforeend', nuevoHTML);
}
```

---

## 3. ESTRUCTURA DE CARPETAS GENERADA

```
media/
├── tareas_documentos/
│   ├── Sistema_Web/
│   │   ├── Diseño_UI/
│   │   │   └── Diseño_UI_20260128143022.pdf
│   │   ├── Desarrollo_Backend/
│   │   │   └── API_Schema_20260128143100.json
│   ├── App_Móvil/
│   │   └── Diseño_Mockups/
│   │       └── Mockups_20260128143200.zip
│   └── ...
├── archivos_documentos/  (biblioteca)
└── avatares/
```

---

## 4. VENTAJAS DE ESTA IMPLEMENTACIÓN

✅ **Consistencia**: Usa el mismo patrón que biblioteca  
✅ **Seguridad**: Validación de extensiones  
✅ **Organización**: Rutas claras: Proyecto → Tarea → Documento  
✅ **Escalabilidad**: Cada tarea puede tener múltiples documentos  
✅ **Trazabilidad**: Registra responsable, fecha, estado  
✅ **Flexibilidad**: Soporta archivos o URLs externas  
✅ **Compliance**: Usa `verificar_permiso` (COPILOT_RULES)  

---

## 5. ORDEN DE IMPLEMENTACIÓN

1. ✅ Función `archivo_tarea_path()` en models.py
2. ✅ Función `validate_file_extension_tareas()` en models.py
3. ✅ Actualizar campo `archivo` en `TareaDocumento`
4. ✅ Crear `TareaDocumentoForm` en forms.py
5. ✅ Crear `SubirDocumentoTareaView` en views.py
6. ✅ Agregar ruta en urls.py
7. ✅ Actualizar modal en tarea_form.html
8. ✅ Actualizar función guardarDocumento() en JavaScript
9. ✅ Crear migración
10. ✅ Probar flujo completo

---

## 6. TESTING

```python
# test_implementation.py

def test_subir_documento_tarea():
    # 1. Crear tarea
    # 2. Crear archivo de prueba
    # 3. POST a subir_documento_tarea
    # 4. Verificar archivo en media/tareas_documentos/
    # 5. Verificar registro en BD
    # 6. Verificar estado = 'PENDIENTE'
```

