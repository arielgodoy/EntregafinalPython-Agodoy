from django.http import HttpResponseForbidden,JsonResponse
from django.shortcuts import redirect, render
from .models import Vista, Permiso, Empresa



class PermisoDenegadoJson(Exception):
    def __init__(self, mensaje="No tienes permiso para esta acción."):
        self.mensaje = mensaje
        super().__init__(self.mensaje)

def verificar_permiso(vista_nombre, permiso_requerido):
    def decorator(view_func):
        def _wrapped_view(request, *args, **kwargs):
            empresa_id = request.session.get("empresa_id")
            if not empresa_id:
                #raise PermisoDenegadoJson("Debes seleccionar una empresa para continuar.")
                return redirect("access_control:seleccionar_empresa")

            vista, _ = Vista.objects.get_or_create(nombre=vista_nombre)

            try:
                empresa = Empresa.objects.get(id=empresa_id)
                # 💾 Guardar nombre en sesión para usarlo luego
                request.session["empresa_nombre"] = f"{empresa.codigo} - {empresa.descripcion or 'Sin descripción'}"
            except Empresa.DoesNotExist:
                raise PermisoDenegadoJson(f"No se encontró la empresa con ID {empresa_id}.")

            permiso = Permiso.objects.filter(
                usuario=request.user,
                empresa=empresa,
                vista=vista
            ).first()

            if not permiso:
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

            if permiso.supervisor:
                return view_func(request, *args, **kwargs)

            if not getattr(permiso, permiso_requerido, False):
                raise PermisoDenegadoJson(f"No tienes permiso para '{permiso_requerido}' en {vista_nombre}.")

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
