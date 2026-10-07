from django.contrib import admin

from .models import TareaConnectionRole


@admin.register(TareaConnectionRole)
class TareaConnectionRoleAdmin(admin.ModelAdmin):
    list_display = (
        "role",
        "source_type",
        "django_alias",
        "mysql_connection",
        "database_name",
        "updated_at",
    )
    list_filter = ("role", "source_type")
    search_fields = (
        "role",
        "source_type",
        "django_alias",
        "database_name",
        "mysql_connection__nombre_logico",
        "mysql_connection__db_name",
    )
    ordering = ("role",)
    list_select_related = ("mysql_connection", "mysql_connection__empresa")
    readonly_fields = tuple(field.name for field in TareaConnectionRole._meta.fields)
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
