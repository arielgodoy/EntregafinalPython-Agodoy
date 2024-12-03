from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from .models import Permiso, Vista

def verificar_permiso(vista_nombre, permiso_requerido):
    def decorator(view_func):
        def _wrapped_view(request, *args, **kwargs):
            empresa_id = request.session.get("empresa_id")
            if not empresa_id:
                return redirect("seleccionar_empresa")  # Redirige si no hay empresa seleccionada
            
            # Verificar si la vista existe en el modelo Vista
            vista, created = Vista.objects.get_or_create(nombre=vista_nombre)
            if created:
                # Opcional: agregar una descripción inicial
                vista.descripcion = f"Descripción inicial de la vista: {vista_nombre}"
                vista.save()

            print(f"Verificando permisos para la vista: {vista_nombre}")

            # Verificar permisos
            permiso = Permiso.objects.filter(
                usuario=request.user,
                empresa_id=empresa_id,
                vista__nombre=vista_nombre
            ).first()

            if not permiso or not getattr(permiso, permiso_requerido, False):
                # Renderiza un template para el acceso denegado
                empresa_nombre = f"{empresa_id}"  # Si tienes un modelo Empresa, puedes obtener el nombre aquí
                return render(
                    request,
                    'access_control/403_forbidden.html',
                    {'vista_nombre': vista_nombre, 'empresa_nombre': empresa_nombre},
                    status=403
                )

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
