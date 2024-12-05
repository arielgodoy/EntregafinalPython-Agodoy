# access_control/context_processors.py
from access_control.models import Empresa

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
