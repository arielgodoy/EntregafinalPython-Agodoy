from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models
from django.db import transaction
from django.db.models import Avg
from django.urls import reverse_lazy
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from access_control.decorators import verificar_permiso
from access_control.views import VerificarPermisoMixin
from access_control.services.access_requests import build_access_request_context
from .models import Proyecto, Tarea, ClienteEmpresa, Profesional, TipoProyecto, EspecialidadProfesional, TipoTarea, TareaDocumento
from .forms import ProyectoForm, TareaForm, ClienteEmpresaForm, ProfesionalForm, TipoTareaForm, TareaDocumentoForm
import json
from control_operacional.services.alerts import notify_project_created, notify_project_overdue
import logging

logger = logging.getLogger(__name__)


def _get_empresa_id(request):
    return request.session.get("empresa_id")


class ListarProyectosView(VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = Proyecto
    template_name = 'control_de_proyectos/proyecto_lista.html'
    context_object_name = 'proyectos'
    paginate_by = 20
    vista_nombre = "Control de Proyectos - Proyectos"
    permiso_requerido = "ingresar"
    
    def dispatch(self, request, *args, **kwargs):
        empresa_id = _get_empresa_id(request)
        if not empresa_id:
            contexto = build_access_request_context(
                request,
                self.vista_nombre,
                "No tienes permisos suficientes para acceder a esta página.",
            )
            return render(request, "access_control/403_forbidden.html", contexto, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        empresa_id = _get_empresa_id(self.request)
        proyectos = Proyecto.objects.filter(empresa_interna_id=empresa_id).select_related(
            'empresa_interna', 'cliente', 'tipo_ref'
        ).annotate(
            avance_promedio=Avg('tareas__porcentaje_avance')
        ).prefetch_related(
            models.Prefetch(
                'tareas',
                queryset=Tarea.objects.only(
                    'id',
                    'proyecto_id',
                    'porcentaje_avance',
                    'fecha_inicio_plan',
                    'fecha_inicio_real',
                    'fecha_fin_plan',
                    'fecha_fin_real'
                )
            )
        )

        for proyecto in proyectos:
            tareas = list(proyecto.tareas.all())
            if not tareas:
                proyecto.avance_promedio = None
                proyecto.plazo_promedio = None
                proyecto.plazo_estado = None
                continue

            if proyecto.avance_promedio is not None:
                proyecto.avance_promedio = round(proyecto.avance_promedio)

            plazos_raw = [t.plazo_porcentaje for t in tareas if t.plazo_porcentaje is not None]
            if not plazos_raw:
                proyecto.plazo_promedio = None
                proyecto.plazo_estado = None
            else:
                plazos_display = [min(100, p) for p in plazos_raw]
                proyecto.plazo_promedio = round(sum(plazos_display) / len(plazos_display))
                promedio_raw = sum(plazos_raw) / len(plazos_raw)
                if promedio_raw <= 75:
                    proyecto.plazo_estado = "EN_TIEMPO"
                elif promedio_raw <= 100:
                    proyecto.plazo_estado = "EN_RIESGO"
                else:
                    proyecto.plazo_estado = "ATRASADO"

        return proyectos


@method_decorator(ensure_csrf_cookie, name="dispatch")
class DetalleProyectoView(VerificarPermisoMixin, LoginRequiredMixin, DetailView):
    model = Proyecto
    template_name = 'control_de_proyectos/proyecto_detalle.html'
    context_object_name = 'proyecto'
    vista_nombre = "Control de Proyectos - Detalle de proyecto"
    permiso_requerido = "ingresar"

    def get_queryset(self):
        empresa_id = _get_empresa_id(self.request)
        if not empresa_id:
            return Proyecto.objects.none()
        return Proyecto.objects.filter(empresa_interna_id=empresa_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tareas'] = self.object.tareas.all()
        return context


class CrearProyectoView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = Proyecto
    form_class = ProyectoForm
    template_name = 'control_de_proyectos/proyecto_form.html'
    vista_nombre = "Control de Proyectos - Crear proyecto"
    permiso_requerido = "crear"
    
    def dispatch(self, request, *args, **kwargs):
        empresa_id = _get_empresa_id(request)
        if not empresa_id:
            contexto = build_access_request_context(
                request,
                self.vista_nombre,
                "No tienes permisos suficientes para acceder a esta página.",
            )
            return render(request, "access_control/403_forbidden.html", contexto, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        empresa_id = _get_empresa_id(self.request)
        if not empresa_id:
            context['error'] = "No hay empresa seleccionada. Por favor, selecciona una empresa en el menú."
        return context

    def get_form_kwargs(self):
        """Pasar empresa_interna_id al formulario para validación de duplicados"""
        kwargs = super().get_form_kwargs()
        empresa_id = _get_empresa_id(self.request)
        kwargs['empresa_interna_id'] = empresa_id
        return kwargs

    def form_valid(self, form):
        empresa_id = _get_empresa_id(self.request)
        if not empresa_id:
            form.add_error(None, "No hay empresa seleccionada en la sesión")
            return self.form_invalid(form)
        form.instance.empresa_interna_id = empresa_id
        response = super().form_valid(form)
        notify_project_created(self.object, self.request.user)
        return response

    def get_success_url(self):
        return reverse_lazy('control_de_proyectos:detalle_proyecto', kwargs={'pk': self.object.pk})


class EditarProyectoView(VerificarPermisoMixin, LoginRequiredMixin, UpdateView):
    model = Proyecto
    form_class = ProyectoForm
    template_name = 'control_de_proyectos/proyecto_form.html'
    vista_nombre = "Control de Proyectos - Editar proyecto"
    permiso_requerido = "modificar"

    def get_queryset(self):
        empresa_id = _get_empresa_id(self.request)
        if not empresa_id:
            return Proyecto.objects.none()
        return Proyecto.objects.filter(empresa_interna_id=empresa_id)

    def get_form_kwargs(self):
        """Pasar empresa_interna_id al formulario para validación de duplicados"""
        kwargs = super().get_form_kwargs()
        empresa_id = _get_empresa_id(self.request)
        kwargs['empresa_interna_id'] = empresa_id
        return kwargs

    def get_initial(self):
        """Asegurar que las fechas se cargan correctamente"""
        initial = super().get_initial()
        if self.object:
            initial['fecha_inicio_estimada'] = self.object.fecha_inicio_estimada
            initial['fecha_termino_estimada'] = self.object.fecha_termino_estimada
        return initial

    def get_success_url(self):
        return reverse_lazy('control_de_proyectos:detalle_proyecto', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        notify_project_overdue(self.object, self.request.user)
        return response


class EliminarProyectoView(VerificarPermisoMixin, LoginRequiredMixin, DeleteView):
    model = Proyecto
    template_name = 'control_de_proyectos/proyecto_confirmar_eliminar.html'
    vista_nombre = "Control de Proyectos - Eliminar proyecto"
    permiso_requerido = "eliminar"
    success_url = reverse_lazy('control_de_proyectos:listar_proyectos')

    def get_queryset(self):
        empresa_id = _get_empresa_id(self.request)
        if not empresa_id:
            return Proyecto.objects.none()
        return Proyecto.objects.filter(empresa_interna_id=empresa_id)

    def post(self, request, *args, **kwargs):
        """Manejar eliminación vía AJAX conforme a AJAX_DELETION_PATTERN.md; fallback al flujo tradicional."""
        # Detección robusta de petición AJAX/fetch
        xrw = request.META.get('HTTP_X_REQUESTED_WITH')
        accept = request.META.get('HTTP_ACCEPT', '')
        is_ajax = (xrw == 'XMLHttpRequest') or ('application/json' in accept)

        if is_ajax:
            try:
                from auditoria.helpers import audit_log
                from auditoria.services import AuditoriaService

                with transaction.atomic():
                    self.object = self.get_object()

                    # Validar scoping por empresa
                    empresa_activa = _get_empresa_id(request) or request.session.get('empresa_id')
                    if hasattr(self.object, 'empresa_interna_id') and getattr(self.object, 'empresa_interna_id', None) is not None:
                        if empresa_activa and self.object.empresa_interna_id != empresa_activa:
                            return JsonResponse({'success': False, 'message': 'permission_delete_forbidden'}, status=403)

                    nombre = str(self.object)
                    before_snapshot = AuditoriaService.model_to_snapshot(self.object)
                    self.object.delete()

                    audit_log(
                        request=request,
                        action="DELETE",
                        app_label="control_de_proyectos",
                        obj=self.object,
                        before=before_snapshot,
                        vista_nombre=self.vista_nombre,
                        status_code=200,
                        meta={"entity": "Proyecto"},
                    )

                return JsonResponse({'success': True, 'message': f'"{nombre}" eliminado exitosamente'})
            except Exception as e:
                logger.exception('Error eliminando Proyecto (AJAX)')
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

        return super().post(request, *args, **kwargs)


class CrearTareaView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = Tarea
    form_class = TareaForm
    template_name = 'control_de_proyectos/tarea_form.html'
    vista_nombre = "Control de Proyectos - Crear tarea"
    permiso_requerido = "crear"
    
    def dispatch(self, request, *args, **kwargs):
        empresa_id = _get_empresa_id(request)
        if not empresa_id:
            contexto = build_access_request_context(
                request,
                self.vista_nombre,
                "No tienes permisos suficientes para acceder a esta página.",
            )
            return render(request, "access_control/403_forbidden.html", contexto, status=403)
        
        proyecto_id = self.kwargs.get('proyecto_id')
        if proyecto_id:
            try:
                proyecto = Proyecto.objects.get(pk=proyecto_id)
                if proyecto.empresa_interna_id != empresa_id:
                    contexto = build_access_request_context(
                        request,
                        self.vista_nombre,
                        "No tienes permisos suficientes para acceder a esta página.",
                    )
                    return render(request, "access_control/403_forbidden.html", contexto, status=403)
            except Proyecto.DoesNotExist:
                contexto = build_access_request_context(
                    request,
                    self.vista_nombre,
                    "No tienes permisos suficientes para acceder a esta página.",
                )
                return render(request, "access_control/403_forbidden.html", contexto, status=403)
        
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        """Pasar proyecto_id al formulario para filtración de campos"""
        kwargs = super().get_form_kwargs()
        proyecto_id = self.kwargs.get('proyecto_id')
        if proyecto_id:
            kwargs['proyecto_id'] = proyecto_id
        return kwargs

    def get_initial(self):
        """Preseleccionar proyecto si viene en URL"""
        initial = super().get_initial()
        proyecto_id = self.kwargs.get('proyecto_id')
        if proyecto_id:
            try:
                initial['proyecto'] = Proyecto.objects.get(pk=proyecto_id)
            except Proyecto.DoesNotExist:
                pass
        return initial

    def form_valid(self, form):
        proyecto_id = self.kwargs.get('proyecto_id')
        form.instance.proyecto_id = proyecto_id
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        proyecto_id = self.kwargs.get('proyecto_id')
        if proyecto_id:
            context['proyecto'] = Proyecto.objects.get(pk=proyecto_id)
        return context

    def get_success_url(self):
        proyecto_id = self.kwargs.get('proyecto_id')
        return reverse_lazy('control_de_proyectos:detalle_proyecto', kwargs={'pk': proyecto_id})


class EditarTareaView(VerificarPermisoMixin, LoginRequiredMixin, UpdateView):
    model = Tarea
    form_class = TareaForm
    template_name = 'control_de_proyectos/tarea_form.html'
    vista_nombre = "Control de Proyectos - Editar tarea"
    permiso_requerido = "modificar"
    
    def get_queryset(self):
        empresa_id = _get_empresa_id(self.request)
        if not empresa_id:
            return Tarea.objects.none()
        return Tarea.objects.select_related('proyecto').filter(
            proyecto__empresa_interna_id=empresa_id
        )

    def get_form_kwargs(self):
        """Pasar proyecto_id al formulario para filtración de campos"""
        kwargs = super().get_form_kwargs()
        # El proyecto_id viene del objeto tarea que se está editando
        if self.object and self.object.proyecto_id:
            kwargs['proyecto_id'] = self.object.proyecto_id
        return kwargs

    def get_success_url(self):
        return reverse_lazy('control_de_proyectos:detalle_proyecto', kwargs={'pk': self.object.proyecto.pk})

    def post(self, request, *args, **kwargs):
        # Soportar eliminación vía AJAX/fetch con respuesta JSON y auditoría
        xrw = request.META.get('HTTP_X_REQUESTED_WITH')
        accept = request.META.get('HTTP_ACCEPT', '')
        is_ajax = (xrw == 'XMLHttpRequest') or ('application/json' in accept)

        if is_ajax:
            try:
                from auditoria.helpers import audit_log
                from auditoria.services import AuditoriaService

                with transaction.atomic():
                    self.object = self.get_object()

                    empresa_activa = _get_empresa_id(request) or request.session.get('empresa_id')
                    if hasattr(self.object, 'proyecto') and getattr(self.object, 'proyecto', None) is not None:
                        if empresa_activa and getattr(self.object.proyecto, 'empresa_interna_id', None) != empresa_activa:
                            return JsonResponse({'success': False, 'message': 'permission_delete_forbidden'}, status=403)

                    nombre = str(self.object)
                    before_snapshot = AuditoriaService.model_to_snapshot(self.object)
                    self.object.delete()

                    audit_log(
                        request=request,
                        action="DELETE",
                        app_label="control_de_proyectos",
                        obj=self.object,
                        before=before_snapshot,
                        vista_nombre=self.vista_nombre,
                        status_code=200,
                        meta={"entity": "Tarea"},
                    )

                return JsonResponse({'success': True, 'message': f'"{nombre}" eliminado exitosamente'})
            except Exception as e:
                logger.exception('Error eliminando Tarea (AJAX)')
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

        return super().post(request, *args, **kwargs)


class EliminarTareaView(VerificarPermisoMixin, LoginRequiredMixin, DeleteView):
    model = Tarea
    vista_nombre = "Control de Proyectos - Eliminar tarea"
    permiso_requerido = "eliminar"
    
    def get_queryset(self):
        empresa_id = _get_empresa_id(self.request)
        if not empresa_id:
            return Tarea.objects.none()
        return Tarea.objects.select_related('proyecto').filter(
            proyecto__empresa_interna_id=empresa_id
        )

    def get_success_url(self):
        return reverse_lazy('control_de_proyectos:detalle_proyecto', kwargs={'pk': self.object.proyecto.pk})
    
    def post(self, request, *args, **kwargs):
        """Soporta eliminación vía AJAX conforme a AJAX_DELETION_PATTERN.md; fallback al flujo tradicional."""
        xrw = request.META.get('HTTP_X_REQUESTED_WITH')
        accept = request.META.get('HTTP_ACCEPT', '')
        is_ajax = (xrw == 'XMLHttpRequest') or ('application/json' in accept)

        if is_ajax:
            try:
                from auditoria.helpers import audit_log
                from auditoria.services import AuditoriaService

                with transaction.atomic():
                    self.object = self.get_object()

                    empresa_activa = _get_empresa_id(request) or request.session.get('empresa_id')
                    if hasattr(self.object, 'proyecto') and getattr(self.object, 'proyecto', None) is not None:
                        proyecto = getattr(self.object, 'proyecto')
                        if empresa_activa and getattr(proyecto, 'empresa_interna_id', None) != empresa_activa:
                            return JsonResponse({'success': False, 'message': 'permission_delete_forbidden'}, status=403)

                    nombre = str(self.object)
                    before_snapshot = AuditoriaService.model_to_snapshot(self.object)
                    self.object.delete()

                    audit_log(
                        request=request,
                        action="DELETE",
                        app_label="control_de_proyectos",
                        obj=self.object,
                        before=before_snapshot,
                        vista_nombre=self.vista_nombre,
                        status_code=200,
                        meta={"entity": "Tarea"},
                    )

                return JsonResponse({'success': True, 'message': f'"{nombre}" eliminado exitosamente'})
            except Exception as e:
                logger.exception('Error eliminando Tarea (AJAX)')
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

        return super().post(request, *args, **kwargs)


class ListarClientesView(VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = ClienteEmpresa
    template_name = 'control_de_proyectos/cliente_lista.html'
    context_object_name = 'clientes'
    paginate_by = 20
    vista_nombre = "Control de Proyectos - Clientes"
    permiso_requerido = "ingresar"

    def dispatch(self, request, *args, **kwargs):
        empresa_id = _get_empresa_id(request)
        if not empresa_id:
            contexto = build_access_request_context(
                request,
                self.vista_nombre,
                "No tienes permisos suficientes para acceder a esta página.",
            )
            return render(request, "access_control/403_forbidden.html", contexto, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        empresa_id = _get_empresa_id(self.request)
        return ClienteEmpresa.objects.filter(
            proyectos__empresa_interna_id=empresa_id,
            activo=True
        ).distinct()


class CrearClienteView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = ClienteEmpresa
    form_class = ClienteEmpresaForm
    template_name = 'control_de_proyectos/cliente_form.html'
    vista_nombre = "Control de Proyectos - Crear cliente"
    permiso_requerido = "crear"

    def form_valid(self, form):
        self.object = form.save()
        
        # Si es una petición AJAX, devolver JSON
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'cliente_id': self.object.id,
                'cliente_nombre': self.object.nombre,
                'message': 'Cliente creado exitosamente'
            })
        
        return super().form_valid(form)
    
    def form_invalid(self, form):
        # Si es una petición AJAX, devolver errores en JSON
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': 'Error en el formulario',
                'errors': form.errors
            }, status=400)
        
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse_lazy('control_de_proyectos:listar_clientes')


class EditarClienteView(VerificarPermisoMixin, LoginRequiredMixin, UpdateView):
    model = ClienteEmpresa
    form_class = ClienteEmpresaForm
    template_name = 'control_de_proyectos/cliente_form.html'
    vista_nombre = "Control de Proyectos - Editar cliente"
    permiso_requerido = "modificar"

    def get_success_url(self):
        return reverse_lazy('control_de_proyectos:listar_clientes')


class ListarProfesionalesView(VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = Profesional
    template_name = 'control_de_proyectos/profesional_lista.html'
    context_object_name = 'profesionales'
    paginate_by = 20
    vista_nombre = "Control de Proyectos - Profesionales"
    permiso_requerido = "ingresar"

    def dispatch(self, request, *args, **kwargs):
        empresa_id = _get_empresa_id(request)
        if not empresa_id:
            contexto = build_access_request_context(
                request,
                self.vista_nombre,
                "No tienes permisos suficientes para acceder a esta página.",
            )
            return render(request, "access_control/403_forbidden.html", contexto, status=403)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        empresa_id = _get_empresa_id(self.request)
        return Profesional.objects.filter(
            proyectos__empresa_interna_id=empresa_id,
            activo=True
        ).select_related('especialidad_ref', 'user').distinct()


class CrearProfesionalView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = Profesional
    form_class = ProfesionalForm
    template_name = 'control_de_proyectos/profesional_form.html'
    vista_nombre = "Control de Proyectos - Crear profesional"
    permiso_requerido = "crear"

    def form_valid(self, form):
        self.object = form.save()
        
        # Si es una petición AJAX, devolver JSON
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'profesional_id': self.object.id,
                'profesional_nombre': self.object.nombre,
                'message': 'Profesional creado exitosamente'
            })
        
        return super().form_valid(form)
    
    def form_invalid(self, form):
        # Si es una petición AJAX, devolver errores en JSON
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': 'Error en el formulario',
                'errors': form.errors
            }, status=400)
        
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse_lazy('control_de_proyectos:listar_profesionales')


