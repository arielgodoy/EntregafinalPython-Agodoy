# Documento Management & Gantt Chart Support - Implementation Guide

## Overview

This implementation adds comprehensive document management and Gantt chart support to the `control_de_proyectos` app. It allows you to:

1. **Define Task Types** with required documents (entrada/salida)
2. **Auto-generate Document Records** when a task type is assigned
3. **Track Document Status** through workflow states
4. **Validate Task State Transitions** based on document completion
5. **Support Gantt Charts** with planning vs real dates, progress %, and dependencies

## New Models

### 1. TipoTarea (Task Type Catalog)
```python
TipoTarea
├── nombre: CharField (max_length=100, unique=True)
├── descripcion: TextField
├── activo: BooleanField (default=True)
├── fecha_creacion: DateTimeField (auto_now_add=True)
└── fecha_actualizacion: DateTimeField (auto_now=True)
```

**Purpose**: Define standard task types and their required documents

**Usage**: Admin creates task types, defines which documents each type requires


### 2. DocumentoRequeridoTipoTarea (Required Documents per Task Type)
```python
DocumentoRequeridoTipoTarea
├── tipo_tarea: ForeignKey(TipoTarea)
├── nombre_documento: CharField (max_length=150)
├── descripcion: TextField
├── es_obligatorio: BooleanField (default=False)
├── categoria: CharField (max_length=20)
├── tipo_doc: CharField (ENTRADA/SALIDA)
├── orden: IntegerField
└── fecha_creacion: DateTimeField (auto_now_add=True)
```

**Purpose**: Define document requirements for each task type

**Documento Types**:
- `ENTRADA`: Input documents (must be received before task starts)
- `SALIDA`: Output documents (must be delivered when task ends)

**Workflow**:
1. Admin creates DocumentoRequeridoTipoTarea records
2. When Tarea is created with tipo_tarea, TareaDocumento records are auto-generated


### 3. TareaDocumento (Document Instances)
```python
TareaDocumento
├── tarea: ForeignKey(Tarea, related_name='documentos')
├── nombre_documento: CharField (max_length=150)
├── descripcion: TextField
├── tipo_doc: CharField (ENTRADA/SALIDA)
├── es_obligatorio: BooleanField
├── categoria: CharField
├── estado: CharField (PENDIENTE|ENVIADO|RECIBIDO|APROBADO|RECHAZADO|ENTREGADO)
├── responsable: ForeignKey(User, null=True, blank=True)
├── documento_biblioteca: ForeignKey(Documento, null=True, blank=True)
├── archivo: FileField
├── url_documento: URLField
├── observaciones: TextField
├── fecha_entrega: DateField
├── fecha_creacion: DateTimeField (auto_now_add=True)
└── fecha_actualizacion: DateTimeField (auto_now=True)
```

**Estado Workflow**:
```
PENDIENTE → ENVIADO → RECIBIDO → APROBADO → ENTREGADO
                                ↓
                            RECHAZADO (goes back to ENVIADO/PENDIENTE)
```

**Key Features**:
- Multiple upload options (file or URL)
- Tracking of document status through workflow
- Optional assignment to responsible person
- Link to biblioteca.Documento if available


## Tarea Model Extensions

### New Fields (Gantt Support)
```python
Tarea
├── tipo_tarea: ForeignKey(TipoTarea, null=True, blank=True)
├── fecha_inicio_plan: DateField (planned start)
├── fecha_fin_plan: DateField (planned end)
├── fecha_inicio_real: DateField (actual start)
├── fecha_fin_real: DateField (actual end)
├── porcentaje_avance: IntegerField (0-100, default=0)
└── depende_de: ManyToManyField(Tarea) (task dependencies)
```

### Validation Methods
```python
Tarea.puede_marcar_terminada()
    # Returns True if all required SALIDA documents are APROBADO/ENTREGADO
    # Prevents marking task as done if deliverables aren't approved

Tarea.puede_marcar_en_curso()
    # Returns True if all required ENTRADA documents are RECIBIDO/APROBADO
    # Prevents starting task if required inputs aren't received

Tarea.marcar_bloqueada_si_necesario()
    # Auto-blocks task if required SALIDA document is RECHAZADO
    # Ensures rejected documents prevent task progression
```

## Signals & Automation

### Auto-Generation of TareaDocumento

When a Tarea is created or tipo_tarea is assigned:

