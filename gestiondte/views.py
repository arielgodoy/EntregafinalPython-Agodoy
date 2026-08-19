from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from datetime import date
from urllib.parse import urlencode
from django.utils import timezone
from django.db.models import Q
from access_control.decorators import verificar_permiso

from .models import CertificadoSII, TareaRPETC, TareaCesionRPETC, CesionRPETC
from access_control.models import Empresa
from access_control.models import Permiso, Vista
from .forms import CertificadoUploadForm
from .utils.maestro import get_maestroempresa_by_codigo

try:
    from auditoria.helpers import audit_log
except Exception:
    audit_log = None


def _normalizar_rut_filtro(value):
    raw = (value or '').strip().replace('.', '').replace(' ', '')
    if not raw:
        return None, None
    if '-' in raw:
        rut, dv = raw.rsplit('-', 1)
        return rut or None, dv.upper() or None
    return raw, None


def _cesiones_rpetc_context(empresa_activa, fecha_seleccionada=None, filtros=None):
    """Construye resumen y detalle sin duplicar cesiones por tareas repetidas."""
    if not empresa_activa:
        return {
            'cesiones_por_fecha': [],
            'fecha_cesion_seleccionada': None,
            'cesiones_detalle': [],
            'total_cesiones_rpetc': 0,
            'monto_total_cedido': 0,
            'ultima_cesion': None,
            'ultima_sincronizacion': None,
            'tipos_doc_filtro': [],
            'estados_filtro': [],
            'filtros': {},
            'filtros_querystring': '',
            'filtros_error': None,
        }

    filtros = filtros or {}
    base_cesiones = CesionRPETC.objects.filter(
        tareas__tarea__empresa=empresa_activa,
    ).distinct()
    tipos_doc = sorted(set(base_cesiones.values_list('tipo_doc', flat=True)))
    estados = sorted(set(base_cesiones.values_list('estado_cesion', flat=True)))
    cesiones = base_cesiones
    proveedor_rut, proveedor_dv = _normalizar_rut_filtro(filtros.get('rut_proveedor'))
    if proveedor_rut:
        proveedor_q = Q(cedente_rut=proveedor_rut) | Q(vendedor_rut=proveedor_rut)
        if proveedor_dv:
            proveedor_q = (
                Q(cedente_rut=proveedor_rut, cedente_dv=proveedor_dv)
                | Q(vendedor_rut=proveedor_rut, vendedor_dv=proveedor_dv)
            )
        cesiones = cesiones.filter(proveedor_q)
    if filtros.get('tipo_doc'):
        cesiones = cesiones.filter(tipo_doc=filtros['tipo_doc'])
    if filtros.get('folio'):
        cesiones = cesiones.filter(folio_doc=filtros['folio'].strip())
    if filtros.get('estado'):
        cesiones = cesiones.filter(estado_cesion=filtros['estado'])
    if filtros.get('fecha_desde'):
        cesiones = cesiones.filter(fecha_cesion__date__gte=filtros['fecha_desde'])
    if filtros.get('fecha_hasta'):
        cesiones = cesiones.filter(fecha_cesion__date__lte=filtros['fecha_hasta'])
    summary = {}
    total_amount = 0
    for fecha, monto in cesiones.values_list('fecha_cesion', 'monto_cesion'):
        if not fecha:
            continue
        fecha_dia = timezone.localtime(fecha).date() if timezone.is_aware(fecha) else fecha.date()
        item = summary.setdefault(fecha_dia, {'fecha': fecha_dia, 'cantidad': 0, 'monto': 0})
        item['cantidad'] += 1
        item['monto'] += monto or 0
        total_amount += monto or 0
    summaries = sorted(summary.values(), key=lambda item: item['fecha'], reverse=True)[:30]
    allowed_dates = {item['fecha'] for item in summaries}
    if fecha_seleccionada not in allowed_dates:
        fecha_seleccionada = summaries[0]['fecha'] if summaries else None
    detail = []
    if fecha_seleccionada:
        detail = list(cesiones.filter(
            fecha_cesion__date=fecha_seleccionada,
        ).order_by('-fecha_cesion', 'id_cesion'))
    latest = cesiones.order_by('-fecha_cesion').first()
    latest_sync = TareaRPETC.objects.filter(empresa=empresa_activa).order_by('-consultada_en').first()
    return {
        'cesiones_por_fecha': summaries,
        'fecha_cesion_seleccionada': fecha_seleccionada,
        'cesiones_detalle': detail,
        'total_cesiones_rpetc': cesiones.count(),
        'monto_total_cedido': total_amount,
        'ultima_cesion': latest,
        'ultima_sincronizacion': latest_sync,
        'tipos_doc_filtro': tipos_doc,
        'estados_filtro': estados,
        'filtros': filtros,
        'filtros_querystring': urlencode({
            key: value.isoformat() if isinstance(value, date) else value
            for key, value in filtros.items() if value
        }),
        'filtros_error': None,
    }


