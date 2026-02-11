from access_control.models import Empresa, Permiso


def set_empresa_activa_en_sesion(request, empresa):
    request.session["empresa_id"] = empresa.id
    request.session["empresa_codigo"] = empresa.codigo
    request.session["empresa_nombre"] = f"{empresa.codigo} - {empresa.descripcion or 'Sin descripción'}"


def get_empresas_usuario(user):
    return Empresa.objects.filter(permiso__usuario=user).distinct()


def resolve_post_login(request, user):
    empresas = get_empresas_usuario(user)
    count = empresas.count()
    if count == 0:
        return "NONE", None
    if count == 1:
        return "ONE", empresas.first()
    return "MANY", None
