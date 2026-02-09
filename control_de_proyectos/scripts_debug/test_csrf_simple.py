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
from access_control.models import Empresa, Vista, Permiso
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
    print(f"   ✓ Empresa existe: {empresa.codigo}")
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
    vista = Vista.objects.get(nombre=vista_nombre)
    print(f"   ✓ Vista existe: {vista.nombre}")
    
    permiso = Permiso.objects.filter(
        usuario=user,
        empresa=empresa,
        vista=vista
    ).first()
    
    if permiso and permiso.modificar:
        print(f"   ✓ Usuario tiene permiso 'modificar'")
    else:
        print(f"   ✗ Usuario NO tiene permiso 'modificar'")
except Vista.DoesNotExist:
    print(f"   ✗ Vista '{vista_nombre}' no existe")

# 6. Test POST sin CSRF
print("\n6. Test POST sin validar CSRF...")
client = Client(enforce_csrf_checks=False)
client.force_login(user)

# Guardar empresa en sesión (importante!)
session = client.session
session['empresa_activa'] = empresa.id
session.save()

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
else:
    print(f"   ✗ Status: {response.status_code}")
    print(f"   Body: {response.content.decode()}")

# 7. Verificar CSRF_TRUSTED_ORIGINS
print("\n7. Verificando CSRF_TRUSTED_ORIGINS...")
from django.conf import settings
print(f"   Configurados: {settings.CSRF_TRUSTED_ORIGINS}")

print("\n" + "=" * 80)
print("ANÁLISIS COMPLETADO")
print("=" * 80)
