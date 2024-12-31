import logging
from django.db import connections

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
        'USER': 'root',
        'PASSWORD': '123',
        'HOST': '127.0.0.1',
        'PORT': '3306',
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
        'TIME_ZONE': 'UTC',
        'CONN_MAX_AGE': 0,
        'CONN_HEALTH_CHECKS': False,
        'AUTOCOMMIT': True,  # Clave necesaria para evitar el error
        'ATOMIC_REQUESTS': False,  # Asegúrate de incluir esta clave
    }

    connections.databases['dinamica'] = db_config

    try:
        # Probar la conexión
        conexion = connections['dinamica']
        with conexion.cursor() as cursor:
            cursor.execute("SELECT 1")
        logger.info(f"Conexión exitosa a la base de datos: {db_config['NAME']}")
        return conexion
    except Exception as e:
        logger.error(f"Error al conectar a la base de datos: {db_config['NAME']}. Detalles: {e}")
        raise
