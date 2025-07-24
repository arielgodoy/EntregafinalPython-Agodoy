from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from access_control.decorators import verificar_permiso, PermisoDenegadoJson
from django.utils.decorators import method_decorator
from django.shortcuts import render
from django.http import JsonResponse

class VerificarPermisoMixin:
    vista_nombre = None
    permiso_requerido = None

    def dispatch(self, request, *args, **kwargs):
        if self.vista_nombre and self.permiso_requerido:
            decorador = verificar_permiso(self.vista_nombre, self.permiso_requerido)

            @decorador
            def view_func(req, *a, **kw):
                return super(VerificarPermisoMixin, self).dispatch(req, *a, **kw)

            try:
                return view_func(request, *args, **kwargs)
            except PermisoDenegadoJson as e:
                return self.handle_no_permission(request, str(e))

        return super().dispatch(request, *args, **kwargs)

    def handle_no_permission(self, request, mensaje="No tienes permiso para esta acción."):
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.content_type == "application/json":
            return JsonResponse({"success": False, "error": mensaje}, status=403)

        contexto = {
            "mensaje": mensaje,
            "vista_nombre": getattr(self, "vista_nombre", "Desconocida"),
            "empresa_nombre": request.session.get("empresa_nombre", "No definida"),
        }
        return render(request, "access_control/403_forbidden.html", contexto, status=403)


class ImportarPersonasView(VerificarPermisoMixin, LoginRequiredMixin, TemplateView):
    template_name = "importar_personas.html"
    vista_nombre = "Importar Personas"
    permiso_requerido = "ingresar"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Puedes agregar valores iniciales al contexto aquí si es necesario
        return context
