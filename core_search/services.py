from django.db.models import Exists, OuterRef, Q
from django.urls import reverse

from access_control.models import Permiso
from .models import SearchPageIndex


def search_pages_for_user(user, empresa_id, q, limit=10):
    if not empresa_id:
        return []

    qs = SearchPageIndex.objects.filter(is_active=True).select_related("vista")

    if q:
        qs = qs.filter(
            Q(default_label__icontains=q)
            | Q(keywords__icontains=q)
            | Q(vista__nombre__icontains=q)
        )

    perm_exists = Permiso.objects.filter(
        usuario_id=user.id,
        empresa_id=empresa_id,
        vista_id=OuterRef("vista_id"),
    ).filter(Q(ingresar=True) | Q(supervisor=True))

    qs = qs.annotate(can_open=Exists(perm_exists)).filter(can_open=True)
    qs = qs.order_by("order", "default_label")[:limit]

    results = []
    for item in qs:
        try:
            url = reverse(item.url_name, kwargs=item.url_kwargs_json or None)
        except Exception:
            continue

        results.append(
            {
                "key": item.key,
                "label_key": item.label_key,
                "default_label": item.default_label,
                "group_key": item.group_key,
                "url": url,
            }
        )

    return results
