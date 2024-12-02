from django.views.generic.edit import UpdateView,DeleteView,CreateView
from django.urls import reverse_lazy
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView

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
    fields = ['username', 'email', 'password']
    success_url = reverse_lazy('access_control:usuarios_lista')  # Redirigir a la lista de usuarios

    def form_valid(self, form):
        # Encriptar la contraseña antes de guardar
        form.instance.set_password(form.cleaned_data['password'])
        return super().form_valid(form)

class UsuarioEditarView(LoginRequiredMixin, UpdateView):
    model = User
    fields = ['username', 'email', 'password']  # Campos que el usuario puede editar
    template_name = 'access_control/usuarios_form.html'
    success_url = reverse_lazy('access_control:usuarios_lista')

    def form_valid(self, form):
        # Encriptar la contraseña antes de guardar
        if form.cleaned_data['password']:
            form.instance.set_password(form.cleaned_data['password'])
        return super().form_valid(form)



class UsuarioEliminarView(LoginRequiredMixin, DeleteView):
    model = User
    template_name = 'access_control/usuario_confirmar_eliminar.html'
    success_url = reverse_lazy('access_control:usuarios_lista')