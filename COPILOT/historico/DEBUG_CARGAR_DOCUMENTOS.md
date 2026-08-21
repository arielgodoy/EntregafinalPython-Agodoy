# 🔧 Solución: Mensajes de Error Claros al Cargar Documentos

## ✅ Problemas Corregidos

He hecho varios cambios para que los errores se muestren claramente:

### 1. **Backend (views.py)** ✅
- Mejoré el manejo de errores con mensajes más descriptivos
- Ahora retorna en español los nombres de los campos
- Incluye detalles técnicos para debugging

### 2. **Frontend (template)** ✅
- Mejoré la función que muestra alertas (ahora soporta textos largos)
- Mejoré la función que muestra errores de campos específicos
- Los errores se resaltan con color rojo en los campos

### 3. **Formulario (forms.py)** ✅
- Eliminé una clase TareaDocumentoForm duplicada que causaba conflictos
- Ahora hay una sola versión correcta con todos los campos

---

## 🐛 Ahora los Errores se Verán Así

Cuando hayas rellenado incorrectamente un campo, verás:

```
┌────────────────────────────────────┐
│ ❌ Error al cargar el documento    │
│                                    │
│ Nombre del Documento:              │
│ [____________________]             │
│ ⚠️ • Este campo es requerido       │
│                                    │
│ Tipo de Documento:                 │
│ [-- Seleccionar tipo -- ▼]         │
│ ⚠️ • Seleccione una opción válida  │
│                                    │
└────────────────────────────────────┘
```

Y en la alerta principal verá:

```
Nombre del Documento: Este campo es requerido | 
Tipo de Documento: Seleccione una opción válida
```

---

## ✔️ Validaciones Que Se Verifican

### Campo: Nombre del Documento
- ✅ No puede estar vacío
- ✅ Máximo 200 caracteres
- ✅ Obligatorio

### Campo: Tipo de Documento
- ✅ No puede estar vacío
- ✅ Debe ser ENTRADA o SALIDA
- ✅ Obligatorio

### Campo: Archivo (O URL)
- ✅ Debe ser PDF, DOC, DOCX, XLSX, XLS, JPG, PNG, GIF, ZIP, RAR
- ✅ Máximo 50MB
- ✅ **Al menos uno: Archivo O URL (no puede faltar ambos)**

