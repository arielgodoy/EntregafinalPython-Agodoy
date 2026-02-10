from django.db import transaction

from access_control.models import Permiso, PerfilAccesoDetalle


def apply_profile_to_user_empresa(user, empresa, perfil, *, assigned_by=None, overwrite=False):
    if perfil is None:
        return

    detalles = PerfilAccesoDetalle.objects.filter(perfil=perfil).select_related('vista')
    if not detalles.exists():
        return

    defaults = None
    with transaction.atomic():
        for detalle in detalles:
            defaults = {
                'ingresar': detalle.ingresar,
                'crear': detalle.crear,
                'modificar': detalle.modificar,
                'eliminar': detalle.eliminar,
                'autorizar': detalle.autorizar,
                'supervisor': detalle.supervisor,
            }
            if overwrite:
                Permiso.objects.update_or_create(
                    usuario=user,
                    empresa=empresa,
                    vista=detalle.vista,
                    defaults=defaults,
                )
            else:
                Permiso.objects.get_or_create(
                    usuario=user,
                    empresa=empresa,
                    vista=detalle.vista,
                    defaults=defaults,
                )
