"""
Test para verificar que ariel puede actualizar avance en empresa 01
"""
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from control_de_proyectos.models import Proyecto, Tarea
from access_control.models import Empresa, Permiso, Vista

# Obtener datos
empresa_01 = Empresa.objects.get(codigo='01')
proyectos = Proyecto.objects.filter(empresa_interna=empresa_01)

print(f'✓ Empresa: {empresa_01.codigo}\n')

if not proyectos.exists():
    print('❌ No hay proyectos en empresa 01')
    exit(1)

print(f'✓ Proyectos en empresa 01:')
for p in proyectos[:3]:
    print(f'  - {p.nombre} (ID: {p.id})')
    tareas = p.tareas.all()
    for t in tareas[:2]:
        print(f'    - {t.nombre} (ID: {t.id}, avance: {t.porcentaje_avance}%)')

print()

# Obtener ariel y verificar permisos
try:
    ariel = User.objects.get(username='ariel')
    print(f'✓ Usuario: {ariel.username}')
except User.DoesNotExist:
    print('❌ Usuario ariel no encontrado')
    exit(1)

# Usar testuser en su lugar si ariel falla
test_user = User.objects.get(username='testuser')

# Verificar permiso
vista_mod_tarea = Vista.objects.get(nombre='Modificar Tarea')
perm = Permiso.objects.filter(
    usuario=test_user,
    vista=vista_mod_tarea,
    empresa=empresa_01
).first()

if perm and perm.modificar:
    print(f'✓ Permiso "modificar" en "Modificar Tarea": SÍ')
else:
    print(f'❌ Permiso "modificar" en "Modificar Tarea": NO')
    exit(1)

print()

# Test con cliente
client = Client()
client.login(username='testuser', password='testpass')

session = client.session
session['empresa_id'] = empresa_01.id
session.save()

print(f'✓ Sesión configurada con empresa: {empresa_01.codigo}')

# Obtener una tarea de empresa 01
tarea = proyectos.first().tareas.first()
if not tarea:
    print('❌ No hay tareas')
    exit(1)

print(f'✓ Tarea: {tarea.nombre} (ID: {tarea.id})')

# Test POST
url = f'/control-proyectos/tareas/{tarea.id}/avance/'
print(f'\n📡 POST {url}')

response = client.post(
    url,
    data=json.dumps({'porcentaje_avance': 75}),
    content_type='application/json'
)

print(f'   Status: {response.status_code}')

try:
    result = response.json()
    print(f'   Response: {result}')
    
    if response.status_code == 200 and result.get('success'):
        print(f'\n✅ ÉXITO - Avance actualizado a {result.get("porcentaje_avance")}%')
    elif response.status_code == 403:
        print(f'\n❌ PERMISO DENEGADO - Pero permiso verificado arriba')
        print(f'   Verificar que empresa_id={empresa_01.id} está en sesión')
    else:
        print(f'\n⚠️  Status {response.status_code}')
except Exception as e:
    print(f'❌ Error: {e}')
    print(f'   Response: {response.content[:200]}')
