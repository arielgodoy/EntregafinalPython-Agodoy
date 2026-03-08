from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

from .persona_importer import PersonaImportServiceError, importar_personas_desde_api_interna

CACHE_TIMEOUT_SECONDS = 30 * 60

_STATUS_KEY_PREFIX = "persona_import_status"
_LOCK_SUFFIX = ":lock"


def build_persona_import_cache_key(*, user_id: int, empresa_id: int, session_key: Optional[str]) -> str:
    safe_session_key = (session_key or "").strip() or "no-session"
    return f"{_STATUS_KEY_PREFIX}_user_{user_id}_empresa_{empresa_id}_session_{safe_session_key}"


def build_idle_status() -> Dict[str, Any]:
    return {
        "status": "idle",
        "current_page": 0,
        "total_pages": None,
        "total_received": 0,
        "created": 0,
        "updated": 0,
        "omitted": 0,
        "errors": 0,
        "message_key": "",
        "started_at": None,
        "finished_at": None,
    }


def _normalize_status(payload: Any) -> Dict[str, Any]:
    base = build_idle_status()
    if isinstance(payload, dict):
        base.update(payload)

    if base.get("status") not in ("idle", "running", "success", "error"):
        base["status"] = "idle"

    for key in ("current_page", "total_received", "created", "updated", "omitted", "errors"):
        try:
            value = base.get(key)
            if value in (None, ""):
                base[key] = 0
            else:
                base[key] = int(value)
        except (TypeError, ValueError):
            base[key] = 0

    try:
        total_pages = base.get("total_pages")
        if total_pages in (None, ""):
            base["total_pages"] = None
        else:
            total_pages_int = int(total_pages)
            base["total_pages"] = total_pages_int if total_pages_int > 0 else None
    except (TypeError, ValueError):
        base["total_pages"] = None

    for key in ("message_key", "started_at", "finished_at"):
        if base.get(key) is None:
            continue
        base[key] = str(base.get(key) or "")

    return base


def get_status(*, status_key: str) -> Dict[str, Any]:
    return _normalize_status(cache.get(status_key))


def set_status(*, status_key: str, status_payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_status(status_payload)
    cache.set(status_key, normalized, timeout=CACHE_TIMEOUT_SECONDS)
    return normalized


def update_status(*, status_key: str, **updates: Any) -> Dict[str, Any]:
    current = get_status(status_key=status_key)
    current.update(updates)
    return set_status(status_key=status_key, status_payload=current)


def _lock_key(status_key: str) -> str:
    return f"{status_key}{_LOCK_SUFFIX}"


def _try_acquire_lock(status_key: str) -> bool:
    try:
        return bool(cache.add(_lock_key(status_key), "1", timeout=CACHE_TIMEOUT_SECONDS))
    except Exception:
        return True


def _release_lock(status_key: str) -> None:
    try:
        cache.delete(_lock_key(status_key))
    except Exception:
        return


def _spawn_persona_import_thread(*, status_key: str, date_str: str, exclude_pending: bool) -> None:
    thread = threading.Thread(
        target=_run_persona_import,
        kwargs={
            "status_key": status_key,
            "date_str": date_str,
            "exclude_pending": exclude_pending,
        },
        daemon=True,
        name=f"persona-import:{status_key}",
    )
    thread.start()


def start_persona_import_async(*, status_key: str, date_str: str, exclude_pending: bool) -> Dict[str, Any]:
    current = get_status(status_key=status_key)
    if current.get("status") == "running":
        return current

    if not _try_acquire_lock(status_key):
        # Mejor esfuerzo: si no podemos tomar el lock, asumimos que hay un proceso corriendo
        return update_status(
            status_key=status_key,
            status="running",
            message_key="evaluaciones.personas.import.in_progress",
        )

    now_iso = timezone.now().isoformat()
    set_status(
        status_key=status_key,
        status_payload={
            "status": "running",
            "current_page": 0,
            "total_pages": None,
            "total_received": 0,
            "created": 0,
            "updated": 0,
            "omitted": 0,
            "errors": 0,
            "message_key": "evaluaciones.personas.import.progress_starting",
            "started_at": now_iso,
            "finished_at": None,
        },
    )

    try:
        _spawn_persona_import_thread(
            status_key=status_key,
            date_str=date_str,
            exclude_pending=exclude_pending,
        )
    except Exception:
        finish_iso = timezone.now().isoformat()
        _release_lock(status_key)
        return update_status(
            status_key=status_key,
            status="error",
            message_key="evaluaciones.personas.import.progress_failed",
            finished_at=finish_iso,
        )

    return get_status(status_key=status_key)


def _run_persona_import(*, status_key: str, date_str: str, exclude_pending: bool) -> None:
    close_old_connections()

    def _on_progress(update: Dict[str, Any]) -> None:
        payload: Dict[str, Any] = {"status": "running"}
        if isinstance(update, dict):
            payload.update(update)
        update_status(status_key=status_key, **payload)

    try:
        result = importar_personas_desde_api_interna(
            date_str,
            exclude_pending,
            request_user=None,
            progress_callback=_on_progress,
        )
        finish_iso = timezone.now().isoformat()
        update_status(
            status_key=status_key,
            status="success",
            current_page=result.paginas_procesadas,
            total_pages=get_status(status_key=status_key).get("total_pages"),
            total_received=result.total_recibidos,
            created=result.creados,
            updated=result.actualizados,
            omitted=result.omitidos,
            errors=result.errores,
            message_key="evaluaciones.personas.import.success",
            finished_at=finish_iso,
        )
    except PersonaImportServiceError as exc:
        finish_iso = timezone.now().isoformat()
        update_status(
            status_key=status_key,
            status="error",
            message_key=getattr(exc, "message_key", "evaluaciones.personas.import.progress_failed"),
            finished_at=finish_iso,
        )
    except Exception:
        finish_iso = timezone.now().isoformat()
        update_status(
            status_key=status_key,
            status="error",
            message_key="evaluaciones.personas.import.progress_failed",
            finished_at=finish_iso,
        )
    finally:
        _release_lock(status_key)
        close_old_connections()