@login_required
@verificar_permiso("Gestión DTE - Control de Cesiones", "ingresar")
def cesiones(request):
    """Vista principal: Control de Cesiones DTE."""
    # Datos de ejemplo/placeholder para la UI (KPIs)
    kpis = {
        'documentos_revisados': 0,
        'documentos_cedidos': 0,
        'documentos_no_cedidos': 0,
        'pendientes_revision': 0,
    }
    empresa_id = request.session.get('empresa_id')
    empresa_activa = Empresa.objects.filter(pk=empresa_id).first() if empresa_id else None
    from .forms import SincronizarCesionesRPETCForm
    can_sync = False
    if empresa_activa:
        vista = Vista.objects.filter(nombre='Gestión DTE - Control de Cesiones').first()
        permiso = Permiso.objects.filter(
            usuario=request.user, empresa=empresa_activa, vista=vista,
        ).first() if vista else None
        can_sync = bool(permiso and (permiso.modificar or permiso.supervisor))
    context = {
        'kpis': kpis,
        'empresa_activa': empresa_activa,
        'empresas_filtro': [empresa_activa] if empresa_activa else [],
        'can_sync_rpetc': can_sync,
        'sync_form': SincronizarCesionesRPETCForm(),
        'sync_result': None,
        'sync_error': None,
    }
    selected = request.GET.get('fecha_cesion')
    filtros = {
        key: request.GET.get(key, '').strip()
        for key in ('rut_proveedor', 'tipo_doc', 'folio', 'estado', 'fecha_desde', 'fecha_hasta')
    }
    filtros = {key: value for key, value in filtros.items() if value}
    filtros_error = None
    for field in ('fecha_desde', 'fecha_hasta'):
        if field in filtros:
            try:
                filtros[field] = date.fromisoformat(filtros[field])
            except ValueError:
                filtros_error = 'Las fechas del filtro no son válidas.'
                filtros.pop(field, None)
    if filtros.get('fecha_desde') and filtros.get('fecha_hasta') and filtros['fecha_desde'] > filtros['fecha_hasta']:
        filtros_error = 'La fecha desde no puede ser posterior a la fecha hasta.'
        filtros.pop('fecha_desde', None)
        filtros.pop('fecha_hasta', None)
    try:
        selected_date = date.fromisoformat(selected) if selected else None
    except ValueError:
        selected_date = None
    context.update(_cesiones_rpetc_context(empresa_activa, selected_date, filtros))
    context['filtros_error'] = filtros_error
    return render(request, 'gestiondte/cesiones.html', context)


