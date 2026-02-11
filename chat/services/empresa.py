from django.shortcuts import redirect


def get_empresa_activa_id(request):
    return request.session.get("empresa_id")


def assert_empresa_activa(request):
    empresa_id = get_empresa_activa_id(request)
    if not empresa_id:
        return redirect("access_control:seleccionar_empresa")
    return None
