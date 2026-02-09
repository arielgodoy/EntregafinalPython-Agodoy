"""
Test para identificar EXACTAMENTE por qué falla el 403
Incluye logging detallado
"""
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from control_de_proyectos.models import Tarea, Proyecto
from access_control.models import Empresa, Vista, Permiso

# Setup
empresa = Empresa.objects.get(codigo='01')

# Obtener usuario testuser
testuser = User.objects.get(username='testuser')

# Obtener/crear una tarea
proyecto = Proyecto.objects.filter(empresa_interna_id=empresa.id).first()
if not proyecto:
    print("❌ NO HAY PROYECTOS EN EMPRESA 01")
    exit(1)

tarea = Tarea.objects.filter(proyecto=proyecto).first()
if not tarea:
    print("❌ NO HAY TAREAS EN EL PROYECTO")
    exit(1)

print(f"📌 Setup:")
print(f"   Usuario: {testuser.username}")
print(f"   Empresa: {empresa.codigo} (ID: {empresa.id})")
print(f"   Proyecto: {proyecto.nombre} (ID: {proyecto.id})")
print(f"   Tarea: {tarea.nombre} (ID: {tarea.id})")
print()

# Verificar permisos actuales
vista_modificar = Vista.objects.get_or_create(nombre="Modificar Tarea")[0]
permiso_actual = Permiso.objects.filter(
    usuario=testuser,
    empresa=empresa,
    vista=vista_modificar
).first()

print(f"📋 Permiso actual para 'Modificar Tarea':")
if permiso_actual:
    print(f"   ✅ Existe")
    print(f"   - ingresar: {permiso_actual.ingresar}")
    print(f"   - crear: {permiso_actual.crear}")
    print(f"   - modificar: {permiso_actual.modificar}")
    print(f"   - eliminar: {permiso_actual.eliminar}")
    print(f"   - supervisor: {permiso_actual.supervisor}")
else:
    print(f"   ❌ NO EXISTE")
    print(f"   → El decorador lo creará auto con modificar=False")

print()

# Hacer POST
client = Client()
client.force_login(testuser)

session = client.session
session['empresa_id'] = empresa.id
session.save()

url = f'/control-proyectos/tareas/{tarea.id}/avance/'
payload = {'porcentaje_avance': 50}

print(f"🚀 POST {url}")
print(f"   Payload: {payload}")
print(f"   Session empresa_id: {empresa.id}")
print()

response = client.post(
    url,
    data=json.dumps(payload),
    content_type='application/json'
)

print(f"📬 Response:")
print(f"   Status Code: {response.status_code}")

try:
    result = response.json()
    print(f"   Body: {result}")
except:
    print(f"   Body (raw): {response.content.decode()}")

print()

# Análisis del resultado
if response.status_code == 403:
    print("❌ PROBLEMA IDENTIFICADO:")
    try:
        error_msg = response.json().get('error', '')
        if "permiso" in error_msg.lower():
            print(f"   → Causa: PERMISO DENEGADO")
            print(f"   → Mensaje: {error_msg}")
        elif "empresa" in error_msg.lower():
            print(f"   → Causa: EMPRESA NO COINCIDE")
            print(f"   → Mensaje: {error_msg}")
        else:
            print(f"   → Causa: DESCONOCIDA")
            print(f"   → Mensaje: {error_msg}")
    except:
        print(f"   → Response body: {response.content.decode()}")
elif response.status_code == 200:
    print("✅ ÉXITO")
    print(f"   → Tarea actualizada correctamente")
else:
    print(f"⚠️ Status inesperado: {response.status_code}")
