# views.py
from datetime import date
from io import BytesIO
import json
import os
import zipfile

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.mail import EmailMultiAlternatives, get_connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.timezone import now
from django.views.generic import TemplateView, View
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView, DeleteView, UpdateView
from django.views.generic.list import ListView
from django.views.decorators.http import require_POST

from .forms import PropiedadForm, PropietarioForm, TipoDocumentoForm
from .models import Documento, Propiedad, Propietario, TipoDocumento

# OFFICIAL IMPORTS
from access_control.decorators import verificar_permiso
from access_control.models import Empresa
from access_control.views import VerificarPermisoMixin  # OFFICIAL VERSION
from auditoria.mixins import AuditMixin
from settings.models import UserPreferences


class CrearPropietarioModalView(VerificarPermisoMixin, LoginRequiredMixin, View):
    model = Propietario
    vista_nombre = "Biblioteca - Crear Propietario Modal"
    permiso_requerido = "crear"

    def post(self, request, *args, **kwargs):
        from auditoria.helpers import audit_log
        from auditoria.services import AuditoriaService

        try:
            data = json.loads(request.body or "{}")
            form = PropietarioForm(data)

            if form.is_valid():
                propietario = form.save()

                after_snapshot = AuditoriaService.model_to_snapshot(propietario)
                changes = AuditoriaService.diff_snapshots(None, after_snapshot)

                audit_log(
                    request=request,
                    action="CREATE",
                    app_label="biblioteca",
                    obj=propietario,
                    after=after_snapshot,
                    vista_nombre=self.vista_nombre,
                    status_code=200,
                    meta={
                        "entity": "Propietario",
                        "source": "modal",
                        "changes": changes,
                    },
                )

                return JsonResponse(
                    {
                        "success": True,
                        "id": propietario.id,
                        "nombre": propietario.nombre,
                    }
                )

            errors = form.errors.get_json_data()
            error_messages = [e["message"] for field in errors.values() for e in field]
            return JsonResponse({"success": False, "error": " | ".join(error_messages)})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})


class ModalesEjemploView(LoginRequiredMixin, TemplateView):
    template_name = "modales_ejemplo.html"


