from django.contrib import admin
from .models import AuditoriaBibliotecaEvent


@admin.register(AuditoriaBibliotecaEvent)
class AuditoriaBibliotecaEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'user', 'empresa_id', 'action', 'status_code', 'path')
    list_filter = ('action', 'status_code', 'created_at')
    search_fields = ('user__username', 'path', 'message_key')
    readonly_fields = ('created_at', 'user', 'empresa_id', 'action', 'object_type', 'object_id', 
                       'ip_address', 'user_agent', 'method', 'path', 'querystring', 
                       'status_code', 'duration_ms', 'message_key', 'meta', 'before', 'after')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
