from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('auditoria', '0008_auditarchivebatch'),
    ]

    operations = [
        migrations.AddField(
            model_name='auditarchivebatch',
            name='source_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='auditarchivebatch',
            name='first_source_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='auditarchivebatch',
            name='last_source_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='auditarchivebatch',
            name='first_event_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='auditarchivebatch',
            name='last_event_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='auditarchivebatch',
            name='checksum_algorithm',
            field=models.CharField(default='SHA-256', max_length=32),
        ),
        migrations.AddField(
            model_name='auditarchivebatch',
            name='validated_at',
            field=models.DateTimeField(blank=True, null=True),
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
                ],
                db_index=True,
                default='PENDING',
                max_length=20,
            ),
        ),
    ]