"""Autorizacion global del cambio de contrasena del propio usuario."""
from functools import wraps

from django.http import HttpResponseForbidden

from access_control.models import Permiso


PASSWORD_CHANGE_VIEW_NAME = "Accounts - Cambiar Password"


def user_can_change_password_globally(user):
    if not user or not user.is_authenticated:
        return False
    return Permiso.objects.filter(
        usuario=user,
        vista__nombre=PASSWORD_CHANGE_VIEW_NAME,
        modificar=True,
    ).exists()


def require_global_password_change_permission(view_func):
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not user_can_change_password_globally(request.user):
            return HttpResponseForbidden("No tienes permiso para cambiar tu contrasena.")
        return view_func(request, *args, **kwargs)

    return wrapped_view