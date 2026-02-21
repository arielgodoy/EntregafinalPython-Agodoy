import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
import django
django.setup()

from django.test import RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.auth import get_user_model
from access_control.decorators import _build_access_request_context

User = get_user_model()

username = sys.argv[1] if len(sys.argv)>1 else 'ariel'
user = User.objects.get(username=username)

factory = RequestFactory()
request = factory.get('/')
request.user = user
# attach session
middleware = SessionMiddleware(lambda req: None)
middleware.process_request(request)
request.session.save()
# set empresa en session (usar la que existe en AccessRequest)
request.session['empresa_id'] = 1
request.session['empresa_nombre'] = '1 - Test'

ctx = _build_access_request_context(request, 'Settings - Configuracion de Empresa', 'mensaje test')
print('pending_access_requests count:', len(ctx.get('pending_access_requests') or []))
print('pending keys:', list(ctx.keys()))
if ctx.get('pending_access_requests'):
    for r in ctx['pending_access_requests']:
        print('->', r.id, r.vista_nombre, r.empresa_id, r.status)
else:
    print('No pending')
