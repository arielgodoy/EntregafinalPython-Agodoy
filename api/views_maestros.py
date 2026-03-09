import json
import logging
import threading
from contextlib import contextmanager

from django.contrib.auth.decorators import login_required
from django.db import connections
from django.db.utils import ConnectionDoesNotExist
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from access_control.decorators import verificar_permiso

logger = logging.getLogger(__name__)


SQL_MAESTROS_RUBROS_LIST = """SELECT
codigo,
nombre,
ip,
localmatriz,
apostrofe,
colacion
FROM g_maestrorubros
ORDER BY codigo"""


SQL_MAESTROS_RUBROS_GET = """SELECT
codigo,
nombre,
ip,
localmatriz,
apostrofe,
colacion
FROM g_maestrorubros
WHERE codigo = %s"""


SQL_MAESTROS_RUBROS_INSERT = """INSERT INTO g_maestrorubros
(codigo,nombre,ip,localmatriz,apostrofe,colacion)
VALUES (%s,%s,%s,%s,%s,%s)"""


SQL_MAESTROS_RUBROS_UPDATE = """UPDATE g_maestrorubros
SET
nombre=%s,
ip=%s,
localmatriz=%s,
apostrofe=%s,
colacion=%s
WHERE codigo=%s"""


SQL_MAESTROS_RUBROS_DELETE = """DELETE FROM g_maestrorubros
WHERE codigo=%s"""


SQL_MAESTROS_LOCALES_LIST = """SELECT
codigo,
nombre,
direccion,
comuna,
ciudad,
giro,
rut,
ipremota,
ipmaster,
rubro,
nombrelocal,
colacion
FROM g_maestroempresas
ORDER BY codigo"""


SQL_MAESTROS_LOCALES_GET = """SELECT
codigo,
nombre,
direccion,
comuna,
ciudad,
giro,
rut,
ipremota,
ipmaster,
rubro,
nombrelocal,
colacion
FROM g_maestroempresas
WHERE codigo=%s"""


