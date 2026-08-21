# Control de Proyectos - Documentación

## Estructura del módulo

```
control_de_proyectos/
├── models.py           # Modelos: TipoProyecto, EspecialidadProfesional, ClienteEmpresa, Profesional, Proyecto, Tarea
├── views.py            # Vistas web con VerificarPermisoMixin
├── forms.py            # Formularios Django
├── urls.py             # URLs web
├── serializers.py      # Serializers DRF
├── api_views.py        # ViewSets DRF
├── api_urls.py         # URLs API con router
├── admin.py            # Admin customizado con filtros
└── templates/
    └── control_de_proyectos/
        ├── proyecto_lista.html
        ├── proyecto_detalle.html
        ├── proyecto_form.html
        ├── proyecto_confirmar_eliminar.html
        └── tarea_form.html
```

## Características principales

### 1. Catálogos "inteligentes" (Auto-learning)

#### TipoProyecto
- Texto libre al crear/editar Proyecto
- Se normaliza automáticamente (trim + Title case)
- Se crea/obtiene el tipo del catálogo automáticamente
- El proyecto siempre referencia el TipoProyecto correctamente

**Ejemplo:** Al escribir "consultoría", "Consultoría", "CONSULTORÍA" → se guarda como "Consultoría"

#### EspecialidadProfesional
- Texto libre al crear/editar Profesional
- Se normaliza automáticamente (trim + Title case)
- Se crea/obtiene la especialidad del catálogo automáticamente
- El profesional siempre referencia la EspecialidadProfesional correctamente

### 2. Validación de RUT

```python
from control_de_proyectos.models import validar_rut, normalizar_rut

# Valida dígito verificador
validar_rut("12.345.678-9")  # Lanza ValidationError si es inválido

# Normaliza formato
normalizar_rut("12345678-9")  # Retorna "12.345.678-9"
normalizar_rut("12.345.678-9")  # Retorna "12.345.678-9"
```

### 3. Modelos

#### ClienteEmpresa
- RUT único y validado
- Campos: nombre, rut, teléfono, email, dirección, ciudad, contacto
- Separado de Empresa (que es la empresa interna)

#### Profesional
- RUT único y validado
- Especialidad con auto-learning
- Opcional: OneToOne con User (para acceso al sistema)
- Activo/Inactivo

#### Proyecto
- FK a Empresa interna (empresa_interna)
- FK a ClienteEmpresa (cliente)
- Tipo con auto-learning (tipo_texto → tipo_ref)
- Estados: FUTURO_ESTUDIO, EN_ESTUDIO, EN_COTIZACION, EN_EJECUCION, TERMINADO
- M2M con Profesional
- Presupuesto y monto_facturado
- Fechas estimadas y reales

#### Tarea
- FK a Proyecto
- FK a Profesional (asignado)
- Prioridad: BAJA, MEDIA, ALTA, URGENTE
- Estado: PENDIENTE, EN_PROGRESO, COMPLETADA, CANCELADA
- Horas estimadas y reales

### 4. Permisos y Control de Acceso

Todas las vistas usan el patrón del proyecto:

```python
class VerificarPermisoMixin:
    vista_nombre = "Listar Proyectos"  # Nombre de la vista en access_control
    permiso_requerido = "ingresar"      # ingresar, crear, modificar, eliminar, autorizar, supervisor
```

**Ejemplo de uso en view:**
```python
from access_control.decorators import verificar_permiso

class CrearProyectoView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    vista_nombre = "Crear Proyecto"
    permiso_requerido = "crear"
    # ... resto del código
```

### 5. API DRF

#### Endpoints disponibles

```
GET    /api/v1/control-proyectos/tipos-proyecto/
POST   /api/v1/control-proyectos/tipos-proyecto/
GET    /api/v1/control-proyectos/especialidades/
POST   /api/v1/control-proyectos/especialidades/
GET    /api/v1/control-proyectos/clientes/
POST   /api/v1/control-proyectos/clientes/
GET    /api/v1/control-proyectos/profesionales/
POST   /api/v1/control-proyectos/profesionales/
GET    /api/v1/control-proyectos/proyectos/
POST   /api/v1/control-proyectos/proyectos/
GET    /api/v1/control-proyectos/tareas/
POST   /api/v1/control-proyectos/tareas/
```

