# QUICK REFERENCE CARD - Document Management System

## 🚀 GETTING STARTED (5 MINUTES)

### 1. Start Server
```bash
python manage.py runserver
```

### 2. Access Admin
```
http://localhost:8000/admin/
```

### 3. Create Task Type
Admin → Control de Proyectos → Tipo Tareas → Add
```
Name: Code Review
Description: Internal review process
```

### 4. Add Documents
In inline section:
```
+ Source Code (ENTRADA, Required)
+ Review Report (SALIDA, Required)
```

### 5. Create Task
Crear Tarea → Select Type → Auto-generates documents ✓

---

## 📋 KEY CONCEPTS

### Document Types
- **ENTRADA** (Input): Received documents needed to start task
- **SALIDA** (Output): Deliverable documents to complete task

### Document States
```
PENDIENTE → ENVIADO → RECIBIDO → APROBADO → ENTREGADO
                                      ↓
                                  RECHAZADO
```

### Task Workflow
```
CREATE TASK
  ↓
SELECT TYPE → AUTO-GENERATE DOCUMENTS
  ↓
COLLECT ENTRADA DOCS
  ↓
MARK EN_CURSO (validates ENTRADA)
  ↓
COLLECT SALIDA DOCS
  ↓
MARK TERMINADA (validates SALIDA)
```

---

## 🔌 API ENDPOINTS

### Quick Test in Browser

**List task types**:
```
/api/control-de-proyectos/tipos-tarea/
```

**List documents for task**:
```
/api/control-de-proyectos/documentos-tarea/?tarea_id=1
```

**Upload document**:
```
POST /api/control-de-proyectos/documentos-tarea/123/
PATCH {estado: "ENVIADO", archivo: file}
```

**Change task state**:
```
POST /api/control-de-proyectos/tareas/45/cambiar_estado/
{estado: "TERMINADA"}
```

---

## 🎨 UI SHORTCUTS

### In Task Form (tarea_form.html)
- Section appears only for saved tasks
- Red badges = required docs
- Green badges = approved docs
- "Cargar" button = upload file/URL

### Upload Modal
- File upload OR URL (not both required)
- Add observaciones if needed
- Click "Cargar" to submit
- Auto-changes status to ENVIADO

---

## 🔍 ADMIN QUICK LINKS

```
/admin/control_de_proyectos/tipotarea/           → Task Types
/admin/control_de_proyectos/documentorequeridotipotarea/ → Doc Requirements
/admin/control_de_proyectos/tarea/               → Tasks (with docs inline)
/admin/control_de_proyectos/tareadocumento/      → Documents
```

---

## 💾 DATABASE MODELS

### TipoTarea
```python
id | nombre | descripcion | activo | fecha_creacion
```

### DocumentoRequeridoTipoTarea
```python
id | tipo_tarea_id | nombre_documento | tipo_doc (ENTRADA/SALIDA) | es_obligatorio | orden
```

### TareaDocumento
```python
id | tarea_id | nombre_documento | estado | archivo | url_documento | responsable_id | fecha_entrega
```

### Tarea (Extensions)
```python
tipo_tarea_id | fecha_inicio_plan | fecha_fin_plan | porcentaje_avance | ...
```

---

## ⚙️ CONFIGURATION

### Required Settings (AppDocs/settings.py)
```python
INSTALLED_APPS = [..., 'rest_framework', 'control_de_proyectos', ...]
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
```

### API URL (AppDocs/urls.py)
```python
path('api/control-de-proyectos/', include('control_de_proyectos.api_urls'))
```

---

## 🛠️ COMMON TASKS

### Create Task Type Programmatically
```python
from control_de_proyectos.models import TipoTarea, DocumentoRequeridoTipoTarea

tipo = TipoTarea.objects.create(
    nombre="Design Review",
    descripcion="UI/UX design review"
)

DocumentoRequeridoTipoTarea.objects.create(
    tipo_tarea=tipo,
    nombre_documento="Design Files",
    tipo_doc="ENTRADA",
    es_obligatorio=True,
    orden=1
)
```

### Create Task with Auto-Documents
```python
from control_de_proyectos.models import Tarea, Proyecto, TipoTarea

project = Proyecto.objects.get(id=1)
tipo = TipoTarea.objects.get(nombre="Design Review")

tarea = Tarea.objects.create(
    nombre="Review Homepage Design",
    proyecto=project,
    tipo_tarea=tipo  # Signal fires! Documents auto-created
)

# View auto-generated documents
tarea.documentos.all()  # Returns queryset of TareaDocumento
```

