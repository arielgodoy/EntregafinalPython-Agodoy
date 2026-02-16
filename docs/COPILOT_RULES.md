# COPILOT_RULES.md

## 0) Principio base
- Antes de cualquier cambio: leer este archivo COMPLETO y respetarlo.
- Prioridad máxima: NO romper nada que ya esté operativo en producción.
- Para operaciones de ELIMINACIÓN en toda la app: ver archivo `AJAX_DELETION_PATTERN.md` (patrón obligatorio).
- Este archivo DEBE existir físicamente en el repositorio.
- El patrón descrito allí debe coincidir EXACTAMENTE con la implementación actual del sistema.
- Prohibido crear variantes del patrón sin actualizar también `AJAX_DELETION_PATTERN.md`.

---

## 1) Contexto del sistema
- Proyecto Django multi-rubro, multi-empresa, multi-rol y multi-cliente.
- "Empresa activa" se define por sesión (empresa_id / empresa_codigo / empresa_nombre) y se usa para scoping en views/queries.
- Permisos se controlan por: usuario + empresa + vista + flags (ingresar/crear/modificar/eliminar/autorizar/supervisor).

---

## 2) Reglas de seguridad y compatibilidad (NO negociables)
- No duplicar Bootstrap (bootstrap.bundle.js) ni DataTables assets. Cargar 1 sola vez.
- No introducir librerías nuevas si ya existe un patrón interno (ej: DataTables en biblioteca).
- No cambiar constraints/UniqueConstraint existentes sin plan de migración y sin validación de impacto.
- Mantener compatibilidad con SQLite y el entorno local.
- Evitar N+1 queries: usar select_related/prefetch_related/annotate cuando corresponda.

---

## 3) Multiempresa / Scoping (regla crítica)

- Toda vista/listado/modificación que afecte entidades "scoped" debe filtrar por empresa activa:
  - Proyecto.empresa_interna = empresa activa
  - Permiso.empresa = empresa activa
  - ThemePreferences.empresa = empresa activa

- Si una vista olvida filtrar por empresa, se considera BUG crítico.

- Excepciones de scoping (GLOBAL) SOLO si está declarado explícitamente:
  - Opción 1: el modelo tiene un flag/atributo/documentación interna clara de que es global.
  - Opción 2: existe una regla de negocio escrita en un documento del repo (ej: STANDARDS_VIEWS.md).
  - Opción 3: existe un campo/relación que define globalidad (ej: empresa=NULL permitido y documentado).

- Si NO existe declaración explícita, asumir SIEMPRE scoped por empresa activa.
- Copilot NO puede "asumir global" por conveniencia.

---

## 4) UI dinámica: IDs únicos + Bootstrap Collapse (regla crítica)

- Todo elemento con data-bs-toggle="collapse" debe tener:
  - data-bs-target válido (NO "#", NO vacío)
  - aria-controls válido
  - el panel collapse debe tener id válido y único

- En componentes repetidos (listas/child rows/partials), los IDs deben incluir prefijos únicos:
  - proyecto_id + tarea_id + sufijo (ej: proyecto-<pid>-tarea-<tid>-docs-entrada)

- No renderizar HTML con IDs duplicados en "containers ocultos" dentro del DOM.
  - Si se necesita pre-render para DataTables child row, usar <template> y clonar content.

---

## 5) DataTables + Child Rows

- No meter UI interactiva pesada en el <tr> principal (sliders, acordeones internos, formularios).
- El detalle (acordeón + sliders + documentos) va en el child row.
- JS debe funcionar después de redraw: usar delegación de eventos o hooks de DataTables (drawCallback).
- Si se inserta HTML dinámico: re-inicializar handlers con una función tipo initX(rootElement).

---

## 6) Estándares de desarrollo

- Mantener estructura existente del proyecto (apps, partials, templates).
- Reutilizar patrones de biblioteca cuando corresponda (DataTables, estilo, i18n si aplica).
- No "refactor masivo". Si se necesita, dividir en PR/commits.

---

## 7) Logging y debugging