### respaldo biblioteca completa ###
@login_required
@verificar_permiso("Biblioteca - Respaldo Biblioteca", "ingresar")
def respaldo_biblioteca_zip(request):
    from auditoria.helpers import audit_log

    carpeta_archivos = os.path.join(settings.MEDIA_ROOT, "archivos_documentos")
    fecha_str = date.today().strftime("%Y%m%d")
    nombre_zip = f"respaldo_Biblioteca{fecha_str}.zip"

    buffer = BytesIO()
    file_count = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for root, dirs, files in os.walk(carpeta_archivos):
            for file in files:
                ruta_absoluta = os.path.join(root, file)
                ruta_relativa = os.path.relpath(ruta_absoluta, settings.MEDIA_ROOT)
                zip_file.write(ruta_absoluta, arcname=ruta_relativa)
                file_count += 1

    buffer.seek(0)
    response = HttpResponse(buffer, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{nombre_zip}"'

    audit_log(
        request=request,
        action="DOWNLOAD",
        app_label="biblioteca",
        obj=None,
        vista_nombre="Biblioteca - Respaldo Biblioteca",
        status_code=getattr(response, "status_code", None),
        meta={
            "download_type": "backup_zip",
            "filename": nombre_zip,
            "file_count": file_count,
        },
    )

    return response


### respaldo por rol ###
@login_required
@verificar_permiso("Biblioteca - Descargar Propiedad", "ingresar")
def descargar_documentos_propiedad_zip(request, propiedad_id):
    from auditoria.helpers import audit_log

    propiedad = get_object_or_404(Propiedad, pk=propiedad_id)
    documentos = Documento.objects.filter(propiedad=propiedad)

    fecha_str = date.today().strftime("%Y%m%d")
    nombre_zip = f"respaldo_rol_{propiedad.rol}_{fecha_str}.zip"

    buffer = BytesIO()
    file_count = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for doc in documentos:
            if doc.archivo and os.path.isfile(doc.archivo.path):
                ruta_archivo = doc.archivo.path
                nombre_archivo = os.path.basename(ruta_archivo)
                zip_file.write(ruta_archivo, arcname=nombre_archivo)
                file_count += 1

    buffer.seek(0)
    response = HttpResponse(buffer, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{nombre_zip}"'

    audit_log(
        request=request,
        action="DOWNLOAD",
        app_label="biblioteca",
        obj=propiedad,
        vista_nombre="Biblioteca - Descargar Propiedad",
        status_code=getattr(response, "status_code", None),
        meta={
            "download_type": "propiedad_zip",
            "filename": nombre_zip,
            "file_count": file_count,
            "rol": getattr(propiedad, "rol", None),
        },
    )

    return response


###########################################################################
########            CRUD MAESTRO DE PROPIEDADES                  ########
###########################################################################
# CREATE
class CrearPropiedadView(AuditMixin, VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = Propiedad
    form_class = PropiedadForm
    template_name = "crear_propiedad.html"
    vista_nombre = "Biblioteca - Crear Propiedad"
    permiso_requerido = "crear"
    audit_action = "CREATE"
    audit_app_label = "biblioteca"

    def get_success_url(self):
        if hasattr(self, "object") and self.object.propietario:
            return reverse(
                "biblioteca:detalle_propietario", kwargs={"pk": self.object.propietario.id}
            )
        propietario_id = self.kwargs.get("propietario_id", None)
        if propietario_id:
            return reverse("biblioteca:detalle_propietario", kwargs={"pk": propietario_id})
        return reverse("biblioteca:listar_propiedades")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["propietarios"] = Propietario.objects.all()

        propietario_id = self.kwargs.get("propietario_id") or self.request.POST.get("propietario")
        if propietario_id:
            propietario = get_object_or_404(Propietario, id=propietario_id)
            context["propietario_nombre"] = propietario.nombre
            context["propietario_id"] = propietario.id
        else:
            context["propietario_nombre"] = None
            context["propietario_id"] = None

        return context

    def get_initial(self):
        initial = super().get_initial()
        propietario_id = self.kwargs.get("propietario_id", None)
        if propietario_id:
            try:
                propietario = Propietario.objects.get(id=propietario_id)
                initial["propietario"] = propietario.id
            except Propietario.DoesNotExist:
                pass
        return initial

    def form_valid(self, form):
        propietario_id = self.kwargs.get("propietario_id", None)
        if propietario_id:
            propietario = get_object_or_404(Propietario, id=propietario_id)
            form.instance.propietario = propietario
        return super().form_valid(form)

    def form_invalid(self, form):
        print("Formulario inválido:", form.errors)
        propietario_id = self.request.POST.get("propietario", None)
        propietario_nombre = None
        if propietario_id:
            try:
                propietario_nombre = Propietario.objects.get(id=propietario_id).nombre
            except Propietario.DoesNotExist:
                pass
        context = self.get_context_data(form=form)
        context["propietario_nombre"] = propietario_nombre
        return self.render_to_response(context)


# READ
class DetallePropiedadView(AuditMixin, VerificarPermisoMixin, LoginRequiredMixin, DetailView):
    model = Propiedad
    template_name = "detalle_propiedad.html"
    context_object_name = "propiedad"
    vista_nombre = "Biblioteca - Detalle Propiedad"
    permiso_requerido = "ingresar"
    audit_action = "VIEW"
    audit_app_label = "biblioteca"


# READ (LIST)
class ListarPropiedadesView(AuditMixin, VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = Propiedad
    template_name = "listado_propiedades.html"
    context_object_name = "propiedades"
    vista_nombre = "Biblioteca - Listar Propiedades"
    permiso_requerido = "ingresar"
    audit_action = "VIEW"
    audit_app_label = "biblioteca"


# UPDATE
class ModificarPropiedadView(AuditMixin, VerificarPermisoMixin, LoginRequiredMixin, UpdateView):
    model = Propiedad
    form_class = PropiedadForm
    template_name = "modificar_propiedad.html"
    success_url = reverse_lazy("biblioteca:listar_propiedades")
    vista_nombre = "Biblioteca - Modificar Propiedad"
    permiso_requerido = "modificar"
    audit_action = "UPDATE"
    audit_app_label = "biblioteca"

    def form_valid(self, form):
        from auditoria.helpers import audit_log
        from auditoria.services import AuditoriaService

        obj_db = self.get_object()
        before_snapshot = AuditoriaService.model_to_snapshot(obj_db)

        response = super().form_valid(form)

        after_snapshot = AuditoriaService.model_to_snapshot(self.object)
        changes = AuditoriaService.diff_snapshots(before_snapshot, after_snapshot)

        audit_log(
            request=self.request,
            action="UPDATE",
            app_label="biblioteca",
            obj=self.object,
            before=before_snapshot,
            after=after_snapshot,
            vista_nombre=self.vista_nombre,
            status_code=getattr(response, "status_code", None),
            meta={"entity": "Propiedad", "changes": changes},
        )

        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["propiedad"] = self.object
        context["propietario_nombre"] = self.object.propietario.nombre if self.object.propietario else ""
        return context


# DELETE
class EliminarPropiedadView(VerificarPermisoMixin, LoginRequiredMixin, DeleteView):
    model = Propiedad
    template_name = "eliminar_propiedad.html"
    success_url = reverse_lazy("biblioteca:listar_propiedades")
    vista_nombre = "Biblioteca - Eliminar Propiedad"
    permiso_requerido = "eliminar"

    def form_valid(self, form):
        from auditoria.helpers import audit_log
        from auditoria.services import AuditoriaService

        obj = self.get_object()
        before_snapshot = AuditoriaService.model_to_snapshot(obj)

        response = super().form_valid(form)

        audit_log(
            request=self.request,
            action="DELETE",
            app_label="biblioteca",
            obj=obj,
            before=before_snapshot,
            vista_nombre=self.vista_nombre,
            status_code=getattr(response, "status_code", None),
            meta={"entity": "Propiedad"},
        )

        return response


###########################################################################
########            CRUD MAESTRO DE PROPIETARIOS                   ########
###########################################################################
# CREATE
class CrearPropietarioView(AuditMixin, VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = Propietario
    form_class = PropietarioForm
    template_name = "crear_propietario.html"
    success_url = reverse_lazy("biblioteca:listar_propietarios")
    vista_nombre = "Biblioteca - Crear Propietario"
    permiso_requerido = "crear"
    audit_action = "CREATE"
    audit_app_label = "biblioteca"


# READ
class DetallePropietarioView(AuditMixin, VerificarPermisoMixin, LoginRequiredMixin, DetailView):
    model = Propietario
    template_name = "detalle_propietario.html"
    context_object_name = "propietario"
    vista_nombre = "Biblioteca - Detalle Propietario"
    permiso_requerido = "ingresar"
    audit_action = "VIEW"
    audit_app_label = "biblioteca"


# READ (LIST)
class ListarPropietariosView(AuditMixin, VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = Propietario
    template_name = "listado_propietarios.html"
    context_object_name = "propietarios"
    vista_nombre = "Biblioteca - Listar Propietarios"
    permiso_requerido = "ingresar"
    audit_action = "VIEW"
    audit_app_label = "biblioteca"


# UPDATE
class ModificarPropietarioView(AuditMixin, VerificarPermisoMixin, LoginRequiredMixin, UpdateView):
    model = Propietario
    form_class = PropietarioForm
    template_name = "modificar_propietario.html"
    success_url = reverse_lazy("biblioteca:listar_propietarios")
    vista_nombre = "Biblioteca - Modificar Propietario"
    permiso_requerido = "modificar"
    audit_action = "UPDATE"
    audit_app_label = "biblioteca"

    def form_valid(self, form):
        from auditoria.helpers import audit_log
        from auditoria.services import AuditoriaService

        obj_db = self.get_object()
        before_snapshot = AuditoriaService.model_to_snapshot(obj_db)

        response = super().form_valid(form)

        after_snapshot = AuditoriaService.model_to_snapshot(self.object)
        changes = AuditoriaService.diff_snapshots(before_snapshot, after_snapshot)

        audit_log(
            request=self.request,
            action="UPDATE",
            app_label="biblioteca",
            obj=self.object,
            before=before_snapshot,
            after=after_snapshot,
            vista_nombre=self.vista_nombre,
            status_code=getattr(response, "status_code", None),
            meta={"entity": "Propietario", "changes": changes},
        )

        return response


# DELETE
class EliminarPropietarioView(VerificarPermisoMixin, LoginRequiredMixin, DeleteView):
    model = Propietario
    template_name = "eliminar_propietario.html"
    success_url = reverse_lazy("biblioteca:listar_propietarios")
    vista_nombre = "Biblioteca - Eliminar Propietario"
    permiso_requerido = "eliminar"

    def form_valid(self, form):
        from auditoria.helpers import audit_log
        from auditoria.services import AuditoriaService

        obj = self.get_object()
        before_snapshot = AuditoriaService.model_to_snapshot(obj)

        response = super().form_valid(form)

        audit_log(
            request=self.request,
            action="DELETE",
            app_label="biblioteca",
            obj=obj,
            before=before_snapshot,
            vista_nombre=self.vista_nombre,
            status_code=getattr(response, "status_code", None),
            meta={"entity": "Propietario"},
        )

        return response


###########################################################################
########            CRUD MAESTRO DE TIPOS DE DOCUMENTOS            ########
###########################################################################
# CREATE
class CrearTipoDocumentoView(AuditMixin, VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = TipoDocumento
    form_class = TipoDocumentoForm
    template_name = "crear_tipo_documento.html"
    success_url = reverse_lazy("biblioteca:listar_tipos_documentos")
    vista_nombre = "Biblioteca - Crear Tipo Documento"
    permiso_requerido = "crear"
    audit_action = "CREATE"
    audit_app_label = "biblioteca"


# READ (LIST)
class ListarTiposDocumentosView(AuditMixin, VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = TipoDocumento
    template_name = "listar_tipos_documentos.html"
    context_object_name = "tipos_documentos"
    vista_nombre = "Biblioteca - Listar Tipos Documentos"
    permiso_requerido = "ingresar"
    audit_action = "VIEW"
    audit_app_label = "biblioteca"


# UPDATE (custom View)
class ModificarTipoDocumentoView(VerificarPermisoMixin, LoginRequiredMixin, View):
    template_name = "modificar_tipo_documento.html"
    success_url = reverse_lazy("biblioteca:listar_tipos_documentos")
    vista_nombre = "Biblioteca - Modificar Tipo Documento"
    permiso_requerido = "modificar"

    def get(self, request, pk):
        tipo_documento = get_object_or_404(TipoDocumento, pk=pk)
        form = TipoDocumentoForm(instance=tipo_documento)
        return render(request, self.template_name, {"form": form})

    def post(self, request, pk):
        from auditoria.helpers import audit_log
        from auditoria.services import AuditoriaService

        tipo_documento = get_object_or_404(TipoDocumento, pk=pk)

        before_snapshot = AuditoriaService.model_to_snapshot(tipo_documento)

        form = TipoDocumentoForm(request.POST, instance=tipo_documento)
        if form.is_valid():
            form.save()

            after_snapshot = AuditoriaService.model_to_snapshot(tipo_documento)
            changes = AuditoriaService.diff_snapshots(before_snapshot, after_snapshot)

            response = redirect(self.success_url)

            audit_log(
                request=request,
                action="UPDATE",
                app_label="biblioteca",
                obj=tipo_documento,
                before=before_snapshot,
                after=after_snapshot,
                vista_nombre=self.vista_nombre,
                status_code=getattr(response, "status_code", None),
                meta={"entity": "TipoDocumento", "changes": changes},
            )

            return response

        return render(request, self.template_name, {"form": form})


# DELETE (custom View)
class EliminarTipoDocumentoView(VerificarPermisoMixin, LoginRequiredMixin, View):
    template_name = "eliminar_tipo_documento.html"
    success_url = reverse_lazy("biblioteca:listar_tipos_documentos")
    vista_nombre = "Biblioteca - Eliminar Tipo Documento"
    permiso_requerido = "eliminar"

    def get(self, request, pk):
        tipo_documento = get_object_or_404(TipoDocumento, pk=pk)
        return render(request, self.template_name, {"tipo_documento": tipo_documento})

    def post(self, request, pk):
        from auditoria.helpers import audit_log
        from auditoria.services import AuditoriaService

        tipo_documento = get_object_or_404(TipoDocumento, pk=pk)
        before_snapshot = AuditoriaService.model_to_snapshot(tipo_documento)

        tipo_documento.delete()
        response = redirect(self.success_url)

        audit_log(
            request=request,
            action="DELETE",
            app_label="biblioteca",
            obj=tipo_documento,
            before=before_snapshot,
            vista_nombre=self.vista_nombre,
            status_code=getattr(response, "status_code", None),
            meta={"entity": "TipoDocumento"},
        )

        return response


###########################################################################
########            CRUD MAESTRO DE DOCUMENTOS                    ########
###########################################################################
# CREATE
class CrearDocumentoView(AuditMixin, VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = Documento
    fields = ["tipo_documento", "nombre_documento", "archivo", "fecha_documento", "fecha_vencimiento"]
    template_name = "crear_documento.html"
    vista_nombre = "Biblioteca - Crear Documento"
    permiso_requerido = "modificar"
    audit_action = "CREATE"
    audit_app_label = "biblioteca"

    def get_initial(self):
        propiedad = get_object_or_404(Propiedad, pk=self.kwargs["pk"])
        return {"propiedad": propiedad}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["propiedad"] = get_object_or_404(Propiedad, pk=self.kwargs["pk"])
        return context

    def form_valid(self, form):
        propiedad = get_object_or_404(Propiedad, pk=self.kwargs["pk"])
        form.instance.propiedad = propiedad
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("biblioteca:detalle_propiedad", kwargs={"pk": self.kwargs["pk"]})


# READ (LIST)
class ListadoDocumentosView(AuditMixin, VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = Documento
    template_name = "listado_documentos.html"
    context_object_name = "documentos"
    vista_nombre = "Biblioteca - Listar Documentos"
    permiso_requerido = "ingresar"
    audit_action = "VIEW"
    audit_app_label = "biblioteca"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["empresa"] = Empresa.objects.get(pk=self.request.session.get("empresa_id"))
        context["fecha_actual"] = now()
        return context

    def get_queryset(self):
        return Documento.objects.select_related("propiedad", "tipo_documento")


# SHARE (email link)
@require_POST
@login_required
@verificar_permiso("Biblioteca - Enviar Enlace Documento", "ingresar")
def enviar_enlace_documento(request, documento_id):
    from auditoria.helpers import audit_log

    vista_nombre = "Biblioteca - Enviar Enlace Documento"

    try:
        email_destino = request.POST.get("correo")
        if not email_destino:
            return JsonResponse({"success": False, "error": "Correo destino no proporcionado."})

        documento = Documento.objects.get(pk=documento_id)
        prefs = UserPreferences.objects.get(user=request.user)
        enlace = request.build_absolute_uri(documento.archivo.url)
        rol = documento.propiedad.rol

        connection = get_connection(
            host=prefs.smtp_host,
            port=prefs.smtp_port,
            username=prefs.smtp_username,
            password=prefs.smtp_password,
            use_tls=(prefs.smtp_encryption == "STARTTLS"),
            use_ssl=(prefs.smtp_encryption == "SSL"),
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
            connection=connection,
        )
        email.attach_alternative(body_html, "text/html")
        email.send()

        email_parts = email_destino.split("@")
        email_masked = f"{email_parts[0][:3]}***@{email_parts[1]}" if len(email_parts) == 2 else "***@***"

        audit_log(
            request=request,
            action="SHARE",
            app_label="biblioteca",
            obj=documento,
            vista_nombre=vista_nombre,
            status_code=200,
            meta={
                "share_type": "email_link",
                "to_email_masked": email_masked,
                "rol": rol,
                "document_name": documento.nombre_documento,
            },
        )

        return JsonResponse({"success": True})

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


# DELETE
class EliminarDocumentoView(VerificarPermisoMixin, LoginRequiredMixin, DeleteView):
    model = Documento
    template_name = "eliminar_documento.html"
    vista_nombre = "Biblioteca - Eliminar Documento"
    permiso_requerido = "eliminar"

    def form_valid(self, form):
        from auditoria.helpers import audit_log
        from auditoria.services import AuditoriaService

        obj = self.get_object()
        before_snapshot = AuditoriaService.model_to_snapshot(obj)

        response = super().form_valid(form)

        audit_log(
            request=self.request,
            action="DELETE",
            app_label="biblioteca",
            obj=obj,
            before=before_snapshot,
            vista_nombre=self.vista_nombre,
            status_code=getattr(response, "status_code", None),
            meta={"entity": "Documento"},
        )

        return response

    def get_success_url(self):
        documento = self.object
        return reverse_lazy("biblioteca:detalle_propiedad", kwargs={"pk": documento.propiedad.pk})
