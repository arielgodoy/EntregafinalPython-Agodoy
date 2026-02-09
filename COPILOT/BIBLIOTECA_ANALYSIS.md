# 📚 ANÁLISIS DE LA APP BIBLIOTECA - Sistema de Gestión de Archivos

## 1. ARQUITECTURA GENERAL

La app **biblioteca** implementa un sistema robusto de gestión de documentos con:
- ✅ Almacenamiento en servidor (media/)
- ✅ Validación de extensiones de archivo
- ✅ Generación automática de rutas organizadas
- ✅ Permisos de acceso
- ✅ Funcionalidad de respaldo (ZIP)

---

## 2. MODELOS - Estructura de Datos

### **Propietario** (Base de la cadena)
```python
class Propietario(models.Model):
    nombre: CharField(50)          # Nombre del propietario
    rut: CharField(20)              # RUT único (validado con función)
    telefono: CharField(20)
    rol: ChoiceField                # 'persona' o 'sociedad'
```

### **Propiedad** (Entidad que agrupa documentos)
```python
class Propiedad(models.Model):
    rol: CharField(20)              # ej: "12-45-6789" (rol del terreno)
    descripcion: CharField(50)
    direccion: CharField(50)
    ciudad: CharField(100)
    telefono: CharField(20)
    propietario: ForeignKey         # Vinculado a Propietario
```

### **TipoDocumento** (Catálogo de tipos)
```python
class TipoDocumento(models.Model):
    nombre: CharField(50)           # ej: "Escritura", "Plano", "Certificado"
    descricion: RichTextField       # Descripción con editor HTML
```

### **Documento** (El archivo final)
```python
class Documento(models.Model):
    tipo_documento: ForeignKey      # Referencia a TipoDocumento
    nombre_documento: CharField(50) # Nombre del documento
    propiedad: ForeignKey           # Referencia a Propiedad
    archivo: FileField              # ARCHIVO FÍSICO (upload_to=archivo_documento_path)
    fecha_documento: DateField      # Fecha de creación
    fecha_vencimiento: DateField    # Fecha de vencimiento (opcional)
```

---

## 3. FUNCIONES CLAVE DE ALMACENAMIENTO

### **3.1 Función: `archivo_documento_path()`**
**Propósito:** Genera la ruta del archivo dinámicamente

```python
def archivo_documento_path(instance, filename):
    """
    Genera: media/archivos_documentos/12-45-6789_Escritura_Documento1.pdf
    """
    # 1. Sanitizar el ROL (reemplazar '/' por '-')
    rol_sanitizado = instance.propiedad.rol.replace("/", "-")
    
    # 2. Extraer extensión del archivo original
    extension = os.path.splitext(filename)[1]
    
    # 3. Generar nombre descriptivo
    nuevo_nombre = f"{rol_sanitizado}_{instance.tipo_documento}_{instance.nombre_documento}{extension}"
    
    # 4. Retornar ruta relativa
    return f"archivos_documentos/{nuevo_nombre}"
```

**Resultado:**
- ✅ Archivos organizados por ROL/tipo
- ✅ Nombres descriptivos y únicos
- ✅ Evita caracteres conflictivos

### **3.2 Función: `validate_file_extension()`**
**Propósito:** Validar que solo suban formatos permitidos

```python
def validate_file_extension(value):
    extensiones_permitidas = ('.pdf', '.jpeg', '.jpg', '.png', '.dwg', '.rar', '.zip')
    if not value.name.lower().endswith(extensiones_permitidas):
        raise ValidationError('Formato no admitido...')
```

---

## 4. VISTAS Y FLUJO DE CARGA

### **4.1 CrearDocumentoView**
```python
class CrearDocumentoView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = Documento
    fields = ['tipo_documento', 'nombre_documento', 'archivo', 'fecha_documento', 'fecha_vencimiento']
    template_name = 'crear_documento.html'
    vista_nombre = "Maestro Propiedades"
    permiso_requerido = "modificar"
    
    def form_valid(self, form):
        # Se obtiene la propiedad desde la URL
        propiedad = get_object_or_404(Propiedad, pk=self.kwargs['pk'])
        # Se vincula el documento a la propiedad
        form.instance.propiedad = propiedad
        return super().form_valid(form)
    
    def get_success_url(self):
        return reverse('biblioteca:detalle_propiedad', kwargs={'pk': self.kwargs['pk']})
```

### **Flujo:**
1. Usuario selecciona Propiedad
2. Click en "Crear Documento"
3. Sube archivo + datos (tipo, nombre, fechas)
4. Django guarda archivo en: `media/archivos_documentos/[ROL]_[TIPO]_[NOMBRE].[ext]`
5. Se crea registro en BD con referencia al archivo
6. Redirige al detalle de la propiedad

