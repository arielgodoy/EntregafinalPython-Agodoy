# views.py
from django.views.generic.edit import UpdateView
from django.views.generic import TemplateView
from django.views.generic.list import ListView
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView, DeleteView
from django.shortcuts import render, redirect,get_object_or_404
from .models import Propiedad, Documento,Propietario
from .forms import PropietarioForm,PropiedadForm
from django.urls import reverse
from django.views.generic.edit import DeleteView
from django.urls import reverse_lazy
from .models import TipoDocumento
from .forms import TipoDocumentoForm
from django.views.generic import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse, reverse_lazy
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from access_control.decorators import verificar_permiso
from access_control.models import Empresa
from django.urls import reverse_lazy, reverse
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.core.mail import EmailMultiAlternatives, get_connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from settings.models import UserPreferences
from biblioteca.models import Documento
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils.timezone import now

import os
import zipfile
from io import BytesIO
from django.http import HttpResponse
from django.conf import settings
from django.contrib.auth.decorators import login_required
from datetime import date

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


class ModalesEjemploView(LoginRequiredMixin, TemplateView):
    template_name = 'modales_ejemplo.html'

### respaldo biblioteca completa ###
@login_required
def respaldo_biblioteca_zip(request):
    # Ruta absoluta al directorio de archivos
    carpeta_archivos = os.path.join(settings.MEDIA_ROOT, 'archivos_documentos')
    fecha_str = date.today().strftime("%Y%m%d")
    nombre_zip = f"respaldo_Biblioteca{fecha_str}.zip"

    # Comprimir todo el contenido de la carpeta
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for root, dirs, files in os.walk(carpeta_archivos):
            for file in files:
                ruta_absoluta = os.path.join(root, file)
                ruta_relativa = os.path.relpath(ruta_absoluta, settings.MEDIA_ROOT)
                zip_file.write(ruta_absoluta, arcname=ruta_relativa)

    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{nombre_zip}"'
    return response
### respaldo por rol ###
@login_required
def descargar_documentos_propiedad_zip(request, propiedad_id):
    propiedad = get_object_or_404(Propiedad, pk=propiedad_id)
    documentos = Documento.objects.filter(propiedad=propiedad)

    fecha_str = date.today().strftime("%Y%m%d")
    nombre_zip = f"respaldo_rol_{propiedad.rol}_{fecha_str}.zip"

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for doc in documentos:
            if doc.archivo and os.path.isfile(doc.archivo.path):
                ruta_archivo = doc.archivo.path
                nombre_archivo = os.path.basename(ruta_archivo)
                zip_file.write(ruta_archivo, arcname=nombre_archivo)

    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{nombre_zip}"'
    return response


###########################################################################
########            CRUD MAESTRO DE PROPIEDADES                  ########
###########################################################################
#CREATE
class CrearPropiedadView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = Propiedad
    form_class = PropiedadForm
    template_name = 'crear_propiedad.html'
    vista_nombre = "Maestro Propiedades"
    permiso_requerido = "crear"

    def get_success_url(self):
        """
        Redirige al detalle del propietario si `propietario_id` está presente,
        de lo contrario, a la lista de propiedades.
        """
        # Usar self.object.propietario.id si el propietario ya está asociado
        if hasattr(self, 'object') and self.object.propietario:
            return reverse('biblioteca:detalle_propietario', kwargs={'pk': self.object.propietario.id})
        # Si no, usa el propietario_id desde kwargs
        propietario_id = self.kwargs.get('propietario_id', None)
        if propietario_id:
            return reverse('biblioteca:detalle_propietario', kwargs={'pk': propietario_id})
        return reverse('biblioteca:listar_propiedades')

    def get_context_data(self, **kwargs):
        """Agrega el propietario preseleccionado al contexto."""
        context = super().get_context_data(**kwargs)
        context['propietarios'] = Propietario.objects.all()

        # Verificar si se pasa `propietario_id` por la URL o el formulario
        propietario_id = self.kwargs.get('propietario_id') or self.request.POST.get('propietario')
        if propietario_id:
            propietario = get_object_or_404(Propietario, id=propietario_id)
            context['propietario_nombre'] = propietario.nombre
            context['propietario_id'] = propietario.id
        else:
            context['propietario_nombre'] = None
            context['propietario_id'] = None

        return context

    def get_initial(self):
        """Preselecciona el propietario si `propietario_id` está presente en la URL."""
        initial = super().get_initial()
        propietario_id = self.kwargs.get('propietario_id', None)
        if propietario_id:
            try:
                propietario = Propietario.objects.get(id=propietario_id)
                initial['propietario'] = propietario.id
            except Propietario.DoesNotExist:
                pass
        return initial

    def form_valid(self, form):
        """Asocia la propiedad al propietario si `propietario_id` está presente."""
        propietario_id = self.kwargs.get('propietario_id', None)
        if propietario_id:
            propietario = get_object_or_404(Propietario, id=propietario_id)
            form.instance.propietario = propietario
        # Asegura que self.object esté disponible para get_success_url
        self.object = form.save()
        return super().form_valid(form)

    def form_invalid(self, form):
        """Maneja los errores del formulario y recupera el propietario."""
        print("Formulario inválido:", form.errors)
        propietario_id = self.request.POST.get('propietario', None)
        propietario_nombre = None
        if propietario_id:
            try:
                propietario_nombre = Propietario.objects.get(id=propietario_id).nombre
            except Propietario.DoesNotExist:
                pass
        context = self.get_context_data(form=form)
        context['propietario_nombre'] = propietario_nombre
        return self.render_to_response(context)
