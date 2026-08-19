import os
import sys

# Ajustar ruta del proyecto
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Inicializar Django con el settings usado por manage.py
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
import django
django.setup()

from gestiondte.utils.maestro import get_maestroempresa_by_codigo

result = get_maestroempresa_by_codigo('08')
print(result)
