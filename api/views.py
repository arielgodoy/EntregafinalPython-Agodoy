import json

from rest_framework import viewsets
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import Contratopublicidad,LmovimientosDetalle19
from biblioteca.models import Propietario
from .serializers import PropietarioSerializer
from django.conf import settings
from common.utils import crear_conexion,sql_sistema
from access_control.decorators import verificar_permiso
from access_control.models import Empresa, Permiso, Vista
from acounts.services.config import get_effective_company_config
from acounts.services.email_service import send_security_email
from acounts.services.tokens import generate_token


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


@verificar_permiso('auth_invite', 'crear')
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

    user = User.objects.filter(username=email).first()
    if not user:
        user = User.objects.filter(email__iexact=email).first()

    if user and user.is_active:
        return JsonResponse({'detail': 'Usuario ya activo'}, status=400)

    if not user:
        user = User(username=email, email=email, is_active=False)
        user.set_unusable_password()
        user.save()

    # Requiere seed de access_control: Vista base "Maestro Usuarios".
    vista_base = Vista.objects.filter(nombre='Maestro Usuarios').first()
    if not vista_base:
        return JsonResponse(
            {
                'detail': 'NO ENCONTRADO: Vista base requerida para permisos no está configurada. Debe definirse por seed.'
            },
            status=400,
        )

    # Si el permiso ya existe, no se modifica para no pisar configuraciones manuales.
    Permiso.objects.get_or_create(
        usuario=user,
        empresa=empresa,
        vista=vista_base,
        defaults={
            'ingresar': True,
            'crear': False,
            'modificar': False,
            'eliminar': False,
            'autorizar': False,
            'supervisor': False,
        },
    )

    token = generate_token(user, meta={'empresa_id': empresa.id}, created_by=request.user)

    config = get_effective_company_config(empresa)
    public_base_url = config.get('public_base_url') if config else None
    if not public_base_url:
        return JsonResponse(
            {'detail': 'No hay public_base_url configurada para la empresa.'},
            status=400,
        )

    activation_link = f"{public_base_url.rstrip('/')}/auth/activate/{token}/"
    subject = 'Activación de cuenta'
    body_text = (
        'Has sido invitado a la plataforma.\n\n'
        f'Activa tu cuenta aquí: {activation_link}\n'
    )
    body_html = (
        '<p>Has sido invitado a la plataforma.</p>'
        f'<p><a href="{activation_link}">Activar cuenta</a></p>'
    )

    send_security_email(
        empresa=empresa,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        to_emails=[email],
    )

    return JsonResponse({'status': 'ok'})

