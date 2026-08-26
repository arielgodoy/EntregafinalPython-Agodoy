from django.http import JsonResponse
from django.views.decorators.http import require_GET

from api.decorators import (
    require_api_authentication,
    require_api_empresa,
    require_api_permission,
)


@require_GET
@require_api_authentication
@require_api_empresa
@require_api_permission("API - Acceso", "ingresar")
def whoami(request):
    identity = request.api_identity
    return JsonResponse({
        "authenticated": True,
        "username": identity.user.get_username(),
        "auth_mode": identity.auth_mode,
        "empresa": request.api_empresa.codigo,
    })
