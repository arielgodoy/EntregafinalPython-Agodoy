from django.views.generic.edit import UpdateView,DeleteView,CreateView
from django.urls import reverse_lazy
from django.contrib.auth.models import User
from django.contrib.auth.models import User as Usuario
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView,FormView
from django.shortcuts import render
from django.utils import timezone
from django.db import transaction

from acounts.models import SystemConfig, EmailAccount, CompanyConfig, UserEmailToken, UserEmailTokenPurpose
from .models import Empresa, Permiso, Vista, UsuarioPerfilEmpresa
from .forms import PermisoForm,PermisoFiltroForm,UsuarioInvitacionForm,UsuarioEditarForm, SystemConfigForm, EmailAccountForm, CompanyConfigForm
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views import View
from django.conf import settings as django_settings
import logging

from .decorators import verificar_permiso, PermisoDenegadoJson
from django.utils.decorators import method_decorator
from acounts.services.email_service import send_email_via_account
from access_control.services.invite import invite_user_flow
#Decorador generar para verificar permispo por mixim
class VerificarPermisoMixin:
    vista_nombre = None
    permiso_requerido = None

    def dispatch(self, request, *args, **kwargs):
        if self.vista_nombre and self.permiso_requerido:
            decorador = verificar_permiso(self.vista_nombre, self.permiso_requerido)
            vista_decorada = decorador(super().dispatch)
            return vista_decorada(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)


class VerificarPermisoSafeMixin(VerificarPermisoMixin):
    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(request, *args, **kwargs)
        except PermisoDenegadoJson as e:
            return self.handle_no_permission(request, str(e))

    def handle_no_permission(self, request, mensaje="No tienes permiso para esta acción."):
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.content_type == "application/json":
            return JsonResponse({"success": False, "error": mensaje}, status=403)

        contexto = {
            "mensaje": mensaje,
            "vista_nombre": getattr(self, "vista_nombre", "Desconocida"),
            "empresa_nombre": request.session.get("empresa_nombre", "No definida"),
        }
        return render(request, "access_control/403_forbidden.html", contexto, status=403)


class EmailAccountVistaRequiredMixin:
    vista_nombre = 'email_accounts'

    def dispatch(self, request, *args, **kwargs):
        if not Vista.objects.filter(nombre=self.vista_nombre).exists():
            messages.error(request, f'NO ENCONTRADO: Vista {self.vista_nombre}')
            if hasattr(self, 'get_form'):
                form = self.get_form()
                context = self.get_context_data(form=form)
            else:
                self.object_list = []
                context = self.get_context_data(object_list=self.object_list)
            return self.render_to_response(context, status=400)
        return super().dispatch(request, *args, **kwargs)


class CompanyConfigVistaRequiredMixin:
    vista_nombre = 'company_config'

    def dispatch(self, request, *args, **kwargs):
        if not Vista.objects.filter(nombre=self.vista_nombre).exists():
            messages.error(request, f'NO ENCONTRADO: Vista {self.vista_nombre}')
            if hasattr(self, 'get_form'):
                form = self.get_form()
                context = self.get_context_data(form=form)
            else:
                self.object_list = []
                context = self.get_context_data(object_list=self.object_list)
            return self.render_to_response(context, status=400)
        return super().dispatch(request, *args, **kwargs)

