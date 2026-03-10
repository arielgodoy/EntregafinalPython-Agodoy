import json
import logging
import re
import threading
from contextlib import contextmanager

from django.contrib.auth.decorators import login_required
from django.db import connections
from django.db.utils import ConnectionDoesNotExist
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from access_control.decorators import verificar_permiso

logger = logging.getLogger(__name__)


VISTA_NOMBRE_MOVIMIENTOS_CABEZA = "API - Movimientos Cabeza"

BASE_ALIAS_PREFIX = "eltit_gestion"

ENGINE_DJANGO_MYSQL = "django.db.backends.mysql"
ENGINE_LEGACY_PYMYSQL = "legacy_pymysql"
ENGINE_API_REMOTA = "api_remota"

_SETTINGS_MYSQL_CONNECTION_TABLE = "settings_settingsmysqlconnection"

_DB_ALIAS_LOCK = threading.Lock()

_SAFE_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_json_object(request):
    if not request.body:
        raise ValueError("JSON inválido.")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("JSON inválido.")

    if not isinstance(payload, dict):
        raise ValueError("JSON inválido.")

    return payload


def _row_to_dict_raw(cursor, row):
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def _rows_to_dicts_raw(cursor, rows):
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def _validate_two_digit_numeric(value, field_name):
    value = (value or "").strip()
    if len(value) != 2 or not value.isdigit():
        raise ValueError(f"{field_name} inválido.")
    return value


def _validate_limit_offset(request):
    limit_raw = None
    offset_raw = None
    try:
        limit_raw = request.GET.get("limit")
        offset_raw = request.GET.get("offset")
    except Exception:
        limit_raw = None
        offset_raw = None

    if limit_raw is None or str(limit_raw).strip() == "":
        limit = 100
    else:
        try:
            limit = int(str(limit_raw).strip())
        except Exception as e:
            raise ValueError("limit inválido.") from e

    if offset_raw is None or str(offset_raw).strip() == "":
        offset = 0
    else:
        try:
            offset = int(str(offset_raw).strip())
        except Exception as e:
            raise ValueError("offset inválido.") from e

    if limit < 1:
        raise ValueError("limit inválido.")
    if offset < 0:
        raise ValueError("offset inválido.")

    if limit > 500:
        limit = 500

    return limit, offset


def _quote_identifier_mysql(name: str) -> str:
    name = name or ""
    return "`" + name.replace("`", "``") + "`"


def _build_alias_for_rubro(rubro: str) -> str:
    if rubro == "00":
        return BASE_ALIAS_PREFIX
    return f"{BASE_ALIAS_PREFIX}{rubro}"


def _build_table_for_local(local: str) -> str:
    return f"l_movimientos_cabeza_{local}"


def _extract_rubro_local(request, payload=None):
    rubro = None
    local = None

    try:
        rubro = request.GET.get("rubro")
        local = request.GET.get("local")
    except Exception:
        rubro = None
        local = None

    if payload and isinstance(payload, dict):
        if rubro is None:
            rubro = payload.get("rubro")
        if local is None:
            local = payload.get("local")

    if rubro is None or local is None:
        raise ValueError("rubro y local son requeridos.")

    rubro = _validate_two_digit_numeric(str(rubro), "rubro")
    local = _validate_two_digit_numeric(str(local), "local")

    return rubro, local


def _cfg_get(cfg, key, default=""):
    if cfg is None:
        return default
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def _normalize_engine(value):
    val = (value or "").strip()
    return val or ENGINE_DJANGO_MYSQL


def _fetch_settings_mysql_connection_cfg(*, empresa_id, nombre_logico):
    """Obtiene configuración de SettingsMySQLConnection sin ORM (SQL directo sobre DB default)."""

    nombre_logico = (nombre_logico or "").strip().lower()
    if not nombre_logico:
        return None

    try:
        default_conn = connections["default"]
        user_col = default_conn.ops.quote_name("user")
        table = default_conn.ops.quote_name(_SETTINGS_MYSQL_CONNECTION_TABLE)

        sql = f"""SELECT
nombre_logico,
engine,
host,
port,
{user_col} as user,
password,
db_name,
charset,
is_active
FROM {table}
WHERE empresa_id = %s AND nombre_logico = %s
LIMIT 1"""

        with default_conn.cursor() as cursor:
            cursor.execute(sql, [empresa_id, nombre_logico])
            row = cursor.fetchone()
            if not row:
                return None
            columns = [c[0] for c in cursor.description]
            data = dict(zip(columns, row))
    except Exception:
        return None

    try:
        data["is_active"] = bool(data.get("is_active"))
    except Exception:
        data["is_active"] = False

    return data


