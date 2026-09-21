from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from typing import cast

from access_control.decorators import verificar_permiso
from access_control.models import Permiso, Vista
from access_control.views import VerificarPermisoMixin

from .forms import GestionDTEConnectionRoleForm
from .models import GestionDTEConnectionRole
from .services.base_dte_schema import BaseDTESchemaInstallError, install_base_dte_schema
from .services.connection_roles import (
    get_gestiondte_connection,
    get_gestiondte_connection_status,
    get_gestiondte_mysql_connection,
)


class GestionDTEConnectionRoleView(VerificarPermisoMixin, LoginRequiredMixin, View):
    template_name = 'gestiondte/connection_roles.html'
    vista_nombre = 'Gestion DTE - Conexiones SQL'
    permiso_requerido = 'ingresar'
    verificar_vicmeas_en_dispatch = False

    def _role_instances(self):
        existing = {
            item.role: item
            for item in GestionDTEConnectionRole.objects.select_related(
                'mysql_connection', 'mysql_connection__empresa'
            )
        }
        return [
            (role, label, existing.get(role))
            for role, label in GestionDTEConnectionRole.ROLE_CHOICES
        ]

    def _context(self, forms):
        status = get_gestiondte_connection_status()
        vista = Vista.objects.filter(nombre=self.vista_nombre).first()
        empresa_id = self.request.session.get('empresa_id') if hasattr(self, 'request') else None
        roles = cast(list[dict[str, object]], status['roles'])
        can_install_base_dte = bool(
            vista
            and empresa_id
            and Permiso.objects.filter(
                usuario=self.request.user,
                empresa_id=empresa_id,
                vista=vista,
                supervisor=True,
            ).exists()
            and any(
                item['role'] == 'serverbasedte'
                and item['status'] == 'configured'
                and item['source_type'] == 'MYSQL_CONFIG'
                for item in roles
            )
        )
        return {
            'role_forms': forms,
            'connection_status': status,
            'can_install_base_dte': can_install_base_dte,
            'vista_nombre': self.vista_nombre,
        }

    @method_decorator(verificar_permiso(vista_nombre, 'ingresar'))
    def get(self, request):
        forms = []
        for role, label, instance in self._role_instances():
            form = GestionDTEConnectionRoleForm(
                prefix=f'role-{role}',
                instance=instance or GestionDTEConnectionRole(role=role),
            )
            forms.append({'role': role, 'label': label, 'form': form})
        return render(request, self.template_name, self._context(forms))

    @method_decorator(verificar_permiso(vista_nombre, 'modificar'))
    def post(self, request):
        forms = []
        for role, label, instance in self._role_instances():
            form = GestionDTEConnectionRoleForm(
                request.POST,
                prefix=f'role-{role}',
                instance=instance or GestionDTEConnectionRole(role=role),
            )
            forms.append({'role': role, 'label': label, 'form': form})

        if not all(item['form'].is_valid() for item in forms):
            return render(request, self.template_name, self._context(forms), status=400)

        with transaction.atomic():
            for item in forms:
                item['form'].save()
        messages.success(request, 'La configuración de conexiones SQL fue guardada.')
        return redirect(reverse('gestion_dte:connection_roles'))


@method_decorator(
    verificar_permiso('Gestion DTE - Conexiones SQL', 'supervisor'),
    name='dispatch',
)
class BaseDTESchemaInstallView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            source = get_gestiondte_connection('serverbasedte')
            if source['type'] != 'MYSQL_CONFIG':
                messages.info(
                    request,
                    'Base DTE utiliza una base administrada por Django; no requiere creación manual de estructura.',
                )
                return redirect('gestion_dte:connection_roles')

            connection_config = get_gestiondte_mysql_connection('serverbasedte')
            install_base_dte_schema(connection_config)
            messages.success(request, 'Estructura Base DTE procesada correctamente.')
        except Exception:
            messages.error(request, 'No se pudo procesar la estructura Base DTE.')
        return redirect('gestion_dte:connection_roles')