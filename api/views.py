import logging
import json
import socket
from datetime import date as date_cls
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from rest_framework import viewsets
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required
from .models import Contratopublicidad,LmovimientosDetalle19
from biblioteca.models import Propietario
from .serializers import PropietarioSerializer
from django.conf import settings
from common.utils import crear_conexion,sql_sistema
from access_control.models import Empresa, Permiso, Vista
from access_control.services.invite import invite_user_flow
from .services.buk_api import BukAPIError

logger = logging.getLogger(__name__)


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
    permission_classes = [IsAuthenticated]
    
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
    permission_classes = [IsAuthenticated]
    
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


@login_required
@require_POST
def invite_user(request):
    if request.content_type != 'application/json':
        return JsonResponse(
            {'detail': 'Content-Type debe ser application/json.'},
            status=400,
        )

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'detail': 'JSON inválido.'}, status=400)

    email = (payload.get('email') or '').strip().lower()
    empresa_id = payload.get('empresa_id')
    tipo_usuario = payload.get('tipo_usuario') or 'PROFESIONAL'

    if not email or not empresa_id:
        return JsonResponse(
            {'detail': 'email y empresa_id son obligatorios.'},
            status=400,
        )

    try:
        empresa = Empresa.objects.get(pk=empresa_id)
    except Empresa.DoesNotExist:
        return JsonResponse(
            {'detail': 'Empresa no encontrada.'},
            status=404,
        )

    vista_auth = Vista.objects.filter(nombre='auth_invite').first()
    if not vista_auth:
        return JsonResponse(
            {'detail': 'NO ENCONTRADO: Vista base requerida auth_invite no está configurada. Debe definirse por seed.'},
            status=400,
        )

    permiso = Permiso.objects.filter(usuario=request.user, empresa=empresa, vista=vista_auth).first()
    if not permiso or not permiso.crear:
        return JsonResponse({'detail': 'No tienes permiso para esta acción.'}, status=403)

    try:
        result = invite_user_flow(
            email=email,
            first_name=payload.get('first_name'),
            last_name=payload.get('last_name'),
            empresas=[empresa],
            tipo_usuario=tipo_usuario,
            usuario_referencia=None,
            created_by=request.user,
        )
    except Exception:
        return JsonResponse({'detail': 'No se pudo enviar el correo de invitación.'}, status=400)

    if not result.get('ok'):
        return JsonResponse({'detail': result.get('error')}, status=400)

    return JsonResponse({'status': 'ok', 'message': f"Invitación enviada a {email}."})


def _parse_bool_param(value, *, default=False):
    if value is None or value == '':
        return default

    normalized = str(value).strip().lower()
    if normalized in ('true', '1'):
        return True
    if normalized in ('false', '0'):
        return False

    raise ValueError('invalid boolean')


@login_required
@require_GET
def employees_active(request):
    logger.info("========== API employees_active ==========")

    # URL que llamó el cliente
    logger.info(f"Request URL: {request.build_absolute_uri()}")

    # Parámetros recibidos
    logger.info(f"Query params: {request.GET.dict()}")

    date_str = (request.GET.get('date') or '').strip()
    if not date_str:
        return JsonResponse({'detail': 'date es obligatorio.'}, status=400)

    try:
        date_cls.fromisoformat(date_str)
    except ValueError:
        return JsonResponse({'detail': 'date debe tener formato YYYY-MM-DD.'}, status=400)

    try:
        exclude_pending = _parse_bool_param(request.GET.get('exclude_pending'), default=False)
    except ValueError:
        return JsonResponse({'detail': 'exclude_pending debe ser true/false/1/0.'}, status=400)

    try:
        base_url = (getattr(settings, 'BUK_API_BASE_URL', '') or '').strip()
        token = (getattr(settings, 'BUK_API_AUTH_TOKEN', '') or '').strip()
        if not base_url or not token:
            raise BukAPIError('Integración Buk no configurada.', status_code=500)

        if not base_url.endswith('/'):
            base_url += '/'

        endpoint = urljoin(base_url, 'employees/active')
        params = {
            'date': date_str,
            'exclude_pending': 'true' if exclude_pending else 'false',
        }
        buk_url = f"{endpoint}?{urlencode(params)}"
        logger.info(f"BUK URL: {buk_url}")

        req = Request(
            buk_url,
            headers={
                'Accept': 'application/json',
                'auth_token': token,
            },
            method='GET',
        )

        try:
            resp = urlopen(req, timeout=10)
            try:
                status_code = getattr(resp, 'status', None) or resp.getcode()
                body = resp.read()
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
        except HTTPError as exc:
            try:
                exc.read()
            except Exception:
                pass
            logger.info(f"BUK status: {getattr(exc, 'code', None)}")
            raise BukAPIError(
                'Error al consultar Buk.',
                status_code=502,
                upstream_status=getattr(exc, 'code', None),
            ) from None
        except (URLError, socket.timeout, TimeoutError, OSError):
            raise BukAPIError('No se pudo conectar con Buk.', status_code=502) from None

        logger.info(f"BUK status: {status_code}")

        try:
            text = body.decode('utf-8')
        except Exception:
            raise BukAPIError('Respuesta inválida desde Buk.', status_code=502) from None

        if not text:
            data = {}
        else:
            try:
                data = json.loads(text)
            except ValueError:
                raise BukAPIError('Respuesta inválida desde Buk.', status_code=502) from None
    except BukAPIError as exc:
        payload = {'detail': exc.detail}
        if exc.upstream_status is not None:
            payload['upstream_status'] = exc.upstream_status
        return JsonResponse(payload, status=exc.status_code)

    return JsonResponse({'data': data}, status=200)

