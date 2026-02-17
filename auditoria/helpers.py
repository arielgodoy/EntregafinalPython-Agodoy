
import time
from .services import AuditoriaService


def audit_log(
    request,
    action,
    app_label,
    obj=None,
    vista_nombre=None,
    message_key=None,
    meta=None,
    before=None,
    after=None,
    status_code=None,
    duration_ms=None,
):
    """
    Helper para registrar eventos de auditoría desde vistas o servicios.
    
    Args:
        request: HttpRequest
        action (str): 'VIEW', 'CREATE', 'UPDATE', 'DELETE'
        app_label (str): 'biblioteca', etc.
        obj: Instancia del modelo afectado (opcional)
        message_key (str): Clave i18n (opcional)
        meta (dict): Metadata adicional (opcional)
        before (dict): Estado anterior para UPDATE/DELETE (opcional)
        after (dict): Estado posterior para CREATE/UPDATE (opcional)
    
    Marca request._audit_logged = True para evitar duplicación por middleware.
    """
    
    # Marcar request como auditado
    request._audit_logged = True
    
    # Extraer información del objeto si existe
    object_type = None
    object_id = None
    if obj:
        object_type = obj.__class__.__name__
        object_id = str(obj.pk)
    
    # Extraer empresa_id de la sesión
    empresa_id = request.session.get('empresa_id')
    
    # Determinar vista_nombre
    if vista_nombre is None:
        vista_nombre = getattr(request, '_audit_vista_nombre', None)

    # Construir datos del evento
    event_data = {
        'action': action,
        'user': request.user if request.user.is_authenticated else None,
        'empresa_id': empresa_id,
        'object_type': object_type,
        'object_id': object_id,
        'ip_address': _get_client_ip(request),
        'user_agent': request.META.get('HTTP_USER_AGENT', '')[:500],
        'method': request.method,
        'path': request.path,
        'querystring': request.META.get('QUERY_STRING', ''),
        'message_key': message_key,
        'meta': meta,
        'before': before,
        'after': after,
        'vista_nombre': vista_nombre,
    }

    # status_code
    if status_code is None:
        status_code = getattr(request, '_audit_response_status_code', None)
    event_data['status_code'] = status_code

    # duration_ms
    if duration_ms is None:
        start_time = getattr(request, '_audit_start_time', None)
        if start_time is not None:
            duration_ms = int((time.time() - start_time) * 1000)
    event_data['duration_ms'] = duration_ms
    
    # Registrar evento
    AuditoriaService.log_event(app_label=app_label, **event_data)


def _get_client_ip(request):
    """Extraer IP real del cliente."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')
