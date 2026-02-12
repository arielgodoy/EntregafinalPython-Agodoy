# views.py
from django.views.generic.edit import UpdateView
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, Exists, OuterRef
from django.views.generic.list import ListView
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView
from .models import Conversacion, Mensaje
from .forms import MensajeForm,ConversacionForm,EnviarMensajeForm

from django.urls import reverse
from django.urls import reverse_lazy
from django.views.generic.edit import DeleteView
from django.urls import reverse_lazy
from django.views.generic import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.contrib.auth.models import User
from .forms import MensajeForm,ConversacionForm, EnviarMensajeForm
from django.contrib import messages
from django.views.generic.edit import CreateView, FormView, FormMixin, DeleteView
from django.utils.decorators import method_decorator

from access_control.decorators import verificar_permiso
from access_control.models import UsuarioPerfilEmpresa
from .services.empresa import get_empresa_activa_id, assert_empresa_activa
from .services.conversations import create_conversation, validate_participants
from .services.messages import create_message
from .services.unread import mark_conversation_read


def _get_conversacion_titulo(conversacion, user):
    if not conversacion:
        return ""
    otros = [p.username for p in conversacion.participantes.all() if p.id != user.id]
    if otros:
        return ", ".join(otros)
    return user.username


@login_required
@verificar_permiso("chat.inbox", "ingresar")
def chat_inbox(request):
    empresa_check = assert_empresa_activa(request)
    if empresa_check:
        return empresa_check

    empresa_id = get_empresa_activa_id(request)
    conversaciones = Conversacion.objects.filter(
        empresa_id=empresa_id,
        participantes=request.user,
    ).prefetch_related('participantes')

    for conversacion in conversaciones:
        conversacion.display_title = _get_conversacion_titulo(conversacion, request.user)

    active_conversation = None
    conversation_id = request.GET.get("conversation_id")
    if conversation_id and str(conversation_id).isdigit():
        active_conversation = conversaciones.filter(id=int(conversation_id)).first()
    if not active_conversation:
        active_conversation = conversaciones.first()

    if active_conversation:
        mark_conversation_read(active_conversation, request.user)

    mensajes = (
        Mensaje.objects.filter(conversacion=active_conversation)
        .select_related('remitente')
        .order_by('fecha_creacion')
        if active_conversation
        else Mensaje.objects.none()
    )
    contacto_ids = UsuarioPerfilEmpresa.objects.filter(
        empresa_id=empresa_id,
    ).values_list('usuario_id', flat=True)
    contactos = User.objects.filter(
        id__in=contacto_ids,
        is_active=True,
    ).exclude(id=request.user.id).distinct()

    context = {
        "conversations": conversaciones,
        "active_conversation": active_conversation,
        "active_title": _get_conversacion_titulo(active_conversation, request.user),
        "messages": mensajes,
        "contacts": contactos,
        "unread_count": {},
        "search_query": "",
        "unread_only": False,
        "show_center_filters": False,
    }
    return render(request, "apps/apps-chat.html", context)


@login_required
@verificar_permiso("chat.inbox", "ingresar")
def centro_mensajes(request):
    empresa_check = assert_empresa_activa(request)
    if empresa_check:
        return empresa_check

    empresa_id = get_empresa_activa_id(request)
    search_query = (request.GET.get("q") or "").strip()
    unread_only = request.GET.get("unread") == "1"

    conversaciones = Conversacion.objects.filter(
        empresa_id=empresa_id,
        participantes=request.user,
    ).prefetch_related('participantes')

    for conversacion in conversaciones:
        conversacion.display_title = _get_conversacion_titulo(conversacion, request.user)

    if search_query:
        mensaje_ids = Mensaje.objects.filter(
            conversacion__empresa_id=empresa_id,
            conversacion__participantes=request.user,
            contenido__icontains=search_query,
        ).values_list("conversacion_id", flat=True)

        conversaciones = conversaciones.filter(
            Q(id__in=mensaje_ids)
            | Q(participantes__username__icontains=search_query)
            | Q(participantes__email__icontains=search_query)
            | Q(participantes__first_name__icontains=search_query)
            | Q(participantes__last_name__icontains=search_query)
        ).distinct()

    if unread_only:
        unread_exists = Mensaje.objects.filter(
            conversacion=OuterRef("pk"),
        ).exclude(remitente_id=request.user.id).exclude(leidos__user=request.user)
        conversaciones = conversaciones.annotate(
            has_unread=Exists(unread_exists)
        ).filter(has_unread=True)

    active_conversation = None
    conversation_id = request.GET.get("conversation_id")
    if conversation_id and str(conversation_id).isdigit():
        active_conversation = conversaciones.filter(id=int(conversation_id)).first()
    if not active_conversation:
        active_conversation = conversaciones.first()

    mensajes = (
        Mensaje.objects.filter(conversacion=active_conversation)
        .select_related('remitente')
        .order_by('fecha_creacion')
        if active_conversation
        else Mensaje.objects.none()
    )
    if active_conversation and search_query:
        mensajes = mensajes.filter(contenido__icontains=search_query)

    contacto_ids = UsuarioPerfilEmpresa.objects.filter(
        empresa_id=empresa_id,
    ).values_list('usuario_id', flat=True)
    contactos = User.objects.filter(
        id__in=contacto_ids,
        is_active=True,
    ).exclude(id=request.user.id).distinct()

    context = {
        "conversations": conversaciones,
        "active_conversation": active_conversation,
        "active_title": _get_conversacion_titulo(active_conversation, request.user),
        "messages": mensajes,
        "contacts": contactos,
        "unread_count": {},
        "search_query": search_query,
        "unread_only": unread_only,
        "show_center_filters": True,
    }
    return render(request, "apps/apps-chat.html", context)

