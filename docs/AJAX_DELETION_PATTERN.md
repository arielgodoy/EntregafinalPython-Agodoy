

## 10) PATRÓN ESTÁNDAR: Modal de Confirmación + AJAX para Eliminaciones

Este proyecto usa un patrón MODERNO y CONSISTENTE para todas las operaciones de eliminación: Modal Bootstrap + AJAX (sin recarga de página).

### 10.1) TEMPLATE (HTML): Modal de Confirmación

En TODOS los templates de listado con botón de eliminar, seguir este patrón:

```html
<!-- En el cuerpo de la tabla/listado -->
{% for objeto in objetos %}
<tr id="objeto-row-{{ objeto.id }}">
    <td>{{ objeto.nombre }}</td>
    <td>
        <button class="btn btn-danger btn-sm btn-eliminar-objeto" 
                data-objeto-id="{{ objeto.id }}" 
                data-objeto-nombre="{{ objeto.nombre }}"
                data-delete-url="{% url 'app:objeto_eliminar' objeto.id %}">
            <i class="bi bi-trash"></i> <span data-key="delete">Eliminar</span>
        </button>
    </td>
</tr>
{% endfor %}

<!-- Modal de Confirmación (después del listado, dentro de {% block content %}) -->
<div class="modal fade" id="deleteModal" tabindex="-1" aria-labelledby="deleteModalLabel" aria-hidden="true">
    <div class="modal-dialog">
        <div class="modal-content">
            <div class="modal-header bg-danger text-white">
                <h5 class="modal-title" id="deleteModalLabel" data-key="confirm_delete">Confirmar Eliminación</h5>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">
                <p data-key="delete_confirmation">¿Estás seguro de que deseas eliminar <strong id="objetoNombre"></strong>?</p>
                <div class="alert alert-warning" role="alert">
                    <i class="bi bi-exclamation-triangle-fill me-2"></i>
                    <strong data-key="warning">Advertencia:</strong>
                    <span data-key="delete_warning">Esta acción es irreversible.</span>
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal" data-key="cancel">Cancelar</button>
                <button type="button" class="btn btn-danger" id="confirmDelete" data-key="delete">Eliminar</button>
            </div>
        </div>
    </div>
</div>
```

**Nota importante**: Reemplazar 'objeto' con el nombre real de la entidad (usuario, empresa, permiso, etc.)

### 10.2) JAVASCRIPT: Manejador AJAX en bloque {% block extra_js %}

**CRÍTICO**: Cargar DataTables y scripts EN `{% block extra_js %}`, NUNCA en `{% block content %}`

Estructura mínima:

```html
{% block extra_js %}
<!-- DataTables: SIEMPRE en extra_js, nunca duplicar -->
<link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css">
<script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>

<script>
    let objetoTable;  // Variable global para la tabla
    let deleteUrl = '';
    let objetoId = '';

    $(document).ready(function () {
        // Inicializar DataTable (si aplica)
        objetoTable = $('#objeto-table').DataTable({
            language: { url: "/static/lang/es-ES.json" },
            responsive: true,
            autoWidth: false,
        });

        // Evento: click en botón de eliminar
        $(document).on('click', '.btn-eliminar-objeto', function(e) {
            e.preventDefault();
            
            objetoId = $(this).data('objeto-id');
            const objetoNombre = $(this).data('objeto-nombre');
            deleteUrl = $(this).data('delete-url');

            // Actualizar modal con datos dinámicos
            $('#objetoNombre').text(objetoNombre);
            
            // Mostrar el modal
            const deleteModal = new bootstrap.Modal(document.getElementById('deleteModal'));
            deleteModal.show();
        });

        // Evento: click en botón de confirmación del modal
        $('#confirmDelete').on('click', function() {
            if (!deleteUrl) return;

            // Deshabilitar botón con spinner
            $(this).prop('disabled', true)
                   .html('<span class="spinner-border spinner-border-sm me-2"></span>Eliminando...');

            // AJAX POST a la vista de eliminación
            $.ajax({
                url: deleteUrl,
                type: 'POST',
                headers: {
                    'X-CSRFToken': $('[name=csrfmiddlewaretoken]').val() || getCookie('csrftoken'),
                    'X-Requested-With': 'XMLHttpRequest'  // Indicador de AJAX
                },
                success: function(response) {
                    // Cerrar modal
                    bootstrap.Modal.getInstance(document.getElementById('deleteModal')).hide();
                    
                    // Eliminar fila de DataTable
                    const row = objetoTable.row('#objeto-row-' + objetoId);
                    row.remove().draw();
                    
                    // Toast de éxito
                    Toastify({
                        text: response.message || "Eliminado exitosamente",
                        duration: 3000,
                        gravity: "top",
                        position: "right",
                        backgroundColor: "linear-gradient(to right, #00b09b, #96c93d)",
                    }).showToast();
                },
                error: function(xhr) {
                    let errorMsg = 'Error al eliminar';
                    if (xhr.responseJSON && xhr.responseJSON.error) {
                        errorMsg = xhr.responseJSON.error;
                    }
                    
                    // Toast de error
                    Toastify({
                        text: errorMsg,
                        duration: 3000,
                        gravity: "top",
                        position: "right",
                        backgroundColor: "linear-gradient(to right, #ff5f6d, #ffc371)",
                    }).showToast();
                },
                complete: function() {
                    // Restaurar botón
                    $('#confirmDelete').prop('disabled', false).text('Eliminar');
                }
            });
        });
    });

    // Función auxiliar para obtener CSRF token de cookies
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
</script>
{% endblock extra_js %}
```