#### Búsqueda y filtros

Todos los ViewSets incluyen:
- `SearchFilter`: buscar en campos específicos
- `OrderingFilter`: ordenar por campos
- Paginación automática

**Ejemplo:**
```
GET /api/v1/control-proyectos/proyectos/?search=cliente&ordering=-fecha_creacion&page=1
```

#### Permisos API

```python
permission_classes = [IsAuthenticated]  # Usuario debe estar logueado
```

### 6. Admin Django

Accede a:
- Tipos de Proyecto (filtros: activo, fecha_creacion)
- Especialidades (filtros: activo, fecha_creacion)
- Clientes (filtros: activo, ciudad, fecha_creacion)
- Profesionales (filtros: activo, especialidad_ref, fecha_creacion)
- Proyectos (filtros: empresa_interna, cliente, tipo_ref, estado, fecha_creacion)
- Tareas (filtros: proyecto, estado, prioridad, profesional_asignado, fecha_creacion)

### 7. Autocomplete/Sugerencias AJAX

```python
GET /control-proyectos/api/sugerir-tipos/?query=cons
GET /control-proyectos/api/sugerir-especialidades/?query=ing
```

Retorna:
```json
{
  "sugerencias": [
    {"id": 1, "nombre": "Consultoría"},
    {"id": 2, "nombre": "Consultoría Técnica"}
  ]
}
```

## Configuración

### settings.py
```python
INSTALLED_APPS = [
    # ...
    'control_de_proyectos',
    # ...
]
```

### urls.py (principal)
```python
path('api/v1/control-proyectos/', include('control_de_proyectos.api_urls')),
path('control-proyectos/', include('control_de_proyectos.urls', namespace='control_de_proyectos')),
```

## Migraciones

```bash
# Crear migraciones
python manage.py makemigrations control_de_proyectos

# Aplicar migraciones
python manage.py migrate control_de_proyectos

# Ver estado
python manage.py showmigrations control_de_proyectos
```

## Ejemplo de uso

### Web

1. Ir a `/control-proyectos/proyectos/`
2. Crear nuevo proyecto:
   - Nombre: "Consultoría Energética"
   - Cliente: Seleccionar o crear
   - Tipo: "Consultoría" (se normaliza y crea automáticamente)
   - Profesionales: Seleccionar varios
   - Estado: EN_ESTUDIO
3. Ver detalles del proyecto
4. Crear tareas dentro del proyecto

### API

```bash
# Listar proyectos
curl http://localhost:8000/api/v1/control-proyectos/proyectos/

# Crear proyecto
curl -X POST http://localhost:8000/api/v1/control-proyectos/proyectos/ \
  -H "Content-Type: application/json" \
  -d '{
    "nombre": "Nuevo Proyecto",
    "empresa_interna": 1,
    "cliente": 1,
    "tipo_texto": "Consultoría",
    "estado": "EN_ESTUDIO"
  }'

# Buscar tipos
curl http://localhost:8000/api/v1/control-proyectos/tipos-proyecto/?search=cons
```

## Notas importantes

1. **Empresa interna es obligatoria**: Se toma de `request.session.get("empresa_id")`
2. **Auto-learning**: Los campos `tipo_texto` y `especialidad_texto` crean catálogos automáticamente
3. **RUT normalizado**: Se guarda siempre en formato XX.XXX.XXX-X
4. **Permisos**: Se validan en todas las vistas web usando `access_control.decorators.verificar_permiso`
5. **API sin permisos granulares**: Solo requiere `IsAuthenticated` (los permisos granulares están en web)

## Troubleshooting

### Error: "No tienes permiso para esta acción"
- Verifica que la vista esté registrada en `access_control` admin
- Verifica que el usuario tenga permisos en esa empresa

### Tipo/Especialidad no se actualiza
- Los campos `tipo_ref` y `especialidad_ref` son **read-only** en los formularios
- Se actualizan automáticamente al guardar basados en `tipo_texto` y `especialidad_texto`

### RUT rechazado
- Verifica el formato: XX.XXX.XXX-X
- Verifica que el dígito verificador sea correcto
- No puede estar duplicado

