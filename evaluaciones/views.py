import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db import DatabaseError, transaction
from django.core import signing
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import ListView
from pymysql import MySQLError

# OFFICIAL IMPORT
from access_control.decorators import verificar_permiso
from access_control.models import Permiso
from access_control.services.permissions import user_has_permission_for_empresa
from access_control.views import VerificarPermisoMixin

from .forms import EvaluacionConnectionRoleForm
from .models import EvaluacionConnectionRole, Persona
from .services.connection_roles import (
    EvaluacionesConnectionError,
    get_evaluaciones_connection_status,
    open_evaluaciones_connection,
)
from .services.persona_storage import PersonaStorageError, list_personas
from .services.base_evaluaciones_schema import (
    BaseEvaluacionesSchemaInstallError,
    install_base_evaluaciones_schema,
    preview_base_evaluaciones_schema,
)
from settings.services.mysql_connections import MySQLConnectionOpenError


logger = logging.getLogger(__name__)


class ImportarPersonasView(VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = Persona
    template_name = "importar_personas.html"
    context_object_name = "personas"
    vista_nombre = "Evaluaciones - Importar Personas"
    permiso_requerido = "ingresar"

    def get_queryset(self):
        # Listado acotado para evitar cargas grandes; se ampliará en la fase de importación real.
        self.personas_total = None
        self.personas_storage_error = False
        try:
            personas, self.personas_total = list_personas()
        except PersonaStorageError:
            self.personas_storage_error = True
            return []
        return personas

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["personas_total"] = getattr(self, "personas_total", None)
        if getattr(self, "personas_storage_error", False):
            context["import_error_key"] = "evaluaciones.personas.import.error.db"
            context["import_error_text"] = (
                "No se pudo cargar la información de personas desde la base de datos."
            )
        empresa_id = self.request.session.get("empresa_id")
        context["can_view_sql_connections"] = bool(
            self.request.user.is_authenticated
            and empresa_id
            and Permiso.objects.filter(
                usuario=self.request.user,
                empresa_id=empresa_id,
                vista__nombre="Evaluaciones - Conexiones Sql",
                ver=True,
            ).exists()
        )
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
        if self.personas_storage_error and not import_error_key:
            import_error_key = "evaluaciones.personas.import.error.db"
            import_error_text = (
                "No se pudo cargar la información de personas desde la base de datos."
            )
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
    permiso_requerido = "supervisor"

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


class EvaluacionesConnectionRolesView(
    VerificarPermisoMixin, LoginRequiredMixin, View
):
    template_name = "evaluaciones/connection_roles.html"
    vista_nombre = "Evaluaciones - Conexiones Sql"
    permiso_requerido = "ingresar"
    crear_permiso_faltante = False
    verificar_vicmeas_en_dispatch = False

    def _role_forms(self, *, bound_role=None, bound_form=None):
        existing = {
            item.role: item
            for item in EvaluacionConnectionRole.objects.select_related(
                "mysql_connection", "mysql_connection__empresa"
            )
        }
        return [
            {
                "role": role,
                "label": label,
                "form": (
                    bound_form
                    if role == bound_role and bound_form is not None
                    else EvaluacionConnectionRoleForm(
                        instance=existing.get(role)
                        or EvaluacionConnectionRole(
                            role=role,
                            source_type=EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG,
                        ),
                        role=role,
                    )
                ),
            }
            for role, label in EvaluacionConnectionRole.ROLE_CHOICES
        ]

    def _context(self, *, bound_role=None, bound_form=None):
        status = get_evaluaciones_connection_status()
        status_by_role = {item["role"]: item for item in status["roles"]}
        role_forms = self._role_forms(bound_role=bound_role, bound_form=bound_form)
        for item in role_forms:
            item["status"] = status_by_role[item["role"]]
        supervisor_allowed = user_has_permission_for_empresa(
            user=self.request.user,
            empresa=self.request.session.get("empresa_id"),
            vista_nombre=self.vista_nombre,
            accion="supervisor",
        )
        base_status = status_by_role.get(EvaluacionConnectionRole.ROLE_BASE_EVALUACIONES, {})
        return {
            "role_forms": role_forms,
            "connection_status": status,
            "connection_probe_allowed": supervisor_allowed,
            "base_schema_install_allowed": bool(
                supervisor_allowed
                and base_status.get("status") == "configured"
                and base_status.get("source_type")
                == EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG
            ),
        }

    @method_decorator(
        verificar_permiso(
            vista_nombre,
            "ingresar",
            crear_permiso_faltante=False,
        )
    )
    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._context())

    @method_decorator(
        verificar_permiso(
            vista_nombre,
            "modificar",
            crear_permiso_faltante=False,
        )
    )
    def post(self, request, *args, **kwargs):
        role = request.POST.get("role", "")
        allowed_roles = {item[0] for item in EvaluacionConnectionRole.ROLE_CHOICES}
        if role not in allowed_roles:
            messages.error(request, "El rol de conexión solicitado no es válido.")
            return redirect(reverse("evaluaciones:connection_roles"))

        instance = EvaluacionConnectionRole.objects.filter(role=role).first()
        if instance is None:
            instance = EvaluacionConnectionRole(
                role=role,
                source_type=EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG,
            )
        form = EvaluacionConnectionRoleForm(
            request.POST,
            instance=instance,
            role=role,
        )
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                self._context(bound_role=role, bound_form=form),
                status=400,
            )

        with transaction.atomic():
            form.save()
        messages.success(request, "La asociación de conexión fue guardada.")
        return redirect(reverse("evaluaciones:connection_roles"))


