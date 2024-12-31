from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from .models import Contratopublicidad,LmovimientosDetalle19
from biblioteca.models import Propietario
from .serializers import PropietarioSerializer
from django.conf import settings
from common.utils import crear_conexion

class TrabajadoresViewSet(ReadOnlyModelViewSet):    
    def list(self, request, *args, **kwargs):
        cliente_sistema = settings.CONFIGURACIONES['CLIENTE_SISTEMA']
        empresa_codigo = self.request.session.get("empresa_codigo", "00")  # Por defecto "00"
        basedatos = f"{cliente_sistema}remu{empresa_codigo}"
        conexion = crear_conexion(basedatos)                
        filtro='año="2023" AND mes ="05"'
        orderby = 'ORDER BY nombre'        
        consulta = """
            SELECT rut,nombre FROM %s.mt_fijo WHERE %s %s
        """
        parametros = (basedatos, filtro,orderby)
        try:            
            with conexion.cursor() as cursor:
                cursor.execute(consulta % parametros)  # Formatear la consulta con parámetros
                resultados = cursor.fetchall()            
            productos = [{'rut': row[0], 'nombre': row[1]} for row in resultados]
            return Response({'status': 'success', 'data': productos})
        except Exception as e:
            return Response({'status': 'error', 'message': str(e)}, status=500)


#API-REST  DE DJANGO
class PropietarioViewSet(ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Propietario.objects.all()
    serializer_class = PropietarioSerializer
    filter_backends = [SearchFilter]
    search_fields = ['nombre', 'rut']