class EditarProfesionalView(VerificarPermisoMixin, LoginRequiredMixin, UpdateView):
    model = Profesional
    form_class = ProfesionalForm
    template_name = 'control_de_proyectos/profesional_form.html'
    vista_nombre = "Control de Proyectos - Editar profesional"
    permiso_requerido = "modificar"

    def get_success_url(self):
        return reverse_lazy('control_de_proyectos:listar_profesionales')


# Endpoints para sugerencias autocomplete (AJAX)
@login_required
@verificar_permiso("Control de Proyectos - Proyectos", "ingresar")
def sugerir_tipos_proyecto(request):
    """Retorna tipos de proyecto existentes para autocomplete"""
    query = request.GET.get('query', '').strip()
    tipos = TipoProyecto.objects.filter(activo=True, nombre__icontains=query)[:10]
    return JsonResponse({
        'sugerencias': [{'id': t.id, 'nombre': t.nombre} for t in tipos]
    })


@login_required
@verificar_permiso("Control de Proyectos - Proyectos", "ingresar")
def sugerir_especialidades(request):
    """Retorna especialidades existentes para autocomplete"""
    query = request.GET.get('query', '').strip()
    especialidades = EspecialidadProfesional.objects.filter(activo=True, nombre__icontains=query)[:10]
    return JsonResponse({
        'sugerencias': [{'id': e.id, 'nombre': e.nombre} for e in especialidades]
    })