SQL_MAESTROS_LOCALES_INSERT = """INSERT INTO g_maestroempresas
(codigo,nombre,direccion,comuna,ciudad,giro,rut,ipremota,ipmaster,rubro,nombrelocal,colacion,
codigocomerciotbk,puntoscada,vendegas,cantidadacumulacioncajera,mts,ciudad_grupo,cuotassininteres,sobreplazomeses,
tesoreria,descuentoefectivo,montominimodescuento,interesconvencional,facturadorelectronico,codigosucursalventa,
cuentailanoazucar,montosensible,diasmaximoretiro)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""


SQL_MAESTROS_LOCALES_UPDATE = """UPDATE g_maestroempresas
SET
nombre=%s,
direccion=%s,
comuna=%s,
ciudad=%s,
giro=%s,
rut=%s,
ipremota=%s,
ipmaster=%s,
rubro=%s,
nombrelocal=%s,
colacion=%s
WHERE codigo=%s"""


SQL_MAESTROS_LOCALES_DELETE = """DELETE FROM g_maestroempresas
WHERE codigo=%s"""


VISTA_NOMBRE = "API - Maestros Rubros"

VISTA_NOMBRE_LOCALES = "API - Maestros Locales"

DB_ALIAS = "eltit_gestion"
_DB_ALIAS_LOCK = threading.Lock()

ENGINE_DJANGO_MYSQL = "django.db.backends.mysql"
ENGINE_LEGACY_PYMYSQL = "legacy_pymysql"
ENGINE_API_REMOTA = "api_remota"

_SETTINGS_MYSQL_CONNECTION_TABLE = "settings_settingsmysqlconnection"


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


def _get_active_mysql_connection_cfg_for_empresa(empresa_id):
    for nombre_logico in (DB_ALIAS, "gestion"):
        cfg = _fetch_settings_mysql_connection_cfg(empresa_id=empresa_id, nombre_logico=nombre_logico)
        if cfg and cfg.get("is_active"):
            return cfg
    return None


def _db_alias_not_configured_response():
    return JsonResponse({"error": f"Database connection '{DB_ALIAS}' is not configured"}, status=500)


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


def _ensure_django_alias_configured_from_cfg(cfg) -> bool:
    """Registra/actualiza DB_ALIAS en django.db.connections.databases.

    Replica el patrón del botón Test en Settings (pero no hace limpieza del alias).

    Nota:
    - En tests, `connections` puede estar mockeado sin atributo `databases`; en ese caso no se valida.
    """

    if not hasattr(connections, "databases"):
        return True

    # Build complete DB config based on settings.DATABASES['default']
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
            existing = connections.databases.get(DB_ALIAS)
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
                connections[DB_ALIAS].close()
            except Exception:
                pass
            try:
                del connections[DB_ALIAS]
            except Exception:
                pass

            try:
                connections.databases[DB_ALIAS] = new_config
            except Exception:
                return False

            try:
                if hasattr(connections, "ensure_defaults"):
                    connections.ensure_defaults(DB_ALIAS)
            except Exception:
                pass

        try:
            _ = connections[DB_ALIAS]
        except Exception:
            return False

    return True


def _resolve_db_for_request(request):
    """Resuelve el modo de conexión para el request.

    Retorna:
    - ("django", cfg_or_None) cuando se usará django.db.connections[DB_ALIAS]
    - ("legacy_pymysql", cfg) cuando se usará PyMySQL directo (MySQL 5.1)
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
        # Sin empresa activa: si el alias ya existe, usarlo; si no, fallar.
        try:
            _ = connections[DB_ALIAS]
            return ("django", None)
        except Exception:
            return None

    cfg = _get_active_mysql_connection_cfg_for_empresa(empresa_id)

    if not cfg:
        try:
            _ = connections[DB_ALIAS]
            return ("django", None)
        except Exception:
            return None

    engine = _normalize_engine(_cfg_get(cfg, "engine", None))
    if engine == ENGINE_LEGACY_PYMYSQL:
        return ("legacy_pymysql", cfg)

    if engine == ENGINE_API_REMOTA:
        return None

    if not _ensure_django_alias_configured_from_cfg(cfg):
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


def _to_bool(value):
    return bool(value)


def _bool_to_int(value):
    if value is True:
        return 1
    if value is False:
        return 0
    raise ValueError("colacion debe ser boolean.")


def _row_to_dict(cursor, row):
    columns = [col[0] for col in cursor.description]
    item = dict(zip(columns, row))
    if "colacion" in item:
        item["colacion"] = _to_bool(item["colacion"])
    return item


def _rows_to_dicts(cursor, rows):
    columns = [col[0] for col in cursor.description]
    data = []
    for row in rows:
        item = dict(zip(columns, row))
        if "colacion" in item:
            item["colacion"] = _to_bool(item["colacion"])
        data.append(item)
    return data


def _row_to_dict_raw(cursor, row):
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def _rows_to_dicts_raw(cursor, rows):
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def _validate_codigo(codigo):
    codigo = (codigo or "").strip()
    if len(codigo) != 2:
        raise ValueError("codigo inválido.")
    return codigo


def _validate_payload_create(payload):
    required = ("codigo", "nombre", "ip", "localmatriz", "apostrofe", "colacion")
    for key in required:
        if key not in payload:
            raise ValueError("Body inválido.")

    codigo = _validate_codigo(payload.get("codigo"))

    nombre = payload.get("nombre")
    ip = payload.get("ip")
    localmatriz = payload.get("localmatriz")
    apostrofe = payload.get("apostrofe")

    if not isinstance(nombre, str) or not isinstance(ip, str) or not isinstance(localmatriz, str) or not isinstance(apostrofe, str):
        raise ValueError("Body inválido.")

    localmatriz = localmatriz.strip()
    if len(localmatriz) != 2:
        raise ValueError("localmatriz inválido.")

    colacion = _bool_to_int(payload.get("colacion"))

    return {
        "codigo": codigo,
        "nombre": nombre.strip(),
        "ip": ip.strip(),
        "localmatriz": localmatriz,
        "apostrofe": apostrofe.strip(),
        "colacion": colacion,
    }