def _same_db_target(a, b):
    try:
        return (
            str((a or {}).get("NAME", "")) == str((b or {}).get("NAME", ""))
            and str((a or {}).get("HOST", "")) == str((b or {}).get("HOST", ""))
            and str((a or {}).get("USER", "")) == str((b or {}).get("USER", ""))
            and str((a or {}).get("PORT", "")) == str((b or {}).get("PORT", ""))
        )
    except Exception:
        return False


def _ensure_django_alias_configured_from_cfg(alias: str, cfg) -> bool:
    """Registra/actualiza alias en django.db.connections.databases según cfg."""

    if not hasattr(connections, "databases"):
        return True

    base_config = {}
    try:
        from django.conf import settings as django_settings

        base_config = django_settings.DATABASES.get("default", {}).copy()
    except Exception:
        base_config = {}

    if not isinstance(base_config, dict):
        base_config = {}

    complete_cfg = base_config.copy()
    complete_cfg.update(
        {
            "ENGINE": ENGINE_DJANGO_MYSQL,
            "NAME": _cfg_get(cfg, "db_name", ""),
            "USER": _cfg_get(cfg, "user", ""),
            "PASSWORD": _cfg_get(cfg, "password", ""),
            "HOST": _cfg_get(cfg, "host", ""),
            "PORT": str(_cfg_get(cfg, "port", "") or ""),
            "OPTIONS": {"charset": "utf8mb4"},
            "CONN_MAX_AGE": 0,
            "ATOMIC_REQUESTS": False,
        }
    )

    new_config = complete_cfg

    with _DB_ALIAS_LOCK:
        try:
            existing = connections.databases.get(alias)
        except Exception:
            existing = None

        needs_replace = False
        if existing is not None:
            try:
                same_connection = _same_db_target(existing, new_config)
            except Exception:
                same_connection = False

            if not same_connection:
                needs_replace = True
            else:
                required_keys = (
                    "ATOMIC_REQUESTS",
                    "CONN_MAX_AGE",
                    "ENGINE",
                    "NAME",
                    "USER",
                    "PASSWORD",
                    "HOST",
                    "PORT",
                    "OPTIONS",
                )
                try:
                    missing = any(k not in existing for k in required_keys)
                except Exception:
                    missing = True
                if missing:
                    needs_replace = True
        else:
            needs_replace = True

        if needs_replace:
            try:
                connections[alias].close()
            except Exception:
                pass
            try:
                del connections[alias]
            except Exception:
                pass

            try:
                connections.databases[alias] = new_config
            except Exception:
                return False

            try:
                if hasattr(connections, "ensure_defaults"):
                    connections.ensure_defaults(alias)
            except Exception:
                pass

        try:
            _ = connections[alias]
        except Exception:
            return False

    return True


def _resolve_db_for_request(request, alias: str):
    """Resuelve el modo de conexión para el request y alias solicitado.

    Retorna:
    - ("django", cfg_or_None) cuando se usará django.db.connections[alias]
    - ("legacy_pymysql", cfg) cuando se usará PyMySQL directo
    - None si no hay configuración usable

    En tests, `connections` puede estar mockeado sin `.databases`; en ese caso se fuerza modo "django".
    """

    if not hasattr(connections, "databases"):
        return ("django", None)

    empresa_id = None
    try:
        if hasattr(request, "session"):
            empresa_id = request.session.get("empresa_id")
    except Exception:
        empresa_id = None

    if not empresa_id:
        try:
            _ = connections[alias]
            return ("django", None)
        except Exception:
            return None

    cfg = _fetch_settings_mysql_connection_cfg(empresa_id=empresa_id, nombre_logico=alias)

    if not cfg or not cfg.get("is_active"):
        try:
            _ = connections[alias]
            return ("django", None)
        except Exception:
            return None

    engine = _normalize_engine(_cfg_get(cfg, "engine", None))
    if engine == ENGINE_LEGACY_PYMYSQL:
        return ("legacy_pymysql", cfg)

    if engine == ENGINE_API_REMOTA:
        return None

    if not _ensure_django_alias_configured_from_cfg(alias, cfg):
        return None

    return ("django", cfg)


