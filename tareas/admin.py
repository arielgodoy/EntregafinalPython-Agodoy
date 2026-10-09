from django.contrib import admin

from .models import (
    Avance,
    CausaAtraso,
    Comentario,
    ComentarioAdjunto,
    ComentarioPausaLectura,
    ComentarioVersion,
    ComentarioVersionDocumento,
    CorrelativoEmpresa,
    CorrelativoTodoEmpresa,
    Cotizacion,
    DocumentoCotizacion,
    DocumentoHistorial,
    DocumentoTarea,
    EnlaceTarea,
    EvaluacionSimilitud,
    EvidenciaCierre,
    EventoAccesoEnlace,
    Hito,
    HitoEvidencia,
    HitoHistorial,
    MiniTarea,
    MiniTareaEvento,
    ReunionParticipante,
    ReunionRevision,
    ReunionTarea,
    Reprogramacion,
    RondaCotizacion,
    Tarea,
    TareaAnulacionSnapshot,
    TareaCierre,
    TareaLectura,
    TareaParticipante,
    TareaReasignacion,
    TareaRelacion,
    TareaTransicion,
    Todo,
    TodoEvento,
    TareaConnectionRole,
    UmbralSimilitudEmpresa,
)


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


class ReadOnlyAdmin(admin.ModelAdmin):
    actions = None

    hidden_detail_fields = frozenset(
        {
            'archivo',
            'comentario',
            'comentario_cierre',
            'comentario_feed',
            'comentario_leido_hasta',
            'comentario_revision',
            'contenido',
            'datos_anteriores',
            'datos_nuevos',
            'descripcion',
            'destinatarios_email',
            'destinatarios_notificacion',
            'justificacion',
            'lugar_o_enlace',
            'mini_tarea',
            'motivo',
            'observaciones',
            'resena_cierre',
            'token_hash',
            'url',
        }
    )
    safe_list_fields = (
        'codigo',
        'correlativo',
        'titulo',
        'nombre',
        'estado',
        'estado_anterior',
        'estado_destino',
        'estado_origen',
        'accion',
        'tipo',
        'tipo_evento',
        'tipo_ambito',
        'prioridad',
        'rol',
        'decision',
        'modo',
        'activo',
        'anulada',
        'fechas_pendientes_confirmacion',
        'cierre_completado',
        'requiere_evidencia_cierre',
        'completado',
        'hecho',
        'vigente',
        'oculto',
        'leido',
        'supera_umbral',
        'porcentaje',
        'umbral_aplicado',
        'cumplimiento',
        'peso',
        'monto',
        'orden',
        'version',
        'numero_version',
        'numero',
        'minimo_cotizaciones',
        'siguiente_numero',
        'fecha_creacion',
        'created_at',
        'updated_at',
        'fecha_publicacion',
        'fecha_asignacion',
        'fecha_tope',
        'fecha_cumplimiento',
        'fecha_actualizacion',
        'fecha_completado',
        'fecha',
        'timestamp',
        'timestamp_anulacion',
        'timestamp_reactivacion',
        'fecha_lectura',
        'fecha_operacion',
        'fecha_tope_anterior',
        'fecha_tope_nueva',
        'fecha_apertura',
        'fecha_cierre',
        'fecha_cotizacion',
        'fecha_documento',
        'fecha_vencimiento',
        'desde',
        'hasta',
        'fecha_expiracion',
        'revocado_at',
        'fecha_hora_programada',
        'convocada_at',
        'confirmada_at',
    )

    def get_list_display(self, request):
        scalar_fields = {
            field.name
            for field in self.model._meta.concrete_fields
            if not field.is_relation and field.name not in self.hidden_detail_fields
        }
        extra_fields = tuple(
            name for name in self.safe_list_fields if name in scalar_fields
        )[:7]
        return (self.model._meta.pk.name, *extra_fields)

    def get_exclude(self, request, obj=None):
        return tuple(
            field.name
            for field in self.model._meta.concrete_fields
            if field.name in self.hidden_detail_fields
        )

    def get_readonly_fields(self, request, obj=None):
        return tuple(
            field.name
            for field in self.model._meta.concrete_fields
            if field.name not in self.hidden_detail_fields
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


READ_ONLY_MODELS = (
    Tarea,
    EvaluacionSimilitud,
    UmbralSimilitudEmpresa,
    ReunionRevision,
    ReunionTarea,
    ReunionParticipante,
    Avance,
    Hito,
    HitoHistorial,
    HitoEvidencia,
    MiniTarea,
    MiniTareaEvento,
    DocumentoTarea,
    DocumentoHistorial,
    EvidenciaCierre,
    CorrelativoEmpresa,
    CorrelativoTodoEmpresa,
    Todo,
    TodoEvento,
    TareaTransicion,
    TareaCierre,
    TareaAnulacionSnapshot,
    TareaParticipante,
    TareaLectura,
    Comentario,
    ComentarioAdjunto,
    ComentarioVersion,
    ComentarioVersionDocumento,
    ComentarioPausaLectura,
    EnlaceTarea,
    EventoAccesoEnlace,
    TareaReasignacion,
    CausaAtraso,
    Reprogramacion,
    TareaRelacion,
    RondaCotizacion,
    Cotizacion,
    DocumentoCotizacion,
)

admin.site.register(READ_ONLY_MODELS, ReadOnlyAdmin)
