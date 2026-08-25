import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('auditoria', '0010_rename_archive_batch_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='auditarchivebatch',
            name='purge_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='auditarchivebatch',
            name='purged_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='auditarchivebatch',
            name='purged_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='auditarchivebatch',
            name='purge_error_message',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='auditarchivebatch',
            name='purged_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='audit_archive_purges',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='auditarchivebatch',
            name='status',
            field=models.CharField(
                choices=[
                    ('PENDING', 'Pendiente'),
                    ('COPYING', 'Copiando'),
                    ('VALIDATING', 'Validando'),
                    ('COMPLETED', 'Completado'),
                    ('FAILED', 'Fallido'),
                    ('PURGING', 'Limpiando origen'),
                    ('PURGED', 'Origen limpiado'),
                    ('PURGE_FAILED', 'Limpieza fallida'),
                ],
                db_index=True,
                default='PENDING',
                max_length=20,
            ),
        ),
    ]