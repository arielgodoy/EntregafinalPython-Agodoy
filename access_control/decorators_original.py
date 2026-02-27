from django.http import HttpResponseForbidden,JsonResponse
from django.shortcuts import redirect, render
import logging
from .models import Vista, Permiso, Empresa



class PermisoDenegadoJson(Exception):
    def __init__(self, mensaje="No tienes permiso para esta acción."):
        self.mensaje = mensaje
        super().__init__(self.mensaje)


def _build_access_request_context(request, vista_nombre, mensaje):
    """Construir contexto para página 403."""
    # Reutilizar el builder central (incluye pending_access_requests, staff_grant_url, etc.)
    from django.contrib.auth.models import User
    try:
        from access_control.services.access_requests import build_access_request_context as _build
        contexto = _build(request, vista_nombre, mensaje)
    except Exception:
        # Fallback ligero si hay algún problema de import/ciclo
        empresa_id = request.session.get("empresa_id")
        empresa_nombre = request.session.get("empresa_nombre", "Empresa no identificada")
        contexto = {
            "mensaje": mensaje,
            "vista_nombre": vista_nombre,
            "empresa_nombre": empresa_nombre,
            "staff_grant_url": None,
            "empresa_id": empresa_id or "",
            "mail_enabled": False,
            "pending_access_requests": [],
        }

    # Añadir lista de usuarios con permiso supervisor (mismo comportamiento previo)
    usuarios_con_permiso = []
    empresa_id = request.session.get("empresa_id")
    if empresa_id:
        try:
            empresa = Empresa.objects.get(id=empresa_id)
            vista = Vista.objects.filter(nombre=vista_nombre).first()
            if vista:
                usuarios_con_permiso = list(
                    User.objects.filter(
                        permiso__empresa=empresa,
                        permiso__vista=vista,
                        permiso__supervisor=True,
                    )
                    .distinct()
                    .values_list("username", flat=True)
                )
        except Exception:
            pass

    contexto["usuarios_con_permiso"] = usuarios_con_permiso
    return contexto


def verificar_permiso(vista_nombre, permiso_requerido):
    def decorator(view_func):
        def _wrapped_view(request, *args, **kwargs):
            try:
                empresa_id = request.session.get("empresa_id")
                if not empresa_id:
                    return redirect("access_control:seleccionar_empresa")

                # Intentar obtener la vista por nombre EXACTO.
                vista = Vista.objects.filter(nombre=vista_nombre).first()

                # Si aún no existe, crear la vista con el nombre completo
                if not vista:
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

                # Auto-crear o actualizar permisos para vistas de usuario
                vistas_auto_permiso = ["Settings - Theme preference", "Accounts - Editar Perfil"]
                if vista_nombre in vistas_auto_permiso:
                    if not permiso:
                        permiso = Permiso.objects.create(
                            usuario=request.user,
                            empresa=empresa,
                            vista=vista,
                            ingresar=True,
                            crear=False,
                            modificar=True,
                            eliminar=False,
                            autorizar=False,
                            supervisor=False
                        )
                    elif not permiso.modificar:
                        permiso.modificar = True
                        permiso.ingresar = True
                        permiso.save(update_fields=['modificar', 'ingresar'])
                elif not permiso:
                    # Crear permiso sin acceso para otras vistas (deny-by-default)
                    logger = logging.getLogger(__name__)
                    logger.warning(
                            "access_control: creating fallback empty Permiso for user=%s empresa=%s vista=%s resolver.url_name=%s",
                            getattr(request.user, 'username', None),
                            getattr(empresa, 'id', None),
                            getattr(vista, 'nombre', vista_nombre),
                            getattr(getattr(request, 'resolver_match', None), 'url_name', None),
                        )
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
            
            except PermisoDenegadoJson as e:
                # Detectar request AJAX/JSON
                is_ajax = (
                    request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest' or
                    request.headers.get("x-requested-with") == "XMLHttpRequest" or
                    request.content_type == "application/json" or
                    "application/json" in request.headers.get("accept", "")
                )
                
                if is_ajax:
                    return JsonResponse({"success": False, "error": str(e)}, status=403)
                
                contexto = _build_access_request_context(request, vista_nombre, str(e))
                return render(request, "access_control/403_forbidden.html", contexto, status=403)
        
        return _wrapped_view
    return decorator