- Cuando haya errores de UI:
  - reproducir
  - revisar consola/network
  - identificar causa raíz exacta
  - aplicar fix mínimo

- Si aparece "'#' is not a valid selector", buscar y eliminar data-bs-target="#" / href="#" / data-bs-parent inválidos.

---

## 8) NUEVAS REGLAS: Tests en carpeta tests/ (OBLIGATORIO)

- Todos los tests deben vivir dentro de una carpeta `tests/` por app (paquete Python).
- No usar tests sueltos en `tests.py` en raíz de la app (migrarlos).

Estructura estándar por app:

  <app>/
    tests/
      __init__.py
      test_models.py
      test_views.py
      test_forms.py
      test_api.py (si aplica)
      test_permissions.py (si aplica)

Naming obligatorio:
- Archivos: test_*.py
- Clases: Test*
- Métodos: test_*

Descubrimiento de Django:
- Asegurar que exista tests/__init__.py para que Django detecte el paquete.

Cobertura mínima por módulo nuevo:
- 1 test de modelo (creación/str/constraint)
- 1 test de permisos/empresa activa (scoping)
- 1 test de vista o endpoint (GET/POST básico)

- Prohibido escribir tests que dependan de datos reales de producción.
- Usar factories/fixtures mínimas (crear Empresa/Usuario/Permiso/Proyecto según corresponda).
- Cada cambio funcional debe incluir o actualizar tests relevantes.

EXCEPCIÓN CONTROLADA (solo hotfix crítico):
- Se permite un fix mínimo sin nuevos tests SOLO si:
  1) Se documenta en comentario del PR/commit ("HOTFIX SIN TEST")
  2) Se crea ticket/nota para agregar tests en el siguiente PR inmediato
- Fuera de hotfix crítico: prohibido merge sin tests.

---

## 9) Checklist antes de entregar cambios

FORMATO DE RESPUESTA OBLIGATORIO:

- TODA respuesta DEBE ser EXACTAMENTE 1 bloque de código (```text``` / ```python``` / ```js``` según corresponda).
- PROHIBIDO escribir cualquier explicación fuera del bloque.
- Dentro del bloque se incluyen: instrucciones + snippets + checklist (todo junto).
- Si se requiere texto plano, usar ```text``` igualmente para mantener "copiar con 1 click".

Comandos oficiales (local):
- scripts\run_local.ps1
- scripts\test_all.ps1
- scripts\test_app.ps1 -App control_operacional
- scripts\migrate_local.ps1

Siempre ejecutar desde scripts para evitar rutas rotas.

---

REGLA OBLIGATORIA – SISTEMA MULTILENGUAJE (i18n)

Este proyecto es MULTILENGUAJE (ES / EN).

REGLAS ESTRICTAS:

1. TODO TEXTO VISIBLE AL USUARIO DEBE TENER EL ATRIBUTO:
   data-key="clave.traduccion"

   Esto incluye, SIN EXCEPCIÓN:
   - Títulos (h1–h6)
   - Labels
   - Botones
   - Links
   - Placeholders
   - Mensajes de error / éxito
   - Textos dentro de modales
   - Textos de tablas
   - Textos condicionales renderizados por lógica
   - Menús y submenús
   - Tooltips y ayudas visuales
   - Placeholders de <input>, <textarea> y <select>

2. NO se deben dejar textos hardcodeados visibles al usuario sin data-key.

EXCEPCIÓN:
- Logging interno (logger.debug/info/warn/error) NO requiere data-key.
- Todo lo que el usuario VE (templates, toasts, alerts, messages.*, confirmaciones JS) SÍ requiere data-key.

3. Las claves de traducción deben:
   - Usar lowercase
   - Usar puntos como separador
   - Ser descriptivas y estables

Ejemplo:
  data-key="users.invite.title"
  data-key="buttons.send_invitation"

4. El sistema utiliza los archivos:
   /static/lang/en.json
   /static/lang/sp.json

Toda nueva clave agregada en templates DEBE:
- Ser incluida en AMBOS archivos JSON
- Mantener equivalencia semántica entre idiomas

