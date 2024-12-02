from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from .models import Permiso

def verificar_permiso(vista_nombre, permiso_requerido):
    def decorator(view_func):
        def _wrapped_view(request, *args, **kwargs):
            empresa_id = request.session.get('empresa_id')
            if not empresa_id:
                return redirect('seleccionar_empresa')  # Redirige si no hay empresa seleccionada

            permiso = Permiso.objects.filter(
                usuario=request.user,
                empresa_id=empresa_id,
                vista__nombre=vista_nombre
            ).first()

            if not permiso or not getattr(permiso, permiso_requerido, False):
                return HttpResponseForbidden("No tienes permisos suficientes.")

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
