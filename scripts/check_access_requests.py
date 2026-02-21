import os
import sys
import django
import pprint

# Ajustar ruta al root del repo
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')

try:
    django.setup()
except Exception as e:
    print('Error al iniciar Django:', e)
    sys.exit(2)

from django.contrib.auth import get_user_model
from access_control.models import AccessRequest, Vista

User = get_user_model()

if len(sys.argv) < 2:
    print('Uso: python check_access_requests.py <username_or_email>')
    sys.exit(1)

identifier = sys.argv[1]

# Intentar por username, luego por email
user = None
try:
    user = User.objects.get(username=identifier)
except Exception:
    try:
        user = User.objects.get(email=identifier)
    except Exception:
        print('No se encontró usuario con username/email:', identifier)
        sys.exit(3)

print('Usuario encontrado:', user.username, getattr(user, 'email', ''))

qs = AccessRequest.objects.filter(solicitante=user).order_by('-id')[:20]
print('\nÚltimas AccessRequest (sin filtrar):', qs.count())
pp = pprint.PrettyPrinter(indent=2)

rows = []
for a in qs:
    vista_nombre = getattr(a, 'vista_nombre', None)
    vista_id = getattr(a, 'vista_id', None)

    row = {
        'id': getattr(a, 'id', None),
        'status': getattr(a, 'status', None),
        'created_at': getattr(a, 'created_at', None),
        'empresa_id': getattr(a, 'empresa_id', getattr(a, 'empresa', None)),
        'vista_id': vista_id,
        'vista_nombre': vista_nombre,
        'motivo': getattr(a, 'motivo', getattr(a, 'reason', None)),
        'solicitante_id': getattr(a, 'solicitante_id', None),
    }
    rows.append(row)

pp.pprint(rows)

# También mostrar count de pending por vista_id/empresa_id agrupado
from django.db.models import Count

pending = AccessRequest.objects.filter(solicitante=user, status='PENDING').values('vista_nombre','empresa_id').annotate(c=Count('id')).order_by('-c')
print('\nPendientes (status==PENDING) agrupados por vista_id/empresa_id:')
pp.pprint(list(pending))

print('\nScript completado.')