class PermisosFiltradosView(VerificarPermisoMixin, LoginRequiredMixin, FormView):
    template_name = 'access_control/permisos_filtrados.html'
    form_class = PermisoFiltroForm
    vista_nombre = "Maestro Permisos"
    permiso_requerido = "modificar"
    success_url = reverse_lazy('access_control:permisos_filtrados')    

    def get_initial(self):
        """
        Obtiene los valores iniciales para los campos del formulario.
        Si se enviaron datos en la solicitud GET o POST, los usa para mantener la selección del usuario.
        """
        initial = super().get_initial()                
        usuario_id = self.request.GET.get('usuario') or self.request.POST.get('usuario')
        empresa_id = self.request.GET.get('empresa') or self.request.POST.get('empresa')                
        if usuario_id:
            try:
                initial['usuario'] = User.objects.get(id=usuario_id)
            except User.DoesNotExist:
                initial['usuario'] = User.objects.first()
        else:
            initial['usuario'] = User.objects.first()

        if empresa_id:
            try:
                initial['empresa'] = Empresa.objects.get(id=empresa_id)
            except Empresa.DoesNotExist:
                initial['empresa'] = Empresa.objects.first()
        else:
            initial['empresa'] = Empresa.objects.first()

        print(f"Valores iniciales del formulario: {initial}")
        return initial

    def form_valid(self, form):
        print("Entrando en form_valid")
        usuario = form.cleaned_data.get('usuario')
        empresa = form.cleaned_data.get('empresa')
        print(f"Usuario recibido: {usuario}")
        print(f"Empresa recibida: {empresa}")

        # Filtra los permisos según los datos proporcionados en el formulario
        if usuario and empresa:
            permisos = Permiso.objects.filter(usuario=usuario, empresa=empresa)
            print("Contenido de permisos:", permisos)
        else:
            permisos = None
            print("Usuario o empresa no proporcionados en el formulario.")

        # Agrega los datos filtrados al contexto
        context = self.get_context_data(form=form)
        context['permisos'] = permisos
        context['fields'] = ['ingresar', 'crear', 'modificar', 'eliminar', 'autorizar', 'supervisor']
        return self.render_to_response(context)

    def form_invalid(self, form):
        print("Formulario inválido")        
        print(f"Errores en el formulario: {form.errors}")
        context = self.get_context_data(form=form)
        context['permisos'] = None
        context['fields'] = ['ingresar', 'crear', 'modificar', 'eliminar', 'autorizar', 'supervisor']
        return self.render_to_response(context)



@csrf_exempt
def toggle_permiso(request):
    if request.method == "POST":
        permiso_id = request.POST.get("permiso_id")
        permiso_field = request.POST.get("permiso_field")
        value = request.POST.get("value") == "true"  # Convertir el valor a booleano

        try:
            permiso = Permiso.objects.get(id=permiso_id)
            setattr(permiso, permiso_field, value)
            permiso.save()
            return JsonResponse({"success": True, "new_value": value})
        except Permiso.DoesNotExist:
            return JsonResponse({"success": False, "error": "Permiso no encontrado"})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Método no permitido"})


# def permisos_filtrados_view(request):
#     form = PermisoFiltroForm(request.GET or None)
#     permisos = None

#     if form.is_valid():
#         usuario = form.cleaned_data.get('usuario')
#         empresa = form.cleaned_data.get('empresa')
#         if usuario and empresa:
#             permisos = Permiso.objects.filter(usuario=usuario, empresa=empresa)

#     context = {
#         'form': form,
#         'permisos': permisos,
#         'fields': ['ingresar', 'crear', 'modificar', 'eliminar', 'autorizar', 'supervisor'],
#     }
#     return render(request, 'access_control/permisos_filtrados.html', context)
class CopyPermisosView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Maestro Permisos"
    permiso_requerido = "supervisor"

    def post(self, request, *args, **kwargs):
        origen_usuario_id = request.POST.get("origen_usuario")
        origen_empresa_id = request.POST.get("origen_empresa")
        destino_usuario_id = request.POST.get("destino_usuario")
        destino_empresa_id = request.POST.get("destino_empresa")
        try:
            origen_usuario = Usuario.objects.get(id=origen_usuario_id)
            origen_empresa = Empresa.objects.get(id=origen_empresa_id)
            destino_usuario = Usuario.objects.get(id=destino_usuario_id)
            destino_empresa = Empresa.objects.get(id=destino_empresa_id)

            permisos_actuales = Permiso.objects.filter(usuario=origen_usuario, empresa=origen_empresa)
            for permiso in permisos_actuales:
                Permiso.objects.update_or_create(
                    usuario=destino_usuario,
                    empresa=destino_empresa,
                    vista=permiso.vista,
                    defaults={
                        'ingresar': permiso.ingresar,
                        'crear': permiso.crear,
                        'modificar': permiso.modificar,
                        'eliminar': permiso.eliminar,
                        'autorizar': permiso.autorizar,
                        'supervisor': permiso.supervisor,
                    }
                )
            return JsonResponse({"success": True})
        except Usuario.DoesNotExist:
            return JsonResponse({"success": False, "error": "Usuario no encontrado."})
        except Empresa.DoesNotExist:
            return JsonResponse({"success": False, "error": "Empresa no encontrada."})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

