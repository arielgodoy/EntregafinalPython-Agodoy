from django.contrib import admin

from .models import EvaluacionConnectionRole, Persona


@admin.register(EvaluacionConnectionRole)
class EvaluacionConnectionRoleAdmin(admin.ModelAdmin):
    list_display = ("role", "connection_summary", "database_name")
    fields = ("role", "connection_summary", "database_name")
    readonly_fields = fields
    ordering = ("role",)

    @admin.display(description="Conexión central")
    def connection_summary(self, obj):
        if obj.mysql_connection_id is None:
            return "Sin conexión"
        connection = obj.mysql_connection
        return f"{connection.empresa.codigo} / {connection.nombre_logico}"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Persona)
class PersonaAdmin(admin.ModelAdmin):
    exclude = ("buk_payload",)