class CrearTipoTareaView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
    model = TipoTarea
    form_class = TipoTareaForm
    template_name = 'control_de_proyectos/tipotarea_form.html'
    vista_nombre = "Control de Proyectos - Crear tipo de tarea"
    permiso_requerido = "crear"

    def form_valid(self, form):
        self.object = form.save()
        
        # Si es una petición AJAX, devolver JSON
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'tipotarea_id': self.object.id,
                'tipotarea_nombre': self.object.nombre,
                'message': 'Tipo de Tarea creado exitosamente'
            })
        
        return super().form_valid(form)
    
    def form_invalid(self, form):
        # Si es una petición AJAX, devolver errores en JSON
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': 'Error en el formulario',
                'errors': form.errors
            }, status=400)
        
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse_lazy('control_de_proyectos:listar_tareas')


class SubirDocumentoTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    """Vista AJAX para subir documentos a una tarea"""
    vista_nombre = "Control de Proyectos - Subir documento de tarea"
    permiso_requerido = "crear"
    
    def post(self, request, tarea_id):
        empresa_id = _get_empresa_id(request)
        if not empresa_id:
            return JsonResponse({
                'success': False,
                'error': 'No hay empresa activa en la sesión'
            }, status=403)
        
        try:
            tarea = get_object_or_404(
                Tarea.objects.select_related('proyecto'),
                pk=tarea_id,
                proyecto__empresa_interna_id=empresa_id
            )
            
            form = TareaDocumentoForm(request.POST, request.FILES)
            if form.is_valid():
                documento = form.save(commit=False)
                documento.tarea = tarea
                documento.responsable = request.user
                documento.save()
                
                # Generar URL del archivo
                archivo_url = None
                if documento.archivo:
                    try:
                        archivo_url = documento.archivo.url
                    except Exception:
                        archivo_url = None
                
                # Usar URL del documento si no hay archivo
                if not archivo_url and documento.url_documento:
                    archivo_url = documento.url_documento
                
                return JsonResponse({
                    'success': True,
                    'documento_id': documento.id,
                    'nombre': documento.nombre_documento,
                    'tipo_doc': documento.tipo_doc,
                    'archivo_url': archivo_url,
                    'url_documento': documento.url_documento,
                    'estado': documento.estado,
                    'message': 'Documento cargado exitosamente'
                })
            else:
                # Convertir errores del formulario a diccionario detallado
                errores_detallados = {}
                mensaje_principal = []
                
                for field, error_list in form.errors.items():
                    # Traducir nombres de campos a español
                    nombres_campos = {
                        'nombre_documento': 'Nombre del Documento',
                        'tipo_doc': 'Tipo de Documento',
                        'archivo': 'Archivo',
                        'url_documento': 'URL del Documento',
                        'observaciones': 'Observaciones',
                        '__all__': 'Validación General'
                    }
                    
                    nombre_campo = nombres_campos.get(field, field)
                    errores_campo = [str(e) for e in error_list]
                    errores_detallados[field] = errores_campo
                    
                    # Agregar al mensaje principal
                    for error in errores_campo:
                        mensaje_principal.append(f"{nombre_campo}: {error}")
                
                return JsonResponse({
                    'success': False,
                    'error': 'Por favor, corrija los siguientes errores:',
                    'errors': errores_detallados,
                    'error_detalle': ' | '.join(mensaje_principal) if mensaje_principal else 'Error en el formulario'
                }, status=400)
        except Tarea.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'La tarea no existe'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Error al procesar la solicitud: {str(e)}'
            }, status=500)


class ActualizarAvanceTareaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    """
    Endpoint AJAX para actualizar el porcentaje de avance de una tarea.
    
    POST /control-proyectos/tareas/<id>/avance/
    Body JSON: {"porcentaje_avance": 0-100}
    
    Respuestas:
        - 200 OK: {'success': true, 'porcentaje_avance': int, 'mensaje': str}
        - 400 Bad Request: {'success': false, 'error': str}
        - 403 Forbidden: {'success': false, 'error': str} (permisos o empresa)
        - 404 Not Found: {'success': false, 'error': str}
    """
    vista_nombre = "Control de Proyectos - Actualizar avance de tarea"
    permiso_requerido = "modificar"
    
    def post(self, request, tarea_id):
        try:
            empresa_id = _get_empresa_id(request)
            if not empresa_id:
                return JsonResponse(
                    {'success': False, 'error': 'No hay empresa activa en la sesión'},
                    status=403
                )

            try:
                empresa_id = int(empresa_id)
            except (TypeError, ValueError):
                return JsonResponse(
                    {'success': False, 'error': 'Empresa activa inválida en la sesión'},
                    status=403
                )

            # Obtener tarea con relación a proyecto
            tarea = Tarea.objects.select_related('proyecto').get(pk=tarea_id)
            
            if tarea.proyecto.empresa_interna_id != empresa_id:
                return JsonResponse(
                    {'success': False, 'error': 'La tarea no pertenece a tu empresa activa'},
                    status=403
                )
            
            # Parsear JSON del cuerpo de la solicitud
            datos = json.loads(request.body)
            porcentaje_avance = datos.get('porcentaje_avance')
            
            # Validar presencia del campo
            if porcentaje_avance is None:
                return JsonResponse(
                    {'success': False, 'error': 'El campo porcentaje_avance es requerido'},
                    status=400
                )
            
            # Validar tipo y rango (0-100)
            porcentaje_avance = int(porcentaje_avance)
            if not (0 <= porcentaje_avance <= 100):
                return JsonResponse(
                    {'success': False, 'error': 'El porcentaje debe estar entre 0 y 100'},
                    status=400
                )
            
            # Actualizar el modelo
            tarea.porcentaje_avance = porcentaje_avance
            tarea.save(update_fields=['porcentaje_avance'])
            
            return JsonResponse({
                'success': True,
                'porcentaje_avance': tarea.porcentaje_avance,
                'mensaje': f'Avance actualizado a {porcentaje_avance}%'
            }, status=200)
        
        except Tarea.DoesNotExist:
            return JsonResponse(
                {'success': False, 'error': 'La tarea no existe'},
                status=404
            )
        except json.JSONDecodeError:
            return JsonResponse(
                {'success': False, 'error': 'Body inválido (JSON esperado)'},
                status=400
            )
        except (ValueError, TypeError):
            return JsonResponse(
                {'success': False, 'error': 'Datos inválidos: porcentaje_avance debe ser un número entre 0 y 100'},
                status=400
            )
        except Exception as e:
            return JsonResponse(
                {'success': False, 'error': f'Error interno del servidor: {str(e)}'},
                status=500
            )
