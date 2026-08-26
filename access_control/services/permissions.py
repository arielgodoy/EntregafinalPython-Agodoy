from access_control.models import Permiso, Vista


def user_has_permission(*, user, empresa, vista, accion):
    if accion not in {
        "ingresar",
        "crear",
        "modificar",
        "eliminar",
        "autorizar",
        "supervisor",
    }:
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
