import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_DB = (PROJECT_ROOT / 'db.sqlite3').resolve()
CHILD_CODE = r'''
import json
import os
import uuid
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings_clone')
import django
django.setup()

from django.db import connection, connections
from django.test import RequestFactory
from django.utils import timezone
from django.contrib.auth import get_user_model
from access_control.models import Empresa, Permiso, Vista
from auditoria.archive_service import AuditArchiveService
from auditoria.models import AuditoriaBibliotecaEvent, AuditArchivePurgeChunk, UserPresence
from auditoria.purge_service import AuditArchivePurgeService
from auditoria.helpers import audit_log

clone_path = os.path.abspath(os.environ['DJANGO_CLONE_DB_PATH'])
if os.path.abspath(str(connection.settings_dict['NAME'])) != clone_path:
    raise RuntimeError('Django no inició contra el clon esperado')
if os.path.abspath(clone_path) == os.path.abspath(os.path.join(os.getcwd(), 'db.sqlite3')):
    raise RuntimeError('El proceso hijo apunta a la base original')

User = get_user_model()
user = User.objects.create_user(username='e2e-' + uuid.uuid4().hex, password='unused')
used_codes = set(Empresa.objects.values_list('codigo', flat=True))
company_code = next(code for code in (f'{number:02d}' for number in range(99, -1, -1)) if code not in used_codes)
empresa = Empresa.objects.create(codigo=company_code, descripcion='E2E Clone')
vista, _ = Vista.objects.get_or_create(nombre='Auditoría - Biblioteca')
Permiso.objects.create(usuario=user, empresa=empresa, vista=vista, ingresar=True, autorizar=True)

presence = UserPresence.objects.create(user=user, empresa_id=empresa.id, app_label='biblioteca', vista_nombre=vista.nombre, path='/e2e/')
presence_before = {field: getattr(presence, field) for field in ('user_id', 'empresa_id', 'app_label', 'vista_nombre', 'path')}
cutoff = timezone.now() + timedelta(days=1)
batch_candidate_ids = []
for index in range(25):
    event = AuditoriaBibliotecaEvent.objects.create(user=user, empresa_id=empresa.id, action='VIEW', path=f'/e2e/{index}/', vista_nombre=vista.nombre, meta={'index': index})
    batch_candidate_ids.append(event.id)
outside_ids = []
for index in range(5):
    event = AuditoriaBibliotecaEvent.objects.create(user=user, empresa_id=empresa.id, action='VIEW', path=f'/outside/{index}/', vista_nombre=vista.nombre, meta={'outside': index})
    outside_ids.append(event.id)
max_source_id = batch_candidate_ids[-1]
batch = AuditArchiveService.run_batch('biblioteca', cutoff, max_source_id=max_source_id, requested_company_ids=[empresa.id], batch_id='e2e-' + uuid.uuid4().hex, user=user, vista_nombre=vista.nombre)
request = RequestFactory().post('/auditoria/biblioteca/archivo/')
request.user = user
request.session = {'empresa_id': empresa.id}
audit_log(request, 'EXECUTE', 'biblioteca', object_type='audit_archive_batch', object_id=batch.batch_id, vista_nombre=vista.nombre, message_key='auditoria.snapshot.creado', meta={'batch_id': batch.batch_id, 'source_count': batch.source_count, 'company_ids': batch.company_ids, 'cutoff': batch.cutoff_datetime.isoformat()})
preview = AuditArchivePurgeService.preview(batch.batch_id, user)
dry_run = AuditArchivePurgeService.purge(batch.batch_id, user, dry_run=True)
result = AuditArchivePurgeService.purge(batch.batch_id, user, dry_run=False, chunk_size=7)
chunks = list(AuditArchivePurgeChunk.objects.filter(batch=batch).order_by('sequence'))
history = AuditArchiveService.read_archived_rows(batch)
presence.refresh_from_db()
execute = AuditoriaBibliotecaEvent.objects.get(action='EXECUTE', object_id=batch.batch_id)
second = AuditArchivePurgeService.purge(batch.batch_id, user, dry_run=False, chunk_size=7)
print(json.dumps({'connection_name': str(connection.settings_dict['NAME']), 'batch_status': result.status, 'source_count': result.source_count, 'archive_count': result.archive_count, 'preview_remaining': preview['remaining_in_source'], 'dry_run_remaining': dry_run['remaining_in_source'], 'batch_candidate_remaining': AuditoriaBibliotecaEvent.objects.filter(id__in=batch_candidate_ids).count(), 'outside_remaining': AuditoriaBibliotecaEvent.objects.filter(id__in=outside_ids).count(), 'execute_id': execute.id, 'execute_outside_frontier': execute.id > batch.source_max_id, 'history_count': len(history), 'chunk_counts': [chunk.expected_count for chunk in chunks], 'chunk_statuses': [chunk.status for chunk in chunks], 'chunk_deleted_counts': [chunk.deleted_count for chunk in chunks], 'purged_count': second.purged_count, 'presence_unchanged': {field: getattr(presence, field) for field in presence_before} == presence_before, 'archive_path': batch.archive_path}, ensure_ascii=False))
connections.close_all()
'''


def fingerprint(path):
    connection = sqlite3.connect(path)
    try:
        tables = ('auditoria_biblioteca_event', 'auditoria_gestiondte_event', 'auditoria_user_presence', 'auditoria_archive_batch', 'auditoria_auditarchivepurgechunk')
        counts = {table: connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in tables if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()}
    finally:
        connection.close()
    return {'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(), 'size': Path(path).stat().st_size, 'counts': counts}


def main():
    original_before = fingerprint(ORIGINAL_DB)
    with tempfile.TemporaryDirectory(prefix='fase5c1_clone_') as root:
        clone = Path(root) / 'db_clone.sqlite3'
        archive = Path(root) / 'archive'
        shutil.copy2(ORIGINAL_DB, clone)
        clone_initial = fingerprint(clone)
        if clone_initial['sha256'] != original_before['sha256']:
            raise RuntimeError('El clon inicial no coincide con el original')
        env = os.environ.copy()
        env['DJANGO_SETTINGS_MODULE'] = 'AppDocs.settings_clone'
        env['DJANGO_CLONE_DB_PATH'] = str(clone)
        env['DJANGO_CLONE_ARCHIVE_ROOT'] = str(archive)
        completed = subprocess.run([sys.executable, '-c', CHILD_CODE], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(completed.stderr or completed.stdout)
        result = json.loads(completed.stdout.strip().splitlines()[-1])
    original_after = fingerprint(ORIGINAL_DB)
    print(json.dumps({'original_before': original_before, 'clone_initial_matches_original': clone_initial == original_before, 'e2e': result, 'original_after': original_after, 'original_hash_unchanged': original_before['sha256'] == original_after['sha256'], 'original_size_unchanged': original_before['size'] == original_after['size'], 'original_counts_unchanged': original_before['counts'] == original_after['counts'], 'temporary_clone_removed': not clone.exists(), 'temporary_archive_removed': not archive.exists(), 'vacuum_executed': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
