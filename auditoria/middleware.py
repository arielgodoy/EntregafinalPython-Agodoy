import time
import logging
from django.utils.deprecation import MiddlewareMixin
from common.http import get_client_ip
from common.navigation import is_navigable_request
from .services import AuditoriaService

logger = logging.getLogger(__name__)


class AuditMiddleware(MiddlewareMixin):
    """
    Middleware de auditoría que captura request-level information:
    - Errores 403 y 500 (siempre se registran)
    - Requests no auditadas explícitamente (excepto static/media)
    
    La vista puede marcar request._audit_logged = True para evitar duplicación.
    """
    
    EXCLUDED_PATHS = ['/static/', '/media/', '/favicon.ico', '/__debug__/']
    
    def process_request(self, request):
        """
        Marcar tiempo de inicio de la petición.
        FIX B: NO sobrescribir _audit_logged si ya existe.
        """
        request._audit_start_time = time.time()
        
        # FIX B APLICADO: solo inicializar si no existe
        if not hasattr(request, '_audit_logged'):
            request._audit_logged = False
    
    def process_response(self, request, response):
        """
        Registrar evento si:
        1) status_code in (403, 500) - SIEMPRE
        2) request._audit_logged != True Y no es static/media
        """
        
        # Calcular duración
        duration_ms = None
        if hasattr(request, '_audit_start_time'):
            duration_ms = int((time.time() - request._audit_start_time) * 1000)
        
        status_code = response.status_code
        path = request.path
        
        # Verificar si la ruta debe excluirse
        if any(path.startswith(excluded) for excluded in self.EXCLUDED_PATHS):
            return response
        
        try:
            # REGLA 1: Errores 403/500 siempre se registran (incluso si ya hay audit explícito)
            if status_code in (403, 500):
                self._log_error(request, response, duration_ms)
                return response

            # REGLA 2: Si no fue auditado explícitamente y es exitoso, registrar genérico
            if not getattr(request, '_audit_logged', False) and status_code < 400:
                self._log_generic(request, response, duration_ms)
        except Exception:
            logger.exception("Falló el middleware de auditoría path=%s", path)
        
        return response
    
    def _log_error(self, request, response, duration_ms):
        """Registrar error 403 o 500."""
        action = 'ERROR_403' if response.status_code == 403 else 'ERROR_500'
        
        # Intentar inferir app desde path
        app_label = self._infer_app_from_request(request)
        if not app_label:
            return
        
        AuditoriaService.log_event(
            app_label=app_label,
            action=action,
            user=request.user if request.user.is_authenticated else None,
            empresa_id=request.session.get('empresa_id'),
            ip_address=self._get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            method=request.method,
            path=request.path,
            querystring=request.META.get('QUERY_STRING', ''),
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
    
    def _log_generic(self, request, response, duration_ms):
        """
        Registrar petición genérica no auditada por vista.
        DECISION: Solo registrar si es biblioteca y es GET (evitar spam de POST no manejados).
        """
        # Solo registrar si es biblioteca y es GET (evitar spam de POST no manejados)
        app_label = self._infer_app_from_request(request)
        if app_label not in ('biblioteca', 'gestiondte') or not is_navigable_request(request):
            return

        # En una fase posterior, app_name/namespace/url_name se obtendrán de
        # request.resolver_match cuando la URL ya haya sido resuelta.
        
        event = AuditoriaService.log_event(
            app_label=app_label,
            action='VIEW',
            user=request.user if request.user.is_authenticated else None,
            empresa_id=request.session.get('empresa_id'),
            ip_address=self._get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            method=request.method,
            path=request.path,
            querystring=request.META.get('QUERY_STRING', ''),
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        if event is not None:
            resolver_match = getattr(request, 'resolver_match', None)
            vista_nombre = getattr(request, '_audit_vista_nombre', None)
            if vista_nombre is None:
                vista_nombre = getattr(resolver_match, 'url_name', None)
            AuditoriaService.update_user_presence(request, app_label, vista_nombre)
    
    def _infer_app_from_path(self, path):
        """Inferir app desde path (ej: /biblioteca/... -> biblioteca)."""
        parts = path.strip('/').split('/')
        if parts and parts[0] == 'biblioteca':
            return 'biblioteca'
        return None

    def _infer_app_from_request(self, request):
        resolver_match = getattr(request, 'resolver_match', None)
        resolver_app = getattr(resolver_match, 'app_name', None) or getattr(resolver_match, 'namespace', None)
        if resolver_app == 'gestion_dte':
            return 'gestiondte'
        if resolver_app == 'biblioteca':
            return 'biblioteca'
        return self._infer_app_from_path(request.path)
    
    def _get_client_ip(self, request):
        """Extraer IP real del cliente."""
        return get_client_ip(request)
