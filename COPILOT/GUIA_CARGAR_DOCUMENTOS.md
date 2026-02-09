# 📚 GUÍA: Cómo Cargar Documentos en Tareas

## 🎯 Resumen Rápido

Para cargar documentos en una tarea, debes:

1. **Primero:** Ir a **Tipos de Tarea** y crear uno con documentos requeridos
2. **Segundo:** Crear/Editar una **Tarea** y asignarle ese Tipo de Tarea
3. **Tercero:** Hacer click en el botón **"Cargar"** para subir documentos

---

## 📋 PASO 1: Crear un Tipo de Tarea con Documentos

### ¿Por qué?
Cada "Tipo de Tarea" define qué documentos necesitas recibir (ENTRADA) y cuáles debes entregar (SALIDA).

### ¿Cómo?

**Opción A: Desde un Proyecto**
```
1. Ir a: Proyectos → Seleccionar Proyecto
2. En la sección "Tipos de Tareas" → Click en "Crear Tipo de Tarea" (botón verde +)
3. Llenar datos:
   - Nombre: "Diseño UI"
   - Descripción: "Diseño de interfaz de usuario"
4. Click en "Guardar"
```

**Opción B: Desde Administración**
```
1. Ir a: /admin/
2. Seleccionar "Tipos de Tareas"
3. Click en "Agregar Tipo de Tarea"
4. Llenar datos y guardar
```

### Agregando Documentos Requeridos al Tipo

Después de guardar el Tipo de Tarea:

```
1. Ver el Tipo de Tarea creado
2. En la sección "Documentos Requeridos" → Click en "Agregar Documento" (botón verde +)
3. Completar:
   - Nombre: "Mockups"
   - Tipo: ENTRADA (lo que recibirás)
   - Descripción: "Archivos de mockup en Figma"
4. Click en "Guardar"

5. Repetir para agregar más documentos:
   - "Especificación técnica" (ENTRADA)
   - "Código fuente" (SALIDA - lo que entregarás)
```

**IMPORTANTE:** Un Tipo de Tarea puede tener múltiples documentos requeridos.

---

## ✅ PASO 2: Crear/Editar una Tarea

### Crear Nueva Tarea

```
1. Ir a: Proyectos → Seleccionar Proyecto → Click en "Crear Tarea" (botón verde +)
2. Llenar datos del formulario:
   - Nombre: "Desarrollar Dashboard"
   - Descripción: (opcional)
   - Tipo de Tarea: ⭐ SELECCIONA EL QUE CREASTE EN PASO 1
   - Profesional Asignado: (tu nombre)
   - Estado: "PENDIENTE"
   - Prioridad: (Alta/Media/Baja)
   - Fechas: (opcional)
3. Click en "Guardar"
```

### Editar Tarea Existente

```
1. Ir a: Proyectos → Seleccionar Proyecto
2. En la lista de tareas → Click en la tarea
3. En el editor → Busca "Tipo de Tarea"
4. Si aún no tiene tipo asignado:
   - Click en el dropdown
   - Selecciona el tipo que creaste
5. Click en "Guardar"
```

---

## 🆙 PASO 3: Cargar Documentos a la Tarea

### Ubicación del Botón

Después de guardar la tarea, verás la sección **"Gestión de Documentos"** con dos áreas:

```
┌─────────────────────────────────────────────┐
│  Gestión de Documentos                      │
├─────────────────────────────────────────────┤
│                                             │
│  📥 Documentos de Entrada (Requeridos)  │ [Cargar] ← BOTÓN VERDE
│  ─────────────────────────────────────  │
│  • Mockups          [Ver] [Cargar]      │
│  • Especificación   [Ver] [Cargar]      │
│                                             │
│  ─────────────────────────────────────────│
│                                             │
│  📤 Documentos de Salida (Entregables)   │ [Cargar] ← BOTÓN VERDE
│  ─────────────────────────────────────  │
│  • Código fuente    [Ver] [Cargar]      │
│  • Informe final    [Ver] [Cargar]      │
│                                             │
└─────────────────────────────────────────────┘
```

### Pasos para Cargar un Documento

```
1. Verifica la tarea esté guardada (ver página)
2. Desplázate hasta "Gestión de Documentos"
3. Busca el documento que necesitas cargar
4. Click en el botón "Cargar" (o en el botón superior "Cargar")
```

### Se Abrirá Modal "Cargar Documento"

Completa los campos:

```
┌──────────────────────────────────┐
│  Cargar Documento                │
├──────────────────────────────────┤
│                                  │
│  Nombre del Documento *          │ ← REQUERIDO
│  [____________________]          │  Ej: "Mockup inicio"
│                                  │
│  Tipo de Documento *             │ ← REQUERIDO
│  [Documento de Entrada ▼]        │  (ya predefinido)
│                                  │
│  Archivo                         │ ← OPCIONAL (SI)
│  [Elegir archivo]                │  PDF, DOC, PNG, etc.
│                                  │
│  O URL del Documento             │ ← OPCIONAL (O)
│  [https://...]                   │  Link en la nube
│                                  │
│  Observaciones                   │
│  [Información adicional...]      │
│                                  │
│  [Cancelar]  [Cargar Documento]  │
└──────────────────────────────────┘
```

### Validaciones

