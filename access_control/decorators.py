from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from .models import Permiso, Empresa

def verificar_permiso(vista_nombre, permiso_requerido):
    def decorator(view_func):
        def _wrapped_view(request, *args, **kwargs):
            empresa_id = request.session.get("empresa_id")
            if not empresa_id:
                return redirect("seleccionar_empresa")  # Redirige si no hay empresa seleccionada
            
            empresa = Empresa.objects.filter(id=empresa_id).first()
            empresa_nombre = empresa.codigo if empresa else "Desconocida"
            
            print(f"Verificando permisos para la vista: {vista_nombre}")

            permiso = Permiso.objects.filter(
                usuario=request.user,
                empresa_id=empresa_id,
                vista__nombre=vista_nombre
            ).first()

            if not permiso or not getattr(permiso, permiso_requerido, False):
                # Renderiza un template para el acceso denegado                
                return render(request, 'access_control/403_forbidden.html', {
                    'vista_nombre': vista_nombre,
                    'empresa_nombre': empresa_nombre,
                }, status=403)

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
