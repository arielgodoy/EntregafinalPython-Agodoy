from rest_framework import viewsets, filters, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
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
from .serializers import (
    TipoProyectoSerializer,
    EspecialidadProfesionalSerializer,
    ClienteEmpresaSerializer,
    ProfesionalSerializer,
    ProyectoSerializer,
    TareaSerializer,
    TipoTareaSerializer,
    DocumentoRequeridoTipoTareaSerializer,
    TareaDocumentoSerializer,
)


class TipoProyectoViewSet(viewsets.ModelViewSet):
    """CRUD para Tipos de Proyecto"""
    queryset = TipoProyecto.objects.filter(activo=True)
    serializer_class = TipoProyectoSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre']
    ordering_fields = ['nombre', 'fecha_creacion']
    ordering = ['nombre']


class EspecialidadProfesionalViewSet(viewsets.ModelViewSet):
    """CRUD para Especialidades Profesionales"""
    queryset = EspecialidadProfesional.objects.filter(activo=True)
    serializer_class = EspecialidadProfesionalSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre']
    ordering_fields = ['nombre', 'fecha_creacion']
    ordering = ['nombre']


class ClienteEmpresaViewSet(viewsets.ModelViewSet):
    """CRUD para Clientes Empresa"""
    queryset = ClienteEmpresa.objects.filter(activo=True)
    serializer_class = ClienteEmpresaSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'rut', 'email']
    ordering_fields = ['nombre', 'fecha_creacion']
    ordering = ['nombre']


class ProfesionalViewSet(viewsets.ModelViewSet):
    """CRUD para Profesionales"""
    queryset = Profesional.objects.filter(activo=True).select_related('especialidad_ref', 'user')
    serializer_class = ProfesionalSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'rut', 'email', 'especialidad_texto']
    ordering_fields = ['nombre', 'especialidad_texto', 'fecha_creacion']
    ordering = ['nombre']


class ProyectoViewSet(viewsets.ModelViewSet):
    """CRUD para Proyectos (filtra por empresa_interna de sesión)"""
    serializer_class = ProyectoSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'cliente__nombre', 'descripcion']
    ordering_fields = ['nombre', 'estado', 'fecha_creacion']
    ordering = ['-fecha_creacion']

    def get_queryset(self):
        empresa_id = self.request.session.get("empresa_id")
        return Proyecto.objects.filter(
            empresa_interna_id=empresa_id
        ).select_related(
            'empresa_interna', 'cliente', 'tipo_ref'
        ).prefetch_related('profesionales')


