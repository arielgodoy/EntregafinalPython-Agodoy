# 📖 RESUMEN: CÓMO FUNCIONA BIBLIOTECA & APLICACIÓN A TAREAS

## 🏗️ ARQUITECTURA DE BIBLIOTECA (Sistema Actual)

```
┌─────────────────────────────────────────────────────┐
│           USUARIO SUBE DOCUMENTO                    │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│     HTML Form: <input type="file">                  │
│     Template: crear_documento.html                  │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│  Vista: CrearDocumentoView                          │
│  ├─ VerificarPermisoMixin (Permisos)               │
│  ├─ LoginRequiredMixin (Autenticación)             │
│  └─ CreateView (Formulario)                        │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│  Validación:                                        │
│  ├─ validate_file_extension()                      │
│  │  (Solo: PDF, JPEG, JPG, PNG, DWG, RAR, ZIP)    │
│  └─ form.is_valid()                                │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│  Función: archivo_documento_path()                  │
│  ├─ Recibe: instance (Documento), filename         │
│  ├─ Sanitiza: rol.replace("/", "-")                │
│  ├─ Genera: "12-45-6789_Escritura_Doc1.pdf"       │
│  └─ Retorna: "archivos_documentos/[nombre]"        │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│  Django FileField.save()                            │
│  ├─ Guarda en: MEDIA_ROOT/archivos_documentos/     │
│  └─ Ruta física: media/archivos_documentos/        │
│                    12-45-6789_Escritura_Doc1.pdf   │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│  Base de Datos: Modelo Documento                    │
│  ├─ id: 1                                           │
│  ├─ tipo_documento: "Escritura"                     │
│  ├─ nombre_documento: "Doc1"                        │
│  ├─ archivo: "archivos_documentos/12-45-6789..."   │
│  ├─ fecha_documento: 2026-01-28                     │
│  └─ propiedad_id: 5                                 │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│  Acceso:                                            │
│  ├─ Template: {{ documento.archivo.url }}          │
│  ├─ URL: /media/archivos_documentos/...            │
│  └─ Descarga: <a href="{{ doc.archivo.url }}">    │
└─────────────────────────────────────────────────────┘
```

---

## 🔧 COMPONENTES CLAVE DE BIBLIOTECA

| Componente | Ubicación | Propósito |
|-----------|-----------|----------|
| **Modelo Documento** | `models.py` | Almacena metadatos (nombre, fecha, estado) |
| **Función `archivo_documento_path()`** | `models.py` | Genera ruta descriptiva automáticamente |
| **Función `validate_file_extension()`** | `models.py` | Solo permite extensiones seguras |
| **Formulario DocumentoForm** | `forms.py` | Interfaz de carga de archivo |
| **Vista CrearDocumentoView** | `views.py` | Procesa POST, guarda en servidor |
| **Configuración MEDIA** | `settings.py` | Define dónde se guardan archivos |

---

## 📊 COMPARATIVA: BIBLIOTECA vs TAREAS

```python
# ═══════════════════════════════════════════════════════════════

# BIBLIOTECA (Modelo de referencia)
class Documento(models.Model):
    archivo = FileField(upload_to=archivo_documento_path)  # ← Función custom
    # archivo_documento_path genera:
    # media/archivos_documentos/[ROL]_[TIPO]_[NOMBRE].pdf

# ───────────────────────────────────────────────────────────────

# TAREAS (Lo que implementaremos - COPIAR PATRÓN)
class TareaDocumento(models.Model):
    archivo = FileField(upload_to=archivo_tarea_path)  # ← Función custom
    # archivo_tarea_path generará:
    # media/tareas_documentos/[PROYECTO]/[TAREA]/[NOMBRE].pdf
```

---

## 🎯 PATRÓN A IMPLEMENTAR EN TAREAS

### 1️⃣ Función de Ruta Personalizada

```python
# EN: control_de_proyectos/models.py

def archivo_tarea_path(instance, filename):
    """
    Genera ruta descriptiva: 
    tareas_documentos/Sistema_Web/Diseño_UI/mockup_20260128.pdf
    """
    proyecto = instance.tarea.proyecto.nombre.replace(" ", "_").replace("/", "-")
    tarea = instance.tarea.nombre.replace(" ", "_")
    extension = os.path.splitext(filename)[1]
    
    nombre = f"{instance.tarea.nombre}_{datetime.now().strftime('%Y%m%d%H%M%S')}{extension}"
    
    return f"tareas_documentos/{proyecto}/{tarea}/{nombre}"


def validate_file_extension_tareas(value):
    """Validar tipos permitidos"""
    extensiones = ('.pdf', '.doc', '.docx', '.xlsx', '.jpg', '.jpeg', '.png', '.zip', '.rar')
    if not value.name.lower().endswith(extensiones):
        raise ValidationError('Formato no permitido')
```

### 2️⃣ Actualizar Campo en Modelo

```python
class TareaDocumento(models.Model):
    archivo = models.FileField(
        upload_to=archivo_tarea_path,  # ← Usar función
        validators=[validate_file_extension_tareas],  # ← Validar
        blank=True
    )
```

### 3️⃣ Crear Vista AJAX (Como biblioteca lo hace)