5. Si se modifica un template existente:
- Se deben agregar data-key a TODOS los textos visibles nuevos o existentes
- No se permite mezclar textos con y sin data-key

6. No romper funcionalidad existente:
- Solo se agrega data-key
- No se cambia lógica ni comportamiento salvo que se solicite explícitamente

7. Si falta una traducción:
- Se debe crear la clave
- Se deben agregar los valores en en.json y sp.json
- No se deja texto sin traducir como "temporal"

8. i18n EN JAVASCRIPT (OBLIGATORIO):
- Todos los textos generados dinámicamente desde JS (toasts, alerts, innerHTML, confirmaciones, mensajes de error) deben usar el sistema de traducción.
- Está PROHIBIDO hardcodear strings visibles en JS.
- Se debe utilizar la función global de traducción ya existente en el proyecto.
- Está PROHIBIDO crear nuevas funciones de traducción si ya existe una implementación global.

---

COMPORTAMIENTO

- NO pedir confirmaciones intermedias.
- NO dejar pasos "para después".
- NO detenerse por supuestos faltantes; documentarlos dentro del bloque y continuar.
- NO modificar login/logout ni UserPreferences salvo instrucción explícita.
- RESPETAR estrictamente la arquitectura existente del proyecto.
- NO introducir dependencias nuevas sin justificar dentro del mismo bloque.

MODO DE TRABAJO OBLIGATORIO:
- Se trabaja APP POR APP.
- En cada app: entregar el cambio COMPLETO del paso (sin preguntas intermedias).
- Al terminar una app: detenerse y esperar el "OK" del usuario para continuar a la siguiente app.

---

INCUMPLIMIENTO

- CUALQUIER RESPUESTA QUE NO CUMPLA ESTE FORMATO SE CONSIDERA INVÁLIDA.

---

10) PATRÓN OBLIGATORIO: AJAX + Modal para Eliminaciones

REFERENCIA COMPLETA: Ver archivo AJAX_DELETION_PATTERN.md

Resumen obligatorio para TODAS las eliminaciones:

Componentes requeridos:
1. Template: Botón .btn-eliminar-objeto + Modal Bootstrap + {% csrf_token %}
2. JavaScript: AJAX en {% block extra_js %} con delegación de eventos
3. Vista: JsonResponse detectando solicitud AJAX de forma robusta

Reglas técnicas:
- El Modal de eliminación debe tener ID único por página.
- Si solo existe un listado en la vista, puede usarse deleteModal.
- Si existen múltiples componentes reutilizables o partials, el ID debe incluir prefijo contextual.
- Está PROHIBIDO generar IDs duplicados en el DOM.
- La vista debe detectar AJAX usando:
  - Header X-Requested-With: XMLHttpRequest
  O
  - Header Accept: application/json
  O
  - Parámetro ?ajax=1
- Siempre retornar JsonResponse cuando se detecte solicitud AJAX.
- Usar transaction.atomic() en la vista.
- Incluir spinner durante procesamiento.
- Mostrar Toast de éxito/error usando sistema i18n.
- Todos los textos deben incluir data-key.

Aclaración:
- Si la vista NO es un listado y NO usa modal (pantalla simple), no insertar modal innecesario.
  - Igual se debe soportar AJAX detection y retornar JsonResponse cuando aplique.
  - El modal es obligatorio SOLO cuando existe UI de eliminación desde listado/tabla.

Referencia oficial:
- Template: access_control/templates/access_control/usuarios_lista.html
- Vista: access_control/views.py (clase UsuarioEliminarView)

Este es el patrón OFICIAL del sistema. Aplicar a TODOS los listados con eliminación.

---

10.1) REGLA TÉCNICA CRÍTICA: DeleteView + AJAX (OBLIGATORIO LEER)

⚠️ PROBLEMA COMÚN: Sobrescribir delete() en DeleteView NO funciona para AJAX

CAUSA RAÍZ:
- Django DeleteView recibe peticiones POST (no DELETE HTTP)
- El flujo es: POST → post() → form_valid() → delete()
- Si sobrescribes delete() y retornas JsonResponse, Django ya renderizó HTML antes

