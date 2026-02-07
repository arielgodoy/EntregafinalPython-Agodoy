"""
Test simple: POST directo al endpoint CON sesión configurada
(como lo hace el slider desde el navegador)
"""
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from control_de_proyectos.models import Tarea, Proyecto
from access_control.models import Empresa, Permiso, Vista

# Setup
empresa = Empresa.objects.get(codigo='01')
testuser = User.objects.get(username='testuser')

proyecto = Proyecto.objects.filter(empresa_interna_id=empresa.id).first()
tarea = Tarea.objects.filter(proyecto=proyecto).first()

print("="*60)
print("TEST: POST /control-proyectos/tareas/<id>/avance/")
print("="*60)
print()

# Verificar permisos ANTES
vista = Vista.objects.get_or_create(nombre="Modificar Tarea")[0]
perm = Permiso.objects.filter(usuario=testuser, empresa=empresa, vista=vista).first()

print("📋 ANTES DEL POST:")
print(f"   Usuario: {testuser.username}")
print(f"   Empresa: {empresa.codigo} (ID: {empresa.id})")
print(f"   Tarea: {tarea.nombre} (ID: {tarea.id})")
print(f"   Permiso 'Modificar Tarea':")
if perm:
    print(f"      modificar={perm.modificar}, supervisor={perm.supervisor}")
else:
    print(f"      NO EXISTE (será creado por decorador)")
print()

# Cliente con sesión
client = Client()
client.force_login(testuser)

session = client.session
session['empresa_id'] = empresa.id
session.save()

print(f"🔐 Sesión configurada:")
print(f"   Usuario: testuser (autenticado)")
print(f"   empresa_id: {empresa.id}")
print()

# POST
url = f'/control-proyectos/tareas/{tarea.id}/avance/'
payload = {'porcentaje_avance': 80}

print(f"📤 ENVIANDO:")
print(f"   Método: POST")
print(f"   URL: {url}")
print(f"   Payload: {json.dumps(payload)}")
print(f"   Content-Type: application/json")
print()

response = client.post(
    url,
    data=json.dumps(payload),
    content_type='application/json'
)

print(f"📥 RESPUESTA:")
print(f"   Status Code: {response.status_code}")

try:
    body = response.json()
    print(f"   Body JSON: {json.dumps(body, indent=6)}")
except:
    print(f"   Body (raw): {response.content.decode()}")

print()
print("="*60)

if response.status_code == 200:
    # Verificar que se guardó
    tarea.refresh_from_db()
    print(f"✅ ÉXITO")
    print(f"   Porcentaje en BD: {tarea.porcentaje_avance}%")
elif response.status_code == 403:
    print(f"❌ FALLO 403")
    try:
        error = response.json().get('error', '')
        print(f"   Error: {error}")
        if "permiso" in error.lower():
            # Verificar permisos nuevamente
            perm.refresh_from_db() if perm else Permiso.objects.filter(usuario=testuser, empresa=empresa, vista=vista).first()
            print(f"   → Permiso 'modificar' actual: {perm.modificar if perm else 'NINGUNO'}")
    except:
        print(f"   Body: {response.content.decode()}")
else:
    print(f"⚠️ Status inesperado: {response.status_code}")

print("="*60)
