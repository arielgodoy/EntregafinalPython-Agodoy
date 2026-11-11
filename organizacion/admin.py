from django.contrib import admin
from django.db import DEFAULT_DB_ALIAS
from django.db.models import F

from access_control.models import Empresa
from access_control.services.permissions import get_valid_users_for_empresa
from .models import (
    ControlOrganizacionEmpresa,
    Departamento,
    EventoMembresia,
    Local,
    MembresiaDepartamental,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EmpresaScopedReadOnlyAdmin(ReadOnlyAdmin):
    def _authorized_empresa_id(self, request):
        if not getattr(request.user, "is_authenticated", False):
            return None

        session = getattr(request, "session", None)
        raw_empresa_id = session.get("empresa_id") if session is not None else None
        if isinstance(raw_empresa_id, bool):
            return None
        if isinstance(raw_empresa_id, str):
            raw_empresa_id = raw_empresa_id.strip()
            if not raw_empresa_id.isascii() or not raw_empresa_id.isdecimal():
                return None
        elif not isinstance(raw_empresa_id, int):
            return None

        try:
            empresa_id = int(raw_empresa_id)
        except (TypeError, ValueError):
            return None
        if empresa_id < 1:
            return None

        empresa = Empresa.objects.using(DEFAULT_DB_ALIAS).filter(pk=empresa_id).first()
        if empresa is None:
            return None

        valid_users = get_valid_users_for_empresa(empresa, active_only=True).using(
            DEFAULT_DB_ALIAS
        )
        if not valid_users.filter(pk=request.user.pk).exists():
            return None
        return empresa.pk

    def has_module_permission(self, request):
        return super().has_module_permission(request) and self.has_view_permission(request)

    def has_view_permission(self, request, obj=None):
        if not super().has_view_permission(request, obj):
            return False
        empresa_id = self._authorized_empresa_id(request)
        if empresa_id is None:
            return False
        return obj is None or obj.empresa_id == empresa_id

    def get_queryset(self, request):
        queryset = super().get_queryset(request).using(DEFAULT_DB_ALIAS)
        if not super().has_view_permission(request):
            return queryset.none()
        empresa_id = self._authorized_empresa_id(request)
        if empresa_id is None:
            return queryset.none()
        return self.scope_queryset(queryset, empresa_id)

    def scope_queryset(self, queryset, empresa_id):
        return queryset.filter(empresa_id=empresa_id)


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


@admin.register(MembresiaDepartamental)
class MembresiaDepartamentalAdmin(EmpresaScopedReadOnlyAdmin):
    fields = (
        'id', 'empresa', 'departamento', 'usuario', 'rol', 'estado',
        'version', 'created_at', 'updated_at',
    )
    list_display = (
        'id', 'empresa', 'departamento', 'usuario', 'rol', 'estado',
        'version', 'created_at', 'updated_at',
    )
    list_filter = ('rol', 'estado')
    search_fields = ('departamento__codigo', 'departamento__nombre', 'usuario__username')
    readonly_fields = fields
    list_select_related = ('empresa', 'departamento', 'usuario')
    date_hierarchy = 'created_at'
    ordering = ('departamento__codigo', 'usuario__username')

    def scope_queryset(self, queryset, empresa_id):
        return queryset.filter(
            empresa_id=empresa_id,
            departamento__empresa_id=empresa_id,
        )


@admin.register(EventoMembresia)
class EventoMembresiaAdmin(EmpresaScopedReadOnlyAdmin):
    fields = (
        'id', 'empresa', 'departamento', 'membresia', 'usuario_afectado', 'autor',
        'fecha', 'operacion_id', 'secuencia', 'tipo', 'motivo',
        'rol_antes', 'estado_antes', 'version_antes',
        'rol_despues', 'estado_despues', 'version_despues',
    )
    list_display = (
        'id', 'fecha', 'empresa', 'departamento', 'usuario_afectado',
        'autor', 'tipo', 'operacion_id', 'secuencia',
    )
    list_filter = ('tipo', 'fecha')
    search_fields = (
        'operacion_id', 'departamento__codigo', 'usuario_afectado__username',
        'autor__username',
    )
    readonly_fields = fields
    list_select_related = (
        'empresa', 'departamento', 'membresia', 'usuario_afectado', 'autor',
    )
    date_hierarchy = 'fecha'
    ordering = ('-fecha', 'pk')

    def scope_queryset(self, queryset, empresa_id):
        return queryset.filter(
            empresa_id=empresa_id,
            departamento__empresa_id=empresa_id,
            membresia__empresa_id=empresa_id,
            membresia__departamento_id=F('departamento_id'),
            membresia__usuario_id=F('usuario_afectado_id'),
        )


@admin.register(ControlOrganizacionEmpresa)
class ControlOrganizacionEmpresaAdmin(EmpresaScopedReadOnlyAdmin):
    fields = ('id', 'empresa', 'version')
    list_display = ('id', 'empresa', 'version')
    readonly_fields = fields
    list_select_related = ('empresa',)
    ordering = ('empresa__codigo',)