SOLUCIÓN OBLIGATORIA:

class MiEliminarView(VerificarPermisoMixin, LoginRequiredMixin, DeleteView):
    model = MiModelo
    template_name = 'mi_confirmar_eliminar.html'
    success_url = reverse_lazy('mi_lista')
    vista_nombre = "Mi Vista"
    permiso_requerido = "eliminar"
    
    def post(self, request, *args, **kwargs):
        """SOBRESCRIBIR POST - NO DELETE"""
        # 1. Detectar AJAX
        is_ajax = (
            request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest' or
            'application/json' in request.META.get('HTTP_ACCEPT', '')
        )
        
        if is_ajax:
            # 2. Manejar eliminación AJAX directamente
            try:
                with transaction.atomic():
                    self.object = self.get_object()
                    
                    # 3. Validaciones de negocio (scoping, etc.)
                    empresa_activa = request.session.get('empresa_id')
                    if hasattr(self.object, 'empresa_id') and self.object.empresa_id != empresa_activa:
                        return JsonResponse({
                            'success': False,
                            'message': 'no_permission_delete'
                        }, status=403)
                    
                    # 4. Eliminar
                    self.object.delete()
                    
                    # 5. Retornar JSON
                    return JsonResponse({
                        'success': True,
                        'message': 'deleted_successfully'
                    })
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'message': 'delete_error'
                }, status=500)
        else:
            # 6. Flujo tradicional (form HTML)
            return super().post(request, *args, **kwargs)

DETECCIÓN DE AJAX - MÉTODO ROBUSTO:

Opción 1 (Header X-Requested-With):
    request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'

Opción 2 (Header Accept):
    'application/json' in request.META.get('HTTP_ACCEPT', '')

Opción 3 (Combinada - RECOMENDADA):
    is_ajax = (
        request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest' or
        'application/json' in request.META.get('HTTP_ACCEPT', '')
    )

JAVASCRIPT - Configuración correcta de headers:

var xhr = new XMLHttpRequest();
xhr.open('POST', deleteUrl, true);
xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
xhr.setRequestHeader('X-CSRFToken', csrfToken);
xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');  // ← CRÍTICO
xhr.setRequestHeader('Accept', 'application/json');           // ← RESPALDO

// O con jQuery:
$.ajax({
    url: deleteUrl,
    type: 'POST',
    headers: {
        'X-CSRFToken': csrfToken,
        'X-Requested-With': 'XMLHttpRequest'
    },
    success: function(response) {
        // Manejar response.success / response.message
    }
});

VALIDACIÓN DE PERMISOS EN AJAX:

Si se necesita mensaje personalizado con username:

def handle_no_permission(self, request, mensaje="No tienes permiso para esta acción."):
    """Sobrescribir para incluir username en mensaje de error"""
    is_ajax = (
        request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest' or
        'application/json' in request.META.get('HTTP_ACCEPT', '')
    )
    
    if is_ajax:
        username = request.user.username if request.user.is_authenticated else "Desconocido"
        return JsonResponse({
            "success": False,
            "message": "permission_denied",
            "username": username,
            "action": "Eliminar"
        }, status=403)
    
    return super().handle_no_permission(request, mensaje)

MENSAJE CON PLACEHOLDERS (i18n):

JavaScript:
    function tReplace(key, replacements) {
        var text = t(key);
        if (replacements) {
            for (var placeholder in replacements) {
                text = text.replace('{' + placeholder + '}', replacements[placeholder]);
            }
        }
        return text;
    }
    
    // Uso:
    var errorMsg = tReplace('permission_denied', {
        username: data.username,
        action: data.action
    });

JSON (sp.json / en.json):
    "permission_denied": "El usuario {username} no tiene acceso a {action}"
    "permission_denied": "User {username} doesn't have access to {action}"

VALIDACIÓN MULTIEMPRESA (Scoping):

SIEMPRE validar que el objeto a eliminar pertenece a la empresa activa:

empresa_activa = request.session.get('empresa_id')

# Para modelos con empresa_id directo:
if self.object.empresa_id != empresa_activa:
    return JsonResponse({'success': False, 'message': 'forbidden'}, status=403)