def _validate_payload_update(payload):
    required = ("nombre", "ip", "localmatriz", "apostrofe", "colacion")
    for key in required:
        if key not in payload:
            raise ValueError("Body inválido.")

    nombre = payload.get("nombre")
    ip = payload.get("ip")
    localmatriz = payload.get("localmatriz")
    apostrofe = payload.get("apostrofe")

    if not isinstance(nombre, str) or not isinstance(ip, str) or not isinstance(localmatriz, str) or not isinstance(apostrofe, str):
        raise ValueError("Body inválido.")

    localmatriz = localmatriz.strip()
    if len(localmatriz) != 2:
        raise ValueError("localmatriz inválido.")

    colacion = _bool_to_int(payload.get("colacion"))

    return {
        "nombre": nombre.strip(),
        "ip": ip.strip(),
        "localmatriz": localmatriz,
        "apostrofe": apostrofe.strip(),
        "colacion": colacion,
    }


_LOCALES_INSERT_REQUIRED_DEFAULTS = {
    "codigocomerciotbk": "",
    "puntoscada": 0.0,
    "vendegas": 0,
    "cantidadacumulacioncajera": 0.0,
    "mts": 0.0,
    "ciudad_grupo": "",
    "cuotassininteres": 0.0,
    "sobreplazomeses": 0.0,
    "tesoreria": "",
    "descuentoefectivo": 0.0,
    "montominimodescuento": 0.0,
    "interesconvencional": 0.0,
    "facturadorelectronico": 0,
    "codigosucursalventa": "",
    "cuentailanoazucar": "",
    "montosensible": 0.0,
    "diasmaximoretiro": 0.0,
}


def _validate_locales_payload_create(payload):
    required = (
        "codigo",
        "nombre",
        "direccion",
        "comuna",
        "ciudad",
        "giro",
        "rut",
        "ipremota",
        "ipmaster",
        "rubro",
        "nombrelocal",
        "colacion",
    )
    for key in required:
        if key not in payload:
            raise ValueError("Body inválido.")

    codigo = _validate_codigo(payload.get("codigo"))
    rubro = _validate_codigo(payload.get("rubro"))

    string_fields = {
        "nombre": (50, True),
        "direccion": (50, True),
        "comuna": (50, True),
        "ciudad": (50, True),
        "giro": (50, True),
        "rut": (10, True),
        "ipremota": (30, True),
        "ipmaster": (30, True),
        "nombrelocal": (20, False),
    }

    clean = {"codigo": codigo, "rubro": rubro}
    for field_name, (max_len, allow_blank) in string_fields.items():
        value = payload.get(field_name)
        if not isinstance(value, str):
            raise ValueError("Body inválido.")
        value = value.strip()
        if not allow_blank and not value:
            raise ValueError(f"{field_name} inválido.")
        if len(value) > max_len:
            raise ValueError(f"{field_name} inválido.")
        clean[field_name] = value

    colacion = payload.get("colacion")
    if isinstance(colacion, bool) or not isinstance(colacion, (int, float)):
        raise ValueError("colacion inválido.")
    clean["colacion"] = float(colacion)

    return clean


def _validate_locales_payload_update(payload):
    required = (
        "nombre",
        "direccion",
        "comuna",
        "ciudad",
        "giro",
        "rut",
        "ipremota",
        "ipmaster",
        "rubro",
        "nombrelocal",
        "colacion",
    )
    for key in required:
        if key not in payload:
            raise ValueError("Body inválido.")

    rubro = _validate_codigo(payload.get("rubro"))

    string_fields = {
        "nombre": (50, True),
        "direccion": (50, True),
        "comuna": (50, True),
        "ciudad": (50, True),
        "giro": (50, True),
        "rut": (10, True),
        "ipremota": (30, True),
        "ipmaster": (30, True),
        "nombrelocal": (20, False),
    }

    clean = {"rubro": rubro}
    for field_name, (max_len, allow_blank) in string_fields.items():
        value = payload.get(field_name)
        if not isinstance(value, str):
            raise ValueError("Body inválido.")
        value = value.strip()
        if not allow_blank and not value:
            raise ValueError(f"{field_name} inválido.")
        if len(value) > max_len:
            raise ValueError(f"{field_name} inválido.")
        clean[field_name] = value

    colacion = payload.get("colacion")
    if isinstance(colacion, bool) or not isinstance(colacion, (int, float)):
        raise ValueError("colacion inválido.")
    clean["colacion"] = float(colacion)

    return clean


