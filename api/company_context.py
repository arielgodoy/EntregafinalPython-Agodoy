from django.core.exceptions import ValidationError

from access_control.models import Empresa


class InvalidApiEmpresa(Exception):
    def __init__(self, detail, status=400):
        self.detail = detail
        self.status = status
        super().__init__(detail)


def _normalize_empresa_codigo(raw_value):
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidApiEmpresa("El parámetro empresa es obligatorio.")

    codigo = raw_value.strip()
    field = Empresa._meta.get_field("codigo")
    try:
        return field.clean(codigo, None)
    except ValidationError as exc:
        raise InvalidApiEmpresa("El parámetro empresa no es válido.") from exc


def resolve_api_empresa(request, identity):
    explicit_codigo = request.GET.get("empresa")
    if identity.auth_mode == "bearer":
        if explicit_codigo is None or not explicit_codigo.strip():
            raise InvalidApiEmpresa("El parámetro empresa es obligatorio.")
        codigo = _normalize_empresa_codigo(explicit_codigo)
    elif explicit_codigo is not None:
        codigo = _normalize_empresa_codigo(explicit_codigo)
    else:
        empresa_id = request.session.get("empresa_id")
        if not empresa_id:
            raise InvalidApiEmpresa("No hay una empresa activa.")
        try:
            return Empresa.objects.get(pk=empresa_id)
        except Empresa.DoesNotExist as exc:
            raise InvalidApiEmpresa("Empresa no encontrada.", status=404) from exc

    try:
        return Empresa.objects.get(codigo=codigo)
    except Empresa.DoesNotExist as exc:
        raise InvalidApiEmpresa("Empresa no encontrada.", status=404) from exc
