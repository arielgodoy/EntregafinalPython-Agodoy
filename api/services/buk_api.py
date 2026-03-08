import json
import socket
from typing import Any, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from django.conf import settings

DEFAULT_TIMEOUT_SECONDS = 10
EMPLOYEES_ACTIVE_PATH = 'employees/active'


class BukAPIError(Exception):
    def __init__(
        self,
        detail: str,
        *,
        status_code: int = 500,
        upstream_status: Optional[int] = None,
    ):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.upstream_status = upstream_status


def _get_buk_config() -> Tuple[str, str]:
    base_url = (getattr(settings, 'BUK_API_BASE_URL', '') or '').strip()
    token = (getattr(settings, 'BUK_API_AUTH_TOKEN', '') or '').strip()

    if not base_url or not token:
        raise BukAPIError('Integración Buk no configurada.', status_code=500)

    # urljoin necesita que el base termine en '/' para no truncar el último segmento
    if not base_url.endswith('/'):
        base_url += '/'

    return base_url, token


def fetch_active_employees(*, date_str: str, exclude_pending: bool) -> Any:
    base_url, token = _get_buk_config()

    endpoint = urljoin(base_url, EMPLOYEES_ACTIVE_PATH)
    params = {
        'date': date_str,
        'exclude_pending': 'true' if exclude_pending else 'false',
    }
    url = f"{endpoint}?{urlencode(params)}"

    req = Request(
        url,
        headers={
            'Accept': 'application/json',
            'auth_token': token,
        },
        method='GET',
    )

    try:
        resp = urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS)
        try:
            body = resp.read()
        finally:
            try:
                resp.close()
            except Exception:
                pass
    except HTTPError as exc:
        try:
            # Consumir body para liberar el socket
            exc.read()
        except Exception:
            pass
        raise BukAPIError(
            'Error al consultar Buk.',
            status_code=502,
            upstream_status=getattr(exc, 'code', None),
        ) from None
    except (URLError, socket.timeout, TimeoutError, OSError):
        raise BukAPIError('No se pudo conectar con Buk.', status_code=502) from None

    try:
        text = body.decode('utf-8')
    except Exception:
        raise BukAPIError('Respuesta inválida desde Buk.', status_code=502) from None

    if not text:
        return {}

    try:
        return json.loads(text)
    except ValueError:
        raise BukAPIError('Respuesta inválida desde Buk.', status_code=502) from None


def fetch_buk_url(*, url: str) -> Any:
    """Fetch de una URL paginada devuelta por Buk (pagination.next).

    Seguridad: solo se permiten URLs relativas o absolutas que cuelguen del BUK_API_BASE_URL.
    """

    base_url, token = _get_buk_config()

    normalized_url = (url or '').strip()
    if not normalized_url:
        return {}

    parsed = urlparse(normalized_url)
    if not parsed.scheme:
        normalized_url = urljoin(base_url, normalized_url.lstrip('/'))

    base_parsed = urlparse(base_url)
    target_parsed = urlparse(normalized_url)
    if target_parsed.scheme != base_parsed.scheme or target_parsed.netloc != base_parsed.netloc:
        raise BukAPIError('URL de paginación inválida.', status_code=502)
    if EMPLOYEES_ACTIVE_PATH not in (target_parsed.path or ''):
        raise BukAPIError('URL de paginación inválida.', status_code=502)

    req = Request(
        normalized_url,
        headers={
            'Accept': 'application/json',
            'auth_token': token,
        },
        method='GET',
    )

    try:
        resp = urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS)
        try:
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
        raise BukAPIError(
            'Error al consultar Buk.',
            status_code=502,
            upstream_status=getattr(exc, 'code', None),
        ) from None
    except (URLError, socket.timeout, TimeoutError, OSError):
        raise BukAPIError('No se pudo conectar con Buk.', status_code=502) from None

    try:
        text = body.decode('utf-8')
    except Exception:
        raise BukAPIError('Respuesta inválida desde Buk.', status_code=502) from None

    if not text:
        return {}

    try:
        return json.loads(text)
    except ValueError:
        raise BukAPIError('Respuesta inválida desde Buk.', status_code=502) from None
