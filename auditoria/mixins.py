from .helpers import audit_log


class AuditMixin:
    """
    Mixin para auditar CBVs automáticamente.
    
    FIX A APLICADO:
    - VIEW: solo registra si GET y response 200
    - CREATE: solo registra si POST y response 302/303 O existe self.object con pk
    - UPDATE: solo registra si POST/PUT/PATCH y response 302/303 O existe self.object
    - DELETE: solo registra si POST y response 302/303
    
    Uso:
        class MiVista(AuditMixin, VerificarPermisoMixin, CreateView):
            audit_action = 'CREATE'
            audit_app_label = 'biblioteca'
            model = Documento
            ...
    
    Sobrescribir audit_get_object() si el objeto no está en self.object.
    """
    
    audit_action = None  # 'VIEW', 'CREATE', 'UPDATE', 'DELETE'
    audit_app_label = None  # 'biblioteca', etc.
    audit_message_key = None  # Clave i18n opcional
    
    def dispatch(self, request, *args, **kwargs):
        """Hook principal del ciclo de vida de la vista."""
        response = super().dispatch(request, *args, **kwargs)

        # Guardar status_code y vista_nombre en request para helpers
        request._audit_response_status_code = response.status_code
        request._audit_vista_nombre = getattr(self, 'vista_nombre', None)

        # Evitar duplicación si ya auditado manualmente
        if getattr(request, '_audit_logged', False):
            return response

        # Validar método HTTP y status code según acción
        if self._should_audit(request, response):
            self._audit_dispatch(request, response)

        return response
    
    def _should_audit(self, request, response):
        """
        FIX A: Determina si se debe auditar según método HTTP y status code.
        """
        if not self.audit_action or not self.audit_app_label:
            return False
        
        status_code = response.status_code
        method = request.method
        
        # VIEW: solo GET exitoso (200)
        if self.audit_action == 'VIEW':
            return method == 'GET' and status_code == 200
        
        # CREATE: POST exitoso (redirect 302/303) O existe objeto creado
        elif self.audit_action == 'CREATE':
            if method != 'POST':
                return False
            # Redirect exitoso O objeto con pk (guardado exitosamente)
            return status_code in (302, 303) or (hasattr(self, 'object') and self.object and self.object.pk)
        
        # UPDATE: POST/PUT/PATCH exitoso (redirect 302/303) O existe objeto
        elif self.audit_action == 'UPDATE':
            if method not in ('POST', 'PUT', 'PATCH'):
                return False
            # Redirect exitoso O objeto existe
            return status_code in (302, 303) or (hasattr(self, 'object') and self.object)
        
        # DELETE: POST exitoso (redirect 302/303)
        elif self.audit_action == 'DELETE':
            return method == 'POST' and status_code in (302, 303)
        
        # Otras acciones: por defecto no auditar
        return False
    
    def _audit_dispatch(self, request, response):
        """Registrar auditoría según tipo de acción."""
        obj = self.audit_get_object()

        # Preparar after snapshot para CREATE
        after = None
        if self.audit_action == 'CREATE' and hasattr(self, 'object') and self.object and getattr(self.object, 'pk', None):
            from .services import AuditoriaService
            after = AuditoriaService.model_to_snapshot(self.object)

        audit_log(
            request=request,
            action=self.audit_action,
            app_label=self.audit_app_label,
            obj=obj,
            vista_nombre=getattr(self, 'vista_nombre', None),
            message_key=self.audit_message_key,
            after=after,
            status_code=response.status_code,
        )
    
    def audit_get_object(self):
        """
        Retorna el objeto a auditar.
        Por defecto usa self.object (disponible en DetailView, UpdateView, CreateView post-save).
        Sobrescribir si necesitas lógica custom.
        """
        return getattr(self, 'object', None)
