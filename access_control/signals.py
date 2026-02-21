from django.conf import settings
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.apps import apps


@receiver(post_migrate)
def _maybe_seed_access_control_vistas(sender, **kwargs):
    # Evitar ejecución si la app no está instalada o si la opción no está activada
    if not apps.is_installed("access_control"):
        return
    if not getattr(settings, "ACCESS_CONTROL_AUTO_SEED_VISTAS", False):
        return

    # Importar de forma local para evitar dependencias en import time
    try:
        from access_control.management.commands.seed_vistas import VISTAS
        from access_control.models import Vista
    except Exception:
        return

    for v in VISTAS:
        Vista.objects.get_or_create(nombre=v["nombre"], defaults={"descripcion": v.get("descripcion", "")})
