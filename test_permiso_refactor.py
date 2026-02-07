"""
Test directo: verificar que el endpoint RECHAZA sin permisos
"""
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from control_de_proyectos.models import Tarea
from access_control.models import Empresa, Vista, Permiso

# Setup
empresa = Empresa.objects.get(codigo='01')
tarea = Tarea.objects.get(nombre='Test Tarea')

# 2. Crear usuario sin permisos si no existe
user_sin_permisos, created = User.objects.get_or_create(
    username='test_usuario_nuevo'
)
if created:
    user_sin_permisos.set_password('testpass123')
    user_sin_permisos.save()

# 2. Remover cualquier permiso existente para esta vista
Vista_obj, _ = Vista.objects.get_or_create(nombre="Modificar Tarea")
Permiso.objects.filter(
    usuario=user_sin_permisos,
    vista=Vista_obj,
    empresa=empresa
).delete()

# 3. Crear un permiso EXPLÍCITO sin modificar
permiso_sin_modificar = Permiso.objects.create(
    usuario=user_sin_permisos,
    empresa=empresa,
    vista=Vista_obj,
    ingresar=False,
    crear=False,
    modificar=False,  # <-- EXPLÍCITO: NO TIENE PERMISO
    eliminar=False,
    autorizar=False,
    supervisor=False
)

# 4. Hacer la solicitud
client = Client()
client.login(username='test_usuario_nuevo', password='testpass123')

session = client.session
session['empresa_id'] = empresa.id
session.save()

url = f'/control-proyectos/tareas/{tarea.id}/avance/'
response = client.post(
    url,
    data=json.dumps({'porcentaje_avance': 50}),
    content_type='application/json'
)

print(f"Status Code: {response.status_code}")
try:
    result = response.json()
    print(f"Response JSON: {result}")
except:
    print(f"Response Text: {response.content.decode()}")

if response.status_code == 403:
    print("✅ CORRECTO: Usuario sin permisos recibió 403")
else:
    print(f"❌ ERROR: Esperaba 403, recibió {response.status_code}")
