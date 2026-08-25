from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('auditoria', '0009_complete_auditarchivebatch'),
    ]

    operations = [
        migrations.RenameIndex(
            model_name='auditarchivebatch',
            new_name='auditoria_archive_batch_idx',
            old_name='auditoria_ar_app_lab_9b3a34_idx',
        ),
    ]