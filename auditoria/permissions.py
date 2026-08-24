from access_control.models import Empresa, Permiso, Vista


PERMISSION_FLAGS = (
    "ingresar",
    "crear",
    "modificar",
    "eliminar",
    "autorizar",
    "supervisor",
)


def get_auditable_company_ids(user, vista_nombre, permiso="ingresar"):
    if permiso not in PERMISSION_FLAGS or not getattr(user, "is_authenticated", False):
        return set()

    return set(
        Permiso.objects.filter(
            usuario=user,
            vista__nombre=vista_nombre,
            **{permiso: True},
        ).values_list("empresa_id", flat=True)
    )


def get_auditable_companies(user, vista_nombre, permiso="ingresar"):
    company_ids = get_auditable_company_ids(user, vista_nombre, permiso)
    return Empresa.objects.filter(id__in=company_ids).order_by("codigo", "id")
