from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from .models import Vista, Permiso, Empresa

def verificar_permiso(vista_nombre, permiso_requerido):
    def decorator(view_func):
        def _wrapped_view(request, *args, **kwargs):
            empresa_id = request.session.get("empresa_id")
            if not empresa_id:
                return redirect("seleccionar_empresa")  # Redirige si no hay empresa seleccionada
            
            # Verificar si la vista existe en el modelo Vista
            vista, created = Vista.objects.get_or_create(nombre=vista_nombre)
            if created:
                vista.descripcion = f"Descripción inicial de la vista: {vista_nombre}"
                vista.save()
            print(f"Verificando permisos para la vista: {vista_nombre}")

            # Obtener la empresa asociada al ID
            try:
                empresa = Empresa.objects.get(id=empresa_id)
            except Empresa.DoesNotExist:
                return render(
                    request,
                    'access_control/403_forbidden.html',
                    {'vista_nombre': vista_nombre, 'empresa_nombre': "Empresa desconocida"},
                    status=403
                )

            # Verificar si el permiso existe
            permiso = Permiso.objects.filter(
                usuario=request.user,
                empresa=empresa,
                vista=vista
            ).first()

            if not permiso:
                # Crear un permiso inicial con todos los accesos en False
                permiso = Permiso.objects.create(
                    usuario=request.user,
                    empresa=empresa,
                    vista=vista,
                    ingresar=False,
                    crear=False,
                    modificar=False,
                    eliminar=False,
                    autorizar=False,
                    supervisor=False
                )
                print(f"Permiso creado para la vista {vista_nombre} y empresa {empresa.codigo} - {empresa.descripcion or 'Sin descripción'}")

            # Verificar si el usuario tiene el permiso requerido
            if not getattr(permiso, permiso_requerido, False):
                empresa_nombre = f"{empresa.codigo} - {empresa.descripcion or 'Sin descripción'}"
                return render(
                    request,
                    'access_control/403_forbidden.html',
                    {'vista_nombre': vista_nombre, 'empresa_nombre': empresa_nombre},
                    status=403
                )

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