1. **Pre-save Signal** (`tarea_pre_save`):
   - Detects if tipo_tarea changed on existing Tarea
   - Marks for cleanup if changed

2. **Post-save Signal** (`auto_generar_documentos_tarea`):
   - Creates TareaDocumento records from DocumentoRequeridoTipoTarea
   - Removes old documents if tipo_tarea changed
   - Initializes all documents with PENDIENTE status

```python
# Example: Create Tarea with tipo_tarea
tarea = Tarea.objects.create(
    nombre="Implementación",
    proyecto=proyecto,
    tipo_tarea=tipo_implementacion  # Signal fires here
)
# Auto-creates TareaDocumento for each required document
```

## Forms

### TipoTareaForm
- nombre (TextInput)
- descripcion (Textarea)
- activo (CheckboxInput)

### DocumentoRequeridoTipoTareaForm
- tipo_tarea (Select)
- nombre_documento (TextInput)
- descripcion (Textarea)
- es_obligatorio (Checkbox)
- categoria (TextInput)
- tipo_doc (Select - ENTRADA/SALIDA)
- orden (NumberInput)

### TareaDocumentoForm
- estado (Select)
- archivo (FileInput)
- url_documento (URLInput)
- observaciones (Textarea)

**Validation**: Ensures at least archivo or url_documento is provided

## API Endpoints

### ViewSets (DRF)

```
GET    /api/control-de-proyectos/tipos-tarea/
POST   /api/control-de-proyectos/tipos-tarea/
GET    /api/control-de-proyectos/tipos-tarea/{id}/

GET    /api/control-de-proyectos/documentos-requeridos/
POST   /api/control-de-proyectos/documentos-requeridos/
GET    /api/control-de-proyectos/documentos-requeridos/{id}/
// Query params: ?tipo_tarea_id=X

GET    /api/control-de-proyectos/documentos-tarea/
POST   /api/control-de-proyectos/documentos-tarea/
GET    /api/control-de-proyectos/documentos-tarea/{id}/
PATCH  /api/control-de-proyectos/documentos-tarea/{id}/
// Query params: ?tarea_id=X&tipo_doc=ENTRADA
```

### Custom Actions

#### Tareas
```
POST   /api/control-de-proyectos/tareas/{id}/cambiar_estado/
       Request: {"estado": "TERMINADA"}
       Validates document requirements before allowing state change

GET    /api/control-de-proyectos/tareas/por_proyecto/
       Query params: ?proyecto_id=X
       Returns all tasks for a project
```

#### Documentos
```
POST   /api/control-de-proyectos/documentos-tarea/{id}/cambiar_estado/
       Request: {"estado": "APROBADO"}
       Enforces valid state transitions

GET    /api/control-de-proyectos/documentos-tarea/por_tarea_y_tipo/
       Query params: ?tarea_id=X&tipo_doc=SALIDA
       Returns documents filtered by task and type
```

## UI Components

### Document Management Section (tarea_form.html)

**Location**: Below task form, only shown for existing tasks

**Features**:
1. **Documentos de Entrada** (Inputs Required)
   - Shows all ENTRADA documents
   - Displays status badge
   - Shows "Cargar" button if PENDIENTE
   - Shows "Ver" button if file uploaded

2. **Documentos de Salida** (Deliverables)
   - Shows all SALIDA documents
   - Same controls as ENTRADA
   - Critical for task completion

3. **Upload Modal**
   - File upload (with validation)
   - URL option (for cloud documents)
   - Observaciones field
   - Auto-loads when document is created

**JavaScript Functions**:
```javascript
cargarDocumentos()              // Fetch documents from API
mostrarDocumentos(id, docs)     // Render document cards
abrirModalSubirDocumento(id)    // Show upload modal
guardarDocumento()              // Upload document (PATCH)
obtenerColorEstado(estado)      // Get badge color
```

## Admin Interface

### TipoTareaAdmin
- Inline display of DocumentoRequeridoTipoTarea
- Search by nombre/descripcion
- Filter by activo
- Order by nombre

### DocumentoRequeridoTipoTareaAdmin
- List view with all metadata
- Filter by tipo_tarea, tipo_doc, obligatorios
- Search by documento name
- Order by orden

### TareaDocumentoAdmin
- Inline display in TareaAdmin
- List view shows Task name and document name
- Filter by proyecto, tarea, estado, tipo_doc
- Search by task/document name

### TareaAdmin
- Updated list display with tipo_tarea and porcentaje_avance
- Inline editing of TareaDocumento
- Filter options for all Gantt fields
- Fieldsets organized by section

