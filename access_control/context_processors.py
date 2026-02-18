# access_control/context_processors.py
from access_control.models import Empresa, Permiso
from access_control.services.access_requests import is_user_mail_enabled


def global_context(request):
    """
    Context processor para añadir el usuario, la empresa seleccionada y
    el flag `mail_enabled` al contexto de las plantillas.
    """
    empresa_seleccionada = None
    if getattr(request, 'user', None) and request.user.is_authenticated:
        empresa_id = request.session.get('empresa_id')
        if empresa_id:
            empresa_seleccionada = Empresa.objects.filter(pk=empresa_id).first()

    mail_enabled = False
    try:
        mail_enabled = bool(is_user_mail_enabled(request.user)) if getattr(request, 'user', None) else False
    except Exception:
        # No queremos que un fallo en el context processor rompa el render
        mail_enabled = False

    return {
        'empresa_seleccionada': empresa_seleccionada,
        'mail_enabled': mail_enabled,
    }
def empresas_disponibles(request):
    if request.user.is_authenticated:
        permisos = Permiso.objects.filter(usuario=request.user).select_related('empresa')
        empresas = Empresa.objects.filter(id__in=permisos.values('empresa'))
        return {'empresas': empresas}
    return {}