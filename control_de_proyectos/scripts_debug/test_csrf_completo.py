#!/usr/bin/env python
"""
Test CSRF Completo: Verifica exactamente qué está fallando
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from control_de_proyectos.models import Tarea, Proyecto
from access_control.models import Empresa, PermisoVista, Usuario_Permiso
import json

print("=" * 80)
print("TEST: CSRF + Permisos en Avance")
print("=" * 80)

# 1. Crear usuario de prueba
print("\n1. Verificando usuario...")
try:
    user = User.objects.get(username='testuser')
    print(f"   ✓ Usuario existe: {user.username}")
except:
    print("   ✗ Usuario no existe")
    sys.exit(1)

# 2. Verificar empresa
print("\n2. Verificando empresa...")
try:
    empresa = Empresa.objects.first()
    print(f"   ✓ Empresa existe: {empresa.nombre} (ID: {empresa.id})")
except:
    print("   ✗ Empresa no existe")
    sys.exit(1)

# 3. Verificar proyecto
print("\n3. Verificando proyecto...")
try:
    proyecto = Proyecto.objects.filter(empresa=empresa).first()
    print(f"   ✓ Proyecto existe: {proyecto.nombre} (ID: {proyecto.id})")
except:
    print("   ✗ Proyecto no existe")
    sys.exit(1)

# 4. Verificar tarea
print("\n4. Verificando tarea...")
try:
    tarea = Tarea.objects.filter(proyecto=proyecto).first()
    print(f"   ✓ Tarea existe: {tarea.nombre} (ID: {tarea.id})")
except:
    print("   ✗ Tarea no existe")
    sys.exit(1)

# 5. Verificar permisos
print("\n5. Verificando permisos...")
vista_nombre = "Modificar Tarea"
try:
    permiso_vista = PermisoVista.objects.get(nombre=vista_nombre)
    print(f"   ✓ PermisoVista existe: {permiso_vista.nombre}")
    
    user_permiso = Usuario_Permiso.objects.filter(
        usuario=user,
        permiso_vista=permiso_vista,
        permiso='modificar'
    ).first()
    
    if user_permiso:
        print(f"   ✓ Usuario tiene permiso 'modificar' en '{vista_nombre}'")
    else:
        print(f"   ✗ Usuario NO tiene permiso 'modificar' en '{vista_nombre}'")
        # Crear el permiso
        Usuario_Permiso.objects.get_or_create(
            usuario=user,
            permiso_vista=permiso_vista,
            permiso='modificar'
        )
        print(f"   → Permiso creado automáticamente")
except PermisoVista.DoesNotExist:
    print(f"   ✗ PermisoVista '{vista_nombre}' no existe")
    sys.exit(1)

# 6. Test POST con Cliente Django (sin CSRF)
print("\n6. Test POST con Client (sin validar CSRF)...")
client = Client(enforce_csrf_checks=False)
client.force_login(user)

payload = {
    'porcentaje_avance': 75
}

url = f'/control-proyectos/tareas/{tarea.id}/avance/'

response = client.post(
    url,
    data=json.dumps(payload),
    content_type='application/json'
)

print(f"   Status: {response.status_code}")
if response.status_code == 200:
    print(f"   ✓ SIN CSRF = 200 OK")
    data = json.loads(response.content)
    print(f"   Respuesta: {data}")
else:
    print(f"   ✗ Status: {response.status_code}")
    print(f"   Body: {response.content.decode()}")

# 7. Test POST CON CSRF validation
print("\n7. Test POST con CSRF validation...")
client_csrf = Client(enforce_csrf_checks=True)
client_csrf.force_login(user)

# Obtener CSRF token
response_get = client_csrf.get(f'/control-proyectos/proyectos/{proyecto.id}/')
csrf_token = response_get.cookies['csrftoken'].value

print(f"   CSRF Token obtenido: {csrf_token[:20]}...")

# Hacer POST con token
response_csrf = client_csrf.post(
    url,
    data=json.dumps(payload),
    content_type='application/json',
    HTTP_X_CSRFTOKEN=csrf_token,
    HTTP_ORIGIN='http://localhost:8000'
)

print(f"   Status con CSRF: {response_csrf.status_code}")
if response_csrf.status_code == 200:
    print(f"   ✓ CON CSRF = 200 OK")
    data = json.loads(response_csrf.content)
    print(f"   Respuesta: {data}")
else:
    print(f"   ✗ Status: {response_csrf.status_code}")
    print(f"   Body: {response_csrf.content.decode()}")
    print(f"   Headers: {dict(response_csrf)}")

# 8. Verificar CSRF_TRUSTED_ORIGINS
print("\n8. Verificando CSRF_TRUSTED_ORIGINS...")
from django.conf import settings
print(f"   Configurados: {settings.CSRF_TRUSTED_ORIGINS}")

print("\n" + "=" * 80)
print("TEST COMPLETADO")
print("=" * 80)
