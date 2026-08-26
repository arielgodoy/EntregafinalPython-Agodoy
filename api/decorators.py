from functools import wraps

from django.http import JsonResponse

from api.authentication import InvalidApiAuthentication, resolve_api_identity
from api.company_context import InvalidApiEmpresa, resolve_api_empresa
from access_control.services.permissions import user_has_permission


def _authentication_error_response():
    response = JsonResponse({"detail": "Autenticación API requerida."}, status=401)
    response["WWW-Authenticate"] = "Bearer"
    return response


def require_api_authentication(view_func):
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        try:
            request.api_identity = resolve_api_identity(request)
        except InvalidApiAuthentication:
            return _authentication_error_response()
        return view_func(request, *args, **kwargs)

    return wrapped_view


def require_api_empresa(view_func):
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        try:
            request.api_empresa = resolve_api_empresa(request, request.api_identity)
        except InvalidApiEmpresa as exc:
            return JsonResponse({"detail": exc.detail}, status=exc.status)
        return view_func(request, *args, **kwargs)

    return wrapped_view


def require_api_permission(vista, permiso):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if not user_has_permission(
                user=request.api_identity.user,
                empresa=request.api_empresa,
                vista=vista,
                accion=permiso,
            ):
                return JsonResponse(
                    {"detail": "No tiene permisos para acceder a este recurso."},
                    status=403,
                )
            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator
