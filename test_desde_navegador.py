"""
Test del endpoint DESDE LA VISTA COMPLETA (como en navegador)
Simula GET primero (para obtener CSRF), luego POST
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from control_de_proyectos.models import Tarea, Proyecto
from access_control.models import Empresa
import json
import re

# Setup
empresa = Empresa.objects.get(codigo='01')
testuser = User.objects.get(username='testuser')

# Obtener proyecto y tarea
proyecto = Proyecto.objects.filter(empresa_interna_id=empresa.id).first()
tarea = Tarea.objects.filter(proyecto=proyecto).first()

print(f"📌 Simulando acceso desde navegador...")
print(f"   Usuario: {testuser.username}")
print(f"   Empresa: {empresa.codigo}")
print(f"   Tarea: {tarea.nombre} (ID: {tarea.id})")
print()

client = Client()

# PASO 1: GET a la página de proyecto (para obtener sesión y CSRF)
print(f"1️⃣ GET /control-proyectos/proyectos/{proyecto.id}/")
response_get = client.get(f'/control-proyectos/proyectos/{proyecto.id}/')
print(f"   Status: {response_get.status_code}")

if response_get.status_code == 302:
    print(f"   → Redirect (no autenticado), ubicación: {response_get.get('Location')}")
    # Loguear e intentar nuevamente
    client.force_login(testuser)
    response_get = client.get(f'/control-proyectos/proyectos/{proyecto.id}/detalle/')
    print(f"   Status después de login: {response_get.status_code}")

# Setear empresa en sesión
if response_get.status_code == 200:
    session = client.session
    session['empresa_id'] = empresa.id
    session.save()
    print(f"   ✅ Session empresa_id: {empresa.id}")
else:
    print(f"   ❌ No se pudo acceder a la página")
    exit(1)

# Extraer CSRF token del HTML
html = response_get.content.decode()
csrf_match = re.search(r"csrfmiddlewaretoken.*?value=['\"]([^'\"]+)['\"]", html)
csrf_token_from_html = csrf_match.group(1) if csrf_match else None

print(f"   CSRF token from HTML: {csrf_token_from_html[:20]}..." if csrf_token_from_html else "   ❌ No CSRF in HTML")
print()

# PASO 2: POST con CSRF token
print(f"2️⃣ POST /control-proyectos/tareas/{tarea.id}/avance/")

# Intentar CON CSRF token
url = f'/control-proyectos/tareas/{tarea.id}/avance/'
headers = {
    'Content-Type': 'application/json',
}

if csrf_token_from_html:
    headers['X-CSRFToken'] = csrf_token_from_html

payload = json.dumps({'porcentaje_avance': 75})

print(f"   Payload: {payload}")
print(f"   Headers: {list(headers.keys())}")

response_post = client.post(
    url,
    data=payload,
    content_type='application/json',
    **{'HTTP_X_CSRFTOKEN': csrf_token_from_html} if csrf_token_from_html else {}
)

print(f"   Status: {response_post.status_code}")

try:
    result = response_post.json()
    print(f"   Body: {json.dumps(result, indent=6)}")
except:
    print(f"   Body (raw): {response_post.content.decode()}")

print()

if response_post.status_code == 200:
    print("✅ ÉXITO - El endpoint funciona correctamente")
    print(f"   Tarea actualizada a {result.get('porcentaje_avance')}%")
elif response_post.status_code == 403:
    print("❌ FALLO 403 - Permiso denegado")
    print(f"   Error: {result.get('error', 'desconocido')}")
else:
    print(f"⚠️ Status inesperado: {response_post.status_code}")