```python
class SubirDocumentoTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Subir Documentos"
    permiso_requerido = "modificar"
    
    def post(self, request, tarea_id):
        tarea = get_object_or_404(Tarea, pk=tarea_id)
        form = TareaDocumentoForm(request.POST, request.FILES)
        
        if form.is_valid():
            doc = form.save(commit=False)
            doc.tarea = tarea
            doc.save()
            
            # Respuesta AJAX (JSON)
            return JsonResponse({
                'success': True,
                'archivo_url': doc.archivo.url,
                'documento_id': doc.id
            })
        
        return JsonResponse({'success': False, 'errors': form.errors})
```

### 4️⃣ Ruta en URLs

```python
path('tareas/<int:tarea_id>/documentos/subir/', 
     SubirDocumentoTareaView.as_view(), 
     name='subir_documento_tarea')
```

### 5️⃣ Modal en HTML (Como profesionales/tipos_tarea)

```html
<div class="modal fade" id="modalSubirDocumento">
    <div class="modal-dialog modal-lg">
        <div class="modal-content">
            <form id="formSubirDocumento" enctype="multipart/form-data">
                {% csrf_token %}
                
                <input type="file" name="archivo" required>
                <input type="text" name="nombre_documento" placeholder="Nombre" required>
                <select name="tipo_doc">
                    <option value="ENTRADA">Entrada</option>
                    <option value="SALIDA">Salida</option>
                </select>
                
                <button type="button" onclick="guardarDocumento()">
                    Guardar
                </button>
            </form>
        </div>
    </div>
</div>
```

### 6️⃣ Función JavaScript AJAX

```javascript
function guardarDocumento() {
    const tareaId = {{ form.instance.pk|default:'null' }};
    const formData = new FormData(document.getElementById('formSubirDocumento'));
    
    fetch(`/control-de-proyectos/tareas/${tareaId}/documentos/subir/`, {
        method: 'POST',
        body: formData,
        headers: {'X-Requested-With': 'XMLHttpRequest'}
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            // Documento guardado en: media/tareas_documentos/[Proyecto]/[Tarea]/...
            // Archivo accesible en: data.archivo_url
            mostrarAlerta('Documento cargado', 'success');
            cargarDocumentos();  // Recargar lista
        }
    });
}
```

---

## 📁 ESTRUCTURA DE CARPETAS RESULTANTE

```
EntregafinalPython-Agodoy/
├── media/
│   ├── archivos_documentos/        ← BIBLIOTECA
│   │   ├── 12-45-6789_Escritura_Doc1.pdf
│   │   ├── 98-76-5432_Certificado_Vigencia.pdf
│   │   └── ...
│   │
│   ├── tareas_documentos/          ← NUESTRAS TAREAS (NUEVO)
│   │   ├── Sistema_Web/            (Proyecto)
│   │   │   ├── Diseño_UI/          (Tarea)
│   │   │   │   ├── Diseño_UI_20260128143022.pdf
│   │   │   │   ├── mockup_inicio_20260128143100.png
│   │   │   │   └── estilos_css_20260128143200.css
│   │   │   │
│   │   │   └── Desarrollo_Backend/
│   │   │       └── API_Schema_20260128143300.json
│   │   │
│   │   └── App_Móvil/
│   │       └── Diseño_Mockups/
│   │           └── mockups_20260128143400.zip
│   │
│   ├── avatares/
│   └── ...
```

---

## 🔐 SEGURIDAD & COMPLIANCE

✅ **Permisos:**
- Usa `VerificarPermisoMixin` (COPILOT_RULES)
- Requiere permiso `"modificar"`

✅ **Validación:**
- `validate_file_extension_tareas()` evita archivos maliciosos
- Solo exts: PDF, DOC, DOCX, XLSX, JPG, PNG, ZIP, RAR

✅ **Nombres únicos:**
- Timestamp: `documento_20260128143022.pdf`
- No se sobrescriben archivos

✅ **Almacenamiento:**
- En servidor (`media/` = persistencia)
- No en BD (solo referencia)

---

## ✨ VENTAJAS DE ESTE PATRÓN

| Ventaja | Descripción |
|---------|------------|
| **Organización** | Archivos organizados por Proyecto → Tarea → Documento |
| **Escalabilidad** | Maneja miles de archivos sin conflicto |
| **Seguridad** | Validación + Permisos + Rutas sanitizadas |
| **Recuperación** | Fácil hacer respaldo ZIP de tareas |
| **Consistencia** | Mismo patrón que biblioteca (reutilizable) |
| **Flexibilidad** | Soporta archivos locales + URLs externas |
| **Trazabilidad** | Registra: usuario, fecha, estado del documento |

---

## 🚀 PRÓXIMAS IMPLEMENTACIONES

```
1. ✅ Función archivo_tarea_path()
2. ✅ Validar extensiones
3. ✅ Crear SubirDocumentoTareaView
4. ✅ Agregar ruta en urls.py
5. ✅ Modal + JavaScript en tarea_form.html
6. ✅ Crear migración
7. ✅ Probar flujo completo
8. ✅ Agregar descarga de documentos
9. ✅ Implementar respaldo ZIP por tarea
10. ✅ Dashboard de documentos pendientes
```

---

## 📝 NOTAS IMPORTANTES

- **MEDIA_ROOT** = `EntregafinalPython-Agodoy/media/` (servidor)
- **MEDIA_URL** = `/media/` (acceso web)
- **FileField.url** genera URL automática → `{{ doc.archivo.url }}`
- **Validación** ocurre antes de guardar (seguro)
- **Timestamp** previene sobrescritura de archivos
- **Permisos** se verifican en la vista AJAX

