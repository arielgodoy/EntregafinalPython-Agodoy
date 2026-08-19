import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
import django
django.setup()

from django.conf import settings
from django.db import connections

def check_maestro_in_all():
    results = {}
    for alias in settings.DATABASES.keys():
        try:
            conn = connections[alias]
        except Exception as e:
            results[alias] = f"no disponible: {e}"
            continue
        try:
            with conn.cursor() as cursor:
                # Try a harmless read-only query; param style differs by backend
                try:
                    cursor.execute('SELECT COUNT(*) FROM maestroempresas')
                except Exception:
                    # Try backticks or different casing
                    try:
                        cursor.execute('SELECT COUNT(*) FROM `maestroempresas`')
                    except Exception as e:
                        results[alias] = f"tabla no encontrada o error: {e}"
                        continue
                row = cursor.fetchone()
                results[alias] = f"tabla encontrada, filas={row[0] if row else 'unknown'}"
        except Exception as e:
            results[alias] = f"error lectura: {e}"
    return results

if __name__ == '__main__':
    res = check_maestro_in_all()
    for k, v in res.items():
        print(f"{k}: {v}")
