"""
Test para ver exactamente qué es 72 bytes en 403
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
testuser = User.objects.get(username='testuser')
proyecto = Proyecto.objects.filter(empresa_interna_id=empresa.id).first()
tarea = Tarea.objects.filter(proyecto=proyecto).first()

# Crear usuario sin permisos
user_sin_permisos, _ = User.objects.get_or_create(username='sin_permisos')
user_sin_permisos.set_password('pass')
user_sin_permisos.save()

# Remover permisos
vista = Vista.objects.get_or_create(nombre="Modificar Tarea")[0]
Permiso.objects.filter(usuario=user_sin_permisos, vista=vista, empresa=empresa).delete()

# Crear permiso SIN modificar
Permiso.objects.create(
    usuario=user_sin_permisos,
    empresa=empresa,
    vista=vista,
    ingresar=False,
    crear=False,
    modificar=False,
    eliminar=False,
    autorizar=False,
    supervisor=False
)

# POST sin permisos
client = Client()
client.force_login(user_sin_permisos)

session = client.session
session['empresa_id'] = empresa.id
session.save()

response = client.post(
    f'/control-proyectos/tareas/{tarea.id}/avance/',
    data=json.dumps({'porcentaje_avance': 50}),
    content_type='application/json'
)

print(f"Status: {response.status_code}")
print(f"Content-Length: {len(response.content)} bytes")
print(f"Content: {response.content.decode()}")
print()

# Contar bytes exactos
json_response = response.json()
json_str = json.dumps(json_response)
print(f"JSON length: {len(json_str)} bytes")
print(f"JSON: {json_str}")
