import logging
from datetime import date

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
from .services.persona_storage import (
    PersonaStorageError,
    list_persona_period_data,
)
from .services.base_evaluaciones_schema import (
    BaseEvaluacionesSchemaInstallError,
    install_base_evaluaciones_schema,
    preview_base_evaluaciones_schema,
)
from settings.services.mysql_connections import MySQLConnectionOpenError
from settings.context_processors import system_date_context


logger = logging.getLogger(__name__)

_SYSTEM_DATE_UNAVAILABLE_KEY = (
    "evaluaciones.personas.import.error.system_date_unavailable"
)


def _resolve_system_date(request):
    try:
        value = system_date_context(request).get("fecha_sistema")
    except Exception as exc:
        logger.error(
            "Persona import system date resolution failed (error_type=%s)",
            type(exc).__name__,
        )
        return None

    if not isinstance(value, str):
        return None
    try:
        resolved_date = date.fromisoformat(value)
    except ValueError:
        return None
    return resolved_date if resolved_date.isoformat() == value else None


def _parse_period_filter(value):
    if not value:
        return None, True
    if (
        len(value) != 7
        or value[4] != "-"
        or not value[:4].isdigit()
        or not value[5:].isdigit()
    ):
        return None, False
    anio, mes = int(value[:4]), int(value[5:])
    if anio < 1 or mes < 1 or mes > 12:
        return None, False
    return (anio, mes), True


def _parse_integer_filter(value, allowed_values):
    if not value:
        return None, True
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, False
    return (parsed, parsed in allowed_values)


def _location_filter_value(value):
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


