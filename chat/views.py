# views.py
from django.views.generic.edit import UpdateView
from django.shortcuts import render, redirect,get_object_or_404
from django.views.generic.list import ListView
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView
from .models import Conversacion,Mensaje
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