# Create your views here.





@login_required
@verificar_permiso("chat.inbox", "ingresar")
def lista_conversaciones(request):
    empresa_check = assert_empresa_activa(request)
    if empresa_check:
        return empresa_check

    empresa_id = get_empresa_activa_id(request)
    conversaciones = Conversacion.objects.filter(
        empresa_id=empresa_id,
        participantes=request.user,
    )

    print(conversaciones)
    return render(request, 'lista_conversaciones.html', {'conversaciones': conversaciones})

@login_required
@verificar_permiso("chat.send_message", "ingresar")
def enviar_mensaje(request, conversacion_id):
    empresa_check = assert_empresa_activa(request)
    if empresa_check:
        return empresa_check

    empresa_id = get_empresa_activa_id(request)
    conversacion = get_object_or_404(
        Conversacion,
        id=conversacion_id,
        empresa_id=empresa_id,
        participantes=request.user,
    )
    form = MensajeForm(request.POST or None)
    
    if request.method == 'POST' and form.is_valid():
        try:
            create_message(
                conversacion,
                request.user,
                form.cleaned_data.get('contenido', ''),
                empresa_id=empresa_id,
            )
        except ValueError:
            return HttpResponseForbidden()
        return redirect('detalle_conversacion', conversacion_id=conversacion_id)

    return render(request, 'enviar_mensaje.html', {'conversacion': conversacion, 'form': form})

@login_required
@verificar_permiso("chat.create", "ingresar")
def crear_conversacion(request):
    empresa_check = assert_empresa_activa(request)
    if empresa_check:
        return empresa_check

    empresa_id = get_empresa_activa_id(request)
    if request.method == 'POST':
        form = ConversacionForm(request.POST, user=request.user, empresa_id=empresa_id)
        try:
            validate_participants(
                empresa_id,
                request.user,
                request.POST.getlist('participantes'),
            )
        except ValueError:
            return HttpResponseForbidden()
        if form.is_valid():
            participantes = form.cleaned_data.get('participantes')
            participant_ids = [user.id for user in participantes]
            try:
                conversacion = create_conversation(
                    empresa_id,
                    request.user,
                    participant_ids,
                )
            except ValueError:
                return HttpResponseForbidden()
            return redirect('detalle_conversacion', conversacion_id=conversacion.id)
    else:
        form = ConversacionForm(user=request.user, empresa_id=empresa_id)

    return render(request, 'crear_conversacion.html', {'form': form})

@login_required
@verificar_permiso("chat.thread", "ingresar")
def detalle_conversacion(request, conversacion_id):
    empresa_check = assert_empresa_activa(request)
    if empresa_check:
        return empresa_check

    empresa_id = get_empresa_activa_id(request)
    conversacion = get_object_or_404(
        Conversacion,
        id=conversacion_id,
        empresa_id=empresa_id,
        participantes=request.user,
    )
    if request.method == 'GET':
        mark_conversation_read(conversacion, request.user)
    mensajes = Mensaje.objects.filter(conversacion=conversacion)

    if request.method == 'POST':
        form = EnviarMensajeForm(request.POST)
        if form.is_valid():
            try:
                create_message(
                    conversacion,
                    request.user,
                    form.cleaned_data.get('contenido', ''),
                    empresa_id=empresa_id,
                )
            except ValueError:
                return HttpResponseForbidden()
            return redirect('detalle_conversacion', conversacion_id=conversacion_id)
    else:
        form = EnviarMensajeForm()

    return render(request, 'detalle_conversacion.html', {'conversacion': conversacion, 'mensajes': mensajes, 'form': form})