@contextmanager
def _legacy_pymysql_connection(cfg):
    """Conecta a MySQL usando PyMySQL directo (modo legacy_pymysql)."""

    try:
        import pymysql
    except Exception as e:
        raise RuntimeError("PyMySQL no disponible") from e

    conn = None
    cursor = None
    try:
        charset = (_cfg_get(cfg, "charset", None) or "utf8").strip() or "utf8"
        conn = pymysql.connect(
            host=_cfg_get(cfg, "host", ""),
            port=int(_cfg_get(cfg, "port", 3306) or 3306),
            user=_cfg_get(cfg, "user", ""),
            password=_cfg_get(cfg, "password", ""),
            database=_cfg_get(cfg, "db_name", ""),
            charset=charset,
            connect_timeout=5,
            read_timeout=10,
            write_timeout=10,
        )
        cursor = conn.cursor()
        yield conn, cursor
    finally:
        try:
            if cursor is not None:
                cursor.close()
        except Exception:
            pass
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _db_alias_not_configured_response(alias: str):
    return JsonResponse({"error": f"Database connection '{alias}' is not configured"}, status=500)


def _validate_update_payload(payload: dict):
    if not isinstance(payload, dict):
        raise ValueError("Body inválido.")

    forbidden = {"tipo", "numero", "fecha"}
    for key in forbidden:
        if key in payload:
            raise ValueError("No se permite modificar tipo/numero/fecha.")

    updates = {}
    for key, value in payload.items():
        if key in ("rubro", "local"):
            continue
        if not isinstance(key, str) or not key:
            raise ValueError("Body inválido.")
        if not _SAFE_COLUMN_RE.match(key) or len(key) > 64:
            raise ValueError(f"Campo inválido: {key}.")
        if isinstance(value, (dict, list)):
            raise ValueError("Body inválido.")
        updates[key] = value

    if not updates:
        raise ValueError("Body inválido.")

    return updates


def _validate_create_payload(payload: dict):
    if not isinstance(payload, dict):
        raise ValueError("Body inválido.")

    required = ("tipo", "numero", "fecha")
    for key in required:
        if key not in payload:
            raise ValueError("Body inválido.")

    tipo = payload.get("tipo")
    numero = payload.get("numero")
    fecha = payload.get("fecha")

    if not isinstance(tipo, str):
        raise ValueError("tipo inválido.")
    tipo = tipo.strip()
    if not tipo:
        raise ValueError("tipo inválido.")

    if isinstance(numero, (int, float)) and not isinstance(numero, bool):
        numero = str(int(numero))
    if not isinstance(numero, str):
        raise ValueError("numero inválido.")
    numero = numero.strip()
    if not numero:
        raise ValueError("numero inválido.")

    if not isinstance(fecha, str):
        raise ValueError("fecha inválido.")
    fecha = fecha.strip()
    if not fecha:
        raise ValueError("fecha inválido.")

    data = {"tipo": tipo, "numero": numero, "fecha": fecha}

    for key, value in payload.items():
        if key in ("rubro", "local", "tipo", "numero", "fecha"):
            continue
        if not isinstance(key, str) or not key:
            raise ValueError("Body inválido.")
        if not _SAFE_COLUMN_RE.match(key) or len(key) > 64:
            raise ValueError(f"Campo inválido: {key}.")
        if isinstance(value, (dict, list)):
            raise ValueError("Body inválido.")
        data[key] = value

    return data


