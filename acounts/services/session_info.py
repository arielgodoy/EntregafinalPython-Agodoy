"""Informacion de la sesion actual del propio usuario para la pestana Sesiones del perfil.

Todo se calcula server-side a partir de request.session/request.user; nunca se acepta
un identificador externo para elegir de quien son los datos mostrados.
"""
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

DISPLAY_DATETIME_FORMAT = "%d/%m/%Y %H:%M"


def _parse_session_datetime(value):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def format_duration(delta):
    """Texto amigable para un timedelta, sin precision de segundos."""
    if delta is None:
        return None
    total_seconds = max(int(delta.total_seconds()), 0)
    if total_seconds < 60:
        return "menos de 1 min"
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    if hours and minutes:
        return f"{hours} h {minutes} min"
    if hours:
        return f"{hours} h"
    return f"{minutes} min"


def format_local_datetime(value):
    """Convierte un datetime aware (almacenado en UTC) a settings.SYSTEM_LOCAL_TIME_ZONE.

    Devuelve un string ya formateado (no un datetime) para que el filtro `date` de
    Django no vuelva a "localizar" el valor usando la zona activa por defecto
    (TIME_ZONE=UTC en este proyecto), lo que revertiria esta conversion.
    """
    if value is None:
        return None
    display_timezone = ZoneInfo(settings.SYSTEM_LOCAL_TIME_ZONE)
    localizado = timezone.localtime(value, timezone=display_timezone)
    return localizado.strftime(DISPLAY_DATETIME_FORMAT)


def format_user_agent(user_agent):
    """Representacion simple 'Navegador · SO' sin agregar dependencias nuevas."""
    if not user_agent:
        return None

    if "Edg/" in user_agent or "Edge/" in user_agent:
        browser = "Edge"
    elif "Firefox/" in user_agent:
        browser = "Firefox"
    elif "OPR/" in user_agent or "Opera/" in user_agent:
        browser = "Opera"
    elif "Chrome/" in user_agent and "Chromium/" not in user_agent:
        browser = "Chrome"
    elif "Safari/" in user_agent and "Chrome/" not in user_agent:
        browser = "Safari"
    else:
        browser = "Navegador desconocido"

    if "Windows" in user_agent:
        sistema = "Windows"
    elif "Mac OS X" in user_agent or "Macintosh" in user_agent:
        sistema = "macOS"
    elif "Android" in user_agent:
        sistema = "Android"
    elif "iPhone" in user_agent or "iPad" in user_agent:
        sistema = "iOS"
    elif "Linux" in user_agent:
        sistema = "Linux"
    else:
        sistema = "SO desconocido"

    return f"{browser} · {sistema}"


def get_current_session_info(request):
    """Construye la informacion de 'Sesion actual' exclusivamente desde request.session."""
    session = request.session
    now = timezone.now()

    login_at = _parse_session_datetime(session.get("login_at"))
    last_activity = _parse_session_datetime(session.get("last_activity"))

    try:
        expires_at = session.get_expiry_date()
    except Exception:
        expires_at = None

    inactive_delta = (now - last_activity) if last_activity else None
    remaining_delta = max(expires_at - now, timedelta(0)) if expires_at else None

    return {
        "login_at": format_local_datetime(login_at),
        "last_activity": format_local_datetime(last_activity),
        "inactive_time_display": format_duration(inactive_delta),
        "expires_at": format_local_datetime(expires_at),
        "remaining_display": format_duration(remaining_delta),
        "ip_address": session.get("ip_address"),
        "user_agent_display": format_user_agent(session.get("user_agent")),
        "remember_me": session.get("remember_me", False),
        "fecha_sistema": session.get("fecha_sistema"),
        "empresa_nombre": session.get("empresa_nombre"),
    }
