from rest_framework import serializers
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


class TipoProyectoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoProyecto
        fields = ['id', 'nombre', 'activo', 'fecha_creacion']
        read_only_fields = ['id', 'fecha_creacion']


class EspecialidadProfesionalSerializer(serializers.ModelSerializer):
    class Meta:
        model = EspecialidadProfesional
        fields = ['id', 'nombre', 'activo', 'fecha_creacion']
        read_only_fields = ['id', 'fecha_creacion']


class ClienteEmpresaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClienteEmpresa
        fields = [
            'id', 'nombre', 'rut', 'telefono', 'email', 'direccion',
            'ciudad', 'contacto_nombre', 'contacto_telefono', 'activo'
        ]
        read_only_fields = ['id']


class ProfesionalSerializer(serializers.ModelSerializer):
    especialidad_nombre = serializers.CharField(source='especialidad_ref.nombre', read_only=True)

    class Meta:
        model = Profesional
        fields = [
            'id', 'nombre', 'rut', 'email', 'telefono', 'especialidad_texto',
            'especialidad_ref', 'especialidad_nombre', 'user', 'activo'
        ]
        read_only_fields = ['id', 'especialidad_ref']


class TareaSerializer(serializers.ModelSerializer):
    profesional_nombre = serializers.CharField(source='profesional_asignado.nombre', read_only=True)
    proyecto_nombre = serializers.CharField(source='proyecto.nombre', read_only=True)
    tipo_tarea_nombre = serializers.CharField(source='tipo_tarea.nombre', read_only=True)

    class Meta:
        model = Tarea
        fields = [
            'id', 'nombre', 'descripcion', 'proyecto', 'proyecto_nombre',
            'tipo_tarea', 'tipo_tarea_nombre', 'profesional_asignado', 'profesional_nombre',
            'estado', 'prioridad', 'porcentaje_avance',
            'fecha_inicio_plan', 'fecha_fin_plan', 'fecha_inicio_real', 'fecha_fin_real',
            'horas_estimadas', 'horas_reales', 'depende_de', 'fecha_creacion', 'fecha_actualizacion'
        ]
        read_only_fields = ['id', 'fecha_creacion', 'fecha_actualizacion']


class ProyectoSerializer(serializers.ModelSerializer):
    tipo_nombre = serializers.CharField(source='tipo_ref.nombre', read_only=True)
    cliente_nombre = serializers.CharField(source='cliente.nombre', read_only=True)
    empresa_nombre = serializers.CharField(source='empresa_interna.descripcion', read_only=True)
    profesionales_count = serializers.SerializerMethodField()
    tareas_count = serializers.SerializerMethodField()

    class Meta:
        model = Proyecto
        fields = [
            'id', 'nombre', 'descripcion', 'empresa_interna', 'empresa_nombre',
            'cliente', 'cliente_nombre', 'tipo_texto', 'tipo_ref', 'tipo_nombre',
            'estado', 'profesionales', 'profesionales_count', 'tareas_count',
            'fecha_inicio_estimada', 'fecha_termino_estimada', 'fecha_inicio_real',
            'fecha_termino_real', 'presupuesto', 'monto_facturado', 'observaciones',
            'activo', 'fecha_creacion', 'fecha_actualizacion'
        ]
        read_only_fields = ['id', 'tipo_ref', 'fecha_creacion', 'fecha_actualizacion']

    def get_profesionales_count(self, obj):
        return obj.profesionales.count()

    def get_tareas_count(self, obj):
        return obj.tareas.count()

class TipoTareaSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoTarea
        fields = ['id', 'nombre', 'descripcion', 'activo', 'fecha_creacion', 'fecha_actualizacion']
        read_only_fields = ['id', 'fecha_creacion', 'fecha_actualizacion']


class DocumentoRequeridoTipoTareaSerializer(serializers.ModelSerializer):
    tipo_tarea_nombre = serializers.CharField(source='tipo_tarea.nombre', read_only=True)

    class Meta:
        model = DocumentoRequeridoTipoTarea
        fields = [
            'id', 'tipo_tarea', 'tipo_tarea_nombre', 'nombre_documento', 'descripcion',
            'es_obligatorio', 'categoria', 'tipo_doc', 'orden', 'fecha_creacion'
        ]
        read_only_fields = ['id', 'fecha_creacion']


class TareaDocumentoSerializer(serializers.ModelSerializer):
    tarea_nombre = serializers.CharField(source='tarea.nombre', read_only=True)
    proyecto_nombre = serializers.CharField(source='tarea.proyecto.nombre', read_only=True)
    responsable_nombre = serializers.CharField(source='responsable.get_full_name', read_only=True)

    class Meta:
        model = TareaDocumento
        fields = [
            'id', 'tarea', 'tarea_nombre', 'proyecto_nombre', 'nombre_documento', 'descripcion',
            'tipo_doc', 'es_obligatorio', 'categoria', 'estado', 'responsable', 'responsable_nombre',
            'documento_biblioteca', 'archivo', 'url_documento', 'observaciones', 
            'fecha_esperada', 'fecha_recibida', 'fecha_aprobacion',
            'fecha_creacion', 'fecha_actualizacion'
        ]
        read_only_fields = ['id', 'fecha_creacion', 'fecha_actualizacion']