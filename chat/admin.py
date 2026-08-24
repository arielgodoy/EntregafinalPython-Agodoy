from django.contrib import admin
from .models import Conversacion, Mensaje, MensajeLeido
# Register your models here.

admin.site.register(Conversacion)
admin.site.register(Mensaje)


@admin.register(MensajeLeido)
class MensajeLeidoAdmin(admin.ModelAdmin):
	list_display = ('user', 'mensaje', 'empresa', 'read_at')
	list_filter = ('empresa', 'read_at')
	search_fields = ('user__username', 'mensaje__contenido', 'mensaje__conversacion__nombre')
	readonly_fields = tuple(field.name for field in MensajeLeido._meta.fields)

	def has_add_permission(self, request):
		return False

	def has_change_permission(self, request, obj=None):
		return False

	def has_delete_permission(self, request, obj=None):
		return False

