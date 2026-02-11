from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from access_control.decorators import verificar_permiso
from .services.kpis import get_proyectos_kpis
from .services.charts import get_proyectos_activos_por_estado


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