#READ
class DetallePropiedadView(VerificarPermisoMixin, LoginRequiredMixin, DetailView):
    model = Propiedad    
    template_name = 'detalle_propiedad.html'
    context_object_name = 'propiedad'
    vista_nombre = "Detalle de Propiedad"
    permiso_requerido = "ingresar"
#READ
class ListarPropiedadesView(VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = Propiedad
    template_name = 'listado_propiedades.html'
    context_object_name = 'propiedades'
    vista_nombre = "Listado de Propiedades"
    permiso_requerido = "ingresar"
#UPDATE
class ModificarPropiedadView(VerificarPermisoMixin, LoginRequiredMixin, UpdateView):
    model = Propiedad
    form_class = PropiedadForm
    template_name = 'modificar_propiedad.html'
    success_url = reverse_lazy('biblioteca:listar_propiedades')
    vista_nombre = "Maestro Propiedades"
    permiso_requerido = "modificar"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['propiedad'] = self.object
        context['propietario_nombre'] = self.object.propietario.nombre if self.object.propietario else ""
        return context
#DELETE
class EliminarPropiedadView(VerificarPermisoMixin,LoginRequiredMixin,DeleteView):
    model = Propiedad
    template_name = 'eliminar_propiedad.html'
    success_url = reverse_lazy('biblioteca:listar_propiedades')
    vista_nombre="Maestro Propiedades"
    permiso_requerido="eliminar"

    def form_valid(self, form):
        # Obtener la propiedad a eliminar
        propiedad = self.get_object()
        # Eliminar la propiedad
        propiedad.delete()
        return redirect(self.success_url)

###########################################################################




###########################################################################
########            CRUD MAESTRO DE PROPIETARIOS                   ########
###########################################################################
#CREATE
class CrearPropietarioView(VerificarPermisoMixin,LoginRequiredMixin,CreateView):
    model = Propietario
    form_class = PropietarioForm
    template_name = 'crear_propietario.html'
    success_url = reverse_lazy('biblioteca:listar_propietarios')
    vista_nombre="Maestro Propietarios"
    permiso_requerido="crear"
#READ
class DetallePropietarioView(VerificarPermisoMixin,LoginRequiredMixin,DetailView):
    model = Propietario
    template_name = 'detalle_propietario.html'
    context_object_name = 'propietario'
    vista_nombre="Detalle Propietario" 
    permiso_requerido="ingresar"
#READ
class ListarPropietariosView(VerificarPermisoMixin,LoginRequiredMixin,ListView):    
    model = Propietario
    template_name = 'listado_propietarios.html'
    context_object_name = 'propietarios'
    vista_nombre="Listar Propietarios" 
    permiso_requerido="ingresar"

#UPDATE
class ModificarPropietarioView(VerificarPermisoMixin,LoginRequiredMixin,UpdateView):
    model = Propietario
    form_class = PropietarioForm
    template_name = 'modificar_propietario.html'
    success_url = reverse_lazy('biblioteca:listar_propietarios')
    vista_nombre="Maestro Propietarios" 
    permiso_requerido="modificar"
#DELETE
class EliminarPropietarioView(VerificarPermisoMixin,LoginRequiredMixin,DeleteView):
    model = Propietario
    template_name = 'eliminar_propietario.html'
    success_url = reverse_lazy('biblioteca:listar_propietarios')
    vista_nombre="Maestro Propietarios" 
    permiso_requerido="eliminar"


    
###########################################################################    




###########################################################################
########            CRUD MAESTRO DE TIPOS DE DOCUMENTOS            ########
###########################################################################
#CREATE
class CrearTipoDocumentoView(VerificarPermisoMixin,LoginRequiredMixin,CreateView):
    model = TipoDocumento
    form_class = TipoDocumentoForm
    template_name = 'crear_tipo_documento.html'
    success_url = reverse_lazy('biblioteca:listar_tipos_documentos')
    vista_nombre="Maestro tipos de Documentos"
    permiso_requerido="crear"
#READ
class ListarTiposDocumentosView(VerificarPermisoMixin,LoginRequiredMixin,ListView):
    model = TipoDocumento
    template_name = 'listar_tipos_documentos.html'
    context_object_name = 'tipos_documentos'
    vista_nombre="Maestro tipos de Documentos"
    permiso_requerido="ingresar"
#UPDATE
class ModificarTipoDocumentoView(VerificarPermisoMixin,LoginRequiredMixin,View):
    template_name = 'modificar_tipo_documento.html'
    success_url = reverse_lazy('biblioteca:listar_tipos_documentos')
    vista_nombre="Maestro tipos de Documentos"
    permiso_requerido="modificar"

    def get(self, request, pk):
        tipo_documento = get_object_or_404(TipoDocumento, pk=pk)
        form = TipoDocumentoForm(instance=tipo_documento)
        return render(request, self.template_name, {'form': form})

    def post(self, request, pk):
        tipo_documento = get_object_or_404(TipoDocumento, pk=pk)
        form = TipoDocumentoForm(request.POST, instance=tipo_documento)
        if form.is_valid():
            form.save()
            return redirect(self.success_url)
        return render(request, self.template_name, {'form': form})
#DELETE
class EliminarTipoDocumentoView(VerificarPermisoMixin,LoginRequiredMixin,View):
    template_name = 'eliminar_tipo_documento.html'
    success_url = reverse_lazy('biblioteca:listar_tipos_documentos')
    vista_nombre="Maestro tipos de Documentos"
    permiso_requerido="eliminar"

    def get(self, request, pk):
        tipo_documento = get_object_or_404(TipoDocumento, pk=pk)
        return render(request, self.template_name, {'tipo_documento': tipo_documento})

    def post(self, request, pk):
        tipo_documento = get_object_or_404(TipoDocumento, pk=pk)
        tipo_documento.delete()
        return redirect(self.success_url)
###########################################################################







###########################################################################
########            CRUD MAESTRO DE DOCUMENTOS                   ########
###########################################################################
#CREATE
class CrearDocumentoView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = Documento
    fields = ['tipo_documento', 'nombre_documento', 'archivo', 'fecha_documento', 'fecha_vencimiento']
    template_name = 'crear_documento.html'
    vista_nombre = "Maestro Propiedades"
    permiso_requerido = "modificar"

    def get_initial(self):
        propiedad = get_object_or_404(Propiedad, pk=self.kwargs['pk'])
        return {'propiedad': propiedad}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['propiedad'] = get_object_or_404(Propiedad, pk=self.kwargs['pk'])
        return context

    def form_valid(self, form):
        propiedad = get_object_or_404(Propiedad, pk=self.kwargs['pk'])
        form.instance.propiedad = propiedad
        return super().form_valid(form)

    def get_success_url(self):
        # Redirigir al detalle de la propiedad después de crear un nuevo documento
        return reverse('biblioteca:detalle_propiedad', kwargs={'pk': self.kwargs['pk']})
#READ
class ListadoDocumentosView(VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = Documento
    template_name = 'listado_documentos.html'
    context_object_name = 'documentos'
    vista_nombre = "Listado General de Documentos"  # Puedes ajustarlo según tu tabla VistaPermiso
    permiso_requerido = "ingresar"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)        
        context["empresa"] = Empresa.objects.get(pk=self.request.session.get("empresa_id"))
        context["fecha_actual"] = now()
        return context

    def get_queryset(self):
        return Documento.objects.select_related('propiedad', 'tipo_documento')
#READ
@csrf_exempt
@require_POST
@login_required
def enviar_enlace_documento(request, documento_id):
    try:
        email_destino = request.POST.get('correo')
        if not email_destino:
            return JsonResponse({"success": False, "error": "Correo destino no proporcionado."})

        documento = Documento.objects.get(pk=documento_id)
        prefs = UserPreferences.objects.get(user=request.user)
        enlace = request.build_absolute_uri(documento.archivo.url)
        rol = documento.propiedad.rol

        # Configuración segura del backend manual
        connection = get_connection(
            host=prefs.smtp_host,
            port=prefs.smtp_port,
            username=prefs.smtp_username,
            password=prefs.smtp_password,
            use_tls=(prefs.smtp_encryption == 'STARTTLS'),
            use_ssl=(prefs.smtp_encryption == 'SSL')
        )

        subject = f"Enlace al documento solicitado {documento.nombre_documento}"
        body_text = f"Hola,\n\nAquí tienes el enlace al documento:\n{enlace}"
        body_html = f"""
        <p>Se adjunta Link al documento solicitado asociado a la Propiedad <strong>ROL: {rol}</strong>:</p>        
        <p><a href="{enlace}" target="_blank">{documento.nombre_documento}</a></p>
        """

        email = EmailMultiAlternatives(
            subject,
            body_text,
            prefs.smtp_username,
            [email_destino],
            connection=connection
        )
        email.attach_alternative(body_html, "text/html")
        email.send()

        return JsonResponse({"success": True})

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})

#DELETE
class EliminarDocumentoView(VerificarPermisoMixin,LoginRequiredMixin, DeleteView):
    model = Documento
    template_name = 'eliminar_documento.html'  # Cambia esto si tienes un template para confirmar eliminación.
    vista_nombre="Maestro Documentos"
    permiso_requerido="eliminar"

    def get_success_url(self):
        """Redirige a la página de detalle de la propiedad asociada."""
        documento = self.object
        return reverse_lazy('biblioteca:detalle_propiedad', kwargs={'pk': documento.propiedad.pk})    
###########################################################################