@login_required
@verificar_permiso("Gestión DTE - Control de Cesiones", "modificar")
def sincronizar_cesiones_rpetc(request):
    from django.utils import timezone
    from .forms import SincronizarCesionesRPETCForm
    from .services.rpetc import (
        RPETCAuthenticationError, RPETCError, RPETCRateLimitError,
        RPETCTaskFailedError, RPETCTaskTimeoutError, RPETCUnauthorizedError,
        RPETCClient,
    )
    from .services.rpetc_importer import importar_resultado_rpetc
    from .services.rpetc_importer import RPETCImportError
    from .services.rpetc_parser import parsear_txt_rpetc

    empresa_id = request.session.get('empresa_id')
    empresa_activa = Empresa.objects.filter(pk=empresa_id).first() if empresa_id else None
    if not empresa_activa:
        return redirect('access_control:seleccionar_empresa')

    form = SincronizarCesionesRPETCForm(request.POST or None)
    context = {
        'kpis': {
            'documentos_revisados': 0,
            'documentos_cedidos': 0,
            'documentos_no_cedidos': 0,
            'pendientes_revision': 0,
        },
        'empresa_activa': empresa_activa,
        'empresas_filtro': [empresa_activa] if empresa_activa else [],
        'can_sync_rpetc': True,
        'sync_form': form,
        'sync_result': None,
        'sync_error': None,
    }
    context.update(_cesiones_rpetc_context(empresa_activa))
    if request.method != 'POST' or not form.is_valid():
        return render(request, 'gestiondte/cesiones.html', context)

    fecha_desde = form.cleaned_data['fecha_desde']
    fecha_hasta = form.cleaned_data['fecha_hasta']
    en_progreso = TareaRPETC.objects.filter(
        empresa=empresa_activa,
        tipo_consulta='DEUDOR',
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        estado__in=['CREADO', 'EN_PROCESO', 'EN PROCESO'],
    ).first()
    if en_progreso:
        context['sync_error'] = 'Ya existe una sincronización en progreso para ese período.'
        return render(request, 'gestiondte/cesiones.html', context)

    maestro = get_maestroempresa_by_codigo(empresa_activa.codigo)
    from .services.rpetc_importer import normalizar_rut
    rut_empresa, dv_empresa = normalizar_rut((maestro or {}).get('rut'))
    certificado = CertificadoSII.objects.filter(
        empresa_codigo=empresa_activa.codigo, activo=True,
    ).first()
    if not maestro or not rut_empresa or not dv_empresa:
        context['sync_error'] = 'No fue posible resolver el RUT de la empresa activa.'
        return render(request, 'gestiondte/cesiones.html', context)
    if not certificado:
        context['sync_error'] = 'No existe un certificado SII activo para la empresa activa.'
        return render(request, 'gestiondte/cesiones.html', context)

    try:
        resultado = RPETCClient(certificado).obtener_cesiones_deudor(
            rut_deudor=rut_empresa,
            dv_deudor=dv_empresa,
            desde=fecha_desde.strftime('%d%m%Y'),
            hasta=fecha_hasta.strftime('%d%m%Y'),
            formato='TXT',
            intervalo=3,
            max_intentos=20,
        )
        estado = resultado['estado_final']
        if estado.get('estado') != 'TERMINADO' or estado.get('codigoError') not in (0, '0', None):
            raise RPETCTaskFailedError(
                estado.get('descripcionError') or 'La tarea SII no terminó correctamente.',
                task_state=estado,
            )
        parseado = parsear_txt_rpetc(resultado['resultado']['bytes'])
        if parseado['consulta'].get('TIPO_CONSULTA') != 'DEUDOR' or not parseado['registros']:
            raise RPETCError('El resultado RPETC no contiene una consulta DEUDOR válida.')
        stats = importar_resultado_rpetc(
            empresa_activa,
            resultado['tarea_inicial'],
            estado,
            parseado,
            'DEUDOR',
            fecha_desde,
            fecha_hasta,
            'TXT',
        )
        context['sync_result'] = {
            **{key: value for key, value in stats.items() if key != 'tarea'},
            'id_tarea': resultado['tarea_inicial'].get('idTarea'),
            'periodo': f'{fecha_desde:%d/%m/%Y} - {fecha_hasta:%d/%m/%Y}',
            'fecha': timezone.localtime(),
        }
        context.update(_cesiones_rpetc_context(empresa_activa))
    except RPETCImportError:
        context['sync_error'] = 'Los datos recibidos del SII no pudieron guardarse.'
    except RPETCError as exc:
        if isinstance(exc, RPETCRateLimitError):
            message = 'El SII limitó temporalmente las solicitudes. Intenta más tarde.'
        elif isinstance(exc, RPETCUnauthorizedError):
            message = 'La empresa activa no está autorizada para esta consulta.'
        elif isinstance(exc, RPETCAuthenticationError):
            message = 'No fue posible autenticar contra el SII.'
        elif isinstance(exc, RPETCTaskTimeoutError):
            message = 'La consulta al SII excedió el tiempo máximo de espera.'
        elif isinstance(exc, RPETCTaskFailedError):
            message = 'La tarea RPETC terminó con error.'
        else:
            message = 'No fue posible completar la sincronización RPETC.'
        context['sync_error'] = message
    return render(request, 'gestiondte/cesiones.html', context)


