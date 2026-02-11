from django.db.models import Count

from control_de_proyectos.models import Proyecto


ESTADO_EN_EJECUCION = "EN_EJECUCION"
ESTADO_EN_COTIZACION = "EN_COTIZACION"
ESTADO_TERMINADO = "TERMINADO"
ESTADO_OTROS = "OTROS"

LABEL_KEYS = {
    ESTADO_EN_EJECUCION: "control_operacional.estado.en_ejecucion",
    ESTADO_EN_COTIZACION: "control_operacional.estado.en_cotizacion",
    ESTADO_TERMINADO: "control_operacional.estado.terminado",
    ESTADO_OTROS: "control_operacional.estado.otros",
}

BUCKET_ORDER = [
    ESTADO_EN_EJECUCION,
    ESTADO_EN_COTIZACION,
    ESTADO_TERMINADO,
    ESTADO_OTROS,
]


def get_proyectos_activos_por_estado(empresa_id):
    labels_keys = [LABEL_KEYS[estado] for estado in BUCKET_ORDER]
    if not empresa_id:
        return {"labels_keys": labels_keys, "series": [0, 0, 0, 0]}

    base_qs = Proyecto.objects.filter(empresa_interna_id=empresa_id, activo=True)
    counts = {estado: 0 for estado in BUCKET_ORDER}

    for row in base_qs.values("estado").annotate(total=Count("id")):
        estado = row["estado"]
        total = row["total"]
        if estado in (ESTADO_EN_EJECUCION, ESTADO_EN_COTIZACION, ESTADO_TERMINADO):
            counts[estado] += total
        else:
            counts[ESTADO_OTROS] += total

    return {
        "labels_keys": labels_keys,
        "series": [counts[estado] for estado in BUCKET_ORDER],
    }
