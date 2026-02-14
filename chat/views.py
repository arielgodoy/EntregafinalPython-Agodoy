# views.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.db.models import Q, Exists, OuterRef
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import ListView, DetailView, DeleteView
from django.views.generic.edit import FormView

from access_control.models import UsuarioPerfilEmpresa
from access_control.views import VerificarPermisoMixin
from .forms import MensajeForm, ConversacionForm, EnviarMensajeForm
from .models import Conversacion, Mensaje
from .services.conversations import create_conversation, validate_participants
from .services.empresa import get_empresa_activa_id, assert_empresa_activa
from .services.messages import create_message
from .services.unread import mark_conversation_read


def _get_conversacion_titulo(conversacion, user):
    if not conversacion:
        return ""
    otros = [p.username for p in conversacion.participantes.all() if p.id != user.id]
    if otros:
        return ", ".join(otros)
    return user.username


class ChatInboxView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Chat - Bandeja de entrada"
    permiso_requerido = "ingresar"

    def dispatch(self, request, *args, **kwargs):
        empresa_check = assert_empresa_activa(request)
        if empresa_check:
            return empresa_check
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
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


class ChatCentroMensajesView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Chat - Centro de mensajes"
    permiso_requerido = "ingresar"

    def dispatch(self, request, *args, **kwargs):
        empresa_check = assert_empresa_activa(request)
        if empresa_check:
            return empresa_check
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
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


class ListaConversacionesView(VerificarPermisoMixin, LoginRequiredMixin, ListView):
    vista_nombre = "Chat - Lista de conversaciones"
    permiso_requerido = "ingresar"
    model = Conversacion
    template_name = 'lista_conversaciones.html'
    context_object_name = 'conversaciones'

    def dispatch(self, request, *args, **kwargs):
        empresa_check = assert_empresa_activa(request)
        if empresa_check:
            return empresa_check
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        empresa_id = get_empresa_activa_id(self.request)
        return Conversacion.objects.filter(
            empresa_id=empresa_id,
            participantes=self.request.user,
        )


class CrearConversacionView(VerificarPermisoMixin, LoginRequiredMixin, FormView):
    vista_nombre = "Chat - Crear conversación"
    permiso_requerido = "ingresar"
    template_name = 'crear_conversacion.html'
    form_class = ConversacionForm

    def dispatch(self, request, *args, **kwargs):
        empresa_check = assert_empresa_activa(request)
        if empresa_check:
            return empresa_check
        return super().dispatch(request, *args, **kwargs)

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
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['empresa_id'] = get_empresa_activa_id(self.request)
        return kwargs

    def form_valid(self, form):
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


class EnviarMensajeView(VerificarPermisoMixin, LoginRequiredMixin, FormView):
    vista_nombre = "Chat - Enviar mensaje"
    permiso_requerido = "ingresar"
    template_name = 'enviar_mensaje.html'
    form_class = MensajeForm

    def dispatch(self, request, *args, **kwargs):
        empresa_check = assert_empresa_activa(request)
        if empresa_check:
            return empresa_check
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['conversacion'] = self.get_conversacion()
        return context

    def get_conversacion(self):
        empresa_id = get_empresa_activa_id(self.request)
        return get_object_or_404(
            Conversacion,
            id=self.kwargs['conversacion_id'],
            empresa_id=empresa_id,
            participantes=self.request.user,
        )

    def form_valid(self, form):
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


class DetalleConversacionView(VerificarPermisoMixin, LoginRequiredMixin, DetailView):
    vista_nombre = "Chat - Ver conversación"
    permiso_requerido = "ingresar"
    model = Conversacion
    template_name = 'detalle_conversacion.html'
    context_object_name = 'conversacion'
    form_class = EnviarMensajeForm

    def dispatch(self, request, *args, **kwargs):
        empresa_check = assert_empresa_activa(request)
        if empresa_check:
            return empresa_check
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        empresa_id = get_empresa_activa_id(self.request)
        return super().get_queryset().filter(
            empresa_id=empresa_id,
            participantes=self.request.user,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        conversacion = self.get_object()
        mark_conversation_read(conversacion, self.request.user)
        context['mensajes'] = Mensaje.objects.filter(conversacion=conversacion)
        if 'form' not in context:
            context['form'] = self.get_form()
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.get_form()
        if form.is_valid():
            return self.form_valid(form)
        else:
            return self.form_invalid(form)

    def form_valid(self, form):
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


class EliminarConversacionView(VerificarPermisoMixin, LoginRequiredMixin, DeleteView):
    vista_nombre = "Chat - Eliminar conversación"
    permiso_requerido = "ingresar"
    model = Conversacion
    template_name = 'eliminar_conversacion.html'
    context_object_name = 'conversacion'
    success_url = reverse_lazy('lista_conversaciones')

    def dispatch(self, request, *args, **kwargs):
        empresa_check = assert_empresa_activa(request)
        if empresa_check:
            return empresa_check
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        empresa_id = get_empresa_activa_id(self.request)
        return super().get_queryset().filter(
            empresa_id=empresa_id,
            participantes=self.request.user,
        )