**Debes completar:**
- ✅ **Nombre del Documento** (siempre)
- ✅ **Tipo de Documento** (siempre)
- ✅ **Archivo O URL** (al menos uno)

**Extensiones de Archivo Permitidas:**
- Documentos: `.pdf`, `.doc`, `.docx`, `.xlsx`, `.xls`
- Imágenes: `.jpg`, `.jpeg`, `.png`, `.gif`
- Comprimidos: `.zip`, `.rar`

### Después de Hacer Click "Cargar Documento"

```
✅ Mensaje de Éxito (verde)
   "Documento cargado exitosamente"
   
El documento aparecerá en la tabla con:
- Nombre: El que ingresaste
- Estado: ENVIADO
- Botón "Descargar" para ver el archivo
```

---

## 📁 Dónde se Guardan los Archivos

Los archivos se almacenan en:

```
media/tareas_documentos/[Proyecto]/[Tarea]/
```

**Ejemplo:**
```
media/tareas_documentos/
├── Sistema_Web/
│   └── Diseño_UI/
│       ├── Mockup_inicio_20260128143022.pdf
│       ├── estilos_20260128143100.css
│       └── especificacion_20260128143200.docx
```

---

## ❓ Solución de Problemas

### Problema: "Error al cargar los documentos"

**Causas posibles:**

1. **La tarea no tiene Tipo asignado**
   - Solución: Edita la tarea → Asigna un "Tipo de Tarea" → Guarda
   
2. **El Tipo de Tarea no tiene documentos requeridos**
   - Solución: Ve al Tipo de Tarea → Agrega documentos requeridos
   
3. **No guardaste la tarea después de asignar el tipo**
   - Solución: Click en "Guardar" después de cambiar el tipo

### Problema: No veo el botón "Cargar"

**Causas posibles:**

1. La tarea no está guardada aún
   - Solución: Primero guarda la tarea
   
2. No hay documentos requeridos para este tipo de tarea
   - Solución: Ve a crear documentos requeridos en el Tipo de Tarea

### Problema: No puedo subir el archivo (error de permiso)

**Causas posibles:**

1. No tienes permiso "modificar" en la tarea
   - Solución: Pide que te asignen ese permiso
   
2. El archivo es demasiado grande o extensión no permitida
   - Solución: Usa archivos menores a 50MB y extensiones permitidas

### Problema: Después de cargar, no veo el documento

- Espera 2-3 segundos para que se recargue automáticamente
- Si sigue sin aparecer: Recarga la página (F5)

---

## 🎬 Flujo Completo de Ejemplo

```
PASO 1: Crear Tipo de Tarea
├─ Ve a Proyecto
├─ Click "Crear Tipo de Tarea"
├─ Nombre: "Especificación"
├─ Guardar
└─ Agregar documentos:
   ├─ "Documento Técnico" (ENTRADA)
   └─ "Código Final" (SALIDA)

PASO 2: Crear Tarea
├─ Ve a Proyecto
├─ Click "Crear Tarea"
├─ Nombre: "Especificación del Sistema"
├─ Tipo de Tarea: "Especificación"
├─ Guardar
└─ ¡Verás la sección "Gestión de Documentos"!

PASO 3: Cargar Documentos
├─ En "Gestión de Documentos"
├─ Click botón "Cargar" (superior o por documento)
├─ Completa:
│  ├─ Nombre: "Documento de Requisitos"
│  ├─ Tipo: "Documento de Entrada"
│  ├─ Archivo: selecciona PDF
│  └─ Guardar
├─ ✅ Documento aparece en tabla
└─ Repite para otros documentos
```

---

## 📚 Referencia Rápida

| Acción | Ubicación | Botón |
|--------|-----------|-------|
| Crear Tipo | Proyecto → Tipos | Verde **+** |
| Agregar Doc Requerido | Tipo Tarea → Documentos | Verde **+** |
| Crear Tarea | Proyecto → Tareas | Verde **+** |
| Cargar Documento | Tarea → Gestión Doc | Verde **Cargar** |
| Descargar Documento | Gestión Documentos | **Ver/Descargar** |

---

## 💡 Tips Útiles

✨ **Tip 1:** Usa URLs para documentos en la nube
```
- Google Drive: https://drive.google.com/...
- Figma: https://figma.com/...
- OneDrive: https://onedrive.live.com/...
```

✨ **Tip 2:** Nombres descriptivos
- ❌ Malo: "archivo1.pdf"
- ✅ Bueno: "Especificación_Sistema_v1"

✨ **Tip 3:** Observaciones útiles
- "Versión 1.0 - Revisión pendiente"
- "Aprobado por Gerencia"
- "Cambios según reunión 25/01"

✨ **Tip 4:** Estados de documentos
- **PENDIENTE**: Aún no cargado
- **ENVIADO**: Cargado, esperando revisión
- **RECIBIDO**: Revisado por responsable
- **APROBADO**: Aprobado
- **RECHAZADO**: Rechazado, requiere cambios
- **ENTREGADO**: Entrega final completa

---

## 📞 ¿Necesitas Más Ayuda?

Si aún tienes problemas:
1. Verifica que el Tipo de Tarea tenga documentos requeridos
2. Verifica que la tarea esté asignada a ese tipo
3. Recarga la página (F5)
4. Contacta al administrador

