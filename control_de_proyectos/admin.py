from django.contrib import admin
from .models import (
    TipoProyecto,
    EspecialidadProfesional,
    ClienteEmpresa,
    Profesional,
    Proyecto,
    Tarea,
    TipoTarea,
    DocumentoRequeridoTipoTarea,
    TareaDocumento,
)


@admin.register(TipoProyecto)
class TipoProyectoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'activo', 'fecha_creacion']
    list_filter = ['activo', 'fecha_creacion']
    search_fields = ['nombre']
    ordering = ['nombre']


@admin.register(EspecialidadProfesional)
class EspecialidadProfesionalAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'activo', 'fecha_creacion']
    list_filter = ['activo', 'fecha_creacion']
    search_fields = ['nombre']
    ordering = ['nombre']


@admin.register(ClienteEmpresa)
class ClienteEmpresaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'rut', 'email', 'activo', 'fecha_creacion']
    list_filter = ['activo', 'ciudad', 'fecha_creacion']
    search_fields = ['nombre', 'rut', 'email', 'contacto_nombre']
    ordering = ['nombre']
    readonly_fields = ['fecha_creacion', 'fecha_actualizacion']
    fieldsets = (
        ('Información General', {
            'fields': ('nombre', 'rut', 'email', 'telefono', 'activo')
        }),
        ('Dirección', {
            'fields': ('direccion', 'ciudad')
        }),
        ('Contacto Principal', {
            'fields': ('contacto_nombre', 'contacto_telefono')
        }),
        ('Auditoría', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Profesional)
class ProfesionalAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'rut', 'especialidad_ref', 'email', 'user', 'activo']
    list_filter = ['activo', 'especialidad_ref', 'fecha_creacion']
    search_fields = ['nombre', 'rut', 'email', 'especialidad_texto']
    ordering = ['nombre']
    readonly_fields = ['fecha_creacion', 'fecha_actualizacion', 'especialidad_ref']
    fieldsets = (
        ('Información Personal', {
            'fields': ('nombre', 'rut', 'email', 'telefono')
        }),
        ('Especialidad', {
            'fields': ('especialidad_texto', 'especialidad_ref')
        }),
        ('Acceso al Sistema', {
            'fields': ('user', 'activo')
        }),
        ('Auditoría', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Proyecto)
class ProyectoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'empresa_interna', 'cliente', 'tipo_ref', 'estado', 'fecha_inicio_estimada']
    list_filter = ['empresa_interna', 'cliente', 'tipo_ref', 'estado', 'fecha_creacion']
    search_fields = ['nombre', 'cliente__nombre', 'descripcion']
    filter_horizontal = ['profesionales']
    readonly_fields = ['fecha_creacion', 'fecha_actualizacion', 'tipo_ref']
    ordering = ['-fecha_creacion']
    fieldsets = (
        ('Información General', {
            'fields': ('nombre', 'descripcion', 'estado', 'activo')
        }),
        ('Empresas', {
            'fields': ('empresa_interna', 'cliente')
        }),
        ('Tipo', {
            'fields': ('tipo_texto', 'tipo_ref')
        }),
        ('Fechas', {
            'fields': ('fecha_inicio_estimada', 'fecha_termino_estimada', 'fecha_inicio_real', 'fecha_termino_real')
        }),
        ('Presupuesto', {
            'fields': ('presupuesto', 'monto_facturado')
        }),
        ('Equipo', {
            'fields': ('profesionales',)
        }),
        ('Observaciones', {
            'fields': ('observaciones',),
            'classes': ('collapse',)
        }),
        ('Auditoría', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )


class TareaDocumentoInline(admin.TabularInline):
    model = TareaDocumento
    extra = 0
    fields = ['nombre_documento', 'estado', 'responsable', 'fecha_entrega', 'archivo']
    readonly_fields = ['fecha_creacion']


@admin.register(Tarea)
class TareaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'proyecto', 'profesional_asignado', 'tipo_tarea', 'estado', 'prioridad', 'porcentaje_avance', 'fecha_fin_plan']
    list_filter = ['proyecto', 'tipo_tarea', 'estado', 'prioridad', 'profesional_asignado', 'fecha_creacion']
    search_fields = ['nombre', 'proyecto__nombre', 'descripcion']
    readonly_fields = ['fecha_creacion', 'fecha_actualizacion']
    filter_horizontal = ['depende_de']
    ordering = ['proyecto', '-prioridad', '-fecha_creacion']
    inlines = [TareaDocumentoInline]
    fieldsets = (
        ('Información General', {
            'fields': ('nombre', 'descripcion', 'proyecto', 'tipo_tarea')
        }),
        ('Asignación', {
            'fields': ('profesional_asignado',)
        }),
        ('Estado y Prioridad', {
            'fields': ('estado', 'prioridad')
        }),
        ('Fechas Planificadas', {
            'fields': ('fecha_inicio_plan', 'fecha_fin_plan')
        }),
        ('Fechas Reales', {
            'fields': ('fecha_inicio_real', 'fecha_fin_real')
        }),
        ('Seguimiento', {
            'fields': ('porcentaje_avance', 'horas_estimadas', 'horas_reales')
        }),
        ('Dependencias', {
            'fields': ('depende_de',),
            'classes': ('collapse',)
        }),
        ('Auditoría', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )


class DocumentoRequeridoTipoTareaInline(admin.TabularInline):
    model = DocumentoRequeridoTipoTarea
    extra = 1
    fields = ['nombre_documento', 'categoria', 'tipo_doc', 'es_obligatorio', 'orden']


@admin.register(TipoTarea)
class TipoTareaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'activo', 'fecha_creacion']
    list_filter = ['activo', 'fecha_creacion']
    search_fields = ['nombre', 'descripcion']
    inlines = [DocumentoRequeridoTipoTareaInline]
    fieldsets = (
        ('Información General', {
            'fields': ('nombre', 'descripcion', 'activo')
        }),
        ('Auditoría', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['fecha_creacion', 'fecha_actualizacion']


@admin.register(DocumentoRequeridoTipoTarea)
class DocumentoRequeridoTipoTareaAdmin(admin.ModelAdmin):
    list_display = ['nombre_documento', 'tipo_tarea', 'tipo_doc', 'es_obligatorio', 'categoria', 'orden']
    list_filter = ['tipo_tarea', 'tipo_doc', 'es_obligatorio', 'categoria']
    search_fields = ['nombre_documento', 'descripcion']
    ordering = ['tipo_tarea', 'orden']
    fieldsets = (
        ('Información General', {
            'fields': ('tipo_tarea', 'nombre_documento', 'descripcion')
        }),
        ('Configuración', {
            'fields': ('es_obligatorio', 'categoria', 'tipo_doc', 'orden')
        }),
    )


@admin.register(TareaDocumento)
class TareaDocumentoAdmin(admin.ModelAdmin):
    list_display = ['get_tarea_nombre', 'nombre_documento', 'tipo_doc', 'estado', 'responsable']
    list_filter = ['tarea__proyecto', 'tarea', 'estado', 'tipo_doc', 'fecha_creacion']
    search_fields = ['tarea__nombre', 'nombre_documento', 'observaciones']
    readonly_fields = ['fecha_creacion', 'fecha_actualizacion']
    ordering = ['-fecha_creacion']
    fieldsets = (
        ('Tarea y Documento', {
            'fields': ('tarea', 'nombre_documento', 'descripcion')
        }),
        ('Tipo y Configuración', {
            'fields': ('tipo_doc', 'es_obligatorio', 'categoria')
        }),
        ('Estado', {
            'fields': ('estado', 'responsable')
        }),
        ('Contenido', {
            'fields': ('documento_biblioteca', 'archivo', 'url_documento')
        }),
        ('Fechas', {
            'fields': ('fecha_entrega',)
        }),
        ('Observaciones', {
            'fields': ('observaciones',),
            'classes': ('collapse',)
        }),
        ('Auditoría', {
            'fields': ('fecha_creacion', 'fecha_actualizacion'),
            'classes': ('collapse',)
        }),
    )
    
    def get_tarea_nombre(self, obj):
        return f"{obj.tarea.proyecto.nombre} - {obj.tarea.nombre}"
    get_tarea_nombre.short_description = "Tarea"
