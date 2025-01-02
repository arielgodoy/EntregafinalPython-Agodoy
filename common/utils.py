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
        # 'USER': 'sistema',
        # 'PASSWORD': 'desarrollo_1990',
        # 'HOST': '192.168.4.8',
        'USER': 'root',
        'PASSWORD': '123',
        'HOST': '127.0.0.1',        
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
