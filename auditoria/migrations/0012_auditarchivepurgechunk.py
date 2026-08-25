from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('auditoria', '0011_auditarchivebatch_purge'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditArchivePurgeChunk',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sequence', models.PositiveIntegerField()),
                ('expected_count', models.PositiveIntegerField()),
                ('deleted_count', models.PositiveIntegerField(default=0)),
                ('source_ids_checksum', models.CharField(max_length=64)),
                ('status', models.CharField(choices=[('PENDING', 'Pendiente'), ('DELETING', 'Eliminando'), ('COMPLETED', 'Completado'), ('FAILED', 'Fallido')], default='PENDING', max_length=16)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('error_message', models.TextField(blank=True, default='')),
                ('first_source_id', models.BigIntegerField(blank=True, null=True)),
                ('last_source_id', models.BigIntegerField(blank=True, null=True)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='purge_chunks', to='auditoria.auditarchivebatch')),
            ],
            options={
                'ordering': ['batch_id', 'sequence'],
                'constraints': [models.UniqueConstraint(fields=('batch', 'sequence'), name='audit_purge_batch_sequence_unique')],
            },
        ),
    ]