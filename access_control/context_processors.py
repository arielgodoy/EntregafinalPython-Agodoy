# access_control/context_processors.py
from access_control.models import Empresa, Permiso, Vista
from access_control.services.access_requests import is_user_mail_enabled
from access_control.services.empresa_activa import get_empresas_usuario


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
        return {'empresas': get_empresas_usuario(request.user)}
    return {}


def auditoria_disponible(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"puede_auditar_biblioteca": False, "puede_auditar_gestiondte": False}

    nombres = {
        "puede_auditar_biblioteca": "Auditoría - Biblioteca",
        "puede_auditar_gestiondte": "Auditoría - Gestión DTE",
    }
    vistas = {
        vista.nombre: vista.id
        for vista in Vista.objects.filter(nombre__in=nombres.values())
    }
    permisos = set(Permiso.objects.filter(
        usuario=request.user,
        vista_id__in=vistas.values(),
        ingresar=True,
    ).values_list("vista__nombre", flat=True))
    return {key: nombre in permisos for key, nombre in nombres.items()}