class VistaListaView(VerificarPermisoMixin,LoginRequiredMixin, ListView):
    model = Vista
    template_name = 'access_control/vistas_lista.html'
    context_object_name = 'vistas'
    vista_nombre = "Maestro Vistas"
    permiso_requerido = "ingresar"

class VistaCrearView(VerificarPermisoMixin,LoginRequiredMixin, CreateView):
    model = Vista
    fields = ['nombre', 'descripcion']
    template_name = 'access_control/vistas_form.html'
    success_url = reverse_lazy('access_control:vistas_lista')
    vista_nombre = "Maestro Vistas"
    permiso_requerido = "crear"

class VistaEditarView(VerificarPermisoMixin,LoginRequiredMixin, UpdateView):
    model = Vista
    fields = ['nombre', 'descripcion']
    template_name = 'access_control/vistas_form.html'
    success_url = reverse_lazy('access_control:vistas_lista')
    vista_nombre = "Maestro Vistas"
    permiso_requerido = "editar"

class VistaEliminarView(VerificarPermisoMixin,LoginRequiredMixin, DeleteView):
    model = Vista
    template_name = 'access_control/vista_confirmar_eliminar.html'
    success_url = reverse_lazy('access_control:vistas_lista')
    vista_nombre = "Maestro Vistas"
    permiso_requerido = "eliminar"



class PermisoListaView(VerificarPermisoMixin,LoginRequiredMixin, ListView):
    model = Permiso
    template_name = 'access_control/permisos_lista.html'
    context_object_name = 'permisos'
    vista_nombre = "Maestro Permisos"
    permiso_requerido = "ingresar"

class PermisoCrearView(LoginRequiredMixin, CreateView):
    model = Permiso
    fields = ['usuario', 'empresa', 'vista', 'ingresar', 'crear', 'modificar', 'eliminar', 'autorizar', 'supervisor']
    template_name = 'access_control/permisos_form.html'
    success_url = reverse_lazy('access_control:permisos_lista')
    vista_nombre = "Maestro Permisos"
    permiso_requerido = "crear"

class PermisoEditarView(LoginRequiredMixin, UpdateView):
    model = Permiso
    fields = ['usuario', 'empresa', 'vista', 'ingresar', 'crear', 'modificar', 'eliminar', 'autorizar', 'supervisor']
    template_name = 'access_control/permisos_form.html'
    success_url = reverse_lazy('access_control:permisos_lista')
    vista_nombre = "Maestro Permisos"
    permiso_requerido = "modificar"

class PermisoEliminarView(LoginRequiredMixin, DeleteView):
    model = Permiso
    template_name = 'access_control/permiso_confirmar_eliminar.html'
    success_url = reverse_lazy('access_control:permisos_lista')
    vista_nombre = "Maestro Permisos"
    permiso_requerido = "eliminar"



class EmpresaListaView(VerificarPermisoMixin,LoginRequiredMixin, ListView):
    model = Empresa
    template_name = 'access_control/empresas_lista.html'
    context_object_name = 'empresas'
    vista_nombre = "Maestro Empresas"
    permiso_requerido = "ingresar"

