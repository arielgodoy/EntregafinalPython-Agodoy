from django.views.generic.edit import UpdateView,DeleteView,CreateView
from django.urls import reverse_lazy
from django.contrib.auth.models import User
from django.contrib.auth.models import User as Usuario
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView,FormView
from django.shortcuts import render

from .models import Empresa,Permiso,Vista
from .forms import PermisoForm,PermisoFiltroForm,UsuarioCrearForm,UsuarioEditarForm
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views import View

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
        
        # Intenta usar los valores enviados en GET o POST
        usuario_id = self.request.GET.get('usuario') or self.request.POST.get('usuario')
        empresa_id = self.request.GET.get('empresa') or self.request.POST.get('empresa')
        
        # Si no hay valores enviados, usa valores predeterminados
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
        request.session["empresa_id"] = empresa_id
        return redirect("listar_propiedades")

    permisos = Permiso.objects.filter(usuario=request.user).select_related("empresa")
    empresas = Empresa.objects.filter(id__in=permisos.values("empresa"))

    print(empresas)  # Para depuración
    return render(request, "access_control/seleccionar_empresa.html", {"empresas": empresas})

