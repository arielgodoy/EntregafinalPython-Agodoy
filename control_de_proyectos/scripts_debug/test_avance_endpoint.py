"""
Test simple para el endpoint actualizar_avance_tarea
"""
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
django.setup()

from django.test import Client, TestCase
from django.contrib.auth.models import User
from control_de_proyectos.models import Proyecto, Tarea
from access_control.models import Empresa, Vista, Permiso

# Crear datos de prueba
print("🔧 Creando datos de prueba...")

# Usuario
user, _ = User.objects.get_or_create(username='testuser')
user.set_password('testpass')
user.save()

# Empresa (codigo debe ser 2 dígitos)
empresa, _ = Empresa.objects.get_or_create(codigo='01', defaults={'descripcion': 'Test Empresa'})

# Dar permisos al usuario
vista, _ = Vista.objects.get_or_create(nombre='Actualizar Avance Tarea')
permiso, created = Permiso.objects.get_or_create(
    usuario=user,
    vista=vista,
    empresa=empresa
)
permiso.modificar = True
permiso.save()
print(f"✓ Permiso: {permiso} (modificar={permiso.modificar})")

# Proyecto
proyecto, _ = Proyecto.objects.get_or_create(
    nombre='Test Proyecto',
    empresa_interna=empresa,
    defaults={'cliente_id': 1}  # Asumiendo que existe cliente con ID 1
)

# Tarea
tarea, _ = Tarea.objects.get_or_create(
    nombre='Test Tarea',
    proyecto=proyecto,
    defaults={'porcentaje_avance': 0}
)

print(f"✓ Usuario: {user.username}")
print(f"✓ Empresa: {empresa.codigo} - {empresa.descripcion}")
print(f"✓ Proyecto: {proyecto.nombre}")
print(f"✓ Tarea: {tarea.nombre} (ID: {tarea.id}, avance: {tarea.porcentaje_avance}%)")

# Test con cliente
print("\n📡 Testeando endpoint...")
client = Client()

# Login
login_ok = client.login(username='testuser', password='testpass')
print(f"✓ Login: {login_ok}")

# Sesión
session = client.session
session['empresa_id'] = empresa.id
session.save()

# POST al endpoint
url = f'/control-proyectos/tareas/{tarea.id}/avance/'
data = {'porcentaje_avance': 50}

print(f"📤 POST {url}")
print(f"   Body: {data}")

response = client.post(
    url,
    data=json.dumps(data),
    content_type='application/json'
)

print(f"✓ Status: {response.status_code}")
print(f"✓ Response: {response.content.decode()}")

if response.status_code == 200:
    result = response.json()
    print(f"\n✅ SUCCESS!")
    print(f"   - Success: {result.get('success')}")
    print(f"   - Porcentaje: {result.get('porcentaje_avance')}%")
    print(f"   - Mensaje: {result.get('mensaje')}")
else:
    print(f"\n❌ ERROR!")
    try:
        result = response.json()
        print(f"   Error: {result.get('error')}")
    except:
        print(f"   Response: {response.content.decode()}")