class EmpresaCrearView(VerificarPermisoMixin,LoginRequiredMixin, CreateView):
    model = Empresa
    fields = ['codigo', 'descripcion']
    template_name = 'access_control/empresas_form.html'
    success_url = reverse_lazy('access_control:empresas_lista')
    vista_nombre = "Maestro Empresas"
    permiso_requerido = "crear"


class EmpresaEditarView(VerificarPermisoMixin,LoginRequiredMixin, UpdateView):
    model = Empresa
    fields = ['codigo', 'descripcion']
    template_name = 'access_control/empresas_form.html'
    success_url = reverse_lazy('access_control:empresas_lista')
    vista_nombre = "Maestro Empresas"
    permiso_requerido = "modificar"

class EmpresaEliminarView(VerificarPermisoMixin,LoginRequiredMixin, DeleteView):
    model = Empresa
    template_name = 'access_control/empresa_confirmar_eliminar.html'
    success_url = reverse_lazy('access_control:empresas_lista')
    vista_nombre = "Maestro Empresas"
    permiso_requerido = "eliminar"


class SystemConfigUpdateView(VerificarPermisoMixin, LoginRequiredMixin, UpdateView):
    model = SystemConfig
    form_class = SystemConfigForm
    template_name = 'access_control/settings_system.html'
    success_url = reverse_lazy('access_control:system_config')
    vista_nombre = 'system_config'
    permiso_requerido = 'modificar'

    def _get_or_create_active_config(self):
        config = SystemConfig.objects.filter(is_active=True).first()
        if not config:
            config = SystemConfig.objects.create(
                is_active=True,
                public_base_url='',
                default_from_email='',
                default_from_name='',
            )
        return config

    def dispatch(self, request, *args, **kwargs):
        if not Vista.objects.filter(nombre='system_config').exists():
            messages.error(request, 'NO ENCONTRADO: Vista system_config')
            config = self._get_or_create_active_config()
            form = self.get_form_class()(instance=config)
            return render(request, self.template_name, {'form': form}, status=400)
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        return self._get_or_create_active_config()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        empresa_id = self.request.session.get("empresa_id")
        permiso = None
        if empresa_id:
            permiso = Permiso.objects.filter(
                usuario=self.request.user,
                empresa_id=empresa_id,
                vista__nombre=self.vista_nombre
            ).first()
        context['puede_probar_email'] = bool(permiso and (permiso.supervisor or permiso.crear))
        return context


class EmailAccountListView(EmailAccountVistaRequiredMixin, VerificarPermisoSafeMixin, LoginRequiredMixin, ListView):
    model = EmailAccount
    template_name = 'access_control/settings_email_accounts_list.html'
    context_object_name = 'email_accounts'
    vista_nombre = 'email_accounts'
    permiso_requerido = 'ingresar'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        empresa_id = self.request.session.get("empresa_id")
        permiso = None
        if empresa_id:
            permiso = Permiso.objects.filter(
                usuario=self.request.user,
                empresa_id=empresa_id,
                vista__nombre=self.vista_nombre
            ).first()
        context['puede_crear'] = bool(permiso and (permiso.supervisor or permiso.crear))
        context['puede_modificar'] = bool(permiso and (permiso.supervisor or permiso.modificar))
        return context


class EmailAccountCreateView(EmailAccountVistaRequiredMixin, VerificarPermisoSafeMixin, LoginRequiredMixin, CreateView):
    model = EmailAccount
    form_class = EmailAccountForm
    template_name = 'access_control/settings_email_accounts_form.html'
    success_url = reverse_lazy('access_control:email_accounts_list')
    vista_nombre = 'email_accounts'
    permiso_requerido = 'crear'