### Update Document Status
```python
from control_de_proyectos.models import TareaDocumento

doc = TareaDocumento.objects.get(id=123)
doc.estado = 'APROBADO'
doc.save()

# Check if task can be marked complete
if doc.tarea.puede_marcar_terminada():
    doc.tarea.estado = 'TERMINADA'
    doc.tarea.save()
```

---

## 🐛 TROUBLESHOOTING

| Issue | Solution |
|-------|----------|
| Documents not auto-generating | Restart Django, check signals in apps.py |
| Can't mark task EN_CURSO | ENTRADA docs must be APROBADO |
| Can't mark task TERMINADA | SALIDA docs must be APROBADO |
| File upload fails | Check MEDIA_ROOT writable, file type allowed |
| API returns 404 | Verify api_urls.py is included in main urls.py |
| Modal not closing | Refresh page or check browser console |

---

## 📊 GANTT CHART DATA

Access via API for chart visualization:

```javascript
// Fetch task data for Gantt
GET /api/control-de-proyectos/tareas/
Returns:
{
  id: 1,
  nombre: "Task Name",
  fecha_inicio_plan: "2024-01-15",
  fecha_fin_plan: "2024-01-20",
  fecha_inicio_real: "2024-01-15",
  fecha_fin_real: "2024-01-22",
  porcentaje_avance: 75,
  depende_de: [2, 3],  // Task IDs this depends on
  estado: "EN_CURSO"
}
```

---

## 📱 MOBILE API

All endpoints return JSON. Perfect for mobile apps:

```bash
# Get all tasks for project
curl /api/control-de-proyectos/tareas/por_proyecto/?proyecto_id=1

# Upload document
curl -X PATCH /api/control-de-proyectos/documentos-tarea/123/ \
  -F "archivo=@/path/to/file.pdf" \
  -F "estado=ENVIADO"

# Get document history
curl /api/control-de-proyectos/documentos-tarea/?tarea_id=1&tipo_doc=SALIDA
```

---

## 🔐 PERMISSIONS

All endpoints require:
- ✓ User authentication (IsAuthenticated)
- ✓ empresa_id in session
- Ready for access_control decorators

### To Add Custom Permissions:
```python
from access_control.decorators import verificar_permiso

# In ViewSet
def perform_create(self, serializer):
    if not verificar_permiso(self.request.user, 'crear_documento'):
        raise PermissionDenied()
    serializer.save()
```

---

## 📚 DOCUMENTATION

| Document | Purpose |
|----------|---------|
| DOCUMENT_MANAGEMENT_GUIDE.md | Complete workflow guide |
| IMPLEMENTATION_SUMMARY.md | Technical details |
| FINAL_IMPLEMENTATION_REPORT.md | Full report with examples |
| CHECKLIST_COMPLETION.md | Implementation checklist |
| test_implementation.py | Verification script |

---

## 🎯 NEXT STEPS

### Phase 2 (Future):
- [ ] Gantt chart visualization (use library)
- [ ] Email notifications on doc status
- [ ] Document versioning
- [ ] Multi-step approval workflows
- [ ] Cloud storage integration (S3)
- [ ] Document signing (eSignature)

### Monitoring:
- [ ] Track document upload metrics
- [ ] Monitor task completion rates
- [ ] Alert on blocked tasks
- [ ] Report on process bottlenecks

---

## 📞 SUPPORT

**For issues**:
1. Check troubleshooting section
2. Review inline code comments
3. Check Django console logs
4. Read comprehensive guides (see Documentation)

**For new features**:
1. Review "Next Steps" section
2. Extend serializers/viewsets
3. Add custom API actions
4. Create additional signals

---

## ✨ KEY FEATURES RECAP

✅ Auto-generates documents when task type assigned
✅ Validates task state based on document completion
✅ Supports file upload or URL reference
✅ REST API for all operations
✅ Gantt data model (dates, progress, dependencies)
✅ Admin interface for all operations
✅ Real-time document tracking
✅ Task workflow enforcement
✅ Mobile-friendly JSON API
✅ Production-ready security

---

**Version**: 1.0.0
**Status**: Production Ready
**Last Updated**: 2024
