from django.views.generic.edit import UpdateView,DeleteView,CreateView
from django.urls import reverse_lazy
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView
from django.shortcuts import render

from .models import Empresa,Permiso,Vista
from .forms import PermisoForm,FiltroPermisosForm,PermisoFiltroForm
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def toggle_permiso(request):
    if request.method == "POST":
        permiso_id = request.POST.get("permiso_id")
        permiso_field = request.POST.get("permiso_field")

        try:
            permiso = Permiso.objects.get(id=permiso_id)
            current_value = getattr(permiso, permiso_field, False)
            setattr(permiso, permiso_field, not current_value)
            permiso.save()
            return JsonResponse({"success": True, "new_value": not current_value})
        except Permiso.DoesNotExist:
            return JsonResponse({"success": False, "error": "Permiso no encontrado"})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Método no permitido"})

def permisos_filtrados_view(request):
    form = PermisoFiltroForm(request.GET or None)
    permisos = None

    if form.is_valid():
        usuario = form.cleaned_data.get('usuario')
        empresa = form.cleaned_data.get('empresa')
        if usuario and empresa:
            permisos = Permiso.objects.filter(usuario=usuario, empresa=empresa)

    context = {
        'form': form,
        'permisos': permisos,
        'fields': ['ingresar', 'crear', 'modificar', 'eliminar', 'autorizar', 'supervisor'],
    }
    return render(request, 'access_control/permisos_filtrados.html', context)


class VistaListaView(LoginRequiredMixin, ListView):
    model = Vista
    template_name = 'access_control/vistas_lista.html'
    context_object_name = 'vistas'

class VistaCrearView(LoginRequiredMixin, CreateView):
    model = Vista
    fields = ['nombre', 'descripcion']
    template_name = 'access_control/vistas_form.html'
    success_url = reverse_lazy('access_control:vistas_lista')

class VistaEditarView(LoginRequiredMixin, UpdateView):
    model = Vista
    fields = ['nombre', 'descripcion']
    template_name = 'access_control/vistas_form.html'
    success_url = reverse_lazy('access_control:vistas_lista')

class VistaEliminarView(LoginRequiredMixin, DeleteView):
    model = Vista
    template_name = 'access_control/vista_confirmar_eliminar.html'
    success_url = reverse_lazy('access_control:vistas_lista')



class PermisoListaView(LoginRequiredMixin, ListView):
    model = Permiso
    template_name = 'access_control/permisos_lista.html'
    context_object_name = 'permisos'

class PermisoCrearView(LoginRequiredMixin, CreateView):
    model = Permiso
    fields = ['usuario', 'empresa', 'vista', 'ingresar', 'crear', 'modificar', 'eliminar', 'autorizar', 'supervisor']
    template_name = 'access_control/permisos_form.html'
    success_url = reverse_lazy('access_control:permisos_lista')

class PermisoEditarView(LoginRequiredMixin, UpdateView):
    model = Permiso
    fields = ['usuario', 'empresa', 'vista', 'ingresar', 'crear', 'modificar', 'eliminar', 'autorizar', 'supervisor']
    template_name = 'access_control/permisos_form.html'
    success_url = reverse_lazy('access_control:permisos_lista')

class PermisoEliminarView(LoginRequiredMixin, DeleteView):
    model = Permiso
    template_name = 'access_control/permiso_confirmar_eliminar.html'
    success_url = reverse_lazy('access_control:permisos_lista')



class EmpresaListaView(LoginRequiredMixin, ListView):
    model = Empresa
    template_name = 'access_control/empresas_lista.html'
    context_object_name = 'empresas'
class EmpresaCrearView(LoginRequiredMixin, CreateView):
    model = Empresa
    fields = ['codigo', 'descripcion']
    template_name = 'access_control/empresas_form.html'
    success_url = reverse_lazy('access_control:empresas_lista')
class EmpresaEditarView(LoginRequiredMixin, UpdateView):
    model = Empresa
    fields = ['codigo', 'descripcion']
    template_name = 'access_control/empresas_form.html'
    success_url = reverse_lazy('access_control:empresas_lista')
class EmpresaEliminarView(LoginRequiredMixin, DeleteView):
    model = Empresa
    template_name = 'access_control/empresa_confirmar_eliminar.html'
    success_url = reverse_lazy('access_control:empresas_lista')




class UsuariosListaView(LoginRequiredMixin, ListView):
    model = User
    template_name = 'access_control/usuarios_lista.html'
    context_object_name = 'usuarios'

    def render_to_response(self, context, **response_kwargs):
        # Imprime el contexto para verificar los datos
        print(context['usuarios'])
        return super().render_to_response(context, **response_kwargs)
    
class UsuarioCrearView(LoginRequiredMixin, CreateView):
    model = User
    template_name = 'access_control/usuarios_form.html'
    fields = ['username', 'email']
    success_url = reverse_lazy('access_control:usuarios_lista')  # Redirigir a la lista de usuarios

    def form_valid(self, form):
        # Encriptar la contraseña antes de guardar
        #form.instance.set_password(form.cleaned_data['password'])
        return super().form_valid(form)

class UsuarioEditarView(LoginRequiredMixin, UpdateView):
    model = User
    fields = ['username', 'email']  # Campos que el usuario puede editar
    template_name = 'access_control/usuarios_form.html'
    success_url = reverse_lazy('access_control:usuarios_lista')

    def form_valid(self, form):
        # Encriptar la contraseña antes de guardar
        #if form.cleaned_data['password']:
        #    form.instance.set_password(form.cleaned_data['password'])
        return super().form_valid(form)



class UsuarioEliminarView(LoginRequiredMixin, DeleteView):
    model = User
    template_name = 'access_control/usuario_confirmar_eliminar.html'
    success_url = reverse_lazy('access_control:usuarios_lista')