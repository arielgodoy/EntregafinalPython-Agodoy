from django.contrib import admin

from .models import ApiToken, Contratopublicidad, LmovimientosDetalle19

admin.site.register(Contratopublicidad)
admin.site.register(LmovimientosDetalle19)


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
	list_display = ("name", "user", "prefix", "is_active", "expires_at", "last_used_at")
	list_filter = ("is_active", "expires_at")
	search_fields = ("name", "prefix", "user__username")
	readonly_fields = ("prefix", "token_hash", "created_at", "revoked_at", "last_used_at")

