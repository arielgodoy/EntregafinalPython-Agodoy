from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from access_control.decorators import PermisoDenegadoJson, verificar_permiso
from .models import AlertaAck
from .services.alerts import build_operational_alerts
from .services.charts import get_proyectos_activos_por_estado
from .services.kpis import get_proyectos_kpis


@login_required
@verificar_permiso("Control Operacional Dashboard", "ingresar")
def dashboard(request):
	empresa_id = request.session.get("empresa_id")
	kpis = get_proyectos_kpis(empresa_id)
	chart_proyectos_por_estado = get_proyectos_activos_por_estado(empresa_id)
	return render(
		request,
		"control_operacional/dashboard.html",
		{"kpis": kpis, "chart_proyectos_por_estado": chart_proyectos_por_estado},
	)


def _is_json_request(request):
	accept = request.headers.get("accept", "")
	requested_with = request.headers.get("x-requested-with", "")
	return requested_with == "XMLHttpRequest" or "application/json" in accept


def _handle_permiso_denegado(request, mensaje):
	if _is_json_request(request):
		return JsonResponse({"success": False, "error": mensaje}, status=403)
	contexto = {"mensaje": mensaje, "vista_nombre": "control_operacional.alertas"}
	return render(request, "access_control/403_forbidden.html", contexto, status=403)


@login_required
def alertas_operacionales(request):
	try:
		decorador = verificar_permiso("control_operacional.alertas", "ingresar")

		@decorador
		def _inner(req):
			return None

		response = _inner(request)
		if response is not None:
			return response
	except PermisoDenegadoJson as e:
		return _handle_permiso_denegado(request, str(e.mensaje))

	empresa_id = request.session.get("empresa_id")
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


@login_required
def ack_alerta(request):
	try:
		decorador = verificar_permiso("control_operacional.alertas", "ingresar")

		@decorador
		def _inner(req):
			return None

		response = _inner(request)
		if response is not None:
			return response
	except PermisoDenegadoJson as e:
		return _handle_permiso_denegado(request, str(e.mensaje))

	if request.method != "POST":
		return HttpResponseNotAllowed(["POST"])

	empresa_id = request.session.get("empresa_id")
	alert_key = (request.POST.get("alert_key") or "").strip()
	if not alert_key:
		error = {"success": False, "error": "alert_key requerido"}
		if _is_json_request(request):
			return JsonResponse(error, status=400)
		return HttpResponseBadRequest("alert_key requerido")

	valid_keys = {alerta["key"] for alerta in build_operational_alerts(empresa_id)}
	if alert_key not in valid_keys:
		error = {"success": False, "error": "alert_key invalido"}
		if _is_json_request(request):
			return JsonResponse(error, status=400)
		return HttpResponseBadRequest("alert_key invalido")

	AlertaAck.objects.get_or_create(
		empresa_id=empresa_id,
		user=request.user,
		alert_key=alert_key,
	)

	if _is_json_request(request):
		return JsonResponse({"success": True})
	return redirect("control_operacional:alertas_operacionales")
