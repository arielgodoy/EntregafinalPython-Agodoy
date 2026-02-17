import logging, sys
logging.basicConfig(level=logging.INFO)
from django.test import Client
from django.contrib.auth import get_user_model
User = get_user_model()
# intentar usuario existente activo
u = User.objects.filter(is_active=True).first()
if not u:
    u = User.objects.create_user('copilot_tmp', 'copilot@example.com', 'pass')

c = Client()
# forzar login
c.force_login(u)
# setear empresa en sesión
s = c.session
s['empresa_id'] = 1
s.save()

r = c.get('/auditoria/biblioteca/')
print('STATUS', r.status_code)
print('LEN', len(r.content))
# imprimir una porción del HTML
try:
    print(r.content.decode('utf-8')[:2000])
except Exception:
    print(r.content[:2000])
sys.stdout.flush()