---

## 5. ACCESO A ARCHIVOS

### **En Template:**
```html
<!-- Mostrar link de descarga -->
{% if documento.archivo %}
    <a href="{{ documento.archivo.url }}" download>
        {{ documento.archivo.name }}
    </a>
{% endif %}
```

### **En Views (Descarga):**
```python
# URL: /media/archivos_documentos/12-45-6789_Escritura_Documento1.pdf
# Acceso a través de MEDIA_URL configurada
```

---

## 6. FUNCIONALIDADES EXTRA

### **6.1 Respaldo de Biblioteca Completa**
```python
@login_required
def respaldo_biblioteca_zip(request):
    # Crea ZIP de toda la carpeta archivos_documentos
    # Descarga como: respaldo_Biblioteca20260128.zip
```

### **6.2 Respaldo por Propiedad**
```python
@login_required
def descargar_documentos_propiedad_zip(request, propiedad_id):
    # Crea ZIP solo de los documentos de esa propiedad
    # Descarga como: respaldo_rol_12-45-6789_20260128.zip
```

---

## 7. CONFIGURACIONES EN SETTINGS.PY

```python
MEDIA_URL = '/media/'                              # URL de acceso
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')      # Ruta física en servidor

# Estructura generada:
# EntregafinalPython-Agodoy/
#   └── media/
#       └── archivos_documentos/
#           ├── 12-45-6789_Escritura_Doc1.pdf
#           ├── 12-45-6789_Plano_Terreno.dwg
#           └── 98-76-5432_Certificado_Vigencia.pdf
```

---

## 8. SEGURIDAD Y VALIDACIONES

| Aspecto | Implementación |
|---------|-----------------|
| **Permisos** | `VerificarPermisoMixin` + `verificar_permiso()` |
| **Autenticación** | `LoginRequiredMixin` |
| **Extensiones** | `validate_file_extension()` |
| **Sanitización** | Reemplazar caracteres conflictivos (/) |
| **Nombres únicos** | Combinación: ROL + TIPO + NOMBRE |

---

## 9. PARA USAR EN control_de_proyectos

### **Lo que necesitamos copiar:**

✅ **Modelo TareaDocumento** (ya existe)
```python
class TareaDocumento(models.Model):
    tarea = ForeignKey(Tarea, on_delete=models.CASCADE)
    archivo = FileField(upload_to=archivo_tarea_path)  # ← Función custom
    fecha_carga = DateTimeField(auto_now_add=True)
```

✅ **Función de ruta personalizada:**
```python
def archivo_tarea_path(instance, filename):
    # media/archivos_tareas/[PROYECTO]_[TAREA]_[NOMBRE].[ext]
    extension = os.path.splitext(filename)[1]
    proyecto = instance.tarea.proyecto.nombre.replace(" ", "_")
    nombre = f"{proyecto}_{instance.tarea.nombre}_{filename}{extension}"
    return f"archivos_tareas/{nombre}"
```

✅ **Formulario con FileField:**
```python
class TareaDocumentoForm(forms.ModelForm):
    archivo = forms.FileField(
        validators=[validate_file_extension_tareas]
    )
    class Meta:
        model = TareaDocumento
        fields = ['archivo', 'descripcion']
```

✅ **Vista AJAX:**
```python
class SubirDocumentoTareaView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = TareaDocumento
    form_class = TareaDocumentoForm
    vista_nombre = "Subir Documentos"
    permiso_requerido = "modificar"
    
    def form_valid(self, form):
        tarea = get_object_or_404(Tarea, pk=self.kwargs['tarea_id'])
        form.instance.tarea = tarea
        self.object = form.save()
        
        return JsonResponse({
            'success': True,
            'archivo_url': self.object.archivo.url,
            'archivo_nombre': self.object.archivo.name
        })
```

---

## 10. RESUMEN DE LA ARQUITECTURA

```
Usuario
  ↓
formulario.html (input type=file)
  ↓
CrearDocumentoView (POST)
  ↓
django.core.files.storage (guardado)
  ↓
archivo_documento_path() → genera ruta
  ↓
media/archivos_documentos/[ROL]_[TIPO]_[NOMBRE].[ext]
  ↓
Modelo Documento (referencia en BD)
  ↓
Acceso: MEDIA_URL + ruta relativa
```

---

## 11. VENTAJAS DEL SISTEMA BIBLIOTECA

✅ Organización automática de archivos  
✅ Validación de tipos de archivo  
✅ Rutas descriptivas y ordenadas  
✅ Respaldos por propiedad o completos  
✅ Seguridad de permisos integrada  
✅ Almacenamiento en servidor (escalable)  
✅ Acceso rápido mediante URL directa  

