# access_control/context_processors.py
from access_control.models import Empresa, Permiso

def global_context(request):
    """
    Context processor para añadir el usuario y la empresa seleccionada al contexto de las plantillas.
    """
    empresa_seleccionada = None
    if request.user.is_authenticated:
        empresa_id = request.session.get('empresa_id')
        if empresa_id:
            empresa_seleccionada = Empresa.objects.filter(pk=empresa_id).first()

    return {
        'empresa_seleccionada': empresa_seleccionada,
    }
def empresas_disponibles(request):
    if request.user.is_authenticated:
        permisos = Permiso.objects.filter(usuario=request.user).select_related('empresa')
        empresas = Empresa.objects.filter(id__in=permisos.values('empresa'))
        return {'empresas': empresas}
    return {}