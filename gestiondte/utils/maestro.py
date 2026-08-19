from django.db import connections


def get_maestroempresa_by_codigo(codigo):
    """Busca en las bases contables (solo lectura) por `codigoempresa` y devuelve
    {'codigo','nombre','rut'} o None.

    Esta implementación reusa la estrategia usada por la vista de prueba de
    conexiones (`settings.views.MySQLConnectionTestView`): crea un alias temporal
    en `connections.databases`, ejecuta una consulta SELECT segura y elimina el
    alias, sin modificar datos.
    """
    if codigo is None:
        return None

    codigo_str = str(codigo).strip()
    candidates = [codigo_str]
    stripped = codigo_str.lstrip('0')
    if stripped and stripped != codigo_str:
        candidates.append(stripped)

    import logging
    logger = logging.getLogger(__name__)

    # Lazy import to avoid ciclos y depender de DB settings al importar el módulo
    try:
        from settings.models import SettingsMySQLConnection
        from django.conf import settings
        try:
            import pymysql
        except Exception:
            pymysql = None
    except Exception:
        logger.exception('Error importing settings models or pymysql')
        return None

    # Try configured SettingsMySQLConnection entries (active first)
    qs = SettingsMySQLConnection.objects.filter(is_active=True).order_by('pk')
    for cfg in qs:
        try:
            engine = SettingsMySQLConnection.normalize_engine(getattr(cfg, 'engine', None))

            # Legacy pymysql direct connection
            if engine == SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL:
                if pymysql is None:
                    logger.warning('pymysql missing for legacy engine')
                    continue
                conn = None
                cursor = None
                try:
                    charset = (getattr(cfg, 'charset', None) or 'utf8').strip() or 'utf8'
                    conn = pymysql.connect(
                        host=cfg.host,
                        port=int(cfg.port or 3306),
                        user=cfg.user,
                        password=cfg.password,
                        database=cfg.db_name,
                        charset=charset,
                        connect_timeout=5,
                        read_timeout=10,
                        write_timeout=10,
                    )
                    cursor = conn.cursor()
                    for c in candidates:
                        try:
                            cursor.execute('SELECT codigoempresa, nombre, rut, rutenviasii FROM maestroempresas WHERE codigoempresa = %s LIMIT 1', (c,))
                        except Exception:
                            # table may not exist on this DB
                            continue
                        row = cursor.fetchone()
                        if row:
                            return {'codigo': row[0], 'nombre': row[1], 'rut': row[2], 'rutenviasii': row[3]}
                except Exception:
                    logger.exception('Error testing legacy pymysql connection for cfg %s', cfg)
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

            # Django DB-backed connection: register alias, run query, cleanup
            else:
                alias = f"maestro_check_{cfg.pk}"
                # build complete config from default and overlay
                base_config = {}
                try:
                    base_config = settings.DATABASES.get('default', {}).copy() or {}
                except Exception:
                    base_config = {}

                new_config = base_config.copy()
                new_config.update({
                    'ENGINE': 'django.db.backends.mysql',
                    'NAME': cfg.db_name,
                    'USER': cfg.user,
                    'PASSWORD': cfg.password,
                    'HOST': cfg.host,
                    'PORT': str(cfg.port or ''),
                    'OPTIONS': {'charset': 'utf8mb4'},
                    'CONN_MAX_AGE': 0,
                    'ATOMIC_REQUESTS': False,
                })

                existing = connections.databases.get(alias)
                replace = False
                if existing is not None:
                    try:
                        same = (
                            str(existing.get('NAME', '')) == str(new_config.get('NAME', '')) and
                            str(existing.get('HOST', '')) == str(new_config.get('HOST', '')) and
                            str(existing.get('USER', '')) == str(new_config.get('USER', '')) and
                            str(existing.get('PORT', '')) == str(new_config.get('PORT', ''))
                        )
                    except Exception:
                        same = False
                    if not same:
                        try:
                            connections[alias].close()
                        except Exception:
                            pass
                        replace = True
                else:
                    replace = True

                if replace:
                    connections.databases[alias] = new_config

                try:
                    with connections[alias].cursor() as cursor:
                        for c in candidates:
                            try:
                                cursor.execute('SELECT codigoempresa, nombre, rut, rutenviasii FROM maestroempresas WHERE codigoempresa = %s LIMIT 1', [c])
                            except Exception:
                                # table missing or other error on this DB
                                continue
                            row = cursor.fetchone()
                            if row:
                                return {'codigo': row[0], 'nombre': row[1], 'rut': row[2], 'rutenviasii': row[3]}
                except Exception:
                    logger.exception('Error consultando maestroempresas en cfg %s', cfg)
                finally:
                    try:
                        connections[alias].close()
                    except Exception:
                        pass
                    try:
                        connections.databases.pop(alias, None)
                    except Exception:
                        pass

        except Exception:
            logger.exception('Error procesando configuración %s', getattr(cfg, 'pk', None))
            continue

    return None
