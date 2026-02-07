"""
Test para verificar que PermisoDenegadoJson se maneja correctamente en JSON
"""
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from control_de_proyectos.models import Tarea
from access_control.models import Empresa

# Obtener datos de prueba
empresa = Empresa.objects.get(codigo='01')
tarea = Tarea.objects.get(nombre='Test Tarea')

print("✅ Datos de prueba obtenidos")
print(f"   Tarea ID: {tarea.id}\n")

# Crear usuario SIN permisos
user_sin_permisos = User.objects.create_user(
    username='user_sin_permisos',
    password='testpass'
)

client = Client()
client.login(username='user_sin_permisos', password='testpass')

# Configurar sesión
session = client.session
session['empresa_id'] = empresa.id
session.save()

print("📋 TEST: Usuario SIN permisos intenta actualizar avance")
url = f'/control-proyectos/tareas/{tarea.id}/avance/'
response = client.post(
    url,
    data=json.dumps({'porcentaje_avance': 50}),
    content_type='application/json'
)

print(f"   Status: {response.status_code}")
print(f"   Content-Type: {response.get('Content-Type')}")

try:
    result = response.json()
    print(f"   Success: {result.get('success')}")
    print(f"   Error: {result.get('error')}")
except Exception as e:
    print(f"   ❌ ERROR: No es JSON válido: {e}")
    print(f"   Raw response: {response.content[:200]}")

if response.status_code == 403:
    print("\n✅ PASS: Retorna 403 Forbidden con JsonResponse")
else:
    print(f"\n❌ FAIL: Expected 403, got {response.status_code}")