@login_required
@verificar_permiso("chat.delete", "ingresar")
def eliminar_conversacion(request, conversacion_id):
    empresa_check = assert_empresa_activa(request)
    if empresa_check:
        return empresa_check

    empresa_id = get_empresa_activa_id(request)
    # Obtener la conversación por su ID o retornar un error 404 si no existe
    conversacion = get_object_or_404(
        Conversacion,
        id=conversacion_id,
        empresa_id=empresa_id,
        participantes=request.user,
    )

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
@method_decorator(verificar_permiso("chat.create", "ingresar"), name="dispatch")
class CrearConversacionView(LoginRequiredMixin, FormView):
    template_name = 'crear_conversacion.html'
    form_class = ConversacionForm
    def post(self, request, *args, **kwargs):
        empresa_id = get_empresa_activa_id(request)
        try:
            validate_participants(
                empresa_id,
                request.user,
                request.POST.getlist('participantes'),
            )
        except ValueError:
            return HttpResponseForbidden()
        return super().post(request, *args, **kwargs)


    def get_form_kwargs(self):
        # Pasar el usuario autenticado al formulario
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['empresa_id'] = get_empresa_activa_id(self.request)
        return kwargs

    def form_valid(self, form):
        # Guardar la conversación cuando el formulario es válido
        empresa_check = assert_empresa_activa(self.request)
        if empresa_check:
            return empresa_check

        empresa_id = get_empresa_activa_id(self.request)
        participantes = form.cleaned_data.get('participantes')
        participant_ids = [user.id for user in participantes]
        try:
            conversacion = create_conversation(
                empresa_id,
                self.request.user,
                participant_ids,
            )
        except ValueError:
            return HttpResponseForbidden()
        return redirect('detalle_conversacion', conversacion_id=conversacion.id)
#CREATE
@method_decorator(verificar_permiso("chat.send_message", "ingresar"), name="dispatch")
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
        empresa_id = get_empresa_activa_id(self.request)
        return get_object_or_404(
            Conversacion,
            id=self.kwargs['conversacion_id'],
            empresa_id=empresa_id,
            participantes=self.request.user,
        )

    def form_valid(self, form):
        # Si el formulario es válido, guardar el mensaje
        empresa_id = get_empresa_activa_id(self.request)
        conversacion = self.get_conversacion()
        try:
            create_message(
                conversacion,
                self.request.user,
                form.cleaned_data.get('contenido', ''),
                empresa_id=empresa_id,
            )
        except ValueError:
            return HttpResponseForbidden()
        return redirect('detalle_conversacion', conversacion_id=self.kwargs['conversacion_id'])
#READ
@method_decorator(verificar_permiso("chat.thread", "ingresar"), name="dispatch")
class DetalleConversacionView(LoginRequiredMixin, DetailView):
    model = Conversacion
    template_name = 'detalle_conversacion.html'
    context_object_name = 'conversacion'
    form_class = EnviarMensajeForm

    def get_queryset(self):
        # Filtrar conversaciones para que solo se puedan acceder a las del usuario autenticado
        empresa_id = get_empresa_activa_id(self.request)
        return super().get_queryset().filter(
            empresa_id=empresa_id,
            participantes=self.request.user,
        )

    def get_context_data(self, **kwargs):
        # Agregar los mensajes de la conversación al contexto
        context = super().get_context_data(**kwargs)
        conversacion = self.get_object()
        mark_conversation_read(conversacion, self.request.user)
        context['mensajes'] = Mensaje.objects.filter(conversacion=conversacion)
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
        empresa_id = get_empresa_activa_id(self.request)
        conversacion = self.get_object()
        try:
            create_message(
                conversacion,
                self.request.user,
                form.cleaned_data.get('contenido', ''),
                empresa_id=empresa_id,
            )
        except ValueError:
            return HttpResponseForbidden()
        return redirect('detalle_conversacion', conversacion_id=self.get_object().id)

#READ
@method_decorator(verificar_permiso("chat.inbox", "ingresar"), name="dispatch")
class ListaConversacionesView(LoginRequiredMixin, ListView):
    model = Conversacion
    template_name = 'lista_conversaciones.html'
    context_object_name = 'conversaciones'

    def get_queryset(self):
        # Filtrar solo las conversaciones en las que el usuario es participante
        empresa_id = get_empresa_activa_id(self.request)
        return Conversacion.objects.filter(
            empresa_id=empresa_id,
            participantes=self.request.user,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Imprimir las conversaciones en la consola para depuración
        print(context['conversaciones'])
        return context
    
#DELETE
@method_decorator(verificar_permiso("chat.delete", "ingresar"), name="dispatch")
class EliminarConversacionView(LoginRequiredMixin, DeleteView):
    model = Conversacion
    template_name = 'eliminar_conversacion.html'
    context_object_name = 'conversacion'
    success_url = reverse_lazy('lista_conversaciones')

    def get_queryset(self):
        # Filtrar conversaciones que solo el usuario autenticado puede eliminar
        empresa_id = get_empresa_activa_id(self.request)
        return super().get_queryset().filter(
            empresa_id=empresa_id,
            participantes=self.request.user,
        )
###########################################################################
