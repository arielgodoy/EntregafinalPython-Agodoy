"""
Test completo del endpoint actualizar_avance_tarea - casos de error
"""
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from control_de_proyectos.models import Proyecto, Tarea
from access_control.models import Empresa, Vista, Permiso

# Obtener datos de prueba (del test anterior)
user = User.objects.get(username='testuser')
empresa = Empresa.objects.get(codigo='01')
proyecto = Proyecto.objects.get(nombre='Test Proyecto')
tarea = Tarea.objects.get(nombre='Test Tarea')

print("✅ Datos de prueba obtenidos")
print(f"   Tarea ID: {tarea.id}")
print(f"   Avance actual: {tarea.porcentaje_avance}%\n")

client = Client()
client.login(username='testuser', password='testpass')

# Configurar sesión
session = client.session
session['empresa_id'] = empresa.id
session.save()

# Test 1: Valor inválido (> 100)
print("📋 TEST 1: Valor > 100")
url = f'/control-proyectos/tareas/{tarea.id}/avance/'
response = client.post(
    url,
    data=json.dumps({'porcentaje_avance': 150}),
    content_type='application/json'
)
result = response.json()
print(f"   Status: {response.status_code}")
print(f"   Error: {result.get('error')}")
assert response.status_code == 400, f"Expected 400, got {response.status_code}"
print("   ✓ PASS\n")

# Test 2: Valor inválido (< 0)
print("📋 TEST 2: Valor < 0")
response = client.post(
    url,
    data=json.dumps({'porcentaje_avance': -10}),
    content_type='application/json'
)
result = response.json()
print(f"   Status: {response.status_code}")
print(f"   Error: {result.get('error')}")
assert response.status_code == 400
print("   ✓ PASS\n")

# Test 3: Campo faltante
print("📋 TEST 3: Campo porcentaje_avance faltante")
response = client.post(
    url,
    data=json.dumps({}),
    content_type='application/json'
)
result = response.json()
print(f"   Status: {response.status_code}")
print(f"   Error: {result.get('error')}")
assert response.status_code == 400
print("   ✓ PASS\n")

# Test 4: JSON inválido
print("📋 TEST 4: JSON inválido")
response = client.post(
    url,
    data='invalid json',
    content_type='application/json'
)
result = response.json()
print(f"   Status: {response.status_code}")
print(f"   Error: {result.get('error')}")
assert response.status_code == 400
print("   ✓ PASS\n")

# Test 5: Tarea no existe
print("📋 TEST 5: Tarea no existe")
url_bad = f'/control-proyectos/tareas/99999/avance/'
response = client.post(
    url_bad,
    data=json.dumps({'porcentaje_avance': 50}),
    content_type='application/json'
)
result = response.json()
print(f"   Status: {response.status_code}")
print(f"   Error: {result.get('error')}")
assert response.status_code == 404
print("   ✓ PASS\n")

# Test 6: Valor válido (0)
print("📋 TEST 6: Valor válido (0)")
response = client.post(
    url,
    data=json.dumps({'porcentaje_avance': 0}),
    content_type='application/json'
)
result = response.json()
print(f"   Status: {response.status_code}")
print(f"   Success: {result.get('success')}")
print(f"   Porcentaje: {result.get('porcentaje_avance')}%")
assert response.status_code == 200
assert result.get('porcentaje_avance') == 0
print("   ✓ PASS\n")

# Test 7: Valor válido (100)
print("📋 TEST 7: Valor válido (100)")
response = client.post(
    url,
    data=json.dumps({'porcentaje_avance': 100}),
    content_type='application/json'
)
result = response.json()
print(f"   Status: {response.status_code}")
print(f"   Success: {result.get('success')}")
print(f"   Porcentaje: {result.get('porcentaje_avance')}%")
assert response.status_code == 200
assert result.get('porcentaje_avance') == 100
print("   ✓ PASS\n")

# Test 8: Verificar que se guardó en BD
print("📋 TEST 8: Verificar persistencia en BD")
tarea.refresh_from_db()
print(f"   Avance en BD: {tarea.porcentaje_avance}%")
assert tarea.porcentaje_avance == 100
print("   ✓ PASS\n")

print("🎉 TODOS LOS TESTS PASARON!")
