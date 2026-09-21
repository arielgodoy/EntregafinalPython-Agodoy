from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View

from access_control.decorators import verificar_permiso
from access_control.views import VerificarPermisoMixin

from .forms import GestionDTEConnectionRoleForm
from .models import GestionDTEConnectionRole
from .services.connection_roles import get_gestiondte_connection_status


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
        return {
            'role_forms': forms,
            'connection_status': get_gestiondte_connection_status(),
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