## Workflow Examples

### Example 1: Create Task with Type

```python
# 1. Admin defines task type
tipo = TipoTarea.objects.create(
    nombre="Code Review",
    descripcion="Review and approve code changes"
)

# 2. Admin adds required documents
DocumentoRequeridoTipoTarea.objects.create(
    tipo_tarea=tipo,
    nombre_documento="Code Changes",
    tipo_doc="ENTRADA",
    es_obligatorio=True,
    orden=1
)

DocumentoRequeridoTipoTarea.objects.create(
    tipo_tarea=tipo,
    nombre_documento="Review Report",
    tipo_doc="SALIDA",
    es_obligatorio=True,
    orden=1
)

# 3. User creates task with type
tarea = Tarea.objects.create(
    nombre="Review PR #123",
    proyecto=proyecto,
    tipo_tarea=tipo  # Signal auto-creates documentos
)

# 4. Result: Two TareaDocumento records created (both PENDIENTE)
assert tarea.documentos.count() == 2
```

### Example 2: Document Workflow

```python
# 1. Get ENTRADA document
entrada_doc = TareaDocumento.objects.get(
    tarea=tarea,
    tipo_doc='ENTRADA',
    nombre_documento='Code Changes'
)

# 2. Developer uploads code
entrada_doc.archivo.save('changes.zip', file_content)
entrada_doc.estado = 'ENVIADO'
entrada_doc.save()

# 3. Reviewer receives and marks
entrada_doc.estado = 'RECIBIDO'
entrada_doc.responsable = reviewer
entrada_doc.save()

# 4. Reviewer approves
entrada_doc.estado = 'APROBADO'
entrada_doc.save()

# 5. Can now mark task EN_CURSO
assert tarea.puede_marcar_en_curso() == True
tarea.estado = 'EN_CURSO'
tarea.save()

# 6. Complete work and upload output
salida_doc = TareaDocumento.objects.get(
    tarea=tarea,
    tipo_doc='SALIDA'
)
salida_doc.archivo.save('report.pdf', file_content)
salida_doc.estado = 'ENVIADO'
salida_doc.save()

# 7. Manager approves report
salida_doc.estado = 'APROBADO'
salida_doc.save()

# 8. Can now mark task TERMINADA
assert tarea.puede_marcar_terminada() == True
tarea.estado = 'TERMINADA'
tarea.porcentaje_avance = 100
tarea.save()
```

## Gantt Chart Data

The extended Tarea model supports Gantt charts:

```javascript
// Frontend can use this data for Gantt rendering:
{
    id: task.id,
    name: task.nombre,
    start_date: task.fecha_inicio_plan,
    end_date: task.fecha_fin_plan,
    progress: task.porcentaje_avance,
    actual_start: task.fecha_inicio_real,
    actual_end: task.fecha_fin_real,
    status: task.estado,
    dependencies: task.depende_de.map(t => t.id),
    tipo_tarea: task.tipo_tarea.nombre
}
```

## Permission Integration

All viewsets use:
```python
permission_classes = [IsAuthenticated]
```

And filter by:
```python
empresa_id = self.request.session.get("empresa_id")
```

To integrate with custom access_control decorators, update viewsets:

```python
from access_control.decorators import verificar_permiso

class TareaDocumentoViewSet(viewsets.ModelViewSet):
    # Add permission check in get_queryset/perform_create
    def perform_create(self, serializer):
        if not verificar_permiso(self.request.user, 'crear_documento'):
            raise PermissionDenied("No tiene permiso para crear documentos")
        serializer.save()
```

## Testing the Implementation

1. **Create a Task Type**:
   - Go to Admin → Tipo Tarea → Add
   - Add 2-3 required documents

2. **Create a Task**:
   - Go to Crear Tarea
   - Select the task type
   - View auto-generated documents

3. **Upload Documents**:
   - Click "Cargar" on ENTRADA document
   - Upload file or paste URL
   - Mark as ENVIADO

4. **Track Workflow**:
   - Watch document status progression
   - Try marking task TERMINADA (should fail if SALIDA missing)
   - Approve SALIDA document
   - Mark task complete

## Future Enhancements

- Gantt chart visualization library integration
- Document templates/generators
- Email notifications on status changes
- Document version history/audit trail
- Batch document operations
- Integration with external storage (AWS S3, etc.)
- Document signing/approval workflows
