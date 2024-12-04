from django.views.generic.edit import UpdateView,DeleteView,CreateView
from django.urls import reverse_lazy
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView,FormView
from django.shortcuts import render

from .models import Empresa,Permiso,Vista
from .forms import PermisoForm,PermisoFiltroForm,UsuarioCrearForm,UsuarioEditarForm
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .decorators import verificar_permiso
from django.utils.decorators import method_decorator
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


class PermisosFiltradosView(VerificarPermisoMixin,LoginRequiredMixin, FormView):
    template_name = 'access_control/permisos_filtrados.html'
    form_class = PermisoFiltroForm
    vista_nombre = "Maestro Permisos"
    permiso_requerido = "modificar"
    success_url = reverse_lazy('access_control:permisos_filtrados')    
    
    def get(self, request, *args, **kwargs):
        print("Datos enviados en la solicitud GET:", request.GET)
        return super().get(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial['usuario'] = User.objects.first()  # Ajusta a un usuario válido
        initial['empresa'] = Empresa.objects.first()  # Ajusta a una empresa válida
        print(f"Valores iniciales del formulario: {initial}")
        return initial



    def form_valid(self, form):
        print("Entrando en form_valid")
        usuario = form.cleaned_data.get('usuario')
        empresa = form.cleaned_data.get('empresa')
        print(f"Usuario recibido: {usuario}")
        print(f"Empresa recibida: {empresa}")

        # Filtra los permisos según los datos proporcionados en el formulario
        print(usuario)
        if usuario and empresa:
            permisos = Permiso.objects.filter(usuario=usuario, empresa=empresa)
            print("Contenido de permisos:", permisos)  # Inspecciona qué contiene permisos
        else:
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
    
class UsuarioCrearView(VerificarPermisoMixin,LoginRequiredMixin, CreateView):
    model = User
    form_class = UsuarioCrearForm
    template_name = 'access_control/usuarios_form.html'
    success_url = reverse_lazy('access_control:usuarios_lista')
    vista_nombre = "Maestro Usuarios"
    permiso_requerido = "crear"

    def form_valid(self, form):
        return super().form_valid(form)

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