# Para modelos con relación:
if self.object.empresa.id != empresa_activa:
    return JsonResponse({'success': False, 'message': 'forbidden'}, status=403)

RESUMEN - CHECKLIST OBLIGATORIO:

✓ Sobrescribir post(), NO delete()
✓ Detectar AJAX al inicio de post()
✓ Validar empresa activa (scoping)
✓ Usar transaction.atomic()
✓ Retornar JsonResponse para AJAX
✓ Llamar super().post() para flujo tradicional
✓ Configurar headers X-Requested-With en JavaScript
✓ Manejar errores con try/except
✓ Usar claves i18n en todos los mensajes
✓ Cerrar modal después de éxito
✓ Actualizar DataTable sin reload (row.remove().draw())

ERRORES COMUNES A EVITAR:

✗ Sobrescribir delete() esperando que funcione con AJAX
✗ No detectar AJAX correctamente (olvidar HTTP_X_REQUESTED_WITH)
✗ Retornar HTML cuando se espera JSON
✗ No validar empresa activa
✗ Hardcodear mensajes en español/inglés
✗ No cerrar el modal después de eliminar
✗ Recargar página completa en lugar de actualizar DataTable

---

11) ARQUITECTURA: FBV vs CBV - Cuándo NO migrar a CBV (REGLA CRÍTICA)

Principio fundamental: No todas las vistas deben ser CBV. CBV es para CRUD simple.

A) FUNCIONALIDAD CRÍTICA - PROCEDIMENTAL COMPLEJA

1. solicitar_acceso()
- Lógica de deduplicación
- Dual-response (JSON + Redirect)
- Notificaciones masivas (bulk_create)
- Email audit
- HTTP_REFERER tracking
✗ NO MIGRAR

2. grant_access_request()
- Validación de staff
- Vista.objects.get_or_create() en múltiples puntos
- transaction.atomic() para múltiples modelos
- Validación de estados
✗ NO MIGRAR

3. toggle_permiso()
- Endpoint de bootstrap/utilidad
- NO usar @verificar_permiso (evita ciclo circular)

SEGURIDAD MÍNIMA OBLIGATORIA:
✓ Debe tener @login_required SIEMPRE
✓ NO usar @csrf_exempt salvo razón técnica documentada
✓ Validar input estrictamente:
  - permiso_id debe ser dígitos válidos
  - permiso_field debe estar en whitelist:
    {'ingresar','crear','modificar','eliminar','autorizar','supervisor'}
  - value parseado de forma segura
✓ Si usuario NO es staff:
  - permitir SOLO si tiene permiso supervisor en "Maestro Permisos"
  - si seed no existe aún: permitir SOLO staff
✓ Responder siempre JsonResponse
✓ Nunca exponer trazas internas

✗ NO MIGRAR

4. seleccionar_empresa()
- Mutación de sesión crítica
- Selector de contexto multiempresa
✗ NO MIGRAR

5. _send_system_test_email()
- Utilidad operacional
- Validaciones en cascada
✗ NO MIGRAR

B) REGLA DE ORO

✓ Migrar a CBV si:
- CRUD simple
- 1 modelo
- Sin lógica transaccional compleja

✗ Mantener FBV si:
- Procedimiento complejo
- Transacciones múltiples
- Dual-response
- Mutación de sesión
- Bootstrap / utilidad

C) PERMISOS EN FBV CRÍTICAS

- toggle_permiso: solo @login_required
- grant_access_request: validación manual staff
- solicitar_acceso: puede usar @verificar_permiso si no interfiere con lógica

D) SEÑALES DE ALERTA - NO MIGRAR SI VES:

⚠️ transaction.atomic() + update_or_create()
⚠️ Vista.objects.get_or_create() múltiples veces
⚠️ Mutación de request.session
⚠️ Dual-response
⚠️ Deduplicación
⚠️ Configuración en cascada
⚠️ Ciclos bootstrap/permisos

Estos patrones NO deben tocarse salvo bug fix operacional.

FIN DEL ARCHIVO