### 10.3) VISTA (Django): DeleteView con respuesta JSON

En `views.py`, la vista debe detectar peticiones AJAX y responder con JSON:

```python
from django.views.generic.edit import DeleteView
from django.urls import reverse_lazy
from django.http import JsonResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.shortcuts import redirect
from django.db import transaction

class ObjetoEliminarView(LoginRequiredMixin, DeleteView):
    model = Objeto
    template_name = 'app/objeto_confirmar_eliminar.html'
    success_url = reverse_lazy('app:objeto_lista')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        objeto_nombre = self.object.nombre
        
        try:
            with transaction.atomic():
                # Limpiar relaciones y dependencias ANTES de eliminar
                # self.object.relacion1.all().delete()
                # self.object.relacion2.all().delete()
                self.object.delete()
            
            # Si es AJAX, responder con JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'"{objeto_nombre}" eliminado exitosamente'
                })
            
            # Si NO es AJAX, comportamiento tradicional
            messages.success(request, 'objects.delete.success')
            return redirect(self.success_url)
            
        except Exception as e:
            # Respuesta de error
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': f'Error: {str(e)}'
                }, status=400)
            
            # Error tradicional (sin AJAX)
            messages.error(request, f'Error al eliminar: {str(e)}')
            return redirect(self.success_url)
```

**Notas**:
- Usar `transaction.atomic()` para garantizar que si una relación falla, se revierte todo
- Borrar relaciones ANTES del objeto principal (evita errores de FK)
- El header `X-Requested-With: XMLHttpRequest` es el estándar para detectar AJAX
- Responder siempre con status 400 en errores AJAX

### 10.4) Checklist de Implementación

Antes de agregar eliminación a un nuevo listado, validar:

**Template HTML**:
- [ ] `{% csrf_token %}` presente en el bloque `content`
- [ ] ID único en cada `<tr>`: `id="objeto-row-{{ objeto.id }}"`
- [ ] Botón con clase `.btn-eliminar-objeto` (ajustar nombre según entidad)
- [ ] Atributos `data-objeto-id`, `data-objeto-nombre`, `data-delete-url`
- [ ] Modal con `id="deleteModal"` y elemento `id="objetoNombre"`
- [ ] Todos los textos del modal con `data-key="..."`

**JavaScript (extra_js)**:
- [ ] DataTables cargado DESDE CDN en extra_js (NO duplicar)
- [ ] Script envuelto en `$(document).ready()`
- [ ] Event listener usa delegación: `$(document).on('click', '.btn-eliminar-objeto', ...)`
- [ ] AJAX envía header `X-Requested-With: XMLHttpRequest`
- [ ] Spinner en botón mientras se procesa: `.html('<span class="spinner-border...`
- [ ] Eliminación de fila: `table.row('#objeto-row-' + id).remove().draw()`
- [ ] Notificaciones con `Toastify({...}).showToast()`
- [ ] Función `getCookie(name)` para extraer CSRF token

**Vista Django (views.py)**:
- [ ] Detecta AJAX: `request.headers.get('X-Requested-With') == 'XMLHttpRequest'`
- [ ] Responde JSON: `JsonResponse({'success': True, 'message': '...'})`
- [ ] Errores con status 400: `JsonResponse({...}, status=400)`
- [ ] Usa `transaction.atomic()` para transacciones seguras
- [ ] Borra relaciones ANTES del objeto principal
- [ ] Implementa fallback para no-AJAX (redirección)
- [ ] Valida permisos (usar `VerificarPermisoMixin`)

**i18n (Multilenguaje)**:
- [ ] Todos los textos visibles tienen `data-key="..."`
- [ ] Claves agregadas en `/static/lang/en.json` y `/static/lang/sp.json`

### 10.5) Claves de Traducción Estándar

Usar estas claves en TODOS los modales de eliminación. Agregar en ambos JSON:

```json
"confirm_delete": "Confirmar Eliminación",
"delete_confirmation": "¿Estás seguro de que deseas eliminar",
"warning": "Advertencia:",
"delete_warning": "Esta acción es irreversible.",
"cancel": "Cancelar",
"delete": "Eliminar"
```

### 10.6) Ventajas del Patrón AJAX + Modal

✅ **UX Moderno**: Sin recarga de página ni navegación  
✅ **Consistencia**: Transacciones atómicas con `transaction.atomic()`  
✅ **Feedback Visual**: Spinners y Toast notifications  
✅ **Reutilizable**: Patrón DRY (una línea de JS por nuevo objeto)  
✅ **Compatible**: Funciona con DataTables, Bootstrap, y frameworks existentes  
✅ **Seguro**: CSRF token validado, permisos controlados  
✅ **Multilenguaje**: Soporta i18n nativo  
✅ **Robusto**: Fallback a redirección si JS deshabilitado  

### 10.7) Ejemplo Real: Usuarios

Ver `/access_control/templates/access_control/usuarios_lista.html` y `/access_control/views.py` (clase `UsuarioEliminarView`) para referencia completa implementada.

