# views.py
from django.views.generic.edit import UpdateView
from django.shortcuts import render, redirect,get_object_or_404
from django.views.generic.list import ListView
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView
from .models import Conversacion,Mensaje
from .forms import MensajeForm,ConversacionForm,EnviarMensajeForm

from django.urls import reverse
from django.urls import reverse_lazy
from django.views.generic.edit import DeleteView
from django.urls import reverse_lazy
from django.views.generic import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .forms import MensajeForm,ConversacionForm, EnviarMensajeForm
from django.contrib import messages
from django.views.generic.edit import CreateView, FormView,FormMixin,DeleteView

# Create your views here.





@login_required
def lista_conversaciones(request):    
    conversaciones = Conversacion.objects.filter(participantes=request.user)   
    
    print(conversaciones)
    return render(request, 'lista_conversaciones.html', {'conversaciones': conversaciones})

@login_required
def enviar_mensaje(request, conversacion_id):
    conversacion = get_object_or_404(Conversacion, id=conversacion_id, participantes=request.user)
    form = MensajeForm(request.POST or None)
    
    if request.method == 'POST' and form.is_valid():
        mensaje = form.save(commit=False)
        mensaje.conversacion = conversacion
        mensaje.remitente = request.user
        mensaje.save()
        return redirect('detalle_conversacion', conversacion_id=conversacion_id)

    return render(request, 'enviar_mensaje.html', {'conversacion': conversacion, 'form': form})

@login_required
def crear_conversacion(request):
    if request.method == 'POST':
        form = ConversacionForm(request.POST, user=request.user)
        if form.is_valid():
            conversacion = form.save()
            # Imprime el ID de la nueva conversación para verificar que se está generando y guardando correctamente
            print(f"ID de la nueva conversación: {conversacion.id}")
            return redirect('detalle_conversacion', conversacion_id=conversacion.id)
    else:
        form = ConversacionForm(user=request.user)

    return render(request, 'crear_conversacion.html', {'form': form})

@login_required
def detalle_conversacion(request, conversacion_id):
    conversacion = get_object_or_404(Conversacion, id=conversacion_id, participantes=request.user)
    mensajes = Mensaje.objects.filter(conversacion=conversacion)

    if request.method == 'POST':
        form = EnviarMensajeForm(request.POST)
        if form.is_valid():
            mensaje = Mensaje(contenido=form.cleaned_data['contenido'], conversacion=conversacion, remitente=request.user)
            mensaje.save()
            return redirect('detalle_conversacion', conversacion_id=conversacion_id)
    else:
        form = EnviarMensajeForm()

    return render(request, 'detalle_conversacion.html', {'conversacion': conversacion, 'mensajes': mensajes, 'form': form})

@login_required
def eliminar_conversacion(request, conversacion_id):
    # Obtener la conversación por su ID o retornar un error 404 si no existe
    conversacion = get_object_or_404(Conversacion, id=conversacion_id)

    if request.method == 'POST':
        # Eliminar la conversación
        conversacion.delete()
        # Redireccionar a la lista de conversaciones después de eliminar
        return redirect('lista_conversaciones')

    return render(request, 'eliminar_conversacion.html', {'conversacion': conversacion})



###########################################################################
########            CRUD CHAT DE CONVERSACIONES                    ########
###########################################################################
#CREATE
class CrearConversacionView(LoginRequiredMixin, FormView):
    template_name = 'crear_conversacion.html'
    form_class = ConversacionForm

    def get_form_kwargs(self):
        # Pasar el usuario autenticado al formulario
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        # Guardar la conversación cuando el formulario es válido
        conversacion = form.save()
        print(f"ID de la nueva conversación: {conversacion.id}")  # Imprimir ID para depuración
        return redirect('detalle_conversacion', conversacion_id=conversacion.id)
#CREATE
class EnviarMensajeView(LoginRequiredMixin, FormView):
    template_name = 'enviar_mensaje.html'
    form_class = MensajeForm

    def get_context_data(self, **kwargs):
        # Agrega la conversación al contexto
        context = super().get_context_data(**kwargs)
        context['conversacion'] = self.get_conversacion()
        return context

    def get_conversacion(self):
        # Obtener la conversación usando el ID y asegurarse de que el usuario sea participante
        return get_object_or_404(Conversacion, id=self.kwargs['conversacion_id'], participantes=self.request.user)

    def form_valid(self, form):
        # Si el formulario es válido, guardar el mensaje
        mensaje = form.save(commit=False)
        mensaje.conversacion = self.get_conversacion()
        mensaje.remitente = self.request.user
        mensaje.save()
        return redirect('detalle_conversacion', conversacion_id=self.kwargs['conversacion_id'])
#READ
class DetalleConversacionView(LoginRequiredMixin,  DetailView):
    model = Conversacion
    template_name = 'detalle_conversacion.html'
    context_object_name = 'conversacion'
    form_class = EnviarMensajeForm

    def get_queryset(self):
        # Filtrar conversaciones para que solo se puedan acceder a las del usuario autenticado
        return super().get_queryset().filter(participantes=self.request.user)

    def get_context_data(self, **kwargs):
        # Agregar los mensajes de la conversación al contexto
        context = super().get_context_data(**kwargs)
        context['mensajes'] = Mensaje.objects.filter(conversacion=self.get_object())
        if 'form' not in context:
            context['form'] = self.get_form()
        return context

    def post(self, request, *args, **kwargs):
        # Manejar el formulario cuando se envía un mensaje
        self.object = self.get_object()  # Obtener la conversación actual
        form = self.get_form()
        if form.is_valid():
            return self.form_valid(form)
        else:
            return self.form_invalid(form)

    def form_valid(self, form):
        # Crear y guardar un nuevo mensaje
        mensaje = form.save(commit=False)
        mensaje.conversacion = self.get_object()
        mensaje.remitente = self.request.user
        mensaje.save()
        return redirect('detalle_conversacion', conversacion_id=self.get_object().id)

#READ
class ListaConversacionesView(LoginRequiredMixin, ListView):
    model = Conversacion
    template_name = 'lista_conversaciones.html'
    context_object_name = 'conversaciones'

    def get_queryset(self):
        # Filtrar solo las conversaciones en las que el usuario es participante
        return Conversacion.objects.filter(participantes=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Imprimir las conversaciones en la consola para depuración
        print(context['conversaciones'])
        return context
    
#DELETE
class EliminarConversacionView(LoginRequiredMixin, DeleteView):
    model = Conversacion
    template_name = 'eliminar_conversacion.html'
    context_object_name = 'conversacion'
    success_url = reverse_lazy('lista_conversaciones')

    def get_queryset(self):
        # Filtrar conversaciones que solo el usuario autenticado puede eliminar
        return super().get_queryset().filter(participantes=self.request.user)
###########################################################################
