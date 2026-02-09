"""
Verificación: ¿Es un error CSRF?
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
django.setup()

from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory
from django.contrib.auth.models import User
from control_de_proyectos.models import Tarea, Proyecto
from access_control.models import Empresa
import json

# Setup
empresa = Empresa.objects.get(codigo='01')
testuser = User.objects.get(username='testuser')
proyecto = Proyecto.objects.filter(empresa_interna_id=empresa.id).first()
tarea = Tarea.objects.filter(proyecto=proyecto).first()

print("="*70)
print("TEST: Verificar CSRF en POST")
print("="*70)
print()

# Crear request de POST
factory = RequestFactory()

request = factory.post(
    f'/control-proyectos/tareas/{tarea.id}/avance/',
    data=json.dumps({'porcentaje_avance': 50}),
    content_type='application/json',
    HTTP_HOST='localhost:8000'  # Simular origen local
)

# Asignar user
request.user = testuser
request.session = {}
request.session['empresa_id'] = empresa.id

print(f"📌 Información de la request:")
print(f"   Método: {request.method}")
print(f"   Ruta: {request.path}")
print(f"   Host: {request.get_host()}")
print(f"   Content-Type: {request.content_type}")
print(f"   Usuario: {request.user.username}")
print()

# Verificar CSRF
csrf_middleware = CsrfViewMiddleware(lambda r: None)

print(f"🔐 Verificación CSRF:")
print(f"   CSRF token en POST: {request.POST.get('csrfmiddlewaretoken', 'NO PRESENTE')}")
print(f"   Header X-CSRFToken: {request.META.get('HTTP_X_CSRFTOKEN', 'NO PRESENTE')}")
print(f"   Content-Type: {request.content_type}")
print()

# Verificar origen
print(f"🌐 Verificación de Origen:")
print(f"   Host de la request: {request.get_host()}")
print(f"   Referer (si existe): {request.META.get('HTTP_REFERER', 'NO PRESENTE')}")

# Simular con referer localhost
request_with_referer = factory.post(
    f'/control-proyectos/tareas/{tarea.id}/avance/',
    data=json.dumps({'porcentaje_avance': 50}),
    content_type='application/json',
    HTTP_HOST='localhost:8000',
    HTTP_REFERER='http://localhost:8000/control-proyectos/proyectos/4/'
)
request_with_referer.user = testuser
request_with_referer.session = {'empresa_id': empresa.id}

print(f"   Con Referer: http://localhost:8000/control-proyectos/proyectos/4/")
print()

print("="*70)
print("RESUMEN:")
print("="*70)
print()
print("Para que funcione POST JSON con CSRF desde localhost:")
print("1. ✅ Content-Type: application/json")
print("2. ✅ Header X-CSRFToken: <token>")
print("3. ✅ Referer apuntando al mismo origin (localhost:8000)")
print()
print("Si estás en HTTPS (biblioteca.eltit.cl):")
print("   → CSRF_TRUSTED_ORIGINS ya incluye: https://biblioteca.eltit.cl")
print()
print("Si estás en localhost:")
print("   → CSRF_TRUSTED_ORIGINS NO incluye localhost")
print("   → Debes:") 
print("      A) Agregar 'http://localhost:8000' a CSRF_TRUSTED_ORIGINS")
print("      B) O usar CSRF token en el header (ya está en el JS)")
print()
