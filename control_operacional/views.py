from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views import View

from access_control.views import VerificarPermisoMixin
from access_control.services.access_requests import build_access_request_context
from .models import AlertaAck
from .services.alerts import build_operational_alerts
from .services.charts import get_proyectos_activos_por_estado
from .services.kpis import get_proyectos_kpis


def _get_empresa_id(request):
    return request.session.get("empresa_id")


def _is_json_request(request):
    accept = request.headers.get("accept", "")
    requested_with = request.headers.get("x-requested-with", "")
    return requested_with == "XMLHttpRequest" or "application/json" in accept


class DashboardView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Control Operacional - Dashboard"
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
    
    def get(self, request, *args, **kwargs):
        empresa_id = _get_empresa_id(request)
        kpis = get_proyectos_kpis(empresa_id)
        chart_proyectos_por_estado = get_proyectos_activos_por_estado(empresa_id)
        return render(
            request,
            "control_operacional/dashboard.html",
            {"kpis": kpis, "chart_proyectos_por_estado": chart_proyectos_por_estado},
        )


class AlertasOperacionalesView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Control Operacional - Alertas"
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
    
    def get(self, request, *args, **kwargs):
        empresa_id = _get_empresa_id(request)
        alertas = build_operational_alerts(empresa_id)
        acked_keys = set(
            AlertaAck.objects.filter(empresa_id=empresa_id, user=request.user).values_list("alert_key", flat=True)
        )
        alertas = [alerta for alerta in alertas if alerta["key"] not in acked_keys]

        severidad_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        alertas.sort(
            key=lambda item: (-severidad_rank.get(item["severity"], 0), item.get("created_at") or timezone.localdate())
        )

        conteo_severidad = {
            "HIGH": sum(1 for alerta in alertas if alerta["severity"] == "HIGH"),
            "MEDIUM": sum(1 for alerta in alertas if alerta["severity"] == "MEDIUM"),
            "LOW": sum(1 for alerta in alertas if alerta["severity"] == "LOW"),
        }

        return render(
            request,
            "control_operacional/alertas.html",
            {"alertas": alertas, "conteo_severidad": conteo_severidad},
        )


class AckAlertaView(VerificarPermisoMixin, LoginRequiredMixin, View):
    vista_nombre = "Control Operacional - Reconocer alerta"
    permiso_requerido = "ingresar"
    
    def post(self, request, *args, **kwargs):
        empresa_id = _get_empresa_id(request)
        if not empresa_id:
            error = {"success": False, "error": "No hay empresa activa en la sesión"}
            return JsonResponse(error, status=403)

        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        alert_key = (request.POST.get("alert_key") or "").strip()
        if not alert_key:
            error = {"success": False, "error": "alert_key requerido"}
            if _is_json_request(request):
                return JsonResponse(error, status=400)
            return JsonResponse(error, status=400)

        valid_keys = {alerta["key"] for alerta in build_operational_alerts(empresa_id)}
        if alert_key not in valid_keys:
            error = {"success": False, "error": "alert_key inválido"}
            if _is_json_request(request):
                return JsonResponse(error, status=400)
            return JsonResponse(error, status=400)

        AlertaAck.objects.get_or_create(
            empresa_id=empresa_id,
            user=request.user,
            alert_key=alert_key,
        )

        if _is_json_request(request):
            return JsonResponse({"success": True})
        return redirect("control_operacional:alertas_operacionales")
    
    def get(self, request, *args, **kwargs):
        return HttpResponseNotAllowed(["POST"])