class EmailAccountUpdateView(EmailAccountVistaRequiredMixin, VerificarPermisoSafeMixin, LoginRequiredMixin, UpdateView):
    model = EmailAccount
    form_class = EmailAccountForm
    template_name = 'access_control/settings_email_accounts_form.html'
    success_url = reverse_lazy('access_control:email_accounts_list')
    vista_nombre = 'email_accounts'
    permiso_requerido = 'modificar'


class CompanyConfigListView(CompanyConfigVistaRequiredMixin, VerificarPermisoSafeMixin, LoginRequiredMixin, ListView):
    model = Empresa
    template_name = 'access_control/settings_company_list.html'
    context_object_name = 'empresas'
    vista_nombre = 'company_config'
    permiso_requerido = 'modificar'


class CompanyConfigUpdateView(CompanyConfigVistaRequiredMixin, VerificarPermisoSafeMixin, LoginRequiredMixin, UpdateView):
    model = CompanyConfig
    form_class = CompanyConfigForm
    template_name = 'access_control/settings_company_form.html'
    success_url = reverse_lazy('access_control:company_config_list')
    vista_nombre = 'company_config'
    permiso_requerido = 'modificar'

    def dispatch(self, request, *args, **kwargs):
        self.empresa = get_object_or_404(Empresa, id=kwargs.get('empresa_id'))
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        config, _ = CompanyConfig.objects.get_or_create(empresa=self.empresa)
        return config

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['empresa'] = self.empresa
        return context


class SystemEmailTestOutgoingView(VerificarPermisoSafeMixin, LoginRequiredMixin, View):
    vista_nombre = 'system_config'
    permiso_requerido = 'crear'

    def dispatch(self, request, *args, **kwargs):
        if not Vista.objects.filter(nombre='system_config').exists():
            return JsonResponse({
                'detail': 'NO ENCONTRADO: Vista system_config',
            }, status=400)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return _send_system_test_email(request, subject='Prueba SMTP', body_text='Prueba de salida SMTP.')


class SystemEmailSendTestView(VerificarPermisoSafeMixin, LoginRequiredMixin, View):
    vista_nombre = 'system_config'
    permiso_requerido = 'crear'

    def dispatch(self, request, *args, **kwargs):
        if not Vista.objects.filter(nombre='system_config').exists():
            return JsonResponse({
                'detail': 'NO ENCONTRADO: Vista system_config',
            }, status=400)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return _send_system_test_email(request, subject='Correo de prueba', body_text='Correo de prueba enviado desde SystemConfig.')


def _send_system_test_email(request, subject, body_text):
    logger = logging.getLogger(__name__)
    if not Vista.objects.filter(nombre='system_config').exists():
        return JsonResponse({
            'detail': 'NO ENCONTRADO: Vista system_config',
        }, status=400)

    config = SystemConfig.objects.filter(is_active=True).select_related(
        'security_email_account'
    ).first()
    if not config:
        return JsonResponse({
            'detail': 'No existe una configuración activa del sistema.',
        }, status=400)

    email_account = config.security_email_account
    if not email_account or not email_account.is_active:
        return JsonResponse({
            'detail': 'Falta security_email_account en SystemConfig.',
        }, status=400)

    missing_fields = _validate_email_account_for_smtp(email_account)
    if missing_fields:
        return JsonResponse({
            'detail': f"El EmailAccount no tiene {', '.join(missing_fields)} configurado",
        }, status=400)

    to_email = (request.user.email or '').strip()
    if not to_email:
        return JsonResponse({
            'detail': 'El usuario no tiene email configurado.',
        }, status=400)

    if django_settings.DEBUG:
        logger.info(
            "System email test: host=%s port=%s user=%s from_email=%s tls=%s ssl=%s reply_to=%s to=%s",
            email_account.smtp_host,
            email_account.smtp_port,
            email_account.smtp_user,
            email_account.from_email,
            email_account.use_tls,
            email_account.use_ssl,
            email_account.reply_to,
            to_email,
        )

    try:
        send_email_via_account(
            email_account=email_account,
            subject=subject,
            body_text=body_text,
            to_emails=[to_email],
        )
    except Exception:
        return JsonResponse({
            'detail': 'Error enviando correo de prueba.',
        }, status=400)

    return JsonResponse({'status': 'ok'})