class ImportarPersonasView(VerificarPermisoMixin, LoginRequiredMixin, ListView):
    model = Persona
    template_name = "importar_personas.html"
    context_object_name = "personas"
    vista_nombre = "Evaluaciones - Importar Personas"
    permiso_requerido = "ingresar"

    def dispatch(self, request, *args, **kwargs):
        self.permiso_requerido = (
            "supervisor" if request.method == "POST" else "ingresar"
        )
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        self.personas_total = None
        self.personas_storage_error = False
        self.personas_filter_error = False
        self.period_options = []
        self.company_options = []
        self.location_options = []
        self.role_options = []
        self.selected_period = ""
        self.selected_company_id = ""
        self.selected_location = ""
        self.selected_role_id = ""

        period_raw = self.request.GET.get("period", "")
        requested_period, valid_period = _parse_period_filter(period_raw)
        self.personas_filter_error = not valid_period

        try:
            periods, selected_period, period_people = list_persona_period_data(
                requested_period
            )
        except PersonaStorageError:
            self.personas_storage_error = True
            return []

        if period_raw and selected_period != requested_period:
            self.personas_filter_error = True

        self.period_options = [
            {
                "value": f"{anio:04d}-{mes:02d}",
                "label": f"{mes:02d}/{anio:04d}",
            }
            for anio, mes in periods
        ]
        if selected_period:
            self.selected_period = (
                f"{selected_period[0]:04d}-{selected_period[1]:02d}"
            )

        self.personas_total = len(period_people)
        company_ids = sorted(
            {
                persona.company_id
                for persona in period_people
                if persona.company_id is not None
            }
        )
        self.company_options = [
            {
                "value": str(company_id),
                "label": f"Empresa BUK #{company_id}",
            }
            for company_id in company_ids
        ]

        company_raw = self.request.GET.get("company_id", "")
        company_id, company_valid = _parse_integer_filter(
            company_raw,
            set(company_ids),
        )
        if not company_valid:
            self.personas_filter_error = True
            selected_company_people = []
        else:
            self.selected_company_id = (
                str(company_id) if company_id is not None else ""
            )
            selected_company_people = [
                persona
                for persona in period_people
                if company_id is None or persona.company_id == company_id
            ]

        location_values = sorted(
            {
                location
                for persona in selected_company_people
                if (location := _location_filter_value(persona.ctrlit_recinto))
                is not None
            },
            key=str.casefold,
        )
        self.location_options = [
            {"value": location, "label": location}
            for location in location_values
        ]

        location_raw = self.request.GET.get("ctrlit_recinto", "")
        location = location_raw or None
        location_valid = location is None or location in location_values
        if not location_valid:
            self.personas_filter_error = True
            selected_location_people = []
        else:
            self.selected_location = location or ""
            selected_location_people = [
                persona
                for persona in selected_company_people
                if location is None
                or _location_filter_value(persona.ctrlit_recinto) == location
            ]

        role_labels = {}
        for persona in selected_location_people:
            if persona.role_id is None:
                continue
            label = (persona.role_name or "").strip()
            if persona.role_id not in role_labels or (
                label
                and (
                    not role_labels[persona.role_id]
                    or label.casefold()
                    < role_labels[persona.role_id].casefold()
                )
            ):
                role_labels[persona.role_id] = label
        self.role_options = [
            {
                "value": str(role_id),
                "label": label or "Sin información",
                "missing_label": not bool(label),
            }
            for role_id, label in sorted(
                role_labels.items(),
                key=lambda item: (item[1].casefold(), item[0]),
            )
        ]

        role_raw = self.request.GET.get("role_id", "")
        role_id, role_valid = _parse_integer_filter(
            role_raw,
            set(role_labels),
        )
        if not role_valid:
            self.personas_filter_error = True
        else:
            self.selected_role_id = str(role_id) if role_id is not None else ""

        if self.personas_filter_error:
            return []
        return [
            persona
            for persona in selected_location_people
            if role_id is None or persona.role_id == role_id
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not hasattr(self, "_resolved_system_date"):
            self._resolved_system_date = _resolve_system_date(self.request)
        system_date = self._resolved_system_date
        context["import_system_date_display"] = (
            system_date.strftime("%d-%m-%Y") if system_date else ""
        )
        context["import_system_date_available"] = system_date is not None
        context["personas_total"] = getattr(self, "personas_total", None)
        context["period_options"] = getattr(self, "period_options", [])
        context["company_options"] = getattr(self, "company_options", [])
        context["location_options"] = getattr(self, "location_options", [])
        context["role_options"] = getattr(self, "role_options", [])
        context["selected_period"] = getattr(self, "selected_period", "")
        context["selected_company_id"] = getattr(
            self,
            "selected_company_id",
            "",
        )
        context["selected_location"] = getattr(
            self,
            "selected_location",
            "",
        )
        context["selected_role_id"] = getattr(self, "selected_role_id", "")
        context["persona_filter_error"] = getattr(
            self,
            "personas_filter_error",
            False,
        )
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

        system_date = _resolve_system_date(request)
        self._resolved_system_date = system_date
        exclude_pending_raw = request.POST.get("exclude_pending")
        exclude_pending = str(exclude_pending_raw).strip().lower() in ("true", "1", "yes", "y", "on")

        import_result = None
        import_success_key = None
        import_success_text = None
        import_error_key = None
        import_error_text = None

        if system_date is None:
            import_error_key = _SYSTEM_DATE_UNAVAILABLE_KEY
            import_error_text = (
                "No se pudo obtener la Fecha de Sistema oficial. "
                "La importación no se inició."
            )
        else:
            try:
                import_result = importar_personas_desde_api_interna(
                    system_date.isoformat(),
                    exclude_pending,
                    request_user=request.user,
                )
                import_success_key = "evaluaciones.personas.import.success"
                import_success_text = "Importación completada."
            except PersonaImportServiceError as exc:
                import_error_key = exc.message_key
                if exc.message_key == "evaluaciones.personas.import.error.invalid_response":
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
        from .services import persona_import_job

        system_date = _resolve_system_date(request)
        if system_date is None:
            return JsonResponse(
                {
                    "success": False,
                    "message_key": _SYSTEM_DATE_UNAVAILABLE_KEY,
                },
                status=503,
            )

        empresa_id = request.session.get("empresa_id") or 0
        status_key = persona_import_job.build_persona_import_cache_key(
            user_id=request.user.id,
            empresa_id=int(empresa_id),
            session_key=request.session.session_key,
        )

        exclude_pending_raw = request.POST.get("exclude_pending")
        exclude_pending = str(exclude_pending_raw).strip().lower() in ("true", "1", "yes", "y", "on")

        status = persona_import_job.start_persona_import_async(
            status_key=status_key,
            date_str=system_date.isoformat(),
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
