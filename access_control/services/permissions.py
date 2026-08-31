from django.contrib.auth.models import User

from access_control.models import Permiso, UsuarioPerfilEmpresa, Vista


ICMEAS_FIELDS = (
    "ingresar",
    "crear",
    "modificar",
    "eliminar",
    "autorizar",
    "supervisor",
)


def get_valid_users_for_empresa(empresa):
    """Return the compatibility union of assigned and permission-bearing users."""
    assigned_user_ids = UsuarioPerfilEmpresa.objects.filter(empresa=empresa).values("usuario_id")
    permission_user_ids = Permiso.objects.filter(empresa=empresa).values("usuario_id")
    return User.objects.filter(id__in=assigned_user_ids.union(permission_user_ids)).order_by("username")


def user_has_permission_for_empresa(*, user, empresa, vista_nombre, accion):
    """Check an existing ICMEAS permission for an explicit company without side effects."""
    return user_has_permission(
        user=user,
        empresa=empresa,
        vista=vista_nombre,
        accion=accion,
    )


def user_has_permission(*, user, empresa, vista, accion):
    if accion not in ICMEAS_FIELDS:
        raise ValueError("Acción ICMEAS no válida.")

    if isinstance(vista, str):
        vista = Vista.objects.filter(nombre=vista).first()
    if vista is None:
        return False

    permiso = Permiso.objects.filter(
        usuario=user,
        empresa=empresa,
        vista=vista,
    ).first()
    if permiso is None:
        return False

    if permiso.supervisor:
        return True
    return bool(getattr(permiso, accion, False))