@verificar_permiso(VISTA_NOMBRE_LOCALES, "ingresar")
def _locales_list(request):
    resolved = _resolve_db_for_request(request)
    if not resolved:
        return _db_alias_not_configured_response()

    mode, cfg = resolved
    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (_conn, cursor):
                cursor.execute(SQL_MAESTROS_LOCALES_LIST)
                rows = cursor.fetchall()
                data = _rows_to_dicts_raw(cursor, rows)
            return JsonResponse(data, safe=False)
        except Exception as e:
            logger.error("maestros_locales_list legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "Error interno."}, status=500)

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            cursor.execute(SQL_MAESTROS_LOCALES_LIST)
            rows = cursor.fetchall()
            data = _rows_to_dicts_raw(cursor, rows)
        return JsonResponse(data, safe=False)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response()
    except Exception as e:
        logger.error("maestros_locales_list error (%s)", type(e).__name__)
        return JsonResponse({"detail": "Error interno."}, status=500)


@verificar_permiso(VISTA_NOMBRE_LOCALES, "ingresar")
def _locales_get(request, codigo):
    resolved = _resolve_db_for_request(request)
    if not resolved:
        return _db_alias_not_configured_response()

    mode, cfg = resolved
    try:
        codigo = _validate_codigo(codigo)
    except ValueError:
        return JsonResponse({"detail": "codigo inválido."}, status=400)

    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (_conn, cursor):
                cursor.execute(SQL_MAESTROS_LOCALES_GET, [codigo])
                row = cursor.fetchone()
                if not row:
                    return JsonResponse({"detail": "No encontrado."}, status=404)
                item = _row_to_dict_raw(cursor, row)
            return JsonResponse(item, safe=True)
        except Exception as e:
            logger.error("maestros_locales_get legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "Error interno."}, status=500)

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            cursor.execute(SQL_MAESTROS_LOCALES_GET, [codigo])
            row = cursor.fetchone()
            if not row:
                return JsonResponse({"detail": "No encontrado."}, status=404)
            item = _row_to_dict_raw(cursor, row)
        return JsonResponse(item, safe=True)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response()
    except Exception as e:
        logger.error("maestros_locales_get error (%s)", type(e).__name__)
        return JsonResponse({"detail": "Error interno."}, status=500)


@verificar_permiso(VISTA_NOMBRE_LOCALES, "crear")
def _locales_create(request):
    resolved = _resolve_db_for_request(request)
    if not resolved:
        return _db_alias_not_configured_response()

    mode, cfg = resolved
    try:
        payload = _parse_json_object(request)
        clean = _validate_locales_payload_create(payload)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    extra_defaults = _LOCALES_INSERT_REQUIRED_DEFAULTS
    params = [
        clean["codigo"],
        clean["nombre"],
        clean["direccion"],
        clean["comuna"],
        clean["ciudad"],
        clean["giro"],
        clean["rut"],
        clean["ipremota"],
        clean["ipmaster"],
        clean["rubro"],
        clean["nombrelocal"],
        clean["colacion"],
        extra_defaults["codigocomerciotbk"],
        extra_defaults["puntoscada"],
        extra_defaults["vendegas"],
        extra_defaults["cantidadacumulacioncajera"],
        extra_defaults["mts"],
        extra_defaults["ciudad_grupo"],
        extra_defaults["cuotassininteres"],
        extra_defaults["sobreplazomeses"],
        extra_defaults["tesoreria"],
        extra_defaults["descuentoefectivo"],
        extra_defaults["montominimodescuento"],
        extra_defaults["interesconvencional"],
        extra_defaults["facturadorelectronico"],
        extra_defaults["codigosucursalventa"],
        extra_defaults["cuentailanoazucar"],
        extra_defaults["montosensible"],
        extra_defaults["diasmaximoretiro"],
    ]

    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (conn, cursor):
                cursor.execute(SQL_MAESTROS_LOCALES_INSERT, params)
                conn.commit()
            return JsonResponse(clean, status=201)
        except Exception as e:
            logger.error("maestros_locales_create legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "No se pudo crear local."}, status=500)

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            cursor.execute(SQL_MAESTROS_LOCALES_INSERT, params)
        connections[DB_ALIAS].commit()
        return JsonResponse(clean, status=201)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response()
    except Exception as e:
        logger.error("maestros_locales_create error (%s)", type(e).__name__)
        return JsonResponse({"detail": "No se pudo crear local."}, status=500)


@verificar_permiso(VISTA_NOMBRE_LOCALES, "modificar")
def _locales_update(request, codigo):
    resolved = _resolve_db_for_request(request)
    if not resolved:
        return _db_alias_not_configured_response()

    mode, cfg = resolved
    try:
        codigo = _validate_codigo(codigo)
    except ValueError:
        return JsonResponse({"detail": "codigo inválido."}, status=400)

    try:
        payload = _parse_json_object(request)
        clean = _validate_locales_payload_update(payload)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    params = [
        clean["nombre"],
        clean["direccion"],
        clean["comuna"],
        clean["ciudad"],
        clean["giro"],
        clean["rut"],
        clean["ipremota"],
        clean["ipmaster"],
        clean["rubro"],
        clean["nombrelocal"],
        clean["colacion"],
        codigo,
    ]

    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (conn, cursor):
                cursor.execute(SQL_MAESTROS_LOCALES_UPDATE, params)
                if cursor.rowcount == 0:
                    return JsonResponse({"detail": "No encontrado."}, status=404)
                conn.commit()
            return JsonResponse({"codigo": codigo, **clean})
        except Exception as e:
            logger.error("maestros_locales_update legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "No se pudo actualizar local."}, status=500)

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            cursor.execute(SQL_MAESTROS_LOCALES_UPDATE, params)
            if cursor.rowcount == 0:
                return JsonResponse({"detail": "No encontrado."}, status=404)
        connections[DB_ALIAS].commit()
        return JsonResponse({"codigo": codigo, **clean})
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response()
    except Exception as e:
        logger.error("maestros_locales_update error (%s)", type(e).__name__)
        return JsonResponse({"detail": "No se pudo actualizar local."}, status=500)


@verificar_permiso(VISTA_NOMBRE_LOCALES, "eliminar")
def _locales_delete(request, codigo):
    resolved = _resolve_db_for_request(request)
    if not resolved:
        return _db_alias_not_configured_response()

    mode, cfg = resolved
    try:
        codigo = _validate_codigo(codigo)
    except ValueError:
        return JsonResponse({"detail": "codigo inválido."}, status=400)

    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (conn, cursor):
                cursor.execute(SQL_MAESTROS_LOCALES_DELETE, [codigo])
                if cursor.rowcount == 0:
                    return JsonResponse({"detail": "No encontrado."}, status=404)
                conn.commit()
            return JsonResponse({}, status=204)
        except Exception as e:
            logger.error("maestros_locales_delete legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "No se pudo eliminar local."}, status=500)

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            cursor.execute(SQL_MAESTROS_LOCALES_DELETE, [codigo])
            if cursor.rowcount == 0:
                return JsonResponse({"detail": "No encontrado."}, status=404)
        connections[DB_ALIAS].commit()
        return JsonResponse({}, status=204)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response()
    except Exception as e:
        logger.error("maestros_locales_delete error (%s)", type(e).__name__)
        return JsonResponse({"detail": "No se pudo eliminar local."}, status=500)



@verificar_permiso(VISTA_NOMBRE, "ingresar")
def _rubros_list(request):
    resolved = _resolve_db_for_request(request)
    if not resolved:
        return _db_alias_not_configured_response()

    mode, cfg = resolved
    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (_conn, cursor):
                cursor.execute(SQL_MAESTROS_RUBROS_LIST)
                rows = cursor.fetchall()
                data = _rows_to_dicts(cursor, rows)
            return JsonResponse(data, safe=False)
        except Exception as e:
            logger.error("maestros_rubros_list legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "Error interno."}, status=500)

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            cursor.execute(SQL_MAESTROS_RUBROS_LIST)
            rows = cursor.fetchall()
            data = _rows_to_dicts(cursor, rows)
        return JsonResponse(data, safe=False)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response()
    except Exception as e:
        logger.error("maestros_rubros_list error (%s)", type(e).__name__)
        return JsonResponse({"detail": "Error interno."}, status=500)


@verificar_permiso(VISTA_NOMBRE, "ingresar")
def _rubros_get(request, codigo):
    resolved = _resolve_db_for_request(request)
    if not resolved:
        return _db_alias_not_configured_response()

    mode, cfg = resolved
    try:
        codigo = _validate_codigo(codigo)
    except ValueError:
        return JsonResponse({"detail": "codigo inválido."}, status=400)

    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (_conn, cursor):
                cursor.execute(SQL_MAESTROS_RUBROS_GET, [codigo])
                row = cursor.fetchone()
                if not row:
                    return JsonResponse({"detail": "No encontrado."}, status=404)
                item = _row_to_dict(cursor, row)
            return JsonResponse(item, safe=True)
        except Exception as e:
            logger.error("maestros_rubros_get legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "Error interno."}, status=500)

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            cursor.execute(SQL_MAESTROS_RUBROS_GET, [codigo])
            row = cursor.fetchone()
            if not row:
                return JsonResponse({"detail": "No encontrado."}, status=404)
            item = _row_to_dict(cursor, row)
        return JsonResponse(item, safe=True)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response()
    except Exception as e:
        logger.error("maestros_rubros_get error (%s)", type(e).__name__)
        return JsonResponse({"detail": "Error interno."}, status=500)


@verificar_permiso(VISTA_NOMBRE, "crear")
def _rubros_create(request):
    resolved = _resolve_db_for_request(request)
    if not resolved:
        return _db_alias_not_configured_response()

    mode, cfg = resolved
    try:
        payload = _parse_json_object(request)
        clean = _validate_payload_create(payload)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (conn, cursor):
                cursor.execute(
                    SQL_MAESTROS_RUBROS_INSERT,
                    [
                        clean["codigo"],
                        clean["nombre"],
                        clean["ip"],
                        clean["localmatriz"],
                        clean["apostrofe"],
                        clean["colacion"],
                    ],
                )
                conn.commit()
            response_item = {
                **clean,
                "colacion": bool(clean["colacion"]),
            }
            return JsonResponse(response_item, status=201)
        except Exception as e:
            logger.error("maestros_rubros_create legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "No se pudo crear rubro."}, status=500)

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            cursor.execute(
                SQL_MAESTROS_RUBROS_INSERT,
                [
                    clean["codigo"],
                    clean["nombre"],
                    clean["ip"],
                    clean["localmatriz"],
                    clean["apostrofe"],
                    clean["colacion"],
                ],
            )
        connections[DB_ALIAS].commit()
        response_item = {
            **clean,
            "colacion": bool(clean["colacion"]),
        }
        return JsonResponse(response_item, status=201)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response()
    except Exception as e:
        logger.error("maestros_rubros_create error (%s)", type(e).__name__)
        return JsonResponse({"detail": "No se pudo crear rubro."}, status=500)


@verificar_permiso(VISTA_NOMBRE, "modificar")
def _rubros_update(request, codigo):
    resolved = _resolve_db_for_request(request)
    if not resolved:
        return _db_alias_not_configured_response()

    mode, cfg = resolved
    try:
        codigo = _validate_codigo(codigo)
    except ValueError:
        return JsonResponse({"detail": "codigo inválido."}, status=400)

    try:
        payload = _parse_json_object(request)
        clean = _validate_payload_update(payload)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (conn, cursor):
                cursor.execute(
                    SQL_MAESTROS_RUBROS_UPDATE,
                    [
                        clean["nombre"],
                        clean["ip"],
                        clean["localmatriz"],
                        clean["apostrofe"],
                        clean["colacion"],
                        codigo,
                    ],
                )
                if cursor.rowcount == 0:
                    return JsonResponse({"detail": "No encontrado."}, status=404)
                conn.commit()

            response_item = {
                "codigo": codigo,
                **clean,
                "colacion": bool(clean["colacion"]),
            }
            return JsonResponse(response_item)
        except Exception as e:
            logger.error("maestros_rubros_update legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "No se pudo actualizar rubro."}, status=500)

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            cursor.execute(
                SQL_MAESTROS_RUBROS_UPDATE,
                [
                    clean["nombre"],
                    clean["ip"],
                    clean["localmatriz"],
                    clean["apostrofe"],
                    clean["colacion"],
                    codigo,
                ],
            )
            if cursor.rowcount == 0:
                return JsonResponse({"detail": "No encontrado."}, status=404)
        connections[DB_ALIAS].commit()

        response_item = {
            "codigo": codigo,
            **clean,
            "colacion": bool(clean["colacion"]),
        }
        return JsonResponse(response_item)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response()
    except Exception as e:
        logger.error("maestros_rubros_update error (%s)", type(e).__name__)
        return JsonResponse({"detail": "No se pudo actualizar rubro."}, status=500)


@verificar_permiso(VISTA_NOMBRE, "eliminar")
def _rubros_delete(request, codigo):
    resolved = _resolve_db_for_request(request)
    if not resolved:
        return _db_alias_not_configured_response()

    mode, cfg = resolved
    try:
        codigo = _validate_codigo(codigo)
    except ValueError:
        return JsonResponse({"detail": "codigo inválido."}, status=400)

    if mode == "legacy_pymysql":
        try:
            with _legacy_pymysql_connection(cfg) as (conn, cursor):
                cursor.execute(SQL_MAESTROS_RUBROS_DELETE, [codigo])
                if cursor.rowcount == 0:
                    return JsonResponse({"detail": "No encontrado."}, status=404)
                conn.commit()
            return JsonResponse({}, status=204)
        except Exception as e:
            logger.error("maestros_rubros_delete legacy_pymysql error (%s)", type(e).__name__)
            return JsonResponse({"detail": "No se pudo eliminar rubro."}, status=500)

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            cursor.execute(SQL_MAESTROS_RUBROS_DELETE, [codigo])
            if cursor.rowcount == 0:
                return JsonResponse({"detail": "No encontrado."}, status=404)
        connections[DB_ALIAS].commit()
        return JsonResponse({}, status=204)
    except ConnectionDoesNotExist:
        return _db_alias_not_configured_response()
    except Exception as e:
        logger.error("maestros_rubros_delete error (%s)", type(e).__name__)
        return JsonResponse({"detail": "No se pudo eliminar rubro."}, status=500)


@login_required
@require_http_methods(["GET", "POST"])
def maestros_rubros_list(request):
    if request.method == "GET":
        return _rubros_list(request)

    return _rubros_create(request)


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def maestros_rubros_detail(request, codigo):
    if request.method == "GET":
        return _rubros_get(request, codigo)

    if request.method == "PUT":
        return _rubros_update(request, codigo)

    return _rubros_delete(request, codigo)


@login_required
@require_http_methods(["GET", "POST"])
def maestros_locales_list(request):
    if request.method == "GET":
        return _locales_list(request)

    return _locales_create(request)


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def maestros_locales_detail(request, codigo):
    if request.method == "GET":
        return _locales_get(request, codigo)

    if request.method == "PUT":
        return _locales_update(request, codigo)

    return _locales_delete(request, codigo)
