from django.contrib import admin

from .models import Departamento, Local


class ReadOnlyAdmin(admin.ModelAdmin):
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Local)
class LocalAdmin(ReadOnlyAdmin):
    list_display = ('empresa', 'codigo', 'nombre', 'activo', 'source', 'created_at', 'updated_at')
    list_filter = ('empresa', 'activo', 'source')
    search_fields = ('empresa__codigo', 'codigo', 'nombre')
    ordering = ('empresa__codigo', 'codigo')


@admin.register(Departamento)
class DepartamentoAdmin(ReadOnlyAdmin):
    list_display = ('empresa', 'codigo', 'nombre', 'activo', 'source', 'created_at', 'updated_at')
    list_filter = ('empresa', 'activo', 'source')
    search_fields = ('empresa__codigo', 'codigo', 'nombre')
    ordering = ('empresa__codigo', 'codigo')
