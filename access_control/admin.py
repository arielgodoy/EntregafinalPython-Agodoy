from django.contrib import admin

from .models import (
	AccessRequest,
	Empresa,
	Vista,
	Permiso,
	PerfilAcceso,
	PerfilAccesoDetalle,
	UsuarioPerfilEmpresa,
)

admin.site.register(Empresa)
admin.site.register(Vista)
admin.site.register(Permiso)
admin.site.register(PerfilAcceso)
admin.site.register(PerfilAccesoDetalle)
admin.site.register(UsuarioPerfilEmpresa)


@admin.register(AccessRequest)
class AccessRequestAdmin(admin.ModelAdmin):
	list_display = ('solicitante', 'empresa', 'vista_nombre', 'status', 'created_at', 'resolved_at')
	list_filter = ('status', 'email_status', 'empresa', 'created_at')
	search_fields = ('solicitante__username', 'solicitante__email', 'empresa__codigo', 'vista_nombre')
	readonly_fields = tuple(field.name for field in AccessRequest._meta.fields)

	def has_add_permission(self, request):
		return False

	def has_change_permission(self, request, obj=None):
		return False

	def has_delete_permission(self, request, obj=None):
		return False