def _validate_email_account_for_smtp(email_account):
    missing = []
    if not (email_account.smtp_host or '').strip():
        missing.append('smtp_host')
    if not email_account.smtp_port:
        missing.append('smtp_port')
    if not (email_account.smtp_user or '').strip():
        missing.append('smtp_user')
    return missing




class UsuariosListaView(VerificarPermisoMixin,LoginRequiredMixin, ListView):
    model = User
    template_name = 'access_control/usuarios_lista.html'
    context_object_name = 'usuarios'
    vista_nombre = "Maestro Usuarios"
    permiso_requerido = "ingresar"

    def render_to_response(self, context, **response_kwargs):
        # Imprime el contexto para verificar los datos
        print(context['usuarios'])
        return super().render_to_response(context, **response_kwargs)


class InvitacionesListView(VerificarPermisoSafeMixin, LoginRequiredMixin, ListView):
    template_name = 'access_control/invitaciones_list.html'
    context_object_name = 'invitaciones'
    vista_nombre = 'invitaciones'
    permiso_requerido = 'ingresar'

    def _resolve_empresa_ids(self, token):
        meta = token.meta or {}
        empresa_ids = meta.get('empresa_ids')
        if empresa_ids:
            return [int(item) for item in empresa_ids if str(item).isdigit()]
        empresa_id = meta.get('empresa_id')
        if empresa_id and str(empresa_id).isdigit():
            return [int(empresa_id)]
        return []

    def _status_key(self, token):
        now = timezone.now()
        if token.used_at:
            return 'invitations.status.used'
        if token.expires_at < now:
            return 'invitations.status.expired'
        return 'invitations.status.active'

    def get_queryset(self):
        tokens = UserEmailToken.objects.filter(
            purpose=UserEmailTokenPurpose.ACTIVATE,
        ).select_related('user').order_by('expires_at')

        status_filter = (self.request.GET.get('estado') or 'active').lower()
        empresa_filter = (self.request.GET.get('empresa') or 'activa').lower()
        empresa_activa_id = self.request.session.get('empresa_id')

        if not self.request.user.is_staff:
            empresa_filter = 'activa'

        items = []
        empresa_ids_map = {}
        for token in tokens:
            empresa_ids = self._resolve_empresa_ids(token)
            empresa_ids_map[token.id] = empresa_ids

        empresas = Empresa.objects.filter(id__in={
            empresa_id for ids in empresa_ids_map.values() for empresa_id in ids
        })
        empresas_lookup = {empresa.id: empresa for empresa in empresas}

        for token in tokens:
            empresa_ids = empresa_ids_map.get(token.id, [])
            is_global = not empresa_ids

            if is_global and not self.request.user.is_staff:
                continue

            if empresa_filter == 'activa':
                if empresa_activa_id:
                    if not is_global and empresa_activa_id not in empresa_ids:
                        continue
                elif not self.request.user.is_staff:
                    continue

            status_key = self._status_key(token)
            if status_filter != 'all' and status_key.split('.')[-1] != status_filter:
                continue

            empresas_labels = []
            for empresa_id in empresa_ids:
                empresa = empresas_lookup.get(empresa_id)
                if empresa:
                    empresas_labels.append(f"{empresa.codigo} - {empresa.descripcion or ''}".strip())

            items.append({
                'token': token,
                'status_key': status_key,
                'empresas_labels': empresas_labels,
                'is_global': is_global,
            })

        status_priority = {
            'invitations.status.active': 0,
            'invitations.status.expired': 1,
            'invitations.status.used': 2,
        }
        items.sort(key=lambda item: (
            status_priority.get(item['status_key'], 99),
            item['token'].expires_at,
        ))
        return items

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['estado'] = (self.request.GET.get('estado') or 'active').lower()
        context['empresa_filtro'] = (self.request.GET.get('empresa') or 'activa').lower()
        context['empresa_activa'] = self.request.session.get('empresa_id')
        return context


