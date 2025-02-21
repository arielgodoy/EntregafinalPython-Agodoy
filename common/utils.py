import logging
from django.db import connections
from django.db.utils import OperationalError

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



def crear_conexion(nombre_bd):
    """
    Crea una conexión dinámica a una base de datos no definida en settings.py.

    Args:
        nombre_bd (str): Nombre de la base de datos incluido el cliente sistema.
    
    Returns:
        django.db.backends.base.BaseDatabaseWrapper: Objeto de conexión.
    """
    db_config = {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': f"{nombre_bd}",
        
         'USER': 'sistema',
         'PASSWORD': 'desarrollo_1990',
         'HOST': '192.168.4.8',

        #  'USER': 'root',
        #  'PASSWORD': '123',
        #  'HOST': '127.0.0.1',        

        'PORT': '3306',
        'OPTIONS': {
            # Intenta primero con utf8mb4; si falla, retrocede a utf8
            'charset': 'utf8',
        },
        'TIME_ZONE': 'UTC',
        'CONN_MAX_AGE': 0,
        'CONN_HEALTH_CHECKS': False,
        'AUTOCOMMIT': True,  # Asegura que se apliquen automáticamente los cambios
        'ATOMIC_REQUESTS': False,
    }

    connections.databases['dinamica'] = db_config

    try:
        # Probar la conexión
        conexion = connections['dinamica']
        with conexion.cursor() as cursor:
            cursor.execute("SELECT 1")
        logger.info(f"Conexión exitosa a la base de datos: {db_config['NAME']}")
        return conexion
    except OperationalError as e:
        if "Unknown character set" in str(e):
            logger.warning(f"Error con el conjunto de caracteres. Cambiando de '{db_config['OPTIONS']['charset']}' a 'utf8'.")
            db_config['OPTIONS']['charset'] = 'utf8'
            connections.databases['dinamica'] = db_config
            try:
                conexion = connections['dinamica']
                with conexion.cursor() as cursor:
                    cursor.execute("SELECT 1")
                logger.info(f"Conexión exitosa a la base de datos con charset 'utf8': {db_config['NAME']}")
                return conexion
            except Exception as ex:
                logger.error(f"Error al conectar con charset 'utf8': {ex}")
                raise ex
        else:
            logger.error(f"Error al conectar a la base de datos: {e}")
            raise



def sql_sistema(operacion, base_datos, tabla, condicion=None, objeto=None):
    """
    Ejecuta operaciones CRUD en la base de datos dinámica especificada.

    Args:
        operacion (int): Tipo de operación (0: Leer, 2: Crear, 3: Modificar, 4: Eliminar).
        base_datos (str): Nombre de la base de datos.
        tabla (str): Nombre de la tabla.
        condicion (str, opcional): Condición para WHERE en las operaciones (solo para leer, modificar y eliminar).
        objeto (dict, opcional): Datos para las operaciones de crear o modificar.

    Returns:
        dict: Contiene el "status" (0: éxito, 3: error, 4: no encontrado) y el "resultado" (datos afectados).
    """
    try:
        # Crear conexión dinámica
        conexion = crear_conexion(base_datos)
        resultado = []

        with conexion.cursor() as cursor:
            if operacion == 0:  # Leer
                consulta = f"SELECT * FROM {tabla}"
                if condicion:
                    consulta += f" WHERE {condicion}"
                cursor.execute(consulta)
                resultado = cursor.fetchall()
                return {"status": 0, "resultado": resultado}

            elif operacion == 2:  # Crear
                if not objeto:
                    raise ValueError("El objeto es requerido para la operación Crear.")

                columnas = ', '.join(objeto.keys())
                valores = ', '.join(["%s" for _ in objeto.values()])
                consulta = f"INSERT INTO {tabla} ({columnas}) VALUES ({valores})"
                cursor.execute(consulta, list(objeto.values()))
                conexion.commit()
                return {"status": 0, "resultado": {"id": cursor.lastrowid, **objeto}}

            elif operacion == 3:  # Modificar
                if not objeto or not condicion:
                    raise ValueError("El objeto y la condición son requeridos para la operación Modificar.")

                set_clause = ', '.join([f"{key}=%s" for key in objeto.keys()])
                consulta = f"UPDATE {tabla} SET {set_clause} WHERE {condicion}"
                cursor.execute(consulta, list(objeto.values()))
                conexion.commit()

                if cursor.rowcount == 0:
                    return {"status": 4, "resultado": []}  # No encontrado

                return {"status": 0, "resultado": {"condicion": condicion, **objeto}}

            elif operacion == 4:  # Eliminar
                if not condicion:
                    raise ValueError("La condición es requerida para la operación Eliminar.")

                consulta = f"DELETE FROM {tabla} WHERE {condicion}"
                cursor.execute(consulta)
                conexion.commit()

                if cursor.rowcount == 0:
                    return {"status": 4, "resultado": []}  # No encontrado

                return {"status": 0, "resultado": {"condicion": condicion}}

            else:
                raise ValueError("Operación no soportada.")

    except OperationalError as e:
        logger.error(f"Error de conexión: {e}")
        return {"status": 3, "resultado": str(e)}

    except Exception as e:
        logger.error(f"Error al ejecutar la operación: {e}")
        return {"status": 3, "resultado": str(e)}