@login_required
@verificar_permiso("Gestión DTE - Verificar Cesión", "ingresar")
def verificar_cesion(request):
    """Vista para consulta individual de cesión (placeholder)."""
    return render(request, 'gestiondte/verificar.html')


def index(request):
    """Página principal de Gestión DTE."""
    return render(request, 'gestiondte/index.html')


@login_required
@verificar_permiso("Gestión DTE - Certificados PFX-DTE", "ingresar")
def certificados_list(request):
    certificados = CertificadoSII.objects.all()
    # gather empresa info for codes present
    codigos = set(cert.empresa_codigo for cert in certificados)
    empresas = {c: get_maestroempresa_by_codigo(c) for c in codigos}
    # compute can_create for UI: if user has crear on active empresa OR on any empresa
    can_create_context = False
    vista = Vista.objects.filter(nombre="Gestión DTE - Certificados PFX-DTE").first()
    empresa_id = request.session.get('empresa_id')
    if vista:
        if empresa_id:
            permiso = Permiso.objects.filter(usuario=request.user, empresa_id=empresa_id, vista=vista).first()
            can_create_context = bool(permiso and getattr(permiso, 'crear', False))
        else:
            # check any company where user has crear
            can_create_context = Permiso.objects.filter(usuario=request.user, vista=vista, crear=True).exists()

    return render(request, 'gestiondte/certificados.html', {'certificados': certificados, 'empresas': empresas, 'can_create_context': can_create_context})


@login_required
@verificar_permiso("Gestión DTE - Certificados PFX-DTE", "crear")
def certificados_cargar(request, codigoempresa=None):
    if request.method == 'POST':
        form = CertificadoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            # Validate PKCS#12 before saving file
            uploaded = request.FILES.get('archivo')
            password = form.cleaned_data.get('password') or ''
            try:
                from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
                from cryptography.hazmat.primitives.serialization import BestAvailableEncryption
                from cryptography.x509 import Certificate
                pwd_bytes = password.encode() if password else None
                data = uploaded.read()
                try:
                    key, cert, additional = load_key_and_certificates(data, pwd_bytes)
                except TypeError:
                    # Some versions expect bytes password or None
                    key, cert, additional = load_key_and_certificates(data, pwd_bytes)
                if cert is None:
                    form.add_error('archivo', 'El archivo no contiene un certificado PKCS#12 válido')
                else:
                    # Extract metadata
                    from cryptography.x509.oid import NameOID
                    subject = cert.subject.rfc4514_string()
                    issuer = cert.issuer.rfc4514_string()
                    try:
                        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
                    except Exception:
                        cn = subject
                    serial = str(cert.serial_number)
                    valido_desde = cert.not_valid_before
                    valido_hasta = cert.not_valid_after
                    # try to get RUT from serialNumber or CN
                    rut = None
                    try:
                        serial_attrs = cert.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)
                        if serial_attrs:
                            rut = serial_attrs[0].value
                    except Exception:
                        rut = None

                    if not rut:
                        import re
                        m = re.search(r"(\d{7,8}-[\dKk])", cn)
                        if m:
                            rut = m.group(1)

                    # Create instance but avoid saving file until metadata set
                    instance = form.save(commit=False)
                    if request.user and not instance.pk:
                        instance.created_by = request.user
                    instance.updated_by = request.user
                    instance.titular = cn
                    instance.emisor_certificado = issuer
                    instance.numero_serie = serial
                    instance.rut_titular = rut
                    instance.valido_desde = valido_desde
                    instance.valido_hasta = valido_hasta
                    # finally save (this saves file to storage)
                    instance.save()
                    if audit_log:
                        try:
                            audit_log(request, 'CREATE_CERTIFICADO', instance)
                        except Exception:
                            pass
                    return redirect('gestion_dte:certificados')
            except ImportError:
                form.add_error(None, 'Biblioteca cryptography no disponible en el entorno')
            except Exception as e:
                form.add_error('archivo', f'Error al validar certificado: {e}')
    else:
        initial = {}
        if codigoempresa:
            initial['empresa_codigo'] = codigoempresa
        else:
            # preferir la empresa activa en sesión cuando exista
            ses_codigo = request.session.get('empresa_codigo')
            if ses_codigo:
                initial['empresa_codigo'] = ses_codigo
        form = CertificadoUploadForm(initial=initial)
    return render(request, 'gestiondte/certificados_cargar.html', {'form': form, 'codigoempresa': codigoempresa})


