from django.urls import path

from . import views

app_name = 'proveedores'

urlpatterns = [
	path("", views.ListadoProveedoresView.as_view(), name="listado_raiz"),
	path("listado/", views.ListadoProveedoresView.as_view(), name="listado"),
	path("crear/", views.CrearProveedorView.as_view(), name="crear"),
	path("<int:pk>/", views.DetalleProveedorView.as_view(), name="detalle"),
	path("<int:pk>/editar/", views.EditarProveedorView.as_view(), name="editar"),
	path("<int:pk>/inactivar/", views.InactivarProveedorView.as_view(), name="inactivar"),
	path("<int:pk>/reactivar/", views.ReactivarProveedorView.as_view(), name="reactivar"),
]
