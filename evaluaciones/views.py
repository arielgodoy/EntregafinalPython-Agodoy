from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views import View
from django.views.generic import ListView

# OFFICIAL IMPORT
from access_control.views import VerificarPermisoMixin

from .models import Persona


class ImportarPersonasView(VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = Persona
    template_name = "importar_personas.html"
    context_object_name = "personas"
    vista_nombre = "Evaluaciones - Importar Personas"
    permiso_requerido = "ingresar"

    def get_queryset(self):
        # Listado acotado para evitar cargas grandes; se ampliará en la fase de importación real.
        return Persona.objects.all().order_by("-anio", "-mes", "full_name")[:5000]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["personas_total"] = Persona.objects.count()
        return context

    def post(self, request, *args, **kwargs):
        from .services.persona_importer import PersonaImportServiceError, importar_personas_desde_api_interna

        date_str = (request.POST.get("date") or "").strip()
        exclude_pending_raw = request.POST.get("exclude_pending")
        exclude_pending = str(exclude_pending_raw).strip().lower() in ("true", "1", "yes", "y", "on")

        import_result = None
        import_success_key = None
        import_success_text = None
        import_error_key = None
        import_error_text = None

        try:
            import_result = importar_personas_desde_api_interna(
                date_str,
                exclude_pending,
                request_user=request.user,
            )
            import_success_key = "evaluaciones.personas.import.success"
            import_success_text = "Importación completada."
        except PersonaImportServiceError as exc:
            import_error_key = exc.message_key
            if exc.message_key == "evaluaciones.personas.import.error.date_required":
                import_error_text = "La fecha es obligatoria."
            elif exc.message_key == "evaluaciones.personas.import.error.date_invalid":
                import_error_text = "La fecha debe tener formato YYYY-MM-DD."
            elif exc.message_key == "evaluaciones.personas.import.error.invalid_response":
                import_error_text = "Respuesta inválida desde la API interna."
            elif exc.message_key == "evaluaciones.personas.import.error.too_many_pages":
                import_error_text = "Paginación inválida o demasiado extensa."
            elif exc.message_key == "evaluaciones.personas.import.error.api":
                import_error_text = "No se pudo consultar la API interna."
            elif exc.message_key == "evaluaciones.personas.import.error.db":
                import_error_text = "No se pudo guardar la importación en la base de datos."
            else:
                import_error_text = "No se pudo completar la importación."
        except Exception:
            import_error_key = "evaluaciones.personas.import.error.generic"
            import_error_text = "No se pudo completar la importación."

        self.object_list = self.get_queryset()
        context = self.get_context_data()
        context["import_date"] = date_str
        context["exclude_pending"] = exclude_pending
        context["import_result"] = import_result
        context["import_success_key"] = import_success_key
        context["import_success_text"] = import_success_text
        context["import_error_key"] = import_error_key
        context["import_error_text"] = import_error_text
        return self.render_to_response(context)


class ImportarPersonasStartView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Evaluaciones - Importar Personas"
    permiso_requerido = "Supervisor"

    def post(self, request, *args, **kwargs):
        from datetime import date as date_cls

        from .services import persona_import_job

        empresa_id = request.session.get("empresa_id") or 0
        status_key = persona_import_job.build_persona_import_cache_key(
            user_id=request.user.id,
            empresa_id=int(empresa_id),
            session_key=request.session.session_key,
        )

        date_str = (request.POST.get("date") or "").strip()
        exclude_pending_raw = request.POST.get("exclude_pending")
        exclude_pending = str(exclude_pending_raw).strip().lower() in ("true", "1", "yes", "y", "on")

        if not date_str:
            persona_import_job.set_status(
                status_key=status_key,
                status_payload={
                    "status": "error",
                    "message_key": "evaluaciones.personas.import.error.date_required",
                    "finished_at": persona_import_job.timezone.now().isoformat(),
                },
            )
            return JsonResponse(
                {"success": False, "message_key": "evaluaciones.personas.import.error.date_required"},
                status=400,
            )

        try:
            date_cls.fromisoformat(date_str)
        except ValueError:
            persona_import_job.set_status(
                status_key=status_key,
                status_payload={
                    "status": "error",
                    "message_key": "evaluaciones.personas.import.error.date_invalid",
                    "finished_at": persona_import_job.timezone.now().isoformat(),
                },
            )
            return JsonResponse(
                {"success": False, "message_key": "evaluaciones.personas.import.error.date_invalid"},
                status=400,
            )

        status = persona_import_job.start_persona_import_async(
            status_key=status_key,
            date_str=date_str,
            exclude_pending=exclude_pending,
        )

        return JsonResponse(
            {
                "success": True,
                "message_key": "evaluaciones.personas.import.progress_starting",
                "status": status,
            }
        )


class ImportarPersonasStatusView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Evaluaciones - Importar Personas"
    permiso_requerido = "ingresar"

    def get(self, request, *args, **kwargs):
        from .services import persona_import_job

        empresa_id = request.session.get("empresa_id") or 0
        status_key = persona_import_job.build_persona_import_cache_key(
            user_id=request.user.id,
            empresa_id=int(empresa_id),
            session_key=request.session.session_key,
        )

        status = persona_import_job.get_status(status_key=status_key)
        return JsonResponse({"success": True, **status})