@login_required
@verificar_permiso("Gestión DTE - Certificados PFX-DTE", "ingresar")
def certificados_detail(request, codigoempresa):
    certificados = CertificadoSII.objects.filter(empresa_codigo=codigoempresa)
    empresa = get_maestroempresa_by_codigo(codigoempresa)
    return render(request, 'gestiondte/certificados_detail.html', {'certificados': certificados, 'codigoempresa': codigoempresa, 'empresa': empresa})


@login_required
@verificar_permiso("Gestión DTE - Certificados PFX-DTE", "modificar")
def certificados_toggle_active(request, pk):
    cert = get_object_or_404(CertificadoSII, pk=pk)
    cert.activo = not cert.activo
    cert.updated_by = request.user
    cert.save()
    if audit_log:
        try:
            audit_log(request, 'TOGGLE_CERTIFICADO_ACTIVO', cert)
        except Exception:
            pass
    return redirect('gestion_dte:certificados')


@login_required
@verificar_permiso("Gestión DTE - Certificados PFX-DTE", "modificar")
def certificados_probar_conexion(request, pk):
    """Prueba de autenticación contra el SII con el certificado indicado (solo auth, sin RPETC)."""
    from django.utils import timezone
    from .services.sii_auth import probar_autenticacion_sii, SiiAuthError
    from .utils.maestro import get_maestroempresa_by_codigo

    cert = get_object_or_404(CertificadoSII, pk=pk)
    empresa = get_maestroempresa_by_codigo(cert.empresa_codigo)

    resultado = {
        'cert': cert,
        'empresa': empresa,
        'fecha_prueba': timezone.now(),
        'success': False,
        'token_obtenido': False,
        'token_expira': None,
        'rut_envio_sii': None,
        'error': None,
        'http_status': None,
    }

    try:
        res = probar_autenticacion_sii(cert)
        # success se deriva exclusivamente de token_obtenido para evitar inconsistencias
        resultado.update({
            'success': res['success'] and res['token_obtenido'],
            'token_obtenido': res['token_obtenido'],
            'token_expira': res.get('token_expira'),
            'rut_envio_sii': res.get('rut_envio_sii'),
        })
        if audit_log:
            try:
                audit_log(request, 'PROBAR_CONEXION_SII_OK', cert)
            except Exception:
                pass
    except SiiAuthError as e:
        resultado['error'] = str(e)
        resultado['http_status'] = e.http_status
        if audit_log:
            try:
                audit_log(request, 'PROBAR_CONEXION_SII_FAIL', cert)
            except Exception:
                pass

    return render(request, 'gestiondte/certificados_probar.html', resultado)
