from django.contrib import admin

from .models import Proveedor


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    fields = ('nombre', 'rut', 'activo', 'created_at', 'updated_at')
    list_display = ('nombre', 'rut', 'activo', 'created_at', 'updated_at')
    list_filter = ('activo',)
    readonly_fields = fields
    search_fields = ('nombre', 'rut')
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
