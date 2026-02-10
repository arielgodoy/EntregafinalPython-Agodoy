from django.contrib.auth.models import User

from access_control.models import Vista, Permiso
from acounts.services.config import get_effective_company_config
from acounts.services.email_service import send_security_email
from acounts.services.tokens import generate_token

def invite_user_flow(email, first_name, last_name, empresas, tipo_usuario, usuario_referencia, created_by):
    empresas = list(empresas or [])
    if not empresas:
        return {'ok': False, 'error': 'validation.company_required'}

    tipo_usuario = (tipo_usuario or '').upper() or 'PROFESIONAL'
    if tipo_usuario not in {'USUARIO', 'PROFESIONAL'}:
        return {'ok': False, 'error': 'validation.user_type_invalid'}

    if tipo_usuario == 'USUARIO' and not usuario_referencia:
        return {'ok': False, 'error': 'validation.reference_required'}

    if not Vista.objects.filter(nombre='auth_invite').exists():
        return {
            'ok': False,
            'error': 'errors.seed.auth_invite_missing'
        }

    vista_base = Vista.objects.filter(nombre='Maestro Usuarios').first()
    if not vista_base:
        return {
            'ok': False,
            'error': 'errors.seed.master_users_missing'
        }

    user = User.objects.filter(username=email).first()
    if not user:
        user = User.objects.filter(email__iexact=email).first()

    if user and user.is_active:
        return {'ok': False, 'error': 'errors.invite.user_active'}

    if not user:
        user = User(username=email, email=email, is_active=False)
        user.set_unusable_password()

    if first_name and not user.first_name:
        user.first_name = first_name
    if last_name and not user.last_name:
        user.last_name = last_name

    user.is_active = False
    user.save()

    if tipo_usuario == 'USUARIO' and usuario_referencia:
        empresas_ids = [empresa.id for empresa in empresas]
        if not Permiso.objects.filter(usuario=usuario_referencia, empresa_id__in=empresas_ids).exists():
            return {
                'ok': False,
                'error': 'validation.reference_company_mismatch'
            }

    for empresa in empresas:
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

        if tipo_usuario == 'USUARIO' and usuario_referencia:
            permisos_referencia = Permiso.objects.filter(
                usuario=usuario_referencia,
                empresa=empresa,
            ).select_related('vista')
            for permiso in permisos_referencia:
                Permiso.objects.update_or_create(
                    usuario=user,
                    empresa=empresa,
                    vista=permiso.vista,
                    defaults={
                        'ingresar': permiso.ingresar,
                        'crear': permiso.crear,
                        'modificar': permiso.modificar,
                        'eliminar': permiso.eliminar,
                        'autorizar': permiso.autorizar,
                        'supervisor': permiso.supervisor,
                    },
                )

    empresa_principal = empresas[0]

    meta = {
        'empresa_id': empresa_principal.id,
        'empresa_ids': [empresa.id for empresa in empresas],
        'tipo_usuario': tipo_usuario,
    }

    token_plain = generate_token(user, meta=meta, created_by=created_by)

    config = get_effective_company_config(empresa_principal)
    public_base_url = config.get('public_base_url') if config else None
    if not public_base_url:
        return {
            'ok': False,
            'error': 'errors.company_config.public_base_url_required'
        }

    activation_link = f"{public_base_url.rstrip('/')}/auth/activate/{token_plain}/"
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
        empresa=empresa_principal,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        to_emails=[email],
    )

    return {
        'ok': True,
        'user': user,
        'email': email,
        'token_plain': token_plain,
        'activation_link': activation_link,
        'empresas': empresas,
    }