@verificar_permiso(VISTA_NOMBRE_MOVIMIENTOS_CABEZA, "ingresar")
def _movimientos_cabeza_list(request):
    try:
        rubro, local = _extract_rubro_local(request)
        limit, offset = _validate_limit_offset(request)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    alias = _build_alias_for_rubro(rubro)
    table_name = _build_table_for_local(local)
    table_sql = _quote_identifier_mysql(table_name)

    resolved = _resolve_db_for_request(request, alias)
    if not resolved:
        return _db_alias_not_configured_response(alias)

    mode, cfg = resolved
    sql = f"SELECT * FROM {table_sql} ORDER BY fecha DESC, tipo, numero LIMIT {limit} OFFSET {offset}"

    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (_conn, cursor):
                cursor.execute(sql)
                rows = cursor.fetchall()
                data = _rows_to_dicts_raw(cursor, rows)
            return JsonResponse(data, safe=False)
        except Exception as e:
            logger.error("movimientos_cabeza_list legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "Error interno."}, status=500)

    try:
        with connections[alias].cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
            data = _rows_to_dicts_raw(cursor, rows)
        return JsonResponse(data, safe=False)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response(alias)
    except Exception as e:
        logger.error("movimientos_cabeza_list error (%s)", type(e).__name__)
        return JsonResponse({"detail": "Error interno."}, status=500)


@verificar_permiso(VISTA_NOMBRE_MOVIMIENTOS_CABEZA, "ingresar")
def _movimientos_cabeza_get(request, tipo, numero):
    try:
        rubro, local = _extract_rubro_local(request)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    alias = _build_alias_for_rubro(rubro)
    table_name = _build_table_for_local(local)
    table_sql = _quote_identifier_mysql(table_name)

    resolved = _resolve_db_for_request(request, alias)
    if not resolved:
        return _db_alias_not_configured_response(alias)

    mode, cfg = resolved
    sql = f"SELECT * FROM {table_sql} WHERE tipo=%s AND numero=%s"
    params = [tipo, numero]

    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (_conn, cursor):
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                if not rows:
                    return JsonResponse({"detail": "No encontrado."}, status=404)
                if len(rows) > 1:
                    return JsonResponse({"detail": "Ambigüedad: múltiples fechas para tipo/numero."}, status=409)
                item = _row_to_dict_raw(cursor, rows[0])
            return JsonResponse(item, safe=True)
        except Exception as e:
            logger.error("movimientos_cabeza_get legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "Error interno."}, status=500)

    try:
        with connections[alias].cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            if not rows:
                return JsonResponse({"detail": "No encontrado."}, status=404)
            if len(rows) > 1:
                return JsonResponse({"detail": "Ambigüedad: múltiples fechas para tipo/numero."}, status=409)
            item = _row_to_dict_raw(cursor, rows[0])
        return JsonResponse(item, safe=True)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response(alias)
    except Exception as e:
        logger.error("movimientos_cabeza_get error (%s)", type(e).__name__)
        return JsonResponse({"detail": "Error interno."}, status=500)


@verificar_permiso(VISTA_NOMBRE_MOVIMIENTOS_CABEZA, "crear")
def _movimientos_cabeza_create(request):
    try:
        payload = _parse_json_object(request)
        rubro, local = _extract_rubro_local(request, payload=payload)
        data = _validate_create_payload(payload)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    alias = _build_alias_for_rubro(rubro)
    table_name = _build_table_for_local(local)
    table_sql = _quote_identifier_mysql(table_name)

    resolved = _resolve_db_for_request(request, alias)
    if not resolved:
        return _db_alias_not_configured_response(alias)

    mode, cfg = resolved

    cols = ["tipo", "numero", "fecha"]
    extra_cols = [k for k in data.keys() if k not in cols]
    extra_cols.sort()
    cols = cols + extra_cols

    col_sql = ",".join(_quote_identifier_mysql(c) for c in cols)
    placeholders = ",".join(["%s"] * len(cols))

    sql_exists = f"SELECT 1 FROM {table_sql} WHERE tipo=%s AND numero=%s AND fecha=%s LIMIT 1"
    sql_insert = f"INSERT INTO {table_sql} ({col_sql}) VALUES ({placeholders})"

    params_exists = [data["tipo"], data["numero"], data["fecha"]]
    params_insert = [data[c] for c in cols]

    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (conn, cursor):
                cursor.execute(sql_exists, params_exists)
                row = cursor.fetchone()
                if row:
                    return JsonResponse({"detail": "Ya existe un registro con la misma PK."}, status=409)

                cursor.execute(sql_insert, params_insert)
                conn.commit()
            return JsonResponse(data, status=201)
        except Exception as e:
            logger.error("movimientos_cabeza_create legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "No se pudo crear movimiento."}, status=500)

    try:
        with connections[alias].cursor() as cursor:
            cursor.execute(sql_exists, params_exists)
            row = cursor.fetchone()
            if row:
                return JsonResponse({"detail": "Ya existe un registro con la misma PK."}, status=409)

            cursor.execute(sql_insert, params_insert)
        connections[alias].commit()
        return JsonResponse(data, status=201)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response(alias)
    except Exception as e:
        logger.error("movimientos_cabeza_create error (%s)", type(e).__name__)
        return JsonResponse({"detail": "No se pudo crear movimiento."}, status=500)


@verificar_permiso(VISTA_NOMBRE_MOVIMIENTOS_CABEZA, "modificar")
def _movimientos_cabeza_update(request, tipo, numero):
    try:
        payload = _parse_json_object(request)
        rubro, local = _extract_rubro_local(request, payload=payload)
        updates = _validate_update_payload(payload)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    alias = _build_alias_for_rubro(rubro)
    table_name = _build_table_for_local(local)
    table_sql = _quote_identifier_mysql(table_name)

    resolved = _resolve_db_for_request(request, alias)
    if not resolved:
        return _db_alias_not_configured_response(alias)

    mode, cfg = resolved

    cols = sorted(updates.keys())
    set_clause = ",".join(f"{_quote_identifier_mysql(c)}=%s" for c in cols)
    sql_select = f"SELECT * FROM {table_sql} WHERE tipo=%s AND numero=%s"
    sql_update = f"UPDATE {table_sql} SET {set_clause} WHERE tipo=%s AND numero=%s AND fecha=%s"

    params_select = [tipo, numero]

    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (conn, cursor):
                cursor.execute(sql_select, params_select)
                rows = cursor.fetchall()
                if not rows:
                    return JsonResponse({"detail": "No encontrado."}, status=404)
                if len(rows) > 1:
                    return JsonResponse({"detail": "Ambigüedad: múltiples fechas para tipo/numero."}, status=409)

                current = _row_to_dict_raw(cursor, rows[0])
                fecha = current.get("fecha")
                if fecha is None:
                    return JsonResponse({"detail": "Error interno."}, status=500)

                params_update = [updates[c] for c in cols] + [tipo, numero, fecha]
                cursor.execute(sql_update, params_update)
                conn.commit()

                current.update(updates)
            return JsonResponse(current, safe=True)
        except Exception as e:
            logger.error("movimientos_cabeza_update legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "No se pudo actualizar movimiento."}, status=500)

    try:
        with connections[alias].cursor() as cursor:
            cursor.execute(sql_select, params_select)
            rows = cursor.fetchall()
            if not rows:
                return JsonResponse({"detail": "No encontrado."}, status=404)
            if len(rows) > 1:
                return JsonResponse({"detail": "Ambigüedad: múltiples fechas para tipo/numero."}, status=409)

            current = _row_to_dict_raw(cursor, rows[0])
            fecha = current.get("fecha")
            if fecha is None:
                return JsonResponse({"detail": "Error interno."}, status=500)

            params_update = [updates[c] for c in cols] + [tipo, numero, fecha]
            cursor.execute(sql_update, params_update)
        connections[alias].commit()

        current.update(updates)
        return JsonResponse(current, safe=True)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response(alias)
    except Exception as e:
        logger.error("movimientos_cabeza_update error (%s)", type(e).__name__)
        return JsonResponse({"detail": "No se pudo actualizar movimiento."}, status=500)


@verificar_permiso(VISTA_NOMBRE_MOVIMIENTOS_CABEZA, "eliminar")
def _movimientos_cabeza_delete(request, tipo, numero):
    try:
        rubro, local = _extract_rubro_local(request)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    alias = _build_alias_for_rubro(rubro)
    table_name = _build_table_for_local(local)
    table_sql = _quote_identifier_mysql(table_name)

    resolved = _resolve_db_for_request(request, alias)
    if not resolved:
        return _db_alias_not_configured_response(alias)

    mode, cfg = resolved

    sql_select = f"SELECT fecha FROM {table_sql} WHERE tipo=%s AND numero=%s"
    sql_delete = f"DELETE FROM {table_sql} WHERE tipo=%s AND numero=%s AND fecha=%s"

    params_select = [tipo, numero]

    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (conn, cursor):
                cursor.execute(sql_select, params_select)
                rows = cursor.fetchall()
                if not rows:
                    return JsonResponse({"detail": "No encontrado."}, status=404)
                if len(rows) > 1:
                    return JsonResponse({"detail": "Ambigüedad: múltiples fechas para tipo/numero."}, status=409)

                fecha = rows[0][0]
                cursor.execute(sql_delete, [tipo, numero, fecha])
                conn.commit()
            return JsonResponse({}, status=204)
        except Exception as e:
            logger.error("movimientos_cabeza_delete legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "No se pudo eliminar movimiento."}, status=500)

    try:
        with connections[alias].cursor() as cursor:
            cursor.execute(sql_select, params_select)
            rows = cursor.fetchall()
            if not rows:
                return JsonResponse({"detail": "No encontrado."}, status=404)
            if len(rows) > 1:
                return JsonResponse({"detail": "Ambigüedad: múltiples fechas para tipo/numero."}, status=409)

            fecha = rows[0][0]
            cursor.execute(sql_delete, [tipo, numero, fecha])
        connections[alias].commit()
        return JsonResponse({}, status=204)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response(alias)
    except Exception as e:
        logger.error("movimientos_cabeza_delete error (%s)", type(e).__name__)
        return JsonResponse({"detail": "No se pudo eliminar movimiento."}, status=500)


@login_required
@require_http_methods(["GET", "POST"])
def movimientos_cabeza_list(request):
    if request.method == "GET":
        return _movimientos_cabeza_list(request)

    return _movimientos_cabeza_create(request)


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def movimientos_cabeza_detail(request, tipo, numero):
    if request.method == "GET":
        return _movimientos_cabeza_get(request, tipo, numero)

    if request.method == "PUT":
        return _movimientos_cabeza_update(request, tipo, numero)

    return _movimientos_cabeza_delete(request, tipo, numero)
