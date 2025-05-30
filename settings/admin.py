from django.contrib import admin
from .models import UserPreferences

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
                'email_username', 'email_password',
                'smtp_host', 'smtp_port', 'smtp_encryption',
                'smtp_username', 'smtp_password',
            )
        }),
        ('🔔 Notificaciones', {
            'fields': ('send_headers', 'send_documents')
        }),
    )