class TareaViewSet(viewsets.ModelViewSet):
    """CRUD para Tareas (filtra por empresa_interna del proyecto)"""
    serializer_class = TareaSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'descripcion']
    ordering_fields = ['prioridad', 'fecha_fin_plan', 'estado', 'porcentaje_avance']
    ordering = ['-prioridad', 'fecha_fin_plan']

    def get_queryset(self):
        empresa_id = self.request.session.get("empresa_id")
        return Tarea.objects.filter(
            proyecto__empresa_interna_id=empresa_id
        ).select_related('proyecto', 'profesional_asignado', 'tipo_tarea').prefetch_related('depende_de')

    @action(detail=False, methods=['get'])
    def por_proyecto(self, request):
        """Obtener tareas filtradas por proyecto"""
        proyecto_id = request.query_params.get('proyecto_id')
        if not proyecto_id:
            return Response(
                {'error': 'proyecto_id es requerido'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        empresa_id = request.session.get("empresa_id")
        tareas = self.get_queryset().filter(proyecto_id=proyecto_id)
        serializer = self.get_serializer(tareas, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def cambiar_estado(self, request, pk=None):
        """Cambiar el estado de la tarea con validaciones"""
        tarea = self.get_object()
        nuevo_estado = request.data.get('estado')
        
        if nuevo_estado == 'TERMINADA':
            if not tarea.puede_marcar_terminada():
                return Response(
                    {'error': 'No puede marcar como Terminada sin documentos de salida obligatorios'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif nuevo_estado == 'EN_CURSO':
            if not tarea.puede_marcar_en_curso():
                return Response(
                    {'error': 'No puede marcar como En Curso sin documentos de entrada obligatorios'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        tarea.estado = nuevo_estado
        tarea.save()
        serializer = self.get_serializer(tarea)
        return Response(serializer.data)


class TipoTareaViewSet(viewsets.ModelViewSet):
    """CRUD para Tipos de Tarea (Catálogo)"""
    queryset = TipoTarea.objects.filter(activo=True)
    serializer_class = TipoTareaSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'descripcion']
    ordering_fields = ['nombre', 'fecha_creacion']
    ordering = ['nombre']


class DocumentoRequeridoTipoTareaViewSet(viewsets.ModelViewSet):
    """CRUD para Documentos Requeridos por Tipo de Tarea"""
    serializer_class = DocumentoRequeridoTipoTareaSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre_documento', 'tipo_tarea__nombre']
    ordering_fields = ['tipo_tarea', 'orden', 'fecha_creacion']
    ordering = ['tipo_tarea', 'orden']

    def get_queryset(self):
        tipo_tarea_id = self.request.query_params.get('tipo_tarea_id')
        queryset = DocumentoRequeridoTipoTarea.objects.select_related('tipo_tarea')
        
        if tipo_tarea_id:
            queryset = queryset.filter(tipo_tarea_id=tipo_tarea_id)
        
        return queryset


class TareaDocumentoViewSet(viewsets.ModelViewSet):
    """CRUD para Documentos de Tarea con validaciones de estado"""
    serializer_class = TareaDocumentoSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['tarea__nombre', 'nombre_documento', 'tipo_doc']
    ordering_fields = ['estado', 'tipo_doc', 'fecha_esperada', 'fecha_creacion']
    ordering = ['-fecha_creacion']

    def get_queryset(self):
        empresa_id = self.request.session.get("empresa_id")
        tarea_id = self.request.query_params.get('tarea_id')
        tipo_doc = self.request.query_params.get('tipo_doc')
        
        # Si no hay empresa_id, retornar queryset vacío en lugar de error
        if not empresa_id:
            return TareaDocumento.objects.none()
        
        queryset = TareaDocumento.objects.filter(
            tarea__proyecto__empresa_interna_id=empresa_id
        ).select_related('tarea', 'responsable', 'documento_biblioteca')
        
        if tarea_id:
            queryset = queryset.filter(tarea_id=tarea_id)
        
        if tipo_doc:
            queryset = queryset.filter(tipo_doc=tipo_doc)
        
        return queryset

    @action(detail=True, methods=['post'])
    def cambiar_estado(self, request, pk=None):
        """Cambiar el estado del documento con validaciones"""
        documento = self.get_object()
        nuevo_estado = request.data.get('estado')
        
        # Estados válidos de transición
        transiciones_validas = {
            'PENDIENTE': ['ENVIADO', 'RECHAZADO'],
            'ENVIADO': ['RECIBIDO', 'RECHAZADO'],
            'RECIBIDO': ['APROBADO', 'RECHAZADO'],
            'APROBADO': ['ENTREGADO'],
            'RECHAZADO': ['ENVIADO', 'PENDIENTE'],
            'ENTREGADO': []
        }
        
        if nuevo_estado not in transiciones_validas.get(documento.estado, []):
            return Response(
                {'error': f'No se puede cambiar de {documento.estado} a {nuevo_estado}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        documento.estado = nuevo_estado
        documento.save()
        
        # Si es APROBADO y es salida, verificar si la tarea puede terminar
        if nuevo_estado == 'APROBADO' and documento.tipo_doc == 'SALIDA':
            documento.tarea.marcar_bloqueada_si_necesario()
        
        serializer = self.get_serializer(documento)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def por_tarea_y_tipo(self, request):
        """Obtener documentos filtrados por tarea y tipo"""
        tarea_id = request.query_params.get('tarea_id')
        tipo_doc = request.query_params.get('tipo_doc')
        
        if not tarea_id:
            return Response(
                {'error': 'tarea_id es requerido'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        queryset = self.get_queryset()
        if tipo_doc:
            queryset = queryset.filter(tipo_doc=tipo_doc)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        """Eliminar documento (elimina archivo del servidor también)"""
        documento = self.get_object()
        
        # Verificar que el usuario sea el propietario o tenga permisos
        if documento.responsable != request.user and not request.user.is_staff:
            return Response(
                {'error': 'No tienes permiso para eliminar este documento'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Eliminar archivo físico si existe
        if documento.archivo:
            try:
                documento.archivo.delete(save=False)
            except Exception as e:
                print(f"Error al eliminar archivo: {e}")
        
        # Eliminar registro de BD
        documento.delete()
        
        return Response(
            {'mensaje': 'Documento eliminado correctamente'},
            status=status.HTTP_204_NO_CONTENT
        )
