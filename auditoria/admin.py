from django.contrib import admin

from .models import (
    AuditArchiveBatch,
    AuditArchivePurgeChunk,
    AuditoriaBibliotecaEvent,
    AuditoriaGestionDTEEvent,
    UserPresence,
)


class ReadOnlyAuditAdmin(admin.ModelAdmin):
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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


@admin.register(AuditoriaGestionDTEEvent)
class AuditoriaGestionDTEEventAdmin(ReadOnlyAuditAdmin):
    fields = (
        'id', 'created_at', 'user', 'empresa_id', 'action', 'object_type',
        'object_id', 'status_code', 'duration_ms', 'vista_nombre', 'message_key',
    )
    list_display = (
        'id', 'created_at', 'user', 'action', 'object_type',
        'status_code', 'vista_nombre',
    )
    list_filter = ('action', 'status_code', 'created_at')
    readonly_fields = fields
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)


@admin.register(UserPresence)
class UserPresenceAdmin(ReadOnlyAuditAdmin):
    fields = ('user', 'empresa_id', 'app_label', 'vista_nombre', 'activity_status', 'last_seen')
    list_display = ('user', 'empresa_id', 'app_label', 'vista_nombre', 'activity_status', 'last_seen')
    list_filter = ('app_label',)
    readonly_fields = fields
    date_hierarchy = 'last_seen'
    ordering = ('-last_seen',)


@admin.register(AuditArchiveBatch)
class AuditArchiveBatchAdmin(ReadOnlyAuditAdmin):
    fields = (
        'id', 'batch_id', 'app_label', 'cutoff_datetime', 'status',
        'source_count', 'archive_count', 'purged_count', 'validated_at',
        'purged_at', 'created_at', 'updated_at',
    )
    list_display = (
        'batch_id', 'app_label', 'cutoff_datetime', 'status',
        'source_count', 'archive_count', 'purged_count', 'created_at',
    )
    list_filter = ('app_label', 'status', 'cutoff_datetime')
    readonly_fields = fields
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)


@admin.register(AuditArchivePurgeChunk)
class AuditArchivePurgeChunkAdmin(ReadOnlyAuditAdmin):
    fields = (
        'id', 'batch', 'sequence', 'expected_count', 'deleted_count',
        'status', 'started_at', 'completed_at',
    )
    list_display = (
        'id', 'batch', 'sequence', 'status', 'expected_count',
        'deleted_count', 'started_at', 'completed_at',
    )
    list_filter = ('status',)
    readonly_fields = fields
    ordering = ('batch_id', 'sequence')
