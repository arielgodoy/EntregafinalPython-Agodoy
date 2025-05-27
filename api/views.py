from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from .models import Contratopublicidad,LmovimientosDetalle19
from biblioteca.models import Propietario
from .serializers import PropietarioSerializer
from django.conf import settings
from common.utils import crear_conexion,sql_sistema


# class TrabajadoresViewSet(ReadOnlyModelViewSet):
#     def list(self, request, *args, **kwargs):
#         cliente_sistema = settings.CONFIGURACIONES['CLIENTE_SISTEMA']
#         empresa_codigo = self.request.session.get("empresa_codigo", "00")  # Por defecto "00"
#         basedatos = f"{cliente_sistema}remu{empresa_codigo}"
#         conexion = crear_conexion(basedatos)                
        
#         search_query = self.request.query_params.get('search', '').strip()  # Obtener el parámetro `search`
#         filtro_base = 'año="2025" AND mes ="01"'
#         orderby = 'ORDER BY nombre'
        
#         if search_query:
#             filtro_base += f' AND (nombre LIKE "%%{search_query}%%" OR rut LIKE "%%{search_query}%%")'

#         consulta = """
#             SELECT rut, nombre FROM %s.mt_fijo WHERE %s %s
#         """
#         parametros = (basedatos, filtro_base, orderby)
        
#         try:            
#             with conexion.cursor() as cursor:
#                 cursor.execute(consulta % parametros)  # Formatear la consulta con parámetros
#                 resultados = cursor.fetchall()            
#             trabajadores = [{'rut': row[0], 'nombre': row[1]} for row in resultados]
#             return Response({'status': 'success', 'data': trabajadores})
#         except Exception as e:
#             return Response({'status': 'error', 'message': str(e)}, status=500)



class TrabajadoresViewSet(ReadOnlyModelViewSet):
    def list(self, request, *args, **kwargs):
        cliente_sistema = settings.CONFIGURACIONES['CLIENTE_SISTEMA']
        empresa_codigo = self.request.session.get("empresa_codigo", "00")  # Por defecto "00"
        basedatos = f"{cliente_sistema}remu{empresa_codigo}"        
        # Obtener el parámetro `search`
        search_query = self.request.query_params.get('search', '').strip()  
        filtro_base = 'año="2023" AND mes="01"'
        
        # Agregar filtro por búsqueda
        if search_query:
            filtro_base += f' AND (nombre LIKE "%%{search_query}%%" OR rut LIKE "%%{search_query}%%")'

        # Definir la tabla y operación
        tabla = "mt_fijo"
        operacion = 0  # Leer
        
        try:
            # Llamar a la función sql_sistema
            resultado = sql_sistema(
                operacion=operacion,
                base_datos=basedatos,
                tabla=tabla,
                condicion=filtro_base,
                objeto={}
            )
            
            if resultado['status'] == 0:
                trabajadores = resultado['resultado']
                return Response({'status': 'success', 'data': trabajadores})
            elif resultado['status'] == 4:
                return Response({'status': 'error', 'message': 'No se encontraron resultados.'}, status=404)
            else:
                return Response({'status': 'error', 'message': 'Error al realizar la operación.'}, status=500)
        
        except Exception as e:
            return Response({'status': 'error', 'message': str(e)}, status=500)
        
class MaestroempresasMRO(ReadOnlyModelViewSet):
    def list(self, request, *args, **kwargs):
        cliente_sistema = settings.CONFIGURACIONES['CLIENTE_SISTEMA']
        empresa_codigo = self.request.session.get("empresa_codigo", "00")  # Por defecto "00"
        basedatos = f"{cliente_sistema}remu{empresa_codigo}"        
        # Obtener el parámetro `search`
        search_query = self.request.query_params.get('search', '').strip()  
        filtro_base = 'año="2023" AND mes="01"'
        
        # Agregar filtro por búsqueda
        if search_query:
            filtro_base += f' AND (nombre LIKE "%%{search_query}%%" OR rut LIKE "%%{search_query}%%")'

        # Definir la tabla y operación
        tabla = "mt_fijo"
        operacion = 0  # Leer
        
        try:
            # Llamar a la función sql_sistema
            resultado = sql_sistema(
                operacion=operacion,
                base_datos=basedatos,
                tabla=tabla,
                condicion=filtro_base,
                objeto={}
            )
            
            if resultado['status'] == 0:
                trabajadores = resultado['resultado']
                return Response({'status': 'success', 'data': trabajadores})
            elif resultado['status'] == 4:
                return Response({'status': 'error', 'message': 'No se encontraron resultados.'}, status=404)
            else:
                return Response({'status': 'error', 'message': 'Error al realizar la operación.'}, status=500)
        
        except Exception as e:
            return Response({'status': 'error', 'message': str(e)}, status=500)


#API-REST  DE DJANGO
class PropietarioViewSet(ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Propietario.objects.all()
    serializer_class = PropietarioSerializer
    filter_backends = [SearchFilter]
    search_fields = ['nombre', 'rut']

