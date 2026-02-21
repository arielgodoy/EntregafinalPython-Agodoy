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

                # Intentar obtener la vista por nombre exacto. Si no existe,
                # buscar por sufijo (ej. 'Control de Acceso - Maestro Usuarios' <-> 'Maestro Usuarios')
                vista = Vista.objects.filter(nombre=vista_nombre).first()
                if not vista:
                    # Intentar emparejar por la parte después del prefijo ' - '
                    suffix = vista_nombre.split(' - ')[-1]
                    vista = Vista.objects.filter(nombre__icontains=suffix).first()
                # NO reutilizar permisos existentes de otras vistas como fallback.
                # Intentar un fallback seguro: si la URL/resolver tiene un
                # `url_name` (p.ej. 'system_config'), buscar una `Vista`
                # con ese nombre interno y usarla si existe. Esto mantiene
                # compatibilidad con tests que crean Vistas usando nombres
                # internos sin conceder permisos por coincidencia entre
                # vistas no relacionadas.
                if not vista:
                    try:
                        resolver = getattr(request, 'resolver_match', None)
                        url_name = getattr(resolver, 'url_name', None) if resolver is not None else None
                        if url_name:
                            # Intentar match exacto con el nombre interno
                            vista = Vista.objects.filter(nombre=url_name).first()
                            if not vista:
                                # Probar variantes eliminando sufijos comunes de acciones
                                for suf in ('_edit', '_create', '_update', '_list', '_detail', '_delete', '_test_outgoing', '_send_test', '_test'):
                                    if url_name.endswith(suf):
                                        candidate = url_name[: -len(suf)]
                                        vista = Vista.objects.filter(nombre=candidate).first()
                                        if vista:
                                            break
                    except Exception:
                        pass
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
                # Mapeos explícitos entre nombres legibles y nombres internos
                # usados por seeds/migrations/tests. Esto evita reusar permisos
                # arbitrarios pero permite compatibilidad con fixtures que
                # crean permisos sobre nombres internos (p.ej. 'auth_invite').
                VISTA_ALIASES = {
                    'Control de Acceso - Invitar Usuario': ['auth_invite', 'invitaciones'],
                    'Settings - Configuracion de Empresa': ['company_config'],
                    'Settings - Emails Acounts': ['email_accounts'],
                    'Settings - Configuración del Sistema': ['system_config', 'system_config_test_outgoing', 'system_config_send_test'],
                }
                # Si no hay permiso directo para la `vista` resuelta, intentar
                # empatar por nombres internos/aliases o por resolver.url_name.
                if not permiso:
                    try:
                        resolver = getattr(request, 'resolver_match', None)
                        url_name = getattr(resolver, 'url_name', None) if resolver is not None else None
                        candidates = [vista_nombre]
                        # Añadir aliases específicos si existen
                        candidates += VISTA_ALIASES.get(vista_nombre, [])
                        if url_name:
                            candidates.append(url_name)
                            for suf in ('_edit', '_create', '_update', '_list', '_detail', '_delete', '_test_outgoing', '_send_test', '_test'):
                                if url_name.endswith(suf):
                                    candidates.append(url_name[: -len(suf)])
                    except Exception:
                        candidates = [vista_nombre]

                    permiso = Permiso.objects.filter(
                        usuario=request.user,
                        empresa=empresa,
                        vista__nombre__in=candidates,
                    ).select_related('vista').first()
                    if permiso:
                        vista = permiso.vista
                # Si no hay permiso directo para la `vista` resuelta, intentar
                # buscar un permiso existente usando el nombre interno de la URL
                # (p.ej. 'company_config') o variantes sin sufijos. Esto solo
                # reutiliza permisos que pertenecen al mismo usuario/empresa y
                # cuya `vista.nombre` coincide con alguno de los candidatos,
                # evitando así el fallback inseguro previo que reutilizaba
                # permisos arbitrarios.
                if not permiso:
                    try:
                        resolver = getattr(request, 'resolver_match', None)
                        url_name = getattr(resolver, 'url_name', None) if resolver is not None else None
                        candidates = [vista_nombre]
                        if url_name:
                            candidates.append(url_name)
                            for suf in ('_edit', '_create', '_update', '_list', '_detail', '_delete', '_test_outgoing', '_send_test', '_test'):
                                if url_name.endswith(suf):
                                    candidates.append(url_name[: -len(suf)])
                    except Exception:
                        candidates = [vista_nombre]

                    permiso = Permiso.objects.filter(
                        usuario=request.user,
                        empresa=empresa,
                        vista__nombre__in=candidates,
                    ).select_related('vista').first()
                    if permiso:
                        vista = permiso.vista
                # Si no existe permiso para la `vista` buscada, intentar reutilizar
                # cualquier permiso existente del mismo usuario y empresa. Esto
                # cubre tests que crean Vistas con nombres internos (p.ej. 'system_config')
                # distintos del nombre legible usado en el código ('Settings - Configuración del Sistema').
                # Si no hay permiso específico, se creará más abajo un permiso
                # vacío (deny-by-default) o un permiso auto-concedido para vistas
                # de usuario listadas en `vistas_auto_permiso`.

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
                        # Actualizar permiso existente para vistas de usuario
                        permiso.modificar = True
                        permiso.ingresar = True
                        permiso.save(update_fields=['modificar', 'ingresar'])
                elif not permiso:
                    # Crear permiso sin acceso para otras vistas
                    logger = logging.getLogger(__name__)
                    logger.warning(
                            "access_control: creating fallback empty Permiso for user=%s empresa=%s vista=%s (all flags False) resolver.url_name=%s",
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
