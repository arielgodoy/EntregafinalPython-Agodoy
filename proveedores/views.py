from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from access_control.views import VerificarPermisoMixin

from .forms import ProveedorForm
from .models import Proveedor


VISTA_PROVEEDORES = "Maestros - Proveedores"


class ListadoProveedoresView(VerificarPermisoMixin, LoginRequiredMixin, ListView):
	model = Proveedor
	template_name = "proveedores/listado.html"
	context_object_name = "proveedores"
	vista_nombre = VISTA_PROVEEDORES
	permiso_requerido = "ingresar"

	def get_queryset(self):
		return Proveedor.objects.all()


class DetalleProveedorView(VerificarPermisoMixin, LoginRequiredMixin, DetailView):
	model = Proveedor
	template_name = "proveedores/detalle.html"
	context_object_name = "proveedor"
	vista_nombre = VISTA_PROVEEDORES
	permiso_requerido = "ingresar"


class CrearProveedorView(VerificarPermisoMixin, LoginRequiredMixin, CreateView):
	model = Proveedor
	form_class = ProveedorForm
	template_name = "proveedores/formulario.html"
	vista_nombre = VISTA_PROVEEDORES
	permiso_requerido = "crear"
	success_url = reverse_lazy("proveedores:listado")


class EditarProveedorView(VerificarPermisoMixin, LoginRequiredMixin, UpdateView):
	model = Proveedor
	form_class = ProveedorForm
	template_name = "proveedores/formulario.html"
	vista_nombre = VISTA_PROVEEDORES
	permiso_requerido = "modificar"
	success_url = reverse_lazy("proveedores:listado")


class CambiarEstadoProveedorView(VerificarPermisoMixin, LoginRequiredMixin, View):
	vista_nombre = VISTA_PROVEEDORES
	permiso_requerido = None
	estado_objetivo = None
	permiso_estado = None

	def dispatch(self, request, *args, **kwargs):
		self.permiso_requerido = self.permiso_estado
		return super().dispatch(request, *args, **kwargs)

	def post(self, request, pk):
		proveedor = get_object_or_404(Proveedor, pk=pk)
		proveedor.activo = self.estado_objetivo
		proveedor.save(update_fields=["activo", "updated_at"])
		return redirect("proveedores:listado")


class InactivarProveedorView(CambiarEstadoProveedorView):
	permiso_requerido = "eliminar"
	permiso_estado = "eliminar"
	estado_objetivo = False


class ReactivarProveedorView(CambiarEstadoProveedorView):
	permiso_requerido = "modificar"
	permiso_estado = "modificar"
	estado_objetivo = True
