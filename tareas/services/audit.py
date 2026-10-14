"""Adapter from Tareas business operations to the shared audit service."""

import logging
import time
from datetime import date, datetime
from decimal import Decimal
from html import escape
from urllib.parse import parse_qsl, quote, urlencode
from uuid import uuid4

from common.http import get_client_ip
from auditoria.services import AuditoriaService


logger = logging.getLogger(__name__)
_SENSITIVE_KEY_PARTS = ("password", "token", "secret", "credential", "api_key", "csrf", "archivo")
_ALLOWED_ACTIONS = frozenset({"CREATE", "UPDATE", "DELETE", "SHARE"})


def _sanitize_value(value):
    if isinstance(value, dict):
        return {
            str(key): _sanitize_value(item)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, str):
        return escape(value[:1000])
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return None


def _safe_path(request):
    path = request.path
    resolver_match = getattr(request, "resolver_match", None)
    for key, value in getattr(resolver_match, "kwargs", {}).items():
        if any(part in key.lower() for part in _SENSITIVE_KEY_PARTS) and value:
            path = path.replace(str(value), "[REDACTED]")
            path = path.replace(quote(str(value), safe=""), "[REDACTED]")
    return path


def _safe_querystring(request):
    querystring = request.META.get("QUERY_STRING", "")
    return urlencode([
        (
            key,
            "[REDACTED]"
            if any(part in key.lower() for part in _SENSITIVE_KEY_PARTS)
            else value,
        )
        for key, value in parse_qsl(querystring, keep_blank_values=True)
    ])


def task_audit_snapshot(task):
    fields = (
        "estado",
        "anulada",
        "prioridad",
        "responsable_id",
        "fecha_tope",
        "fecha_publicacion",
        "fecha_asignacion",
        "fecha_cumplimiento",
        "cierre_completado",
        "fechas_pendientes_confirmacion",
        "requiere_evidencia_cierre",
        "correlativo",
    )
    snapshot = {
        field: getattr(task, field)
        for field in fields
        if hasattr(task, field)
    }
    if "estado" not in snapshot and hasattr(task, "state"):
        snapshot["estado"] = task.state
    return snapshot


def log_task_operation(
    request,
    *,
    task_id,
    empresa_id,
    action,
    operation,
    object_type="Tarea",
    object_id=None,
    correlativo=None,
    before=None,
    after=None,
    meta=None,
):
    """Persist one completed business event without changing the task operation."""
    if action not in _ALLOWED_ACTIONS:
        raise ValueError("Acción de auditoría Tareas no válida.")

    active_company_id = request.session.get("empresa_id")
    if active_company_id is None or str(active_company_id) != str(empresa_id):
        logger.error(
            "Tareas audit event skipped because company scope did not match: task=%s",
            task_id,
        )
        return None

    operation_id = uuid4().hex
    event_meta = {
        "operation": operation,
        "operation_id": operation_id,
        "task_id": task_id,
        "correlativo": correlativo,
    }
    event_meta.update(meta or {})
    duration_ms = None
    started_at = getattr(request, "_audit_start_time", None)
    if started_at is not None:
        duration_ms = max(0, int((time.time() - started_at) * 1000))

    event = AuditoriaService.log_event(
        app_label="tareas",
        action=action,
        user=request.user if getattr(request.user, "is_authenticated", False) else None,
        empresa_id=active_company_id,
        object_type=object_type,
        object_id=str(object_id if object_id is not None else task_id),
        ip_address=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        method=request.method,
        path=_safe_path(request),
        querystring=_safe_querystring(request),
        status_code=getattr(request, "_audit_response_status_code", None),
        duration_ms=duration_ms,
        vista_nombre=getattr(request, "_audit_vista_nombre", None),
        meta=_sanitize_value(event_meta),
        before=_sanitize_value(before),
        after=_sanitize_value(after),
    )
    if event is None:
        logger.error(
            "Tareas audit event was not persisted: task=%s operation=%s",
            task_id,
            operation,
        )
        return None

    request._audit_logged = True
    return operation_id