class InvitacionEliminarView(VerificarPermisoSafeMixin, LoginRequiredMixin, View):
    vista_nombre = 'invitaciones'
    permiso_requerido = 'eliminar'

    def handle_no_permission(self, request, mensaje="No tienes permiso para esta acción."):
        messages.error(request, 'invitations.delete.forbidden')
        return redirect('access_control:invitaciones_lista')

    def post(self, request, pk, *args, **kwargs):
        token = UserEmailToken.objects.filter(pk=pk).select_related('user').first()
        if not token:
            messages.error(request, 'invitations.delete.not_found')
            return redirect('access_control:invitaciones_lista')

        empresa_ids = []
        meta = token.meta or {}
        empresa_ids_meta = meta.get('empresa_ids')
        if empresa_ids_meta:
            empresa_ids = [int(item) for item in empresa_ids_meta if str(item).isdigit()]
        else:
            empresa_id = meta.get('empresa_id')
            if empresa_id and str(empresa_id).isdigit():
                empresa_ids = [int(empresa_id)]

        if empresa_ids and not request.user.is_staff:
            empresa_activa_id = request.session.get('empresa_id')
            if empresa_activa_id not in empresa_ids:
                return self.handle_no_permission(request)

        if not empresa_ids and not request.user.is_staff:
            return self.handle_no_permission(request)

        token.delete()
        messages.success(request, 'invitations.delete.success')
        return redirect('access_control:invitaciones_lista')


class UsuariosPorEmpresasJsonView(VerificarPermisoSafeMixin, LoginRequiredMixin, View):
    vista_nombre = "Maestro Usuarios"
    permiso_requerido = "ingresar"

    def handle_no_permission(self, request, mensaje="No tienes permiso para esta acción."):
        return JsonResponse({"detail": mensaje}, status=403)

    def get(self, request, *args, **kwargs):
        empresa_ids = request.GET.get('empresa_ids', '')
        ids = [item for item in empresa_ids.split(',') if item.isdigit()]

        if not ids:
            empresa_id = request.session.get('empresa_id')
            if empresa_id:
                ids = [str(empresa_id)]

        if not ids:
            return JsonResponse({"users": []})

        users = User.objects.filter(
            permiso__empresa_id__in=ids,
            is_active=True,
        ).distinct().order_by('username')

        data = [
            {
                "id": user.id,
                "username": user.username,
                "email": user.email or "",
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
            }
            for user in users
        ]

        return JsonResponse({"users": data})
    