### Campo: URL del Documento (O Archivo)
- ✅ Debe ser una URL válida (https://...)
- ✅ **Al menos uno: URL O Archivo (no puede faltar ambos)**

### Campo: Observaciones
- ✅ Opcional
- ✅ Máximo 500 caracteres

---

## 🔍 Cómo Entender los Errores

### Error: "Debe proporcionar un archivo o una URL del documento"

**Causa:** Dejaste vacío el campo "Archivo" Y el campo "URL"

**Solución:**
```
Opción A: Sube un archivo
─────────────────────────
1. Click en "Seleccionar archivo"
2. Elige tu PDF, DOC, etc.

O

Opción B: Proporciona una URL
─────────────────────────────
1. Click en campo "O URL del Documento"
2. Ingresa: https://ejemplo.com/documento

O AMBOS:
────────
Puedes llenar ambos si quieres
```

### Error: "Nombre del Documento - Este campo es requerido"

**Causa:** El campo "Nombre del Documento" está vacío

**Solución:**
```
1. Click en el campo "Nombre del Documento"
2. Ingresa un nombre descriptivo:
   - "Especificación Técnica"
   - "Mockup Interfaz"
   - "Código Fuente"
   - "Contrato"
```

### Error: "Tipo de Documento - Seleccione una opción válida"

**Causa:** No seleccionaste un tipo o fue inválido

**Solución:**
```
1. Click en dropdown "Tipo de Documento"
2. Elige una opción:
   - "Documento de Entrada (Requerido)" ← Lo que recibes
   - "Documento de Salida (Entregable)"  ← Lo que entregas
```

---

## 📝 Ejemplo de Carga Correcta

### Carga ENTRADA (Documento que recibirás)

```
Nombre del Documento:           ✅ "Especificación del Cliente"
Tipo de Documento:              ✅ "Documento de Entrada (Requerido)"
Archivo:                        ✅ "especificacion.pdf" (50 MB máx)
O URL:                          - (vacío está bien)
Observaciones:                  - "Recibido 28/01/2026"

RESULTADO: ✅ Documento cargado exitosamente
```

### Carga SALIDA (Documento que entregarás)

```
Nombre del Documento:           ✅ "Código Fuente Final"
Tipo de Documento:              ✅ "Documento de Salida (Entregable)"
Archivo:                        - (vacío está bien)
O URL:                          ✅ "https://github.com/usuario/repo"
Observaciones:                  - "Última versión con documentación"

RESULTADO: ✅ Documento cargado exitosamente
```

### Carga con Ambos (Archivo + URL)

```
Nombre del Documento:           ✅ "Reporte Final"
Tipo de Documento:              ✅ "Documento de Salida (Entregable)"
Archivo:                        ✅ "reporte_final.pdf"
O URL:                          ✅ "https://drive.google.com/..."
Observaciones:                  ✅ "Disponible en ambas ubicaciones"

RESULTADO: ✅ Documento cargado exitosamente
```

---

## 🚨 Errores Comunes y Soluciones

| Error | Causa | Solución |
|-------|-------|----------|
| "Debe proporcionar..." | Archivo Y URL vacíos | Elige uno: archivo O URL |
| "Este campo es requerido" | Campo obligatorio vacío | Completa el campo |
| "Seleccione una opción válida" | Tipo no seleccionado | Elige ENTRADA o SALIDA |
| "La extensión de archivo no es permitida" | Archivo .exe, .bat, etc. | Usa: PDF, DOC, PNG, ZIP, etc. |
| "El archivo es demasiado grande" | > 50 MB | Reduce el tamaño |
| "URL no válida" | Falta https:// | Usa: https://ejemplo.com |

---

## 🎯 Flujo de Carga Correcta

```
1. RELLENAR FORMULARIO
   ├─ Nombre: ________________  ✅
   ├─ Tipo:   [Seleccionar ▼]   ✅
   ├─ Archivo O URL:            ✅ (AL MENOS UNO)
   └─ Observaciones: (opcional)

2. VALIDAR CLIENTE (antes de enviar)
   ├─ ¿Nombre no vacío?         ✅
   ├─ ¿Tipo seleccionado?       ✅
   └─ ¿Archivo O URL?           ✅

3. ENVIAR
   └─ Click [Cargar Documento]

4. VALIDAR SERVIDOR
   ├─ ¿Campos correctos?        ✅
   ├─ ¿Extensión permitida?     ✅
   └─ ¿Tamaño OK?               ✅

5. GUARDAR EN BD
   ├─ INSERT en tabla TareaDocumento
   ├─ Archivo a: media/tareas_documentos/...
   └─ ✅ Documento cargado exitosamente
```

---

## 💻 Para Desarrolladores: Debug Avanzado

Si aún ves errores genéricos, puedes:

### 1. Abrir Console del Navegador
```
F12 → Pestaña "Console"
- Verás logs detallados de la petición
- Busca línea: "Error en la solicitud: ..."
```

### 2. Revisar Logs del Servidor
```
Terminal → Django
- Verás: "Error en SubirDocumentoTareaView: ..."
- Seguido del detalle del error
- Y el traceback completo
```

### 3. Inspeccionar Respuesta JSON
```
F12 → Pestaña "Network"
1. Llena el formulario y carga documento
2. Busca POST a: ".../documentos/subir/"
3. Click en la fila
4. Pestaña "Response"
5. Verás JSON con:
   - success: true/false
   - error: "mensaje"
   - errors: {campo: [mensajes]}
   - error_detalle: "detalles"
```

---

## ✅ Checklist de Prueba

- [ ] Intenta cargar sin nombre → Ves error "Nombre del Documento: Este campo es requerido"
- [ ] Intenta cargar sin tipo → Ves error "Tipo de Documento: Seleccione una opción válida"
- [ ] Intenta cargar sin archivo y sin URL → Ves error "Debe proporcionar un archivo o una URL"
- [ ] Carga correctamente → Ves "Documento cargado exitosamente"
- [ ] Documento aparece en tabla → Sin recargar página
- [ ] Puedes descargar el documento → Link "Ver/Descargar" funciona

---

## 📞 Soporte

Si persisten los errores:

1. Copia el mensaje completo de error
2. Abre Console (F12 → Console)
3. Copia el log que dice "Error en la solicitud:"
4. Proporciona ambos para debugging

