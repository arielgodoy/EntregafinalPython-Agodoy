from django.contrib import admin

from .models import (
    CertificadoSII,
    CesionRPETC,
    CesionRPETCHistorial,
    EstadoContableCesion,
    LecturaAutomaticaConfig,
    LecturaAutomaticaEjecucion,
    TareaCesionRPETC,
    TareaRPETC,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CertificadoSII)
class CertificadoSIIAdmin(ReadOnlyAdmin):
    list_display = (
        'empresa_codigo', 'titular', 'emisor_certificado',
        'valido_desde', 'valido_hasta', 'activo', 'estado_vigencia',
    )
    list_filter = ('activo', 'valido_desde', 'valido_hasta')
    search_fields = ('empresa_codigo', 'titular', 'emisor_certificado', 'rut_titular', 'numero_serie')
    exclude = ('password_encrypted', 'archivo')


@admin.register(TareaRPETC)
class TareaRPETCAdmin(ReadOnlyAdmin):
    list_display = (
        'empresa', 'tipo_consulta', 'estado', 'fecha_desde', 'fecha_hasta',
        'consultada_en', 'actualizada_en',
    )
    list_filter = ('empresa', 'tipo_consulta', 'estado', 'formato')
    search_fields = ('empresa__codigo', 'id_tarea', 'rut_consultado', 'nombre_tarea')
    date_hierarchy = 'consultada_en'


@admin.register(CesionRPETC)
class CesionRPETCAdmin(ReadOnlyAdmin):
    list_display = (
        'id_cesion', 'tipo_doc', 'folio_doc', 'estado_cesion',
        'cedente_rut', 'cesionario_rut', 'fecha_cesion', 'monto_cesion',
    )
    list_filter = ('estado_cesion', 'tipo_doc', 'fecha_cesion')
    search_fields = (
        'id_cesion', 'folio_doc', 'deudor_rut', 'cedente_rut',
        'cesionario_rut', 'cedente_razon_social', 'cesionario_razon_social',
    )
    date_hierarchy = 'fecha_cesion'


@admin.register(LecturaAutomaticaConfig)
class LecturaAutomaticaConfigAdmin(ReadOnlyAdmin):
    list_display = ('id', 'habilitado', 'intervalo_minutos', 'ultima_ejecucion', 'proxima_ejecucion')
    list_filter = ('habilitado', 'intervalo_minutos')


@admin.register(LecturaAutomaticaEjecucion)
class LecturaAutomaticaEjecucionAdmin(ReadOnlyAdmin):
    list_display = (
        'lote_id', 'empresa', 'tipo_ejecucion', 'estado', 'progreso',
        'total_documentos', 'documentos_procesados', 'ultima_actualizacion',
    )
    list_filter = ('empresa', 'tipo_ejecucion', 'estado')
    search_fields = ('lote_id', 'empresa__codigo', 'mensaje_error')
    date_hierarchy = 'ultima_actualizacion'


@admin.register(EstadoContableCesion)
class EstadoContableCesionAdmin(ReadOnlyAdmin):
    list_display = (
        'empresa', 'cesion', 'estado_contabilizacion', 'estado_factoring',
        'estado_proveedor', 'estado_pago_resumen', 'estado_verificacion',
        'fecha_verificacion',
    )
    list_filter = (
        'empresa', 'estado_contabilizacion', 'estado_factoring',
        'estado_proveedor', 'estado_pago_resumen', 'estado_verificacion',
    )
    search_fields = ('empresa__codigo', 'cesion__id_cesion', 'cesion__folio_doc')
    date_hierarchy = 'fecha_verificacion'


@admin.register(TareaCesionRPETC)
class TareaCesionRPETCAdmin(ReadOnlyAdmin):
    list_display = ('tarea', 'cesion', 'rol_consulta', 'fecha_detectada', 'fila_origen')
    list_filter = ('rol_consulta', 'fecha_detectada')
    search_fields = ('tarea__id_tarea', 'cesion__id_cesion', 'cesion__folio_doc')
    date_hierarchy = 'fecha_detectada'


@admin.register(CesionRPETCHistorial)
class CesionRPETCHistorialAdmin(ReadOnlyAdmin):
    list_display = ('cesion', 'estado', 'estado_anterior', 'fecha_detectado', 'tarea_origen')
    list_filter = ('estado', 'fecha_detectado')
    search_fields = ('cesion__id_cesion', 'cesion__folio_doc', 'estado', 'observacion')
    date_hierarchy = 'fecha_detectado'
