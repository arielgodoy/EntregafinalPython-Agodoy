"""
Test mejorado - usando force_login y session correctamente
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

# Crear usuario sin permisos
user_sin_permisos, _ = User.objects.get_or_create(
    username='user_sin_permisos_v3',
    defaults={'password': 'testpass'}
)
user_sin_permisos.set_password('testpass')
user_sin_permisos.save()

# Remover/crear permiso SIN modificar
vista_modificar, _ = Vista.objects.get_or_create(nombre="Modificar Tarea")
Permiso.objects.filter(
    usuario=user_sin_permisos,
    vista=vista_modificar,
    empresa=empresa
).delete()

Permiso.objects.create(
    usuario=user_sin_permisos,
    empresa=empresa,
    vista=vista_modificar,
    ingresar=False,
    crear=False,
    modificar=False,
    eliminar=False,
    autorizar=False,
    supervisor=False
)

test_cases = [
    {
        'name': '✓ POST con permiso y valor válido (50)',
        'user': 'testuser',
        'status_esperado': 200,
        'body': {'porcentaje_avance': 50},
        'validar': lambda r: r.get('success') == True
    },
    {
        'name': '✓ POST con permiso y valor 0',
        'user': 'testuser',
        'status_esperado': 200,
        'body': {'porcentaje_avance': 0},
        'validar': lambda r: r.get('porcentaje_avance') == 0
    },
    {
        'name': '✓ POST con permiso y valor 100',
        'user': 'testuser',
        'status_esperado': 200,
        'body': {'porcentaje_avance': 100},
        'validar': lambda r: r.get('porcentaje_avance') == 100
    },
    {
        'name': '❌ POST sin permiso',
        'user': user_sin_permisos,
        'status_esperado': 403,
        'body': {'porcentaje_avance': 50},
        'validar': lambda r: r.get('success') == False
    },
    {
        'name': '❌ Valor > 100',
        'user': 'testuser',
        'status_esperado': 400,
        'body': {'porcentaje_avance': 150},
        'validar': lambda r: r.get('success') == False
    },
    {
        'name': '❌ Valor < 0',
        'user': 'testuser',
        'status_esperado': 400,
        'body': {'porcentaje_avance': -10},
        'validar': lambda r: r.get('success') == False
    },
    {
        'name': '❌ Campo faltante',
        'user': 'testuser',
        'status_esperado': 400,
        'body': {},
        'validar': lambda r: r.get('success') == False
    },
    {
        'name': '❌ JSON inválido',
        'user': 'testuser',
        'status_esperado': 400,
        'body': 'invalid',
        'validar': lambda r: r.get('success') == False,
        'json': False
    },
    {
        'name': '❌ Tarea no existe',
        'user': 'testuser',
        'tarea_id': 99999,
        'status_esperado': 404,
        'body': {'porcentaje_avance': 50},
        'validar': lambda r: r.get('success') == False
    },
]

url_template = '/control-proyectos/tareas/{}/avance/'
passed = 0
failed = 0

for test in test_cases:
    client = Client()
    
    # Resolver usuario
    user_input = test['user']
    if isinstance(user_input, str):
        user = User.objects.get(username=user_input)
    else:
        user = user_input
    
    # Usar force_login y luego setear sesión
    client.force_login(user)
    
    # Setear empresa_id en sesión
    session = client.session
    session['empresa_id'] = empresa.id
    session.save()
    
    tarea_id = test.get('tarea_id', tarea.id)
    url = url_template.format(tarea_id)
    
    body = test.get('body')
    is_json = test.get('json', True)
    
    if is_json:
        response = client.post(
            url,
            data=json.dumps(body),
            content_type='application/json'
        )
    else:
        response = client.post(
            url,
            data=body,
            content_type='application/json'
        )
    
    try:
        result = response.json()
    except:
        result = {}
    
    expected = test['status_esperado']
    actual = response.status_code
    validation = test['validar'](result)
    
    if actual == expected and validation:
        print(f"✅ {test['name']}")
        print(f"   Status: {actual} (expected {expected}) ✓")
        passed += 1
    else:
        print(f"❌ {test['name']}")
        print(f"   Status: {actual} (expected {expected})")
        print(f"   Validation: {validation}")
        print(f"   Response: {result}")
        failed += 1

print(f"\n📊 RESULTADOS: {passed} PASS, {failed} FAIL")
if failed == 0:
    print("🎉 ¡TODOS LOS TESTS PASARON!")