class BaseUsuarioInviteView(VerificarPermisoMixin, LoginRequiredMixin, FormView):
    form_class = UsuarioInvitacionForm
    template_name = 'access_control/usuarios_form.html'
    success_url = reverse_lazy('access_control:usuarios_lista')
    vista_nombre = 'auth_invite'
    permiso_requerido = 'crear'

    def dispatch(self, request, *args, **kwargs):
        if not Vista.objects.filter(nombre='auth_invite').exists():
            form = self.get_form()
            form.add_error(None, 'Falta ejecutar seed_access_control para crear la Vista base "auth_invite".')
            context = self.get_context_data(form=form)
            return self.render_to_response(context, status=400)
        try:
            return super().dispatch(request, *args, **kwargs)
        except PermisoDenegadoJson as e:
            return self.handle_no_permission(request, str(e))

    def handle_no_permission(self, request, mensaje="No tienes permiso para esta acción."):
        return render(request, "access_control/403_forbidden.html", {"mensaje": mensaje}, status=403)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        empresa_id = self.request.session.get('empresa_id')
        empresa = None
        if empresa_id:
            empresa = Empresa.objects.filter(pk=empresa_id).first()
        kwargs['empresa_in_session'] = empresa
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context.get('form') or self.get_form()
        referencia_field = form.fields.get('usuario_referencia') if form else None
        context['usuarios_referencia_vacios'] = not bool(
            referencia_field and referencia_field.queryset.exists()
        )
        return context

    def form_valid(self, form):
        email = form.cleaned_data['email']
        empresas = form.cleaned_data.get('empresas')
        tipo_usuario = form.cleaned_data.get('tipo_usuario')
        usuario_referencia = form.cleaned_data.get('usuario_referencia')

        try:
            result = invite_user_flow(
                email=email,
                first_name=form.cleaned_data.get('first_name'),
                last_name=form.cleaned_data.get('last_name'),
                empresas=empresas,
                tipo_usuario=tipo_usuario,
                usuario_referencia=usuario_referencia,
                created_by=self.request.user,
            )
        except Exception:
            form.add_error(None, 'No se pudo enviar el correo de invitación.')
            return self.form_invalid(form)

        if not result.get('ok'):
            form.add_error(None, result.get('error'))
            return self.form_invalid(form)

        messages.success(self.request, f'Invitación enviada a {email}.')
        return redirect(self.success_url)


class UsuarioCrearView(BaseUsuarioInviteView):
    pass


class UsuarioInvitarView(BaseUsuarioInviteView):
    pass

class UsuarioEditarView(VerificarPermisoMixin,LoginRequiredMixin, UpdateView):
    model = User
    form_class = UsuarioEditarForm
    template_name = 'access_control/usuarios_form.html'
    success_url = reverse_lazy('access_control:usuarios_lista')
    vista_nombre = "Maestro Usuarios"
    permiso_requerido = "modificar"


class UsuarioEliminarView(VerificarPermisoMixin,LoginRequiredMixin, DeleteView):
    model = User
    template_name = 'access_control/usuario_confirmar_eliminar.html'
    success_url = reverse_lazy('access_control:usuarios_lista')
    vista_nombre = "Maestro Usuarios"
    permiso_requerido = "eliminar"

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        with transaction.atomic():
            Permiso.objects.filter(usuario=self.object).delete()
            UsuarioPerfilEmpresa.objects.filter(usuario=self.object).delete()
            UserEmailToken.objects.filter(user=self.object).delete()
            self.object.delete()
        messages.success(request, 'users.delete.success')
        return redirect(self.success_url)


# class SeleccionarEmpresaView(VerificarPermisoMixin,LoginRequiredMixin, View):
#     template_name = "access_control/seleccionar_empresa.html"
#     vista_nombre = "Cambiar Empresa"
#     permiso_requerido = "modificar"

#     def get(self, request, *args, **kwargs):
#         permisos = Permiso.objects.filter(usuario=request.user).select_related("empresa")
#         empresas = Empresa.objects.filter(id__in=permisos.values("empresa"))

#         print(empresas)  # Para depuración
#         return render(request, self.template_name, {"empresas": empresas})

#     def post(self, request, *args, **kwargs):
#         empresa_id = request.POST.get("empresa_id")
#         request.session["empresa_id"] = empresa_id
#         return redirect("listar_propiedades")

@login_required
def seleccionar_empresa(request):
    if request.method == "POST":
        empresa_id = request.POST.get("empresa_id")
        empresa = Empresa.objects.get(pk=empresa_id)
        empresa_codigo = empresa.codigo
        request.session["empresa_id"] = empresa_id
        request.session["empresa_codigo"] = empresa_codigo
        return redirect("biblioteca:listar_propiedades")

    permisos = Permiso.objects.filter(usuario=request.user).select_related("empresa")
    empresas = Empresa.objects.filter(id__in=permisos.values("empresa"))

    print(empresas)  # Para depuración
    return render(request, "access_control/seleccionar_empresa.html", {"empresas": empresas})

