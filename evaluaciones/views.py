from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.http import JsonResponse

# OFFICIAL IMPORT
from access_control.views import VerificarPermisoMixin


class ImportarPersonasView(VerificarPermisoMixin, LoginRequiredMixin, TemplateView):
    template_name = "importar_personas.html"
    vista_nombre = "Evaluaciones - Importar Personas"
    permiso_requerido = "ingresar"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Puedes agregar valores iniciales al contexto aquí si es necesario
        return context
