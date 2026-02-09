# ✅ Solución: Error 404 al Cargar Archivos

## 🔧 Problemas Corregidos

He hecho 4 cambios importantes para solucionar el error 404:

### 1. **Limpiar el Input File Correctamente** ✅
- El campo de archivo ahora se limpia completamente cuando se abre el modal
- Se evita que muestre rutas locales del usuario (D:\Ruta\Archivo.pdf)

### 2. **Validar Guardado del Archivo** ✅
- La vista ahora valida que el archivo se guardó correctamente
- Si hay error al obtener la URL, lo maneja gracefully
- Usa la URL del documento si no hay archivo

### 3. **Generar URL Correcta** ✅
- Ahora retorna primero la URL del archivo (`archivo_url`)
- Si no hay archivo, retorna la URL del documento (`url_documento`)
- El JavaScript usa lo que esté disponible

### 4. **Configurar Servicio de Archivos Multimedia** ✅
- Agregué configuración en `urls.py` para servir archivos en desarrollo
- Ahora Django sirve los archivos desde `/media/`

---

## 📍 Cómo Funciona Ahora

### Flujo de Carga

```
1. Usuario abre modal "Cargar Documento"
   ↓
2. Input file se LIMPIA completamente (no muestra ruta local)
   ↓
3. Usuario selecciona archivo
   ↓
4. Click "Cargar Documento"
   ↓
5. Servidor recibe archivo
   ↓
6. Valida y guarda en: media/tareas_documentos/[Proyecto]/[Tarea]/[Archivo]
   ↓
7. Genera URL correcta: /media/tareas_documentos/.../archivo.pdf
   ↓
8. Retorna JSON con archivo_url
   ↓
9. JavaScript crea botón "Descargar" con URL correcta
   ↓
10. Usuario hace click → Descarga sin error 404 ✅
```

---

## 🧪 Cómo Verificar que Funciona

### Test 1: Cargar Archivo PDF

```
1. Abre formulario de tarea (que ya esté guardada)
2. Desplázate a "Gestión de Documentos"
3. Click botón "Cargar"
4. Completa:
   - Nombre: "Especificación"
   - Tipo: "Documento de Entrada"
   - Archivo: Selecciona un PDF
5. Click "Cargar Documento"

RESULTADO ESPERADO:
✅ Mensaje verde: "Documento cargado exitosamente"
✅ Documento aparece en tabla
✅ Botón "Descargar" está disponible
✅ Click en "Descargar" → Se descarga sin error 404
```

### Test 2: Cargar Solo URL

```
1. Repite steps 1-3
2. Completa:
   - Nombre: "Documentación"
   - Tipo: "Documento de Salida"
   - Archivo: (vacío)
   - URL: https://ejemplo.com/doc
3. Click "Cargar Documento"

RESULTADO ESPERADO:
✅ Documento se carga exitosamente
✅ Botón "Descargar" apunta a la URL correcta
✅ Sin error 404
```

### Test 3: Cargar Archivo + URL

```
1. Repite steps 1-3
2. Completa:
   - Nombre: "Documento Dual"
   - Tipo: "Documento de Entrada"
   - Archivo: Selecciona PDF
   - URL: https://ejemplo.com/doc
3. Click "Cargar Documento"

RESULTADO ESPERADO:
✅ Documento se carga
✅ Botón "Descargar" usa la URL del ARCHIVO (prioridad)
✅ Sin error 404
```

---

## 🔍 Si Aún Hay Error 404

### Paso 1: Verificar que el archivo se guardó

```bash
# En terminal, navega a:
cd EntregafinalPython-Agodoy/media/tareas_documentos/

# Verifica si existen archivos:
# Deberías ver carpetas como:
# - Sistema_Web/
#   └── Tarea_1/
#       └── archivo_20260128.pdf
```

### Paso 2: Verificar la configuración de Django

```python
# Abre AppDocs/settings.py
# Verifica que exista:

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
```

### Paso 3: Verificar URLs configuradas

```python
# Abre AppDocs/urls.py
# Debe tener al final:

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

### Paso 4: Reinicia Django

```bash
# Detén el servidor (Ctrl+C)
# Reinicia:
python manage.py runserver
```

---

## 📊 Estructura de Carpetas Esperada

Después de cargar un documento, deberías ver:

```
EntregafinalPython-Agodoy/
├── media/
│   └── tareas_documentos/
│       └── Sistema_Web/                    (Nombre del Proyecto)
│           └── Diseño_UI/                  (Nombre de la Tarea)
│               └── Especificacion_20260128143022.pdf
```

---

## 🐛 Debugging Avanzado

### Si ves error 404 en descargar:

1. **Abre Console del navegador** (F12)
2. **Haz click en "Descargar"**
3. **Verás el error completo:**
   ```
   GET /media/tareas_documentos/Sistema_Web/Diseño_UI/Especificacion_20260128143022.pdf 404
   ```

4. **Verifica que el archivo existe:**
   ```bash
   # En terminal:
   ls -la media/tareas_documentos/Sistema_Web/Diseño_UI/
   # Deberías ver el archivo
   ```

### Si el archivo NO existe en servidor:

- El formulario validó pero el archivo no se guardó
- Causa probable: Permisos de carpeta `/media/`
- Solución:
  ```bash
  # Dale permisos a la carpeta:
  chmod -R 755 media/
  ```

### Si la URL es incorrecta:

- Verifica en la response JSON (F12 → Network → Response)
- La URL debe ser: `/media/tareas_documentos/...`
- NO debe ser: `D:\Users\Admin\...` (ruta local)

---

## ✅ Checklist Final

- [ ] ¿Reiniciaste Django después de los cambios?
- [ ] ¿La carpeta `media/` existe y tiene permisos de escritura?
- [ ] ¿Cargaste un archivo pequeño (< 1MB) primero para probar?
- [ ] ¿El botón "Descargar" muestra URL `/media/...`?
- [ ] ¿Puedes descargar sin error 404?

---

## 📞 Soporte

Si persiste el problema:

1. Copia el error exacto de la red (F12 → Network)
2. Verifica que el archivo existe en `media/`
3. Reinicia Django completamente
4. Limpia el navegador (Ctrl+Shift+Delete)
5. Intenta de nuevo