class EvaluacionesConnectionProbeView(
    VerificarPermisoMixin, LoginRequiredMixin, View
):
    vista_nombre = "Evaluaciones - Conexiones Sql"
    permiso_requerido = "supervisor"
    crear_permiso_faltante = False

    def post(self, request, *args, **kwargs):
        role = request.POST.get("role", "")
        allowed_roles = {item[0] for item in EvaluacionConnectionRole.ROLE_CHOICES}
        if role not in allowed_roles:
            messages.error(request, "El rol de conexión solicitado no es válido.")
            return redirect(reverse("evaluaciones:connection_roles"))

        try:
            with open_evaluaciones_connection(role) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute("SELECT 1")
                finally:
                    cursor.close()
        except (
            EvaluacionesConnectionError,
            MySQLConnectionOpenError,
            DatabaseError,
            MySQLError,
        ) as exc:
            logger.warning(
                "Evaluaciones SQL probe failed for role=%s error_type=%s",
                role,
                type(exc).__name__,
            )
            messages.error(
                request,
                "No se pudo validar la conexión SQL. Revise su configuración.",
            )
        else:
            messages.success(request, "La conexión SQL respondió correctamente.")
        return redirect(reverse("evaluaciones:connection_roles"))


_BASE_EVALUACIONES_SCHEMA_PREVIEW_SALT = (
    "evaluaciones.base_evaluaciones_schema.preview.v1"
)
_BASE_EVALUACIONES_SCHEMA_PREVIEW_MAX_AGE = 10 * 60


@method_decorator(
    verificar_permiso(
        "Evaluaciones - Conexiones Sql",
        "supervisor",
        crear_permiso_faltante=False,
    ),
    name="dispatch",
)
class BaseEvaluacionesSchemaInstallView(LoginRequiredMixin, View):
    vista_nombre = "Evaluaciones - Conexiones Sql"
    permiso_requerido = "supervisor"
    crear_permiso_faltante = False
    http_method_names = ["post"]

    def _render_connection_roles(
        self,
        request,
        *,
        schema_preview=None,
        schema_preview_token=None,
        schema_error=None,
        status=200,
    ):
        page = EvaluacionesConnectionRolesView()
        page.request = request
        context = page._context()
        context.update(
            {
                "schema_preview": schema_preview,
                "schema_preview_token": schema_preview_token,
                "schema_error": schema_error,
            }
        )
        return render(
            request,
            page.template_name,
            context,
            status=status,
        )

    def post(self, request, *args, **kwargs):
        action = request.POST.get("schema_action")
        try:
            if action == "preview":
                preview = preview_base_evaluaciones_schema()
                token = None
                if preview["missing"] and not preview["conflicts"]:
                    token = signing.dumps(
                        {
                            "role": EvaluacionConnectionRole.ROLE_BASE_EVALUACIONES,
                            "connection_id": preview["connection_id"],
                            "connection_updated_at": preview[
                                "connection_updated_at"
                            ],
                            "database_name": preview["database_name"],
                            "fingerprint": preview["fingerprint"],
                            "missing": preview["missing"],
                        },
                        salt=_BASE_EVALUACIONES_SCHEMA_PREVIEW_SALT,
                        compress=True,
                    )
                return self._render_connection_roles(
                    request,
                    schema_preview=preview,
                    schema_preview_token=token,
                )

            if action != "confirm":
                raise BaseEvaluacionesSchemaInstallError(
                    "La operación requiere inspección y confirmación explícitas."
                )

            try:
                preview_data = signing.loads(
                    request.POST.get("schema_preview_token", ""),
                    salt=_BASE_EVALUACIONES_SCHEMA_PREVIEW_SALT,
                    max_age=_BASE_EVALUACIONES_SCHEMA_PREVIEW_MAX_AGE,
                )
            except signing.BadSignature as exc:
                raise BaseEvaluacionesSchemaInstallError(
                    "La vista previa expiró o no es válida; vuelva a inspeccionar."
                ) from exc
            if (
                not isinstance(preview_data, dict)
                or preview_data.get("role")
                != EvaluacionConnectionRole.ROLE_BASE_EVALUACIONES
                or not isinstance(preview_data.get("connection_id"), int)
                or not isinstance(preview_data.get("connection_updated_at"), str)
                or not isinstance(preview_data.get("database_name"), str)
                or not isinstance(preview_data.get("fingerprint"), str)
                or preview_data.get("missing") != ["evaluaciones_persona"]
            ):
                raise BaseEvaluacionesSchemaInstallError(
                    "La vista previa no autoriza el objeto solicitado."
                )

            install_base_evaluaciones_schema(
                expected_fingerprint=preview_data["fingerprint"],
                expected_missing=tuple(preview_data["missing"]),
                expected_connection_id=preview_data["connection_id"],
                expected_connection_updated_at=preview_data[
                    "connection_updated_at"
                ],
                expected_database_name=preview_data["database_name"],
            )
        except BaseEvaluacionesSchemaInstallError as exc:
            return self._render_connection_roles(
                request,
                schema_error=str(exc),
                status=409 if action == "confirm" else 400,
            )

        messages.success(
            request,
            "Se creó la tabla evaluaciones_persona en Base Evaluaciones.",
        )
        return redirect(reverse("evaluaciones:connection_roles"))
