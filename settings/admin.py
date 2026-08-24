from django.contrib import admin
from .models import SettingsMySQLConnection, ThemePreferences, UserPreferences

@admin.register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
    list_display = ('user', 'data_layout', 'data_bs_theme', 'email_enabled', 'send_headers', 'send_documents')
    list_filter = ('data_bs_theme', 'data_layout', 'email_enabled')
    search_fields = ('user__username', 'user__email')

    fieldsets = (
        ('🖥️ Preferencias de Tema/Layout', {
            'fields': (
                'data_layout', 'data_bs_theme', 'data_sidebar_visibility',
                'data_layout_width', 'data_layout_position', 'data_topbar',
                'data_sidebar_size', 'data_layout_style', 'data_sidebar',
                'data_sidebar_image', 'data_preloader'
            )
        }),
        ('📧 Configuración de Correo Electrónico', {
            'classes': ('collapse',),  # contraído por defecto
            'fields': (
                'email_enabled',
                'email_protocol', 'email_host', 'email_port', 'email_encryption',
                'email_username',
                'smtp_host', 'smtp_port', 'smtp_encryption',
                'smtp_username',
            )
        }),
        ('🔔 Notificaciones', {
            'fields': ('send_headers', 'send_documents')
        }),
    )


@admin.register(ThemePreferences)
class ThemePreferencesAdmin(admin.ModelAdmin):
    list_display = ('user', 'empresa', 'data_layout', 'data_bs_theme')
    list_filter = ('data_bs_theme', 'data_layout', 'empresa')
    search_fields = ('user__username', 'user__email', 'empresa__codigo')

    fieldsets = (
        ('🖥️ Preferencias de Tema/Layout', {
            'fields': (
                'user', 'empresa',
                'data_layout', 'data_bs_theme', 'data_sidebar_visibility',
                'data_layout_width', 'data_layout_position', 'data_topbar',
                'data_sidebar_size', 'data_layout_style', 'data_sidebar',
                'data_sidebar_image', 'data_preloader'
            )
        }),
    )


@admin.register(SettingsMySQLConnection)
class SettingsMySQLConnectionAdmin(admin.ModelAdmin):
    list_display = ('empresa', 'nombre_logico', 'engine', 'host', 'port', 'user', 'db_name', 'is_active')
    list_filter = ('engine', 'is_active', 'empresa')
    search_fields = ('empresa__codigo', 'empresa__descripcion', 'nombre_logico', 'engine', 'host', 'user', 'db_name')
    exclude = ('password',)
    readonly_fields = tuple(field.name for field in SettingsMySQLConnection._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
