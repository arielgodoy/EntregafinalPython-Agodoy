from control_de_proyectos.models import Proyecto


ESTADO_EN_EJECUCION = "EN_EJECUCION"
ESTADO_EN_COTIZACION = "EN_COTIZACION"
ESTADO_TERMINADO = "TERMINADO"


def get_proyectos_kpis(empresa_id):
    if not empresa_id:
        return {
            "total_activos": 0,
            "en_ejecucion": 0,
            "en_cotizacion": 0,
            "terminados": 0,
        }

    base_qs = Proyecto.objects.filter(empresa_interna_id=empresa_id, activo=True)
    return {
        "total_activos": base_qs.count(),
        "en_ejecucion": base_qs.filter(estado=ESTADO_EN_EJECUCION).count(),
        "en_cotizacion": base_qs.filter(estado=ESTADO_EN_COTIZACION).count(),
        "terminados": base_qs.filter(estado=ESTADO_TERMINADO).count(